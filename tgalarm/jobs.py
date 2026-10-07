"""jobs：排程倉 CRUD＋列表／暫停／恢復／編輯／下一任務行。"""
from __future__ import annotations

from . import core, engine


def _add_simple_job(chat_id: int, job: dict) -> dict:
    jobs = engine._jobs()
    # monotonic ID（2026-10-07 用戶令「號碼跳得好犀利」）：已用 ID 記喺
    # JOBS_PATH 旁 _ids.json，剷咗嘅 job 號碼都唔會攞返——號碼只會向上升
    ids_path = engine.JOBS_PATH.replace(".json", "") + "_ids.json"
    try:
        hi = int(engine._load_json(ids_path, {"hi": 0})["hi"])
    except (TypeError, KeyError, ValueError):
        hi = 0
    jid = max(hi, max((j["id"] for j in jobs), default=0)) + 1
    engine._save_json(ids_path, {"hi": jid})
    job["id"] = jid
    job.setdefault("daily", False)
    job.setdefault("seconds", 0)
    job.setdefault("url", "")
    job.setdefault("shuffle", False)
    job.setdefault("paused", False)
    jobs.append(job)
    engine._save_json(engine.JOBS_PATH, jobs)
    engine._arm(job)
    return job



def _jobs() -> list:
    return engine._load_json(engine.JOBS_PATH, [])



def _fmt_job_content(j: dict) -> str:
    """列表/訊息用嘅排程內容描述。"""
    fmt = core.JOB_FORMATTERS.get(j.get("type", ""))
    if fmt:                     # S13 收口：註冊表優先（takeaway 等）
        return fmt(j)
    if j.get("type") == "webplay":
        return f"網播 {j.get('label', '')}"
    if j.get("type", "play") == "timer":
        tag = f"（{j['label']}）" if j.get("label") else ""
        return f"計時 {engine.fmt_duration(j.get('seconds', 0))}{tag}"
    if j.get("type") == "nav":
        return f"導航去「{j['label']}」"
    if j.get("type") == "weather":
        return "天氣簡報"
    if j.get("type") == "bell":
        pre = "語音提醒" if j.get("bell") == "timer" else "響"
        return f"{pre}：{j.get('label') or '時間到'}"
    if j.get("type") == "series":
        return (f"每{(j.get('every') or 0) // 60}分鐘 "
                f"{j['hh']:02d}:{j['mm']:02d}–{j.get('end_hh', 0):02d}:{j.get('end_mm', 0):02d} "
                f"{j.get('label') or '時間到'}")
    if j.get("type") == "web":
        return f"開網頁「{j.get('label')}」"
    if j.get("type") == "seal":
        return "、".join(f"{x['label']}→{x['until']}" for x in j.get("apps", []))
    if j.get("type") == "nag":
        return f"每{(j.get('every') or 3600) // 60}分 {j.get('label', '')}"
    if j.get("type") == "focus":
        return (f"專注 {j.get('wmin', 25)}/{j.get('bmin', 5)}"
                + (f"（{j['label']}）" if j.get("label") else ""))
    if j.get("type") == "battery":
        return f"電量守 ≤{j.get('thr', 20)}%"
    if j.get("type") == "bthead":
        return f"耳機守 ≤{j.get('thr', 60)}%"
    if j.get("type") == "takeaway_on":
        return "排定開外賣模式"
    if j.get("type") == "takeaway_off":
        return "排定收外賣模式"
    if j.get("type") in ("sched_pause", "sched_resume"):
        act = "暫停" if j["type"] == "sched_pause" else "繼續"
        ids = j.get("ids") or []
        return f"排定{act}排程：" + ("、".join(f"#{i}" for i in ids) if ids else "全部")
    if j.get("type") == "alloc":
        segs = j.get("segments", [])
        names = "、".join(s["text"] for s in segs)
        if len(names) > 24:
            names = names[:21] + "…"
        return f"分配 {names}（{len(segs)}項）"
    return (f"播「{j['label']}」" + ("🔀" if j.get("shuffle") else "")
            + (f" 🔊{j['vol']}%" if j.get("vol") is not None else ""))



