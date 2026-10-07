"""alarms：鬧鐘／計時／連環／倒數／專注／碎念域。"""
from __future__ import annotations

from . import engine

# ---------------- Android Intent（純函數，方便測試） ----------------

def timer_intent_cmd(seconds: int, label: str) -> list:
    return [
        "am", "start", "-a", "android.intent.action.SET_TIMER",
        "--ei", "android.intent.extra.alarm.LENGTH", str(int(seconds)),
        "--es", "android.intent.extra.alarm.MESSAGE", label or "Telegram 計時器",
        "--ez", "android.intent.extra.alarm.SKIP_UI", "true" if engine.SKIP_UI else "false",
    ]



def alarm_intent_cmd(hour: int, minute: int, label: str,
                     days: list | None = None) -> list:
    cmd = [
        "am", "start", "-a", "android.intent.action.SET_ALARM",
        "--ei", "android.intent.extra.alarm.HOUR", str(hour),
        "--ei", "android.intent.extra.alarm.MINUTES", str(minute),
        "--es", "android.intent.extra.alarm.MESSAGE", label or "Telegram 鬧鐘",
        "--ez", "android.intent.extra.alarm.SKIP_UI", "true" if engine.SKIP_UI else "false",
    ]
    if days:
        # EXTRA_DAYS＝Calendar 整數陣列（1=週日…7=週六）——app 原生循環鬧鐘
        cmd += ["--eia", "android.intent.extra.alarm.DAYS",
                ",".join(str(d) for d in days)]
    return cmd



DAILY = [1, 2, 3, 4, 5, 6, 7]   # 日日



# ---- 倒數日 ----

def _countdowns() -> dict:
    return engine._load_json(engine.COUNTDOWNS_PATH, {})



def _cd_abs(entry_date: str) -> engine.dt.date:
    y, m, d = (int(x) for x in entry_date.split("-"))
    return engine.dt.date(y, m, d)



def _countdown_days(entry: dict, today: engine.dt.date) -> int:
    if entry["kind"] == "abs":
        return (engine._cd_abs(entry["date"]) - today).days
    mm, dd = (int(x) for x in entry["date"].split("-"))
    try:
        d = engine.dt.date(today.year, mm, dd)
    except ValueError:
        d = engine.dt.date(today.year + 1, mm, dd)
    if d < today:
        d = engine.dt.date(today.year + 1, mm, dd)
    return (d - today).days



def _countdown_handle(t: str, chat_id: int):
    """倒數日：倒數 名 YYYY-MM-DD／倒數 名 MM-DD（每年）／倒數（清單）／刪倒數 名。"""
    if t in ("倒數", "倒數日"):
        cd = engine._countdowns()
        if not cd:
            return ("📅 仲未有倒數。例：倒數 考試 2027-05-04・倒數 聖誕 12-25（每年）")
        today = engine.dt.date.today()
        lines = ["📅 倒數日："]
        for name, e in cd.items():
            days = engine._countdown_days(e, today)
            when = e["date"] if e["kind"] == "abs" else f"{e['date']}（每年）"
            lines.append(f"・{name}：{'啱啱今日！' if days == 0 else f'仲有 {days} 日'}（{when}）")
        return "\n".join(lines)
    m = engine.re.fullmatch(r"(?:刪倒數|刪除倒數)\s+(.+)", t)
    if m:
        cd = engine._countdowns()
        if m.group(1).strip() in cd:
            del cd[m.group(1).strip()]
            engine._save_json(engine.COUNTDOWNS_PATH, cd)
            return f"🗑 已刪倒數「{m.group(1).strip()}」"
        return f"搵唔到倒數「{m.group(1).strip()}」"
    m = engine.re.fullmatch(r"倒數\s+(\S{1,20})\s+(\d{4}-\d{1,2}-\d{1,2}|\d{1,2}-\d{1,2})", t)
    if not m:
        return None
    name, ds = m.group(1), m.group(2)
    if engine.re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", ds):
        try:
            engine._cd_abs(ds)
        except ValueError:
            return "❓ 日期唔存在，格式：YYYY-MM-DD 或 MM-DD（每年）"
        entry = {"kind": "abs", "date": ds}
    else:
        try:
            mm, dd = (int(x) for x in ds.split("-"))
            engine.dt.date(2024, mm, dd)
        except ValueError:
            return "❓ 日期唔存在，格式：YYYY-MM-DD 或 MM-DD（每年）"
        entry = {"kind": "ann", "date": f"{mm:02d}-{dd:02d}"}
    cd = engine._countdowns()
    cd[name] = entry
    engine._save_json(engine.COUNTDOWNS_PATH, cd)
    days = engine._countdown_days(entry, engine.dt.date.today())
    tag = "（每年）" if entry["kind"] == "ann" else ""
    return f"📅 {name}：{'啱啱今日！' if days == 0 else f'仲有 {days} 日'}（{entry['date']}{tag}）"



