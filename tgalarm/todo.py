"""todo：待辦＋時間分配域（todo 倉／alloc 分段快進）。"""
from __future__ import annotations

from . import engine


def _alloc_buf(num: str | None, unit: str | None) -> tuple:
    """留空選項：回傳 (百分比, 分鐘)。冇寫 → (0, 0)；% 同分鐘二擇一。
    1.5分鐘呢類小數會向下對齊成整分鐘（最少 0）。"""
    if not num or not unit:
        return 0, 0
    val = float(num)
    if unit == "%":
        return int(val), 0
    return 0, int(val)



# ---------------- 置頂待辦清單 ----------------

def _todos() -> dict:
    """結構：{items:[{id,text,done}], msg_id, chat_id, next_id}"""
    st = engine._load_json(engine.TODO_PATH, {})
    st.setdefault("items", [])
    st.setdefault("next_id", 1)
    return st



def _todo_add(text: str) -> int:
    """加一項或多項（、「，；」分隔）。回傳加咗幾多項。"""
    parts = [p.strip() for p in engine.re.split(r"[、，,;；]+", text) if p.strip()]
    if not parts:
        return 0
    st = engine._todos()
    for p in parts:
        st["items"].append({"id": st["next_id"], "text": p, "done": False})
        st["next_id"] += 1
    engine._save_json(engine.TODO_PATH, st)
    return len(parts)



def _todo_toggle_idx(idx: int, done: bool):
    """按顯示位置（1-based）標記完成/未完成。回傳項目文字或 None。"""
    st = engine._todos()
    if not (1 <= idx <= len(st["items"])):
        return None
    st["items"][idx - 1]["done"] = done
    engine._save_json(engine.TODO_PATH, st)
    return st["items"][idx - 1]["text"]



def _todo_del_idx(idx: int):
    st = engine._todos()
    if not (1 <= idx <= len(st["items"])):
        return None
    text = st["items"].pop(idx - 1)["text"]
    engine._save_json(engine.TODO_PATH, st)
    return text



def _todo_clear_done() -> tuple:
    """清除已完成項目。回傳 (清咗幾多, 剩返幾多)。"""
    st = engine._todos()
    keep = [it for it in st["items"] if not it.get("done")]
    n = len(st["items"]) - len(keep)
    if n:
        st["items"] = keep
        engine._save_json(engine.TODO_PATH, st)
    return n, len(keep)



def _todo_speech() -> str:
    """待辦清單→一句廣東話（打「待辦」時讀出）。"""
    st = engine._todos()
    if not st["items"]:
        return "待辦清單空晒"
    open_items = [it["text"] for it in st["items"] if not it.get("done")]
    if not open_items:
        return "待辦清單全清，好嘢"
    return (f"待辦清單，{len(open_items)} 項未完成："
            + "、".join(engine._speech_scrub(x) for x in open_items))



def _fmt_todos() -> str:
    st = engine._todos()
    items = st["items"]
    if not items:
        return "📋 待辦清單空晒。send：待辦 牛奶、交電費"
    lines = ["📋 待辦清單"]
    for i, it in enumerate(items, 1):
        mark = "✅" if it.get("done") else "☐"
        lines.append(f"{i}. {mark} {it['text']}")
    left = sum(1 for it in items if not it.get("done"))
    lines.append(f"（仲有 {left} 項未完成・撳下面按鈕打勾，或 send「完成 2」「刪 2」）")
    return "\n".join(lines)



def _todo_keyboard():
    """每項一粒核取方塊按鈕。lazy import 等純函數測試唔使裝 telegram。"""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    rows = []
    for i, it in enumerate(engine._todos()["items"], 1):
        mark = "✅" if it.get("done") else "⬜"
        rows.append([InlineKeyboardButton(
            f"{mark} {i}. {it['text'][:24]}", callback_data=f"todo:{it['id']}")])
    return InlineKeyboardMarkup(rows) if rows else None