def _fmt_jobs(now: engine.dt.datetime) -> str:
    jobs = engine._jobs()
    tw = ("\n🛵 外賣模式生效——計時提早 5 分鐘響（「外賣結束」收工）"
          if engine._TAKEAWAY.get("on") else "")
    if not jobs:
        return ("🗓 冇排程。例：每日 0700 播 lofi・2130 播・"
                "每日 0900 計時 25分鐘・每日 0800 導航 公司" + tw)
    lines = ["🗓 排程："]
    if engine._TAKEAWAY.get("on"):
        lines.append("🛵 外賣模式生效——計時提早 5 分鐘響（「外賣結束」收工）")
    for j in jobs:
        kind = "每日" if j.get("daily") else "一次"
        icon = {"timer": "⏱", "nav": "🧭", "alloc": "🧩", "series": "⏰",
                "bell": "⏰", "weather": "🌤", "web": "🌐", "nag": "💧",
                "focus": "🎯", "battery": "🔋", "bthead": "🎧",
                "takeaway_on": "🛵", "takeaway_off": "🏁",
                "sched_pause": "⏸", "sched_resume": "▶️"}.get(j.get("type"), "🎵")
        if j.get("paused"):
            state = "（⏸已暫停）"
        else:
            nxt = engine.dt.datetime.fromisoformat(j["next"])
            state = f"→ {engine.day_label(nxt, now)} {nxt:%H:%M}"
        lines.append(f"#{j['id']} {icon}{kind} {j['hh']:02d}:{j['mm']:02d} {engine._fmt_job_content(j)} {state}")
    lines.append("管理：取消 N・暫停 N・繼續 N・改 N <時間/每日/一次/歌單/時長>"
                 "・暫停排程＝全部停・繼續排程＝全部恢復"
                 "・mmdd 暫停/繼續排程 N＝排定日期")
    return "\n".join(lines)



def _add_job(cmd: engine.PlayerCmd, chat_id: int, now: engine.dt.datetime,
             url: str = "", seconds: int = 0, mode: str = "d", label: str = "",
             pl: str = "") -> tuple:
    """新增排程；同類型同時間嘅舊排程會被取代。回傳 (job, 被取代嘅 id 列表)。"""
    is_timer = cmd.action in ("sched_timer", "sched_timer_daily")
    is_nav = cmd.action in ("sched_nav", "sched_nav_daily")
    is_web = cmd.action in ("sched_web", "sched_web_daily")
    is_webplay = cmd.action in ("sched_webplay", "sched_webplay_daily")
    is_series = cmd.action in ("series", "series_daily")
    is_alarm = cmd.action == "sched_alarm_daily"
    jtype = ("series" if is_series
             else ("timer" if is_timer
                   else ("nav" if is_nav
                         else ("web" if is_web
                               else ("bell" if is_alarm
                                     else ("webplay" if is_webplay
                                           else "play"))))))
    jobs = engine._jobs()
    # 去重：同類型 + 同 hh:mm  collide → 取代舊嘅
    replaced = [j["id"] for j in jobs
                if j.get("type", "play") == jtype and j["hh"] == cmd.hour and j["mm"] == cmd.minute]
    for rid in replaced:
        t = engine._TASKS.pop(rid, None)
        if t:
            t.cancel()
    jobs = [j for j in jobs if j["id"] not in replaced]

    ids_path = engine.JOBS_PATH.replace(".json", "") + "_ids.json"
    try:
        hi = int(engine._load_json(ids_path, {"hi": 0})["hi"])
    except (TypeError, KeyError, ValueError):
        hi = 0
    jid = max(hi, max((j["id"] for j in jobs), default=0)) + 1
    engine._save_json(ids_path, {"hi": jid})
    if is_timer or is_series:
        default_label = ""
    elif is_nav:
        default_label = "目的地"
    elif is_web:
        default_label = "網頁"
    else:
        default_label = engine._playlists().get("default") or "歌單"
    first = engine._next_occurrence(now, cmd.hour, cmd.minute)
    job = {"id": jid, "type": jtype, "hh": cmd.hour, "mm": cmd.minute,
           "daily": cmd.action in ("sched_daily", "sched_timer_daily",
                                   "sched_nav_daily", "sched_web_daily",
                                   "sched_webplay_daily",
                                   "series_daily", "sched_alarm_daily"),
           "url": url, "playlist": pl, "seconds": seconds, "mode": mode,
           "label": label or cmd.ref or default_label,
           "chat_id": chat_id, "next": first.isoformat(),
           "shuffle": cmd.shuffle, "vol": cmd.vol, "paused": False}
    if is_series:
        job["end_hh"] = cmd.hour2
        job["end_mm"] = cmd.minute2
        job["every"] = seconds
    jobs.append(job)
    engine._save_json(engine.JOBS_PATH, jobs)
    engine._arm(job)
    return {"next_dt": first, **job}, replaced



