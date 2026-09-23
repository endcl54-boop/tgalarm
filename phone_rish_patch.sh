#!/data/data/com.termux/files/usr/bin/bash
# rish/Shizuku 整合：喺手機 Termux 一貼即用
# 作用：patch 行緊嘅 bot.py，導航改用 adb shell 身份彈出（繞過 vivo 背景閘），然後自動重啟 bot
set -u
python3 - <<'PATCHEOF'
import os, re, subprocess, sys, time

def find_bot():
    try:
        pids = subprocess.run(["pgrep", "-f", "bot.py"],
                              capture_output=True, text=True).stdout.split()
    except FileNotFoundError:
        pids = []
    for pid in pids:
        if pid == str(os.getpid()):
            continue
        try:
            args = open(f"/proc/{pid}/cmdline", "rb").read().decode("utf-8", "ignore").split("\0")
        except OSError:
            continue
        for a in args:
            if a.endswith("bot.py"):
                if os.path.isabs(a):
                    return a, pid
                try:
                    cwd = os.readlink(f"/proc/{pid}/cwd")
                except OSError:
                    cwd = os.getcwd()
                return os.path.join(cwd, a), pid
    return None, None

NEW = '''# ---- Shizuku / rish：用 adb shell 身份發 intent（vivo/小米 背景閘剋星） ----
_RISH_CACHE = {"t": 0.0, "ok": False}
_RISH_TTL = 600.0


def _rish_probe() -> bool:
    if not shutil.which("rish"):
        return False
    try:
        r = subprocess.run(["rish", "-c", "id"], capture_output=True, text=True, timeout=10)
        return r.returncode == 0 and "uid=2000" in (r.stdout + r.stderr)
    except Exception:
        return False


def _rish_available() -> bool:
    now = dt.datetime.now().timestamp()
    if now - _RISH_CACHE["t"] < _RISH_TTL:
        return _RISH_CACHE["ok"]
    _RISH_CACHE["ok"] = _rish_probe()
    _RISH_CACHE["t"] = now
    return _RISH_CACHE["ok"]


def _open_nav(dest: str, mode: str = "r") -> tuple:
    """⓪ rish（adb shell）優先 ① google.navigation VIEW ② 明部件 https ③ 系統 https。"""
    import urllib.parse
    if re.match(r"^(https?:|geo:|google\\.)", dest, re.IGNORECASE):
        uri = dest
    else:
        uri = f"google.navigation:q={urllib.parse.quote(dest)}&mode={mode}"
    base = ["am", "start", "-a", "android.intent.action.VIEW", "-d", uri]
    if _rish_available():
        ok, out = run_intent(["rish", "-c",
                              "input keyevent KEYCODE_WAKEUP; " + shlex.join(base)])
        if ok:
            log.info("導航已經 rish（adb shell 身份）發出")
            return ok, out
        log.info("rish 發送失敗，轉返普通 am：%s", out[:120])
    ok, out = run_intent(base)
    if ok:
        return ok, out
    tmode = {"r": "transit", "w": "walking", "d": "driving"}.get(mode, "transit")
    web = (f"https://www.google.com/maps/dir/?api=1&destination="
           f"{urllib.parse.quote(dest)}&travelmode={tmode}")
    ok, out = run_intent(["am", "start", "-n",
                          "com.google.android.apps.maps/com.google.android.maps.MapsActivity",
                          "-d", web])
    if ok:
        return ok, out
    return run_intent(["am", "start", "-a", "android.intent.action.VIEW", "-d", web])

'''

p, pid = find_bot()
if not p:
    sys.exit("❌ 搵唔到行緊嘅 bot（bot.py 冇開住？先照舊同我一聲）")
src = open(p, encoding="utf-8").read()
if "_RISH_CACHE" in src:
    print("ℹ️ 已經 patch 過，跳去重啟")
else:
    src2, n = re.subn(
        r'def _open_nav\(dest: str, mode: str = "r"\) -> tuple:\n(?:.*?\n)+?(?=\ndef _fmt_dests)',
        NEW, src)
    if n != 1:
        sys.exit("❌ 搵唔到 _open_nav 分界（版本唔對？）")
    bak = p + ".bak_rish"
    open(bak, "w", encoding="utf-8").write(src)
    open(p, "w", encoding="utf-8").write(src2)
    chk = subprocess.run(["python3", "-m", "py_compile", p],
                         capture_output=True, text=True)
    if chk.returncode != 0:
        open(p, "w", encoding="utf-8").write(src)  # 還原
        sys.exit("❌ 語法檢查失敗，已還原：" + chk.stderr[:200])
    print("✅ 已 patch（備份喺 " + bak + "）")

# 重啟 bot
if pid:
    try:
        os.kill(int(pid), 15)
        time.sleep(1)
    except OSError:
        pass
d = os.path.dirname(p)
subprocess.run(["bash", "-c",
                f'cd "{d}" && nohup python3 bot.py >> ~/tgalarm.log 2>&1 &'])
time.sleep(4)
tail = subprocess.run(["bash", "-c", "tail -4 ~/tgalarm.log"],
                      capture_output=True, text=True)
alive = subprocess.run(["pgrep", "-fc", "bot.py"], capture_output=True, text=True).stdout.strip()
print("== bot 進程數:", alive, "== log 尾:")
print(tail.stdout)
print("✅ 完成。bot 重啟咗；試 send「排程」睇佢有冇應。")
PATCHEOF
