"""nav：導航域（地點倉／Maps URI／彈窗確認／導航任務）。"""
from __future__ import annotations

from . import engine

# ---------------- 導航（Google Maps） ----------------

def _dests() -> dict:
    return engine._load_json(engine.DESTINATIONS_PATH, {})



# 用戶只用步行同公共交通：預設 transit，要打「步行」先轉行路
_NAV_MODES = {"步行": "w", "行路": "w", "walk": "w",
              "巴士": "r", "公共交通": "r", "公交": "r", "transit": "r"}

_NAV_MODE_LABEL = {"w": "行路", "r": "公共交通"}



def _mode_label(mode: str) -> str:
    return engine._NAV_MODE_LABEL.get(mode, mode)  # 舊 job 可能有 d/b，照樣顯示



def _nav_target(arg: str) -> tuple:
    """拆走尾部交通模式、查已儲地點名。回傳 (目的地查詢, mode, 顯示名)。"""
    parts = arg.strip().split()
    mode = "r"  # 預設：大眾運輸
    if len(parts) > 1 and parts[-1].lower() in engine._NAV_MODES:
        mode = engine._NAV_MODES[parts.pop().lower()]
    name = " ".join(parts)
    return engine._dests().get(name, name), mode, name



def _nav_uri(dest: str, mode: str = "r") -> str:
    """導航 URI：純文字→google.navigation:q=…；連結/geo 直接用。"""
    import urllib.parse
    if engine.re.match(r"^(https?:|geo:|google\.)", dest, engine.re.IGNORECASE):
        return dest
    return f"google.navigation:q={urllib.parse.quote(dest)}&mode={mode}"



# ---- 導航確認彈窗：到點先彈通知，撳「確定」先開地圖 ----
# vivo 背景閘 + 鎖屏令「靜雞雞開 app」睇唔到；改做頭條通知＋確定掣，
# 撳掣嗰下 Termux:API 有前台交互 → 地圖一定彈到。
def _nav_go_script_path(job: dict) -> str:
    return engine.os.path.join(engine.os.path.dirname(engine.JOBS_PATH), f"nav_go_{job.get('id', 0)}.sh")



def _nav_write_go_script(job: dict) -> str:
    """寫「開地圖」腳本，三層後備：
    ⓪ adb lane（WAKEUP＋--activity-clear-task，最齊全）
    ① rish（Shizuku；無線調試死咗都仲行，重啟後先要再駁）
    ③ termux-open-url（零權限兜底；冇 clear-task，舊 task 可能淨係帶上前）
    回傳腳本路徑。呢個腳本俾通知掣＋彈窗確認共用。"""
    dest = job.get("url") or job.get("label", "")
    mode = job.get("mode", "r")
    uri = engine._nav_uri(dest, mode)
    import urllib.parse
    tmode = {"r": "transit", "w": "walking", "d": "driving"}.get(mode, "transit")
    web = (f"https://www.google.com/maps/dir/?api=1&destination="
           f"{urllib.parse.quote(dest)}&travelmode={tmode}")
    script = engine._nav_go_script_path(job)
    adb = engine.shutil.which("adb") or "/data/data/com.termux/files/usr/bin/adb"
    rish = engine.shutil.which("rish") or "/data/data/com.termux/files/usr/bin/rish"
    with open(script, "w") as f:
        f.write(f"""#!/system/bin/sh
# bot 自動寫：開地圖三層後備（--activity-clear-task 必填——
# 唔清舊 task 嘅話 Maps 淨係 brought to front，新導航指令送唔入去）
# ⓪ adb lane
{adb} connect {engine.ADB_TARGET} >/dev/null 2>&1
if {adb} -s {engine.ADB_TARGET} shell "input keyevent KEYCODE_WAKEUP; \\
am start --activity-clear-task -a android.intent.action.VIEW -d '{uri}'" >/dev/null 2>&1; then
  exit 0
fi
# ① rish（Shizuku）
if [ -x {rish} ]; then
  if {rish} -c "input keyevent KEYCODE_WAKEUP; am start --activity-clear-task -a android.intent.action.VIEW -d '{uri}'" >/dev/null 2>&1; then
    exit 0
  fi
fi
# ② termux-open-url（零權限兜底）
termux-open-url '{web}'
""")
    engine.os.chmod(script, 0o700)
    return script



