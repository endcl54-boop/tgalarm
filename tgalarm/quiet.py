"""quiet：靜音時段——自定義每日時段暫停語音（2026-10-07 用戶令）。

拍板：TTS 全靜（TG 訊息照出）＋每日時段制＋最短式文法：
    靜音 2300 0730   日日 23:00–07:30 唔出聲（過午夜自動處理）
    取消靜音         解除（靜音完／靜音結束 同義）
    靜音             查現況
機制：quiet 域 import 期經 engine._QUIET_CHECK 註冊檢查函數；
engine._say 開頭檢查，時段內直接早退（唔出 TTS，log 記低）。
"""
from __future__ import annotations

from . import engine


def _win() -> dict:
    return engine._load_json(engine.QUIET_PATH, {})


def in_window(now=None) -> bool:
    """而家（或指定時間）喺唔喺靜音時段內。s>e＝過午夜。"""
    w = _win()
    if w.get("s") is None or w.get("e") is None:
        return False
    if now is None:
        now = engine.dt.datetime.now()
    cur = now.hour * 60 + now.minute
    s, e = int(w["s"]), int(w["e"])
    return (cur >= s or cur < e) if s > e else (s <= cur < e)


def _fmt(m: int) -> str:
    return f"{m // 60:02d}{m % 60:02d}"


def handle(t: str):
    """靜音文法前哨（_on_message pre-hook；唔關事回 None）。"""
    if t == "靜音":
        w = _win()
        if w.get("s") is None:
            return "而家冇靜音時段。例：靜音 2300 0730（日日呢段唔出聲）"
        tag = "——而家靜緊" if in_window() else ""
        return (f"🔇 靜音時段：{_fmt(w['s'])}–{_fmt(w['e'])}"
                f"（日日，TG 照出）{tag}")
    if t in ("取消靜音", "靜音完", "靜音結束"):
        if _win().get("s") is None:
            return "本來就冇靜音。"
        engine._save_json(engine.QUIET_PATH, {})
        return "🔊 靜音解除——語音恢復"
    m = engine.re.fullmatch(r"靜音\s*(\d{3,4})\s+(\d{3,4})", t)
    if not m:
        return None
    s = int(m.group(1)[:-2]) * 60 + int(m.group(1)[-2:])
    e = int(m.group(2)[:-2]) * 60 + int(m.group(2)[-2:])
    if m.group(1)[:2] in ("24",) or s > 1439 or e > 1439 or s == e:
        return "❓ 時間要 hhmm 兩個唔同。例：靜音 2300 0730"
    engine._save_json(engine.QUIET_PATH, {"s": s, "e": e})
    cross = "（過午夜）" if s > e else ""
    tag = "——而家靜緊" if in_window() else ""
    return (f"🔇 已設定：日日 {_fmt(s)}–{_fmt(e)}{cross} 唔出聲"
            f"（TG 訊息照出）{tag}")


# 註冊：engine._say 每次出聲前問呢個 hook（import 期＝域載入即生效）
engine._QUIET_CHECK = in_window
