"""finance 域：GAS2「財務防護」app（層數／提議／活動／使咗）。

2026-10-07 整合、同日 S1 遷入套件；文法→(op, params)→JSON 門。
GAS project 1z25m5U…、deployment AKfycbxtoKU0…、v15（todayMinutes
計行緊＋stop_min 補時）。key 喺設定檔 GAS2_URL／GAS2_KEY。
"""
from __future__ import annotations

import json
import re

from . import core

GAS2_URL = core.config_get("GAS2_URL")
GAS2_KEY = core.config_get("GAS2_KEY")


def route(t: str):
    """財務防護文法 → (op, params)；唔關事回 None。最短式（用戶令）。"""
    # 洗左＝口語同義（2026-10-07 用戶實錄「洗左 10.6 地鐵」睇唔明）
    m = re.fullmatch(
        r"(?:使咗|使左|洗咗|洗左)\s*(\d+(?:\.\d+)?)\s*(想要|需要)?\s*(.*)", t)
    if m:
        return ("expense", {"amt": m.group(1), "kind": m.group(2),
                            "note": m.group(3).strip()})
    if t in ("層數", "狀態", "防護", "活動"):
        return ("status", {})
    if t == "提議":
        return ("pick", {})
    m = re.fullmatch(r"(?:活動完|停活動)\s*(\d+(?:\.\d+)?)?", t)
    if m:
        # 活動完 3＝按口供補時埋單（2026-10-07 個案：行緊嗰陣顯示 0）
        if m.group(1):
            return ("stop", {"mins": m.group(1)})
        return ("stop", {})
    m = re.fullmatch(r"活動\s+(.+)", t)
    if m:
        return ("start", {"name": m.group(1).strip()})
    return None


def api(op: str, params: dict) -> tuple:
    """叫財務防護 app 嘅 JSON 門（?op=&key=）。回 (ok, TG 文字)。"""
    import urllib.parse
    import urllib.request
    if not GAS2_URL:
        return False, "未設定 GAS2_URL（~/.tgalarm/config 加 GAS2_URL=<財務防護 /exec URL>）"
    q = {"op": op, "key": GAS2_KEY}
    q.update({k: v for k, v in params.items() if v})
    url = GAS2_URL + ("&" if "?" in GAS2_URL else "?") + urllib.parse.urlencode(q)
    try:
        with urllib.request.urlopen(url, timeout=25) as r:
            d = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return False, f"❌ 財務防護攞唔到：{str(e)[:120]}"
    if not d.get("ok"):
        return False, f"❌ {d.get('message', '唔知咩事')}"
    if op == "status":
        w = d.get("week") or {}
        act = d.get("activity") or {}
        run = act.get("running")
        lines = [f"🛡 財務防護（{w.get('weekStart')}–{w.get('weekEnd')}）",
                 (f"層 {w.get('layer')}/{w.get('layers')}（{w.get('mode')}）："
                  f"本週 ${w.get('quota')} 額度"),
                 f"用咗 ${w.get('spent')}（{w.get('pct')}%）｜剩 ${w.get('remaining')}"
                 + ("　⚠️ 超咗！" if w.get("over") else "")]
        lines.append(f"活動：{run['activity'] if run else '冇行緊'}"
                     f"｜今日 {act.get('todayMinutes', 0)} 分鐘")
        return True, "\n".join(lines)
    if op == "stop" and params.get("mins"):
        op = "stop_min"          # app 端 stop_min.mins＝手動補時埋單
    if op == "pick":
        p = d.get("pick") or {}
        return True, f"🎲 提議（{p.get('level', '')}）：{p.get('activity', '?')}"
    msg = d.get("message") or "✅ 搞掂"
    if op == "expense" and isinstance(d.get("status"), dict):
        msg += f"｜本週剩 ${d['status'].get('remaining')}"
    return True, msg