def _nav_confirm_notify(job: dict) -> tuple:
    """發通知做提醒（聲＋震動）；回傳 (ok, 輸出)。
    真正確認靠 _nav_dialog_task 嘅彈窗；通知掣留返做後備。"""
    dest = job.get("url") or job.get("label", "")
    script = engine._nav_write_go_script(job)
    if not engine.shutil.which("termux-notification"):
        return False, "冇 termux-notification"
    nid = f"nav{job.get('id', 0)}"
    label = job.get("label") or dest
    cmd = ["termux-notification",
           "--id", nid,
           "--title", "⏰ 到點！開導航？",
           "--content", f"去「{label}」——彈窗問緊你，撳【是】開地圖",
           "--priority", "high",
           "--button1", "確定開地圖", "--button1-action", f"sh {script}",
           "--button2", "唔使", "--button2-action", f"termux-notification-remove {nid}",
           "--sound", "--vibrate", "500,300,500"]
    try:
        r = engine.subprocess.run(cmd, capture_output=True, text=True, timeout=12)
        out = (r.stdout + r.stderr).strip()
        return r.returncode == 0, out or "ok"
    except engine.subprocess.TimeoutExpired:
        return False, "termux-notification 超時"
    except Exception as e:
        return False, str(e)



def _nav_dialog_block(job: dict, timeout: int = 600) -> str:
    """阻塞式真彈窗：termux-dialog confirm，等用戶撳【是】／【否】。
    回傳 'yes'／'no'／'timeout'／'err'。要喺 thread 度行（會等最多 10 分鐘）。
    實測（2026-09-24）：Termux 自己開嘅彈窗係出到嘅——之前死係死喺經 rish。"""
    label = job.get("label") or job.get("url", "")
    try:
        r = engine.subprocess.run(["termux-dialog", "confirm",
                            "-t", "⏰ 開導航？",
                            "-i", f"而家開地圖去「{label}」？"],
                           capture_output=True, text=True, timeout=timeout)
    except engine.subprocess.TimeoutExpired:
        return "timeout"
    except Exception:
        return "err"
    out = (r.stdout or "")
    if '"yes"' in out:
        return "yes"
    if '"no"' in out:
        return "no"
    engine.logging.info("彈窗#%s → err raw_out=%r raw_err=%r rc=%s",
                 job.get("id", 0), out[:160], (r.stderr or "")[:160],
                 getattr(r, "returncode", "?"))
    return "err"



def _nav_run_go(job: dict) -> None:
    """行「開地圖」腳本＋清埋通知。"""
    script = engine._nav_go_script_path(job)
    try:
        engine.subprocess.run(["sh", script], capture_output=True, timeout=30)
    except Exception:
        pass
    try:
        engine.subprocess.run(["termux-notification-remove", f"nav{job.get('id', 0)}"],
                       capture_output=True, timeout=6)
    except Exception:
        pass



def _nav_keyboard(nid: str):
    try:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    except ImportError:            # 沘木殫測試環境們 telegram lib
        return None
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("\U0001F5FA \u958B\u5730\u5716",
                             callback_data=f"nav:go:{nid}"),
        InlineKeyboardButton("\u2716 \u5514\u53bb",
                             callback_data=f"nav:no:{nid}")]])



async def _nav_keyboard_msg(chat_id: int, job: dict) -> None:
    label = job.get("label") or job.get("url", "")
    engine._PENDING_NAVS[str(job["id"])] = job
    # 順手清理 30 分鐘以上嘅舊 pending
    now_ts = engine.dt.datetime.now().timestamp()
    for k in [k for k, v in engine._PENDING_NAVS.items()
              if str(v.get("_ts", 0)) and now_ts - v.get("_ts", now_ts) > 1800]:
        engine._PENDING_NAVS.pop(k, None)
    await engine._send_safe(chat_id,
                     f"🧭 開導航去「{label}」？撳下面掣",
                     "\u5c0e\u822a\u78ba\u8a8d", markup=engine._nav_keyboard(str(job["id"])))



async def _on_nav_callback(update, context) -> None:
    q = update.callback_query
    try:
        await q.answer()
    except Exception:
        pass
    try:
        _, act, nid = q.data.split(":", 2)
    except ValueError:
        return
    job = engine._PENDING_NAVS.get(nid)
    if job is None:
        for j in engine._jobs():
            if str(j.get("id")) == nid and j.get("type") == "nav":
                job = dict(j)
                job["chat_id"] = q.message.chat_id
                break
    if job is None:
        try:
            await q.edit_message_text(
                "\u23f1 \u5462\u500b\u78ba\u8a8d\u5df2\u904e\u671f\uff0c"
                "send\u300c\u5c0e\u822a <\u5730\u65b9>\u300d\u518d\u4fc2\u904e")
        except Exception:
            pass
        return
    if act == "go":
        await engine.asyncio.to_thread(engine._nav_run_go, job)
        try:
            await q.edit_message_text(
                f"\U0001F5FA \u5df2\u958b\u5730\u5716\u53bb\u300c{job.get('label')}\u300d")
        except Exception:
            pass
    else:
        try:
            await engine.asyncio.to_thread(
                engine.subprocess.run, ["termux-notification-remove", f"nav{job.get('id', 0)}"],
                capture_output=True, timeout=6)
        except Exception:
            pass
        try:
            await q.edit_message_text(
                "\u2702\u6536\u5de5\uff0c\u5187\u958b\u5730\u5716")
        except Exception:
            pass
    engine._PENDING_NAVS.pop(nid, None)



