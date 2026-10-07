"""takeaway：外賣模式域（即開／即收／每日排程版）。"""
from __future__ import annotations

from . import engine


def _takeaway_set(on: bool) -> None:
    engine._TAKEAWAY["on"] = on
    engine._save_json(engine.TAKEAWAY_PATH, engine._TAKEAWAY)



def _takeaway_handle(t: str, chat_id: int = 0):
    """外賣模式開關（2026-09-27 用戶加）：開咗之後所有計時提早 5 分鐘響，
    直到「外賣結束」。2026-10-06 加排程版：「1100 外賣」／「1400 外賣結束」
    （空格可省）＝排定自動開／收（一次過 job）。回傳回覆文字；None=唔關事。"""
    m = engine.re.fullmatch(r"(每日|每天|everyday)?\s*(\d{3,4})\s*外賣\s*(結束|收工|收)?",
                     t, engine.re.IGNORECASE)
    if m:
        daily = bool(m.group(1))
        v = m.group(2)
        hh, mm = int(v[:-2]), int(v[-2:])
        if hh > 23 or mm > 59:
            return "❓ 時間要 hhmm。例：每日1100 外賣／每日1400 外賣結束"
        off = bool(m.group(3))
        now = engine.dt.datetime.now()
        nxt = engine._next_occurrence(now, hh, mm)
        # 同類型同時間撞 → 取代舊（同 _add_job 去重語義；2026-10-07 用戶令加每日版）
        jtype = "takeaway_off" if off else "takeaway_on"
        old = [j["id"] for j in engine._jobs()
               if j.get("type") == jtype and j.get("hh") == hh and j.get("mm") == mm]
        if old:
            for rid in old:
                _t = engine._TASKS.pop(rid, None)
                if _t:
                    _t.cancel()
            engine._save_json(engine.JOBS_PATH, [j for j in engine._jobs() if j["id"] not in old])
        job = engine._add_simple_job(chat_id, {
            "type": jtype, "daily": daily,
            "chat_id": chat_id, "hh": hh, "mm": mm,
            "next": nxt.isoformat()})
        day = ("日日" if daily
               else ("今日" if nxt.date() == now.date() else "聽日"))
        act = "收外賣模式" if off else "開外賣模式（計時提早 5 分鐘響）"
        return f"{'🏁' if off else '🛵'} 已排定（#{job['id']}）：{day} {hh:02d}:{mm:02d} 自動{act}"
    if t in ("外賣", "外賣開", "叫外賣", "外賣模式"):
        if engine._TAKEAWAY.get("on"):
            return "🛵 外賣模式開緊——計時照樣提早 5 分鐘響。「外賣結束」收工。"
        engine._takeaway_set(True)
        return ("🛵 外賣模式開！由而家起所有「計時／計時到」自動提早 5 分鐘響"
                "（例：25分鐘→20分鐘）。hhmm 後面嘅數字會當單號"
                "（例：計時 1830 25＝18:25 響＋單號25）。攞完嘢打「外賣結束」還原。")
    if t in ("外賣結束", "收外賣", "唔叫外賣"):
        if not engine._TAKEAWAY.get("on"):
            return "本來就冇開外賣模式。"
        engine._takeaway_set(False)
        return "✅ 外賣模式收工——計時還原，唔再提早響。"
    return None