# ---- 習慣提醒（每 N 分鐘 TG 提一次，取消 N 收）----

def _nag_handle(t: str, chat_id: int):
    if t == "提醒":
        nags = [j for j in engine._jobs() if j.get("type") == "nag"]
        if not nags:
            return "💧 仲未有習慣提醒。例：提醒 每60分 飲水（取消 N 收）"
        lines = ["💧 習慣提醒："]
        for j in nags:
            lines.append(f"・#{j['id']} 每{j.get('every', 3600) // 60}分 "
                         f"{j.get('label', '')}")
        return "\n".join(lines)
    m = engine.re.fullmatch(r"提醒\s*每\s*(\d{1,4})\s*分(鐘)?\s+(.+)", t)
    if not m:
        return None
    every = int(m.group(1)) * 60
    label = m.group(3).strip()
    now = engine.dt.datetime.now()
    job = engine._add_simple_job(chat_id, {
        "type": "nag", "every": every, "label": label, "chat_id": chat_id,
        "hh": now.hour, "mm": now.minute, "next": (now + engine.dt.timedelta(seconds=every)).isoformat()})
    return (f"💧 已設提醒（#{job['id']}）：每 {every // 60} 分鐘提你「{label}」"
            "——「取消 %d」收" % job["id"])



# ---- 專注模式（番茄鐘：工作/休息循環，用系統計時器響）----

def _focus_handle(t: str, chat_id: int):
    if t in ("專注結束", "唔專注", "收工專注"):
        fs = [j for j in engine._jobs() if j.get("type") == "focus"]
        if not fs:
            return "而家冇專注模式行緊。"
        for j in fs:
            engine._remove_job(j["id"])
        return "🛑 專注模式收工——下個循環唔會再響（時鐘 app 入面現有計時器自己剷）"
    m = engine.re.fullmatch(r"專注\s*(\d{1,3})?\s*(.*)", t)
    if not m:
        return None
    wmin = int(m.group(1)) if m.group(1) else 25
    if not 5 <= wmin <= 240:
        return "❓ 專注時長要 5–240 分鐘。例：專注 25"
    label = m.group(2).strip()[:40]
    bmin = max(5, wmin // 5)
    # 開新 session 前清走舊 focus job（一副中介准兩條鏈並行）
    for j in [x for x in engine._jobs() if x.get("type") == "focus"]:
        engine._remove_job(j["id"])
    # 唔預落（用戶否決 2026-09-29）：job next=now，即刻 fire 落第一個鐘
    now = engine.dt.datetime.now()
    engine._add_simple_job(chat_id, {
        "type": "focus", "wmin": wmin, "bmin": bmin,
        "session_start": now.isoformat(),
        "label": label, "chat_id": chat_id,
        "hh": now.hour, "mm": now.minute, "next": now.isoformat()})
    tag = f"（{label}）" if label else ""
    return (f"🎯 專注模式開始{tag}：{wmin} 分鐘工作／{bmin} 分鐘休息循環"
            f"——即刻落第一個計時器。「專注結束」收工")



# ---------------- Telegram handlers（延後 import，等 parser 可以單獨測試） ----------------

def _add_bell(chat_id: int, fire_at: engine.dt.datetime, label: str,
              bell: str, daily: bool = False) -> dict:
    """統一 bot 守（2026-09-25 用戶決定）：計時/計時到/鬧鐘全部入排程，
    到點 bot 開 1 秒計時器即響。回傳 job。"""
    jobs = engine._jobs()
    jid = max((j["id"] for j in jobs), default=0) + 1
    job = {"id": jid, "type": "bell", "bell": bell, "hh": fire_at.hour,
           "mm": fire_at.minute, "daily": daily, "label": label,
           "chat_id": chat_id, "next": fire_at.isoformat(),
           "seconds": 0, "url": "", "shuffle": False, "paused": False}
    jobs.append(job)
    engine._save_json(engine.JOBS_PATH, jobs)
    engine._arm(job)
    return job