def _schedule_todo_refresh(chat_id: int) -> None:
    """喺同步 executor 入面排程更新置頂訊息（bot 未啟動就靜靜雞 skip）。"""
    if engine._APP is None:
        return
    try:
        engine.asyncio.get_running_loop().create_task(engine._refresh_todo(chat_id))
    except RuntimeError:
        pass  # 冇 event loop（測試環境）



async def _refresh_todo(chat_id: int) -> None:
    """編輯置頂待辦訊息；訊息被刪/未存在就重發兼置頂。"""
    if engine._APP is None:
        return
    st, text, kb = engine._todos(), engine._fmt_todos(), engine._todo_keyboard()
    mid, cid = st.get("msg_id") or 0, st.get("chat_id") or chat_id
    if mid:
        try:
            await engine._APP.bot.edit_message_text(text, chat_id=cid, message_id=mid, reply_markup=kb)
            return
        except Exception as e:
            if "not modified" in str(e).lower():
                return
            engine.log.warning("更新待辦訊息失敗（%s），重發", e)
    try:
        m = await engine._APP.bot.send_message(chat_id, text, reply_markup=kb)
        st["msg_id"], st["chat_id"] = m.message_id, chat_id
        engine._save_json(engine.TODO_PATH, st)
        try:
            await engine._APP.bot.pin_chat_message(chat_id, m.message_id, disable_notification=True)
        except Exception as e:
            engine.log.warning("置頂失敗（可能權限問題）：%s", e)
    except Exception as e:
        engine.log.warning("待辦清單發送失敗：%s", e)



async def _on_todo_callback(update, context) -> None:
    """撳核取方塊 → 翻轉 done 並原地更新條訊息。"""
    q = update.callback_query
    m = engine.re.fullmatch(r"todo:(\d+)", q.data or "")
    if not m:
        return
    iid = int(m.group(1))
    st = engine._todos()
    item = next((it for it in st["items"] if it["id"] == iid), None)
    if item is None:
        await q.answer("項目已經刪咗")
        return
    item["done"] = not item.get("done")
    engine._save_json(engine.TODO_PATH, st)
    try:
        await q.edit_message_text(engine._fmt_todos(), reply_markup=engine._todo_keyboard())
    except Exception:  # "Message is not modified"
        pass
    await q.answer("✅ 完成！" if item["done"] else "☐ 還原咗，加油")



def _alloc_segments(items_text: str, buf_pct: int, total_sec: int,
                    buf_min: int = 0) -> tuple:
    """按 留空%／留空分鐘 + 加權 切時間。回傳 (segments, 錯誤訊息)；
    segments=[{"text","seconds"}, …]。
    比例寫法：項目後面 x2 / ×2 / *2；冇就當 1。最後一項食埋剩尾秒數，總和啱啱好。"""
    parts = [p.strip() for p in engine.re.split(r"[、，,／/；;]+", items_text) if p.strip()]
    if not parts:
        return None, "俾個項目清單先，例：`1930至2230 分配 温習、做功課`"
    items = []
    for p in parts:
        mm = engine.re.fullmatch(r"(.+?)\s*[xX×*]\s*(\d+(?:\.\d+)?)", p)
        if mm:
            name, w = mm.group(1).strip(), float(mm.group(2))
            if not name or w <= 0:
                return None, f"項目「{p}」格式怪"
        else:
            name, w = p, 1.0
        items.append((name, w))
    avail = (int(total_sec * (100 - buf_pct) / 100) - buf_min * 60) // 60 * 60  # 對齊分鐘
    if avail < 60 * len(items):
        why = f"留空 {buf_pct}%" if buf_pct else f"留空 {buf_min}分鐘"
        return None, f"{why} 之後得 {engine.fmt_duration(avail)}，唔夠分畀 {len(parts)} 項（每項至少 1 分鐘）"
    W = sum(w for _, w in items)
    segs, used = [], 0
    for i, (name, w) in enumerate(items):
        if i == len(parts) - 1:
            secs = avail - used  # 最後一項食埋剩尾，總和啱啱好
        else:
            secs = int(avail * w / W) // 60 * 60
            used += secs
        segs.append({"text": name, "seconds": secs, "w": w})
    return segs, None