# 停用中（2026-09-25 用戶決定：有 TG 掣後唔再用彈窗），函數保留做後備
async def _nav_dialog_task(job: dict) -> None:
    """彈窗確認任務：彈窗等用戶撳；撳【是】→ 開地圖；【否】→ 清通知收工。
    鎖屏時彈窗活動照起，解鎖後個窗仲喺度等撳——唔會錯過。"""
    loop = engine.asyncio.get_event_loop()
    try:
        ans = await loop.run_in_executor(None, engine._nav_dialog_block, job)
    except Exception:
        return
    if ans == "err":
        # 好可能啱啱俾通知橫額搶咗焦點——2 秒後重彈一次
        engine.logging.info("彈窗#%s err——2 秒後重彈一次", job.get("id", 0))
        await engine.asyncio.sleep(2)
        try:
            ans = await loop.run_in_executor(None, engine._nav_dialog_block, job)
        except Exception:
            return
    nid = f"nav{job.get('id', 0)}"
    label = job.get("label") or job.get("url", "")
    engine.logging.info("彈窗#%s → %s（去「%s」）", job.get("id", 0), ans, label)
    if ans == "yes":
        engine._nav_run_go(job)
    else:
        try:
            await engine.asyncio.to_thread(
                engine.subprocess.run, ["termux-notification-remove", nid],
                capture_output=True, timeout=6)
        except Exception:
            pass



def _open_nav(dest: str, mode: str = "r") -> tuple:
    """開 Google Maps 導航，rish（Shizuku/adb shell）優先，三重後備：
    ⓪ rish＋喚醒螢幕（vivo/小米 背景閘剋星；有 Shizuku 一定行呢步）
    ① google.navigation VIEW ② MapsActivity 明部件開 https dir
    ③ https dir 交畀系統揀 app（Maps 有事嗰啲手機可以用瀏覽器檔）。
    純文字→google.navigation:q=…；連結/geo URI→直接開。"""
    import urllib.parse
    uri = engine._nav_uri(dest, mode)
    base = ["am", "start", "--activity-clear-task",
            "-a", "android.intent.action.VIEW", "-d", uri]
    if engine._rish_available() or engine._adb_lane_available():
        ok, out = engine._shell_priv_exec(
            "input keyevent KEYCODE_WAKEUP; " + engine.shlex.join(base))
        if ok:
            engine.log.info("導航已經 uid2000 通道（rish/adb lane）發出")
            return ok, out
        engine.log.info("uid2000 通道發送失敗，轉返普通 am：%s", out[:120])
    ok, out = engine.run_intent(base)
    if ok:
        return ok, out
    tmode = {"r": "transit", "w": "walking", "d": "driving"}.get(mode, "transit")
    web = (f"https://www.google.com/maps/dir/?api=1&destination="
           f"{urllib.parse.quote(dest)}&travelmode={tmode}")
    ok, out = engine.run_intent(["am", "start", "--activity-clear-task", "-n",
                          "com.google.android.apps.maps/com.google.android.maps.MapsActivity",
                          "-d", web])
    if ok:
        return ok, out
    return engine.run_intent(["am", "start", "--activity-clear-task",
                       "-a", "android.intent.action.VIEW", "-d", web])



def _fmt_dests() -> str:
    d = engine._dests()
    if not d:
        return ("📍 仲未有地點。send：地點 公司 沙田石門安群街1號\n"
                "之後可以：導航 公司・每日 0830 導航 公司・導航 公司 步行")
    lines = ["📍 已儲存地點："]
    for name, dest in d.items():
        disp = dest if len(dest) <= 40 else dest[:37] + "…"
        lines.append(f"・{name}：{disp}")
    lines.append("用法：導航 公司 [步行]（預設巴士）・0830 導航 公司・每日 0830 導航 公司・刪地點 公司")
    return "\n".join(lines)
