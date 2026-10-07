"""calm 域——每日提醒＋自動開 Calm app（2026-10-07 用戶令）。

用戶需求：「手機有個 app 叫 calm 幫我冥想，但我成日唔記得開」。
拍板：方案 B（TG 提醒＋自動開 app）＋自訂時間。
實證：com.calm.android 喺部機；開通＝特權 lane monkey（LAUNCHER 1），
topResumedActivity=com.calm.android/.ui.home.MainActivity（2026-10-07）。

文法（最短式；用戶令：叫 calm 唔叫靜度）：
    calm            即刻：開 Calm＋確認
    2130 calm       排今日一次
    每日2130 calm   日日（同一時間撞→取代）
"""
from __future__ import annotations

import re

from . import engine
from .core import register_fire, register_formatter

CALM_PKG = "com.calm.android"


def _launch_calm() -> tuple:
    """開 Calm（特權 lane monkey；monkey 喺 Termux 直 exec 唔得＝實證）。"""
    if engine.DRY_RUN:
        return True, "DRY_RUN"
    engine._shell_priv_exec("input keyevent KEYCODE_WAKEUP")
    return engine._shell_priv_exec(
        f"monkey -p {CALM_PKG} -c android.intent.category.LAUNCHER 1")


def handle(t: str, chat_id: int = 0):
    """calm 文法前哨（_on_message pre-hook；唔關事回 None）。"""
    m = re.fullmatch(r"(每日|每天|everyday)?\s*(\d{3,4})?\s*calm",
                     t.strip(), re.IGNORECASE)
    if not m:
        return None
    daily = bool(m.group(1))
    now = engine.dt.datetime.now()
    if m.group(2):
        v = m.group(2)
        hh, mm = int(v[:-2]), int(v[-2:])
        if hh > 23 or mm > 59:
            return "❓ 時間要 hhmm。例：每日2130 靜度／靜度"
        # 同類型同時間撞 → 取代（同 _add_job 去重語義）
        old = [j["id"] for j in engine._jobs()
               if j.get("type") == "calm" and j.get("hh") == hh
               and j.get("mm") == mm]
        if old:
            for rid in old:
                _t = engine._TASKS.pop(rid, None)
                if _t:
                    _t.cancel()
            engine._save_json(engine.JOBS_PATH,
                              [j for j in engine._jobs()
                               if j["id"] not in old])
        nxt = engine._next_occurrence(now, hh, mm)
        job = engine._add_simple_job(chat_id, {
            "type": "calm", "daily": daily, "chat_id": chat_id,
            "hh": hh, "mm": mm, "next": nxt.isoformat()})
        day = "日日" if daily else (
            "今日" if nxt.date() == now.date() else "聽日")
        return (f"🧘 已排定（#{job['id']}）：{day} {hh:02d}:{mm:02d} "
                f"calm——會叫你＋自動開 Calm")
    # 即刻版
    ok, out = _launch_calm()
    if ok:
        return "🧘 開咗 Calm 俾你"
    return f"❌ 開唔到 Calm（特權 lane 死？）：自己開啦——{out[:80]}"


async def _fire(job: dict, now) -> None:
    """每日 calm 到點：開 Calm＋TG＋語音；daily 重排／一次性自清。"""
    ok, _out = _launch_calm()
    when = f"{job['hh']:02d}:{job['mm']:02d}"
    msg = (f"🧘 {when} calm 時間——開咗 Calm 俾你" if ok
           else f"🧘 {when} calm 時間——開唔到 Calm，自己開啦")
    await engine._send_safe(job["chat_id"], msg, "calm")
    await engine._say("calm 時間，開咗 Calm 俾你")
    engine._TASKS.pop(job["id"], None)
    if job.get("daily"):
        job["next"] = engine._next_occurrence(
            now, job["hh"], job["mm"]).isoformat()
        jobs = engine._jobs()
        for j in jobs:
            if j["id"] == job["id"]:
                j["next"] = job["next"]
        engine._save_json(engine.JOBS_PATH, jobs)
        engine._arm(job)
        return
    engine._save_json(engine.JOBS_PATH,
                      [j for j in engine._jobs() if j["id"] != job["id"]])


register_fire("calm")(_fire)


@register_formatter("calm")
def _fmt(job: dict) -> str:
    return "🧘 calm（開 Calm）"