def _alloc_ff(now: engine.dt.datetime, hh: int, mm: int, hh2: int, mm2: int,
              segments: list) -> tuple:
    """「而家仲喺個 block 入面」→ 即刻上車：照顧跨日（如 2300-0200 凌晨 01:xx），
    回傳 (由邊個 idx 開始, 該段淨返秒數)；唔喺窗內 / 全部段已過 → (None, None)。"""
    s0 = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    e0 = now.replace(hour=hh2, minute=mm2, second=0, microsecond=0)
    if e0 <= s0:
        e0 += engine.dt.timedelta(days=1)  # 跨日 block
    for d in (0, -1):
        s_try = s0 + engine.dt.timedelta(days=d)
        e_try = e0 + engine.dt.timedelta(days=d)
        if not (s_try <= now < e_try):
            continue
        elapsed = (now - s_try).total_seconds()
        acc = 0.0
        for i, seg in enumerate(segments):
            acc += seg["seconds"]
            rem = acc - elapsed
            if rem >= 60:  # 淨返至少 1 分鐘 → 由呢段半路加入
                return i, int(rem)
        return None, None  # 仲喺窗內但全部段都過晒（剩 buffer 位）
    return None, None



def _add_alloc_job(chat_id: int, now: engine.dt.datetime, hh: int, mm: int,
                   hh2: int, mm2: int, daily: bool, segments: list,
                   buf: int = 0, buf_min: int = 0) -> tuple:
    """新增分配排程；同時間嘅舊分配排程會被取代。
    如果而家已經喺起止時間窗內 → 即刻開飛（fast-forward），唔會推去下一轉。"""
    jobs = engine._jobs()
    replaced = [j["id"] for j in jobs
                if j.get("type") == "alloc" and j["hh"] == hh and j["mm"] == mm]
    for rid in replaced:
        t = engine._TASKS.pop(rid, None)
        if t:
            t.cancel()
    jobs = [j for j in jobs if j["id"] not in replaced]
    jid = max((j["id"] for j in jobs), default=0) + 1
    idx0, first_rem = engine._alloc_ff(now, hh, mm, hh2, mm2, segments)
    if idx0 is not None:
        start_at = now  # 即刻觸發（喺 block 入面）
    else:
        start_at = engine._next_occurrence(now, hh, mm)
    job = {"id": jid, "type": "alloc", "hh": hh, "mm": mm, "hh2": hh2, "mm2": mm2,
           "daily": daily, "url": "", "seconds": 0, "mode": "",
           "label": "時間分配", "chat_id": chat_id,
           "next": start_at.isoformat(), "shuffle": False, "paused": False,
           "segments": segments, "idx": idx0 or 0, "buf": buf, "buf_min": buf_min}
    if idx0 is not None and first_rem < segments[idx0]["seconds"]:
        job["_rem"] = first_rem  # 半路加入：第一下計時用淨返嘅秒數（一次性）
    jobs.append(job)
    engine._save_json(engine.JOBS_PATH, jobs)
    engine._arm(job)
    return {"next_dt": start_at, **job}, replaced



def _alloc_breakdown(job: dict) -> str:
    """分配排程嘅逐項明細（含開始時間）。job 要帶 next_dt（建立時）或 next。
    半路加入（idx>0 或有 _rem）只會列未嚟緊嘅段。"""
    start = job.get("next_dt") or engine.dt.datetime.fromisoformat(job["next"])
    if not isinstance(start, engine.dt.datetime):
        start = engine.dt.datetime.fromisoformat(start)
    start_idx = job.get("idx", 0)
    t, lines = start, []
    for i, s in enumerate(job.get("segments", [])[start_idx:], 1):
        secs = s["seconds"]
        if i == 1 and job.get("_rem"):
            secs = job["_rem"]  # 半路加入第一下嘅縮短版
        end = t + engine.dt.timedelta(seconds=secs)
        lines.append(f"{i}. {s['text']} — {engine.fmt_duration(secs)}（{t:%H:%M}→{end:%H:%M}）")
        t = end
    return "\n".join(lines)



