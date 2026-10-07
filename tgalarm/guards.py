"""guards：守護域（電量守／耳機守／封印防線）。"""
from __future__ import annotations

from . import engine

# ---- 電量（termux-battery-status 優先，sysfs 後備）----

def _battery_chg(d: dict) -> bool:
    """termux-battery-status JSON → 充電中？
    ★plugged 新版係字串（"PLUGGED_AC"/"UNPLUGGED"），舊版係整數——
    bool("UNPLUGGED")=True 曾令 chg 永遠 True、電量守永久靜默
    （2026-10-06 用戶個案破案），必要型別分流＋startswith（"UNPLUGGED"
    內含 PLUGGED 子串，唔可以用 in）。"""
    if str(d.get("status", "")).lower() in ("charging", "full"):
        return True
    p = d.get("plugged")
    if isinstance(p, str):
        return p.upper().startswith("PLUGGED")
    return bool(p)



def _battery_status() -> tuple:
    """回傳 (剩電%, 充電中?, 溫度℃ or None) 或 (None, None, 錯誤訊息)。
    2026-10-06 加固：Termux:API 偶發死火（真機個案：13:2x 一次
    Permission denied—sysfs fallback 又被 vivo 擋），retry 一發。"""
    for attempt in (1, 2):
        r = engine._battery_status_once()
        if r[0] is not None:
            return r
        if attempt == 1:
            import time as _t
            _t.sleep(3)
    return r



def _battery_status_once() -> tuple:
    """單發讀電（termux-battery-status → sysfs 後備）。"""
    try:
        r = engine.subprocess.run(["termux-battery-status"], capture_output=True,
                           text=True, timeout=6)
        if r.returncode == 0:
            d = engine.json.loads(r.stdout.strip() or "{}")
            pct = int(d.get("percentage", -1))
            chg = engine._battery_chg(d)
            temp = d.get("temperature")
            temp = round(float(temp) / 10.0, 1) if temp else None
            if pct >= 0:
                return pct, chg, temp
    except Exception:
        pass
    try:
        base = "/sys/class/power_supply/battery"
        pct = int(open(f"{base}/capacity", encoding="utf-8").read().strip())
        try:
            st = open(f"{base}/status", encoding="utf-8").read().strip().lower()
            chg = st in ("charging", "full")
        except Exception:
            chg = False
        try:
            temp = round(int(open(f"{base}/temp",
                                  encoding="utf-8").read().strip()) / 10.0, 1)
        except Exception:
            temp = None
        return pct, chg, temp
    except Exception as e:
        return None, None, str(e)



def _batt_line(pct, chg, temp) -> str:
    if pct is None:
        return f"❌ 電量攞唔到：{str(temp)[:80]}"
    bits = [f"🔋 {pct}%"]
    if chg:
        bits.append("⚡充電中")
    if temp is not None:
        bits.append(f"{temp}℃")
    return "・".join(bits)



# ---- 電量守（每 10 分鐘查一次，低過門檻又冇充電先警一次）----

# ---- 電量守（每 10 分鐘查一次，低過門檻又冇充電先警一次）----

# ---- 電量守（每 10 分鐘查一次，低過門檻又冇充電先警一次）----

# ---- 藍牙耳機電量守（2026-10-05 用戶令：≤60% 提醒叉電）----
# 數據源（真機實證 2026-10-05）：①SystemUI dump嘅 mConnectedDevices（邊隻連住）
# ②AdapterService --print dump 嘅 HFP +IPHONEACCEV 紀錄（電量，最後一筆）
_BT_SYSUI = "dumpsys activity service com.android.systemui"

_BT_ADAPTER = ("dumpsys activity service "
               "com.android.bluetooth/.btservice.AdapterService --print")



def _parse_bt_connected(sysui_out: str) -> list:
    """SystemUI dump → 連線中藍牙裝置 [(addr, name)]。"""
    out = []
    for m in engine.re.finditer(r"mConnectedDevices=\[[^\]]*\]", sysui_out or ""):
        for d in engine.re.finditer(
                r"anonymizedAddress=([0-9A-Fa-f:Xx]{8,}), name=([^,}\]]+)",
                m.group(0)):
            out.append((d.group(1).strip(), d.group(2).strip()))
    return out



def _parse_bt_battery(adapter_out: str) -> dict:
    """AdapterService dump → {addr: 電量%}（+IPHONEACCEV 最後一筆；key1=電量）。"""
    levels = {}
    for m in engine.re.finditer(
            r"valString=\+IPHONEACCEV=(\d+(?:,\d+)*),.*?device=([0-9A-Fa-f:Xx]{8,})",
            adapter_out or ""):
        toks = m.group(1).split(",")
        addr = m.group(2).strip()
        try:
            n = int(toks[0])
        except ValueError:
            continue
        vals = toks[1:]
        for i in range(0, min(2 * n, len(vals) - 1), 2):
            if vals[i] == "1":                     # key 1＝電量（HFP 十級制）
                try:
                    lv = int(vals[i + 1])
                except ValueError:
                    break
                if 0 <= lv <= 10:
                    # 十級制：頂級=滿電（真機實證 2026-10-05：100% 報 9；
                    # Sony 官方文檔：10 級顯示 100/70/50/10%——9→100，其餘 ×10）
                    levels[addr] = 100 if lv >= 9 else lv * 10
                break
    return levels



