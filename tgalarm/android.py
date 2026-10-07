"""android：Android 執行 lane（adb→rish 特權通道／探活快取）。"""
from __future__ import annotations

from . import engine

# ---- Shizuku / rish：用 adb shell 身份發 intent ----
# vivo/小米等廠就算攞齊「後台彈窗」權限，仍會對 Termux 呢類背景 app 靜默截糊；
# 但 rish 令指令以 shell（uid 2000）執行——shell 係特權 caller，唔經嗰道閘。
_RISH_CACHE = {"t": 0.0, "ok": False}

_RISH_TTL = 600.0  # 10 分鐘 TTL：Shizuku 重開機會停，用戶重啟之後快啲執返



def _rish_probe() -> bool:
    """真實探測：rish 喺 PATH + Shizuku 行緊（見到 uid=2000 先用得）。"""
    if not engine.shutil.which("rish"):
        return False
    try:
        r = engine.subprocess.run(["rish", "-c", "id"], capture_output=True, text=True, timeout=10)
        return r.returncode == 0 and "uid=2000" in (r.stdout + r.stderr)
    except Exception:
        return False



def _rish_available() -> bool:
    """帶 TTL 快取嘅可用性（負面都快取，免至每次導航都開 JVM 探測）。"""
    now = engine.dt.datetime.now().timestamp()
    if now - engine._RISH_CACHE["t"] < engine._RISH_TTL:
        return engine._RISH_CACHE["ok"]
    engine._RISH_CACHE["ok"] = engine._rish_probe()
    engine._RISH_CACHE["t"] = now
    return engine._RISH_CACHE["ok"]



# ---- ADB lane：Termux 自攜 adb（第三條 uid 2000 通道）----
# adbd tcpip 模式喺 127.0.0.1:5555 已授權（免配對）；呢條路唔使 Shizuku，
# rish 死咗（電話重啟／Shizuku 俾人殺）都可以照樣用 shell 身份發 intent。
ADB_TARGET = "127.0.0.1:5555"

_ADB_CACHE = {"t": 0.0, "ok": False}

_ADB_TTL = 600.0



def _adb_shell(shell_cmd: str, timeout: int = 10) -> tuple:
    """經 adb lane 行 shell 指令；回傳 (ok, 輸出)。"""
    adb = engine.shutil.which("adb")
    if not adb:
        return False, "搵唔到 adb 指令（pkg install android-tools）"
    try:
        r = engine.subprocess.run([adb, "-s", engine.ADB_TARGET, "shell", shell_cmd],
                           capture_output=True, text=True, timeout=timeout)
        out = (r.stdout + r.stderr).strip()
        return r.returncode == 0, out
    except engine.subprocess.TimeoutExpired:
        return False, "adb shell 超時"
    except Exception as e:
        return False, str(e)



def _adb_lane_probe() -> bool:
    """真實探測：行到 id 攞到 uid=2000 先算；斷咗會試重連一次。"""
    adb = engine.shutil.which("adb")
    if not adb:
        return False
    ok, out = engine._adb_shell("id")
    if ok and "uid=2000" in out:
        return True
    try:
        engine.subprocess.run([adb, "connect", engine.ADB_TARGET], capture_output=True,
                       text=True, timeout=8)
    except Exception:
        pass
    ok, out = engine._adb_shell("id")
    return ok and "uid=2000" in out



def _adb_lane_available() -> bool:
    now = engine.dt.datetime.now().timestamp()
    if now - engine._ADB_CACHE["t"] < engine._ADB_TTL:
        return engine._ADB_CACHE["ok"]
    engine._ADB_CACHE["ok"] = engine._adb_lane_probe()
    engine._ADB_CACHE["t"] = now
    return engine._ADB_CACHE["ok"]



def _shell_priv_exec(cmd_str: str) -> tuple:
    """統一嘅 uid 2000 執行：adb lane（自攜 127.0.0.1:5555）優先，死咗用 rish。
    adb lane 唔使 Shizuku 行緊，少一個單點故障；用戶實測通知掣路穩。
    回傳 (ok, 輸出)；兩條都冇 → (False, 原因)。"""
    if engine._adb_lane_available():
        ok, out = engine._adb_shell(cmd_str)
        if ok:
            return ok, out
    if engine._rish_available():
        return engine.run_intent(["rish", "-c", cmd_str])
    return False, "adb lane 同 rish 都唔喺度"