def _alloc_remaining_end(job: dict, now: engine.dt.datetime) -> engine.dt.datetime:
    """進行中 block 嘅結束時間（由 hh:mm → hh2:mm2 推，跨日自動 +1 天）。"""
    s0 = now.replace(hour=job["hh"], minute=job["mm"], second=0, microsecond=0)
    if s0 > now:
        s0 -= engine.dt.timedelta(days=1)
    e0 = s0.replace(hour=job["hh2"], minute=job["mm2"])
    if e0 <= s0:
        e0 += engine.dt.timedelta(days=1)
    return e0



def _alloc_reflow(job: dict, now: engine.dt.datetime, from_idx: int) -> bool:
    """動態數值核心：將剩餘段按權重重新劈（剩牋_block_end − 而家 − 留空%／留空分鐘）。
    提早完成慳到嘅時間跌入到埋嘅段，收工時間照舊唔變。
    剩餘唔夠每段 1 分鐘 → False（交返靜態秒數繼續行）。"""
    segs = job.get("segments", [])
    rem_segs = segs[from_idx:]
    if not rem_segs:
        return False
    R = (engine._alloc_remaining_end(job, now) - now).total_seconds()
    buf = job.get("buf", 0)
    buf_min = job.get("buf_min", 0)
    avail = (int(R * (100 - buf) / 100) - buf_min * 60) // 60 * 60
    if avail < 60 * len(rem_segs):
        return False
    W = sum(s.get("w", 1.0) for s in rem_segs)
    used = 0
    for i, s in enumerate(rem_segs):
        if i == len(rem_segs) - 1:
            secs = avail - used
        else:
            secs = int(avail * s.get("w", 1.0) / W) // 60 * 60
            used += secs
        s["seconds"] = secs
    return True



def _alloc_advance(chat_id: int, now: engine.dt.datetime) -> str:
    """「完成」：提早做完而家呢段 → 立刻快進下一階段。
    找緊進行中嘅分配（idx>=1 表示第一下已 fire；next 係呢段尾）。
    舊 system 倒計時冇 intent 可以取消（只可以停緊響嘅），會照響；回覆有提用戶。"""
    jobs = engine._jobs()
    runs = [j for j in jobs if j.get("type") == "alloc"
            and j.get("idx", 0) >= 1
            and engine.dt.datetime.fromisoformat(j["next"]) > now]
    if not runs:
        return ("❓ 而家冇進行中嘅時間分配。\n"
                "開新 block：`1930至2230 分配 温習、做功課`；send「播程」睇有冇排咗嘅。")
    # 多個就揀最雷嘅嗰段
    job = min(runs, key=lambda j: engine.dt.datetime.fromisoformat(j["next"]))
    segs = job.get("segments", [])
    idx = job.get("idx", 0)                  # 下一段嘅索引（進行中 = idx-1）
    cur = segs[idx - 1] if segs and idx - 1 < len(segs) else {"text": "?"}
    remain = max(0, int((engine.dt.datetime.fromisoformat(job["next"]) - now).total_seconds()))
    saved = engine.fmt_duration(remain) if remain >= 30 else "少於 30 秒"
    t = engine._TASKS.pop(job["id"], None)
    if t:
        t.cancel()
    if idx < len(segs):                      # 仲有下一段 → 即刻 fire 佢
        reflowed = engine._alloc_reflow(job, now, idx)   # 慳返嘅時間動態跌入剩餘段
        nxt = segs[idx]
        job["next"] = now.isoformat()
        engine._save_json(engine.JOBS_PATH, jobs)          # job 已喺 jobs list 內（引用）
        engine._arm(job)
        head = f"⏩ 提早完成「{cur['text']}」（慳返 {saved}）\n"
        if reflowed:
            end = engine._alloc_remaining_end(job, now)
            head += (f"→ 剩餘按權重動態重排（照舊 {end:%H:%M} 收工）：\n"
                     f"{engine._alloc_breakdown(job)} 🚀 馬上開始\n")
        else:
            head += f"→ 即刻開第 {idx + 1}/{len(segs)} 項「{nxt['text']}」🚀\n"
        head += "（時鐘 App 嘅舊倒計時會照響，撳停就得）"
        return head
    # 最後一段都做埋 → 提早收工
    jobs2 = [j for j in jobs if j["id"] != job["id"]]
    if job.get("daily"):
        job["idx"] = 0
        job["next"] = engine._next_occurrence(now, job["hh"], job["mm"]).isoformat()
        jobs2.append(job)
        engine._save_json(engine.JOBS_PATH, jobs2)
        engine._arm(job)
        tail = "（每日分配，聽日自動重開）"
    else:
        engine._save_json(engine.JOBS_PATH, jobs2)
        tail = "（一次性分配，已刪走）"
    return (f"⏩ 提早完成「{cur['text']}」（慳返 {saved}）\n"
            f"🏁 最後一項都做埋，成個分配提早收工！{tail}")