def _headset_levels() -> list:
    """真機讀數：連線中藍牙耳機 [(name, level 或 None)]。失敗 → (ok=False, err)。"""
    ok1, sysui = engine._shell_priv_exec(engine._BT_SYSUI)
    ok2, adapter = engine._shell_priv_exec(engine._BT_ADAPTER)
    if not (ok1 or ok2):
        return False, str(sysui or adapter)[:120]
    conn = engine._parse_bt_connected(sysui if ok1 else "")
    if not conn and ok2:
        conn = [(a, n) for a, n in engine._parse_bt_connected(adapter or "")]  # 冇都有
    lv = engine._parse_bt_battery(adapter if ok2 else "")
    out = [(name, lv.get(addr)) for addr, name in conn]
    return True, out



def _bthead_line(name: str, level, thr: int) -> str:
    if level is None:
        return f"🎧 {name}：讀唔到電量（耳機未報數，連一陣再查）"
    warn = "⚠️ ≤" + str(thr) + "% 記得叉電" if level <= thr else "夠電"
    return f"🎧 {name}：{level}%（{warn}）"



def _bthead_handle(t: str, chat_id: int):
    """耳機電量守：耳機（即查）・耳機守 60・耳機守完。"""
    if t == "耳機":
        ok, data = engine._headset_levels()
        if not ok:
            return f"❌ 耳機電量攞唔到（特權通道死咗）：{data}"
        if not data:
            return "🎧 而家冇藍牙耳機連住。"
        return "\n".join(engine._bthead_line(n, l, 60) for n, l in data)
    if t in ("耳機守完", "耳機守結束"):
        gs = [j for j in engine._jobs() if j.get("type") == "bthead"]
        if not gs:
            return "而家冇耳機守行緊。"
        for j in gs:
            engine._remove_job(j["id"])
        return "🎧 耳機守收工。"
    m = engine.re.fullmatch(r"耳機守\s*(\d{1,3})?", t)
    if not m:
        return None
    thr = int(m.group(1)) if m.group(1) else 60
    if not 5 <= thr <= 95:
        return "❓ 門檻要 5–95%。例：耳機守 60"
    now = engine.dt.datetime.now()
    job = engine._add_simple_job(chat_id, {
        "type": "bthead", "thr": thr, "alerted": False, "chat_id": chat_id,
        "hh": now.hour, "mm": now.minute, "next": now.isoformat()})
    return (f"🎧 耳機守開工（#{job['id']}）：每 10 分鐘查一次連住嘅耳機，"
            f"≤{thr}% 就提你叉電（提一次，回充 +5% 先重置）。「耳機守完」收")



def _battery_handle(t: str, chat_id: int):
    if t == "電量":
        return engine._batt_line(*engine._battery_status())
    if t in ("電量守完", "電量守結束"):
        gs = [j for j in engine._jobs() if j.get("type") == "battery"]
        if not gs:
            return "而家冇電量守行緊。"
        for j in gs:
            engine._remove_job(j["id"])
        return "🔋 電量守收工。"
    m = engine.re.fullmatch(r"電量守\s*(\d{1,3})?", t)
    if not m:
        return None
    thr = int(m.group(1)) if m.group(1) else 20
    if not 5 <= thr <= 90:
        return "❓ 門檻要 5–90%。例：電量守 20"
    now = engine.dt.datetime.now()
    job = engine._add_simple_job(chat_id, {
        "type": "battery", "thr": thr, "alerted": False, "chat_id": chat_id,
        "hh": now.hour, "mm": now.minute, "next": now.isoformat()})
    return (f"🔋 電量守開工（#{job['id']}）：每個鐘查一次，"
            f"低過 {thr}% 又冇充電就提你。「電量守完」收")



def _fg_pkg() -> str:
    """偵測前景 app package（dumpsys 兩式兜底）。失敗回空串。"""
    ok, out = engine._shell_priv_exec(
        "dumpsys activity activities | grep -E 'topResumedActivity|mResumedActivity' | head -2")
    if not ok:
        ok, out = engine._shell_priv_exec(
            "dumpsys window windows | grep mCurrentFocus | head -1")
    if ok and out:
        m = engine.re.search(r"u0\s+([\w.]+)/", str(out))
        if m:
            return m.group(1)
        m = engine.re.search(r"([\w.]+)/[\w.]*MainActivity", str(out))
        if m:
            return m.group(1)
    return ""



_PKG_ALIAS = {
    # 常用短手→package（substring 搜唔到嘅都照封得到，2026-09-30）
    "za": ["com.zhongan.ibank"],
    "zhongan": ["com.zhongan.ibank"],
    "shacom": ["com.shacom.android", "com.shacom.fps"],
    "alipay": ["hk.alipay.wallet"],
    "idlefish": ["com.taobao.idlefish"],
    "octopus": ["com.octopuscards.nfc_reader"],
    "sgame": ["com.tencent.tmgp.sgame"],
}



def _pkg_search(kw: str) -> list:
    """關鍵字搾第三方 package（pm list grep）＋別名表直達。"""
    pkgs = list(engine._PKG_ALIAS.get(kw.lower(), []))
    ok, out = engine._shell_priv_exec(
        f"pm list packages -3 | grep -i {engine.shlex.quote(kw)}")
    if ok:
        for ln in str(out).splitlines():
            ln = ln.strip()
            if ln.startswith("package:"):
                p = ln.split("package:", 1)[1].strip()
                if p and p not in pkgs:
                    pkgs.append(p)
    return pkgs[:8]



def _seal_jobs() -> list:
    return [j for j in engine._jobs() if j.get("type") == "seal"]



async def _say_hammer(text: str, times: int = 3) -> None:
    """最後聲道：時鐘 app 開唔到（深睡冷啟動）就 TTS 連環錘醒人。"""
    for i in range(times):
        await engine._say(text)
        if i < times - 1:
            await engine.asyncio.sleep(8)