def _pause_job(jid: int):
    """暫停排程（保留設定，唔會觸發）。回傳 True/「already」/False。"""
    jobs = engine._jobs()
    for j in jobs:
        if j["id"] == jid:
            if j.get("paused"):
                return "already"
            j["paused"] = True
            engine._save_json(engine.JOBS_PATH, jobs)
            t = engine._TASKS.pop(jid, None)
            if t:
                t.cancel()
            return True
    return False



def _resume_job(jid: int, now: engine.dt.datetime):
    """恢復排程，重新計下一次觸發。回傳下次觸發 datetime 或 None。"""
    jobs = engine._jobs()
    for j in jobs:
        if j["id"] == jid:
            j["paused"] = False
            nxt = engine._next_occurrence(now, j["hh"], j["mm"])
            j["next"] = nxt.isoformat()
            engine._save_json(engine.JOBS_PATH, jobs)
            engine._arm(j)
            return nxt
    return None



def _pause_all() -> tuple:
    """全部暫停。回傳 (新暫停數, 排程總數)。已暫停嘅唔計入新暫停。"""
    jobs = engine._jobs()
    n = 0
    for j in jobs:
        if engine._pause_job(j["id"]) is True:
            n += 1
    return n, len(jobs)



def _resume_all(now: engine.dt.datetime) -> int:
    """全部恢復（淨處理暫停緊嘅；在行緊嘅唔會郁）。回傳恢復數。"""
    paused = [j["id"] for j in engine._jobs() if j.get("paused")]
    n = 0
    for jid in paused:
        if engine._resume_job(jid, now) is not None:
            n += 1
    return n



def _edit_job(jid: int, body: str, now: engine.dt.datetime) -> tuple:
    """就地修改排程：hhmm 改時間・每日/一次 改循環・歌單[隨機]/時長 改內容。"""
    jobs = engine._jobs()
    job = next((j for j in jobs if j["id"] == jid), None)
    if not job:
        return False, f"搵唔到 #{jid}。send「排程」睇編號"
    rest, changes = body.strip(), []
    vm = engine.re.search(r"音量\s*(\d{1,3})\s*%", rest)   # 改 N 音量50%（2026-10-06）
    if vm:
        if int(vm.group(1)) > 100:
            return False, "音量要 0–100。例：改 N 音量50%"
        if job.get("type", "play") != "play":
            return False, "呢類任務冇音量（淨播歌任務有）"
        job["vol"] = int(vm.group(1))
        changes.append(f"音量→{job['vol']}%")
        rest = engine.re.sub(r"\s+", " ",
                      (rest[:vm.start()] + " " + rest[vm.end():]).strip())
    r = engine._read_hhmm(rest)
    if r:
        hh, mm, rest = r
        job["hh"], job["mm"] = hh, mm
        changes.append(f"時間→{hh:02d}:{mm:02d}")
    if engine.re.fullmatch(r"(?:每日|每天)", rest, engine.re.IGNORECASE):
        job["daily"] = True
        rest = ""
        changes.append("改做每日")
    elif engine.re.fullmatch(r"一次", rest):
        job["daily"] = False
        rest = ""
        changes.append("改做一次")
    elif rest:
        if job.get("type", "play") == "timer":
            seconds, end = engine._parse_duration(rest)
            if seconds <= 0:
                return False, f"計時內容睇唔明：{rest}"
            job["seconds"] = seconds
            if rest[end:].strip():
                job["label"] = rest[end:].strip()
            changes.append(f"內容→計時 {engine.fmt_duration(seconds)}")
        elif job.get("type") == "nav":
            dest, mode, shown = engine._nav_target(rest)
            job["url"] = dest
            job["mode"] = mode
            job["label"] = shown
            changes.append(f"內容→導航去「{shown}」（{engine._mode_label(mode)}）")
        elif job.get("type") == "alloc":
            return False, "分配內容改唔到局部，send「取消 N」再排過"
        else:
            ref, sh = engine._strip_shuffle(rest)
            url, info = engine._resolve_playlist(ref)
            if url is None:
                return False, info
            job["url"] = url
            if ref:
                job["label"] = ref
            job["shuffle"] = sh
            changes.append(f"內容→播「{info or job['label']}」" + ("🔀" if sh else ""))
    if not changes:
        return False, ("支援：改 N hhmm｜改 N 每日｜改 N 一次｜改 N 歌單名 [隨機]"
                       "｜改 N 時長｜改 N 地點名｜改 N 音量50%（播歌任務）")
    job["next"] = engine._next_occurrence(now, job["hh"], job["mm"]).isoformat()
    engine._save_json(engine.JOBS_PATH, jobs)
    t = engine._TASKS.pop(jid, None)
    if t:
        t.cancel()
    if not job.get("paused"):
        engine._arm(job)
    return True, "、".join(changes)