async def _fire_alloc(job: dict) -> None:
    """分配排程觸發：fire 呢段嘅計時器 → 自動排下一段；
    最後一段做晒就刪走（每日就重設去第二日）。"""
    now = engine.dt.datetime.now()
    segs = job.get("segments", [])
    idx = job.get("idx", 0)
    if not segs or idx >= len(segs):
        engine._TASKS.pop(job["id"], None)
        engine._save_json(engine.JOBS_PATH, [j for j in engine._jobs() if j["id"] != job["id"]])
        return
    seg = segs[idx]
    secs = seg["seconds"]
    if job.get("_rem"):  # 半路加入嘅縮短第一下（一次性）
        secs = int(job["_rem"])
        job["_rem"] = 0
    ok, info = engine.run_intent(engine.timer_intent_cmd(secs, f"{seg['text']}（{idx + 1}/{len(segs)}）"))
    if ok:
        text = (f"⏰ 到點！開始第 {idx + 1}/{len(segs)} 項「{seg['text']}」"
                f"· 計時 {engine.fmt_duration(secs)}")
    else:
        text = f"❌ 開唔到計時器「{seg['text']}」：{str(info)[:120]}" + (
            engine._BAL_TIP if engine._is_bal_denied(info) else "")
    await engine._send_safe(job["chat_id"], text, "分配到點訊息")
    await engine._say(f"第{idx + 1}項，{engine._speech_scrub(seg['text'])}，"
               f"{engine.fmt_duration(secs)}")
    fired_at = engine.dt.datetime.fromisoformat(job["next"])
    keep = True
    if idx + 1 < len(segs):
        job["idx"] = idx + 1
        # 正常到點：跟足開初嘅靜態分段推移，唔好 reflow——
        # 「提早完成慳時間」嘅重排只屬於 send「完成」嗰下（alloc_advance 自己會做）。
        # 咁樣 fire 鏈先至唔會每段被雙倍留空吸慢。
        job["next"] = (fired_at + engine.dt.timedelta(seconds=secs)).isoformat()
    elif job.get("daily"):
        job["idx"] = 0
        job["next"] = engine._next_occurrence(now, job["hh"], job["mm"]).isoformat()
    else:
        keep = False
    engine._TASKS.pop(job["id"], None)
    if keep:
        jobs = engine._jobs()
        for j in jobs:
            if j["id"] == job["id"]:
                j["next"], j["idx"] = job["next"], job["idx"]
                j["_rem"] = job.get("_rem", 0)
        engine._save_json(engine.JOBS_PATH, jobs)
        engine._arm(job)
    else:
        engine._save_json(engine.JOBS_PATH, [j for j in engine._jobs() if j["id"] != job["id"]])