def _replaced_note(replaced: list) -> str:
    if not replaced:
        return ""
    return "\n（已自動取代同時間嘅 #" + "、#".join(str(i) for i in replaced) + "）"



def _remove_job(jid: int) -> bool:
    jobs = engine._jobs()
    remain = [j for j in jobs if j["id"] != jid]
    t = engine._TASKS.pop(jid, None)     # json 已冇呢 job 都照 cancel——殭屍鏈就係舊版早退唔 cancel 生出嚟
    if t:
        try:
            t.cancel()
        except RuntimeError:
            pass                  # 屍體任務（loop 已滅）唔使理
    if len(remain) == len(jobs):
        return False
    engine._save_json(engine.JOBS_PATH, remain)
    return True



def _clear_jobs() -> int:
    n = len(engine._jobs())
    engine._save_json(engine.JOBS_PATH, [])
    for t in engine._TASKS.values():
        t.cancel()
    engine._TASKS.clear()
    return n



async def _restore_jobs(app) -> None:
    """bot 啟動/重開後：每日排程重新計下一次；過期嘅一次排程即刻補播。"""

    _APP = app
    now = engine.dt.datetime.now()
    jobs = engine._jobs()
    changed = False
    for job in jobs:
        try:
            nxt = engine.dt.datetime.fromisoformat(job["next"])
        except (KeyError, ValueError):
            continue
        if job.get("daily") and nxt <= now:
            job["next"] = engine._next_occurrence(now, job["hh"], job["mm"]).isoformat()
            if job.get("type") == "alloc":
                job["idx"] = 0  # 分配鏈由頭嚟過
                job["_rem"] = 0
            changed = True
    if changed:
        engine._save_json(engine.JOBS_PATH, jobs)
    for job in jobs:
        if job.get("paused"):
            continue
        engine._arm(job)
    if jobs:
        engine.log.info("已恢復 %d 個播放排程", len(jobs))
    # 待辦清單：啟動時更新返條置頂訊息（如果存在過）
    st = engine._todos()
    if st.get("msg_id") and st.get("chat_id"):
        try:
            await engine._refresh_todo(st["chat_id"])
        except Exception as e:
            engine.log.warning("啟動時更新待辦訊息失敗：%s", e)



def _next_task_line(now: engine.dt.datetime | None = None) -> str:
    """下一個排緊嘅任務（focus 進行中唔計）→ 一句廣東話。"""
    now = now or engine.dt.datetime.now()
    cand = []
    for j in engine._jobs():
        if j.get("paused") or j.get("type") == "focus" or not j.get("next"):
            continue
        try:
            cand.append((engine.dt.datetime.fromisoformat(j["next"]), j))
        except ValueError:
            continue
    if not cand:
        return "而家冇排緊任何任務。"
    nxt, job = min(cand, key=lambda p: p[0])
    content = engine._speech_scrub(engine._fmt_job_content(job)) or "任務"
    return f"{engine._cjk_when(nxt, now)}，{content}"
