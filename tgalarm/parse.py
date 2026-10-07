"""parse：文法解析域（parse_lines／parse_command／parse_player／日期時間解析器）。"""
from __future__ import annotations

from . import engine


def parse_player(text: str) -> engine.PlayerCmd | None:
    """解析歌單/排程相關指令；唔係嘅話回傳 None（交返畀計時/鬧鐘解析）。
    唔做 lower()——YouTube URL 大小寫敏感；英文關鍵字改用 IGNORECASE。"""
    s = engine.re.sub(r"\s+", " ", text.strip())
    vol = None
    vm = engine.re.search(r"音量\s*(\d{1,3})\s*%", s)
    # 改播/編輯指令：音量留喺內容入面交 _edit_job 處理（佢先知係咪播歌任務）
    if vm and not engine.re.match(r"/?(?:改播|編輯|改)\s*#?\d+", s):
        if int(vm.group(1)) > 100:
            return engine.PlayerCmd("vol_bad")
        vol = int(vm.group(1))
        s = engine.re.sub(r"\s+", " ", (s[:vm.start()] + " " + s[vm.end():]).strip())
    if engine.re.fullmatch(r"/?(?:完成|完成咗|早完成|提早完成|下一階段|下階段|跳過|skip|next)\s*[！!]?", s, engine.re.IGNORECASE):
        return engine.PlayerCmd("alloc_done")
    m = engine.re.fullmatch(r"/?搬(?:whatsapp|wa)?相\s*(.*)", s, engine.re.IGNORECASE)
    if m:
        rest = m.group(1).strip()
        preview = False
        m2 = engine.re.match(r"^(?:預覽|preview|list)\s+(.*)$", rest, engine.re.IGNORECASE)
        if m2:                                  # 「搬相 預覽 HHMM HHMM」
            preview, rest = True, m2.group(1)
        else:
            m2 = engine.re.search(r"\s+(?:預覽|preview|list)$", rest, engine.re.IGNORECASE)
            if m2:                              # 「搬相 HHMM HHMM 預覽」
                preview, rest = True, rest[:m2.start()]
            elif engine.re.fullmatch(r"(?:預覽|preview|list)", rest, engine.re.IGNORECASE):
                preview, rest = True, ""        # 「搬相預覽」
        toks = rest.split()
        if not toks:                            # 淨「搬相」／「搬相預覽」＝夜更
            return engine.PlayerCmd("wamove", ref="preview" if preview else "")
        if len(toks) == 2:                      # 2026-10-02 用戶令：任何時段
            t0, t1 = engine._read_hhmm_of(toks[0]), engine._read_hhmm_of(toks[1])
            if t0 and t1:
                return engine.PlayerCmd("wamove", ref="preview" if preview else "",
                                 extra=f"{t0[0]} {t0[1]} {t1[0]} {t1[1]}")
        return engine.PlayerCmd("wamove", ref="bad")
    if engine.re.fullmatch(r"/?(?:搬回|搬返)(?:wa|whatsapp)?相?(?:\s*(?:預覽|preview|list))?",
                    s, engine.re.IGNORECASE):
        return engine.PlayerCmd("wareturn",
                         ref="preview" if engine.re.search(r"(?:預覽|preview|list)\s*$",
                                                    s, engine.re.IGNORECASE) else "")
    if engine.re.fullmatch(r"/?(?:停|停止|停播|stop)", s, engine.re.IGNORECASE):
        return engine.PlayerCmd("stop")
    if engine.re.fullmatch(r"/?(?:播程|排程|播放日程|日程|jobs)", s, engine.re.IGNORECASE):
        return engine.PlayerCmd("jobs")
    m = engine.re.fullmatch(r"/?(?:取消播|取消|刪除排程)\s*#?(\d+)", s, engine.re.IGNORECASE)
    if m:
        return engine.PlayerCmd("cancel", job_id=int(m.group(1)))
    if engine.re.fullmatch(r"/?取消全部(?:播|排程)?", s, engine.re.IGNORECASE):
        return engine.PlayerCmd("cancel_all")
    m = engine.re.fullmatch(r"/?(\d{4})\s*(暫停|繼續)(?:排程)?(?:播)?\s*([0-9,，、 ]*)", s)
    if m:
        # mmdd 暫停/繼續排程 [任務號…]（2026-10-04 用戶令：排定日期生效）
        return engine.PlayerCmd("pause_date" if m.group(2) == "暫停" else "resume_date",
                         hour=int(m.group(1)[:2]), minute=int(m.group(1)[2:]),
                         extra=m.group(3).strip())
    if engine.re.fullmatch(r"/?(?:暫停|暫停播|停用)\s*(?:排程|全部|所有)"
                    r"|/?(?:全部|所有)\s*(?:暫停|停用)(?:播)?", s, engine.re.IGNORECASE):
        return engine.PlayerCmd("pause_all")
    if engine.re.fullmatch(r"/?(?:繼續|恢復)\s*(?:排程|全部|所有)"
                    r"|/?(?:全部|所有)\s*(?:繼續|恢復)(?:播)?", s, engine.re.IGNORECASE):
        return engine.PlayerCmd("resume_all")
    m = engine.re.fullmatch(r"(?:暫停|暫停播|停用)\s*#?(\d+)", s, engine.re.IGNORECASE)
    if m:
        return engine.PlayerCmd("pause", job_id=int(m.group(1)))
    m = engine.re.fullmatch(r"(?:繼續|恢復|繼續播|恢復播)\s*#?(\d+)", s, engine.re.IGNORECASE)
    if m:
        return engine.PlayerCmd("resume", job_id=int(m.group(1)))
    m = engine.re.fullmatch(r"(?:改播|編輯|改)\s*#?(\d+)\s+(.+)", s, engine.re.IGNORECASE)
    if m:
        return engine.PlayerCmd("edit", job_id=int(m.group(1)), ref=m.group(2))
    if engine.re.fullmatch(r"/?歌單", s, engine.re.IGNORECASE):
        return engine.PlayerCmd("listpl")
    m = engine.re.fullmatch(r"(?:刪歌單|刪除歌單)\s*(\S+)", s, engine.re.IGNORECASE)
    if m:
        return engine.PlayerCmd("delpl", ref=m.group(1))
    m = engine.re.fullmatch(r"(?:預設歌單|默認歌單)\s*(\S+)", s, engine.re.IGNORECASE)
    if m:
        return engine.PlayerCmd("setdef", ref=m.group(1))
    m = engine.re.fullmatch(r"歌單\s+(\S+)\s+(https?://\S+)", s, engine.re.IGNORECASE)
    if m:
        return engine.PlayerCmd("savepl", ref=m.group(1), url=m.group(2))
    # 地點 / 導航
    if engine.re.fullmatch(r"(?:地點|目的地|dests)", s, engine.re.IGNORECASE):
        return engine.PlayerCmd("dests")
    m = engine.re.fullmatch(r"(?:刪地點|刪除地點|del_place)\s+(.+)", s, engine.re.IGNORECASE)
    if m:
        return engine.PlayerCmd("deldest", ref=m.group(1).strip())
    m = engine.re.fullmatch(r"(?:地點|目的地|set_place)\s+([^\s＝=：:]+)\s*(?:[＝=：:]\s*)?(.+)", s, engine.re.IGNORECASE)
    if m:
        return engine.PlayerCmd("savedest", ref=m.group(1), url=m.group(2).strip())
    # 網頁
    if engine.re.fullmatch(r"(?:網頁|网页|webs)", s, engine.re.IGNORECASE):
        return engine.PlayerCmd("webs")
    m = engine.re.fullmatch(r"(?:刪網頁|刪除網頁|del_web)\s+(.+)", s, engine.re.IGNORECASE)
    if m:
        return engine.PlayerCmd("delweb", ref=m.group(1).strip())
    m = engine.re.fullmatch(r"(?:網頁|网页|set_web)\s+([^\s＝=：:]+)\s*(?:[＝=：]\s*)?(.+)", s, engine.re.IGNORECASE)
    if m:
        return engine.PlayerCmd("saveweb", ref=m.group(1), url=m.group(2).strip())
    m = engine.re.fullmatch(r"(?:開網頁|网页開|open_web)\s+(.+)", s, engine.re.IGNORECASE)
    if m:
        return engine.PlayerCmd("web", ref=m.group(1).strip())
    m = engine.re.fullmatch(r"開\s+(\S.*)", s, engine.re.IGNORECASE)
    if m:
        return engine.PlayerCmd("web", ref=m.group(1).strip())
    # 封印（衝動消費防線）：封印 kw[,kw2] 到 YYYY-MM-DD／解封 [kw]／封印（清單）
    m = engine.re.fullmatch(r"封印到\s*(?:(\d{4})-(\d{1,2})-(\d{1,2})"
                     r"|(\d{1,2})-(\d{1,2})|(\d{4}))", s, engine.re.IGNORECASE)
    if m:
        today = engine.dt.date.today()
        try:
            if m.group(1):
                d = engine.dt.date(int(m.group(1)), int(m.group(2)),
                            int(m.group(3)))
            elif m.group(4):
                d = engine.dt.date(today.year, int(m.group(4)), int(m.group(5)))
            else:
                d = engine.dt.date(today.year, int(m.group(6)[:2]),
                            int(m.group(6)[2:]))
        except ValueError:
            return None
        if d < today:
            try:
                d = d.replace(year=d.year + 1)
            except ValueError:
                d = d.replace(year=d.year + 4)
        return engine.PlayerCmd("seal_again", url=d.isoformat())
    m = engine.re.fullmatch(r"封印\s+(.+?)\s+到\s+(\d{4})-(\d{1,2})-(\d{1,2})", s,
                     engine.re.IGNORECASE)
    if m:
        return engine.PlayerCmd("seal_add", ref=m.group(1),
                         url="%04d-%02d-%02d" % (int(m.group(2)),
                                                 int(m.group(3)),
                                                 int(m.group(4))))
    m = engine.re.fullmatch(r"解封(?:\s+(.+))?", s, engine.re.IGNORECASE)
    if m:
        return engine.PlayerCmd("seal_off", ref=(m.group(1) or "").strip())
    if engine.re.fullmatch(r"封印", s, engine.re.IGNORECASE):
        return engine.PlayerCmd("seal_list")
    # 置頂待辦清單
    if engine.re.fullmatch(r"(?:待辦|todo|todolist|清單)", s, engine.re.IGNORECASE):
        return engine.PlayerCmd("todo")
    m = engine.re.fullmatch(r"待辦\s+(.+)", s, engine.re.IGNORECASE)
    if m:
        return engine.PlayerCmd("todo_add", ref=m.group(1).strip())
    m = engine.re.fullmatch(r"(?:完成|做咗|完成咗|勾選|勾|✓|✔|done)\s*#?(\d+)", s, engine.re.IGNORECASE)
    if m:
        return engine.PlayerCmd("todo_done", job_id=int(m.group(1)))
    m = engine.re.fullmatch(r"(?:未完成|未做|還原|undone)\s*#?(\d+)", s, engine.re.IGNORECASE)
    if m:
        return engine.PlayerCmd("todo_undone", job_id=int(m.group(1)))
    m = engine.re.fullmatch(r"(?:刪|刪除|踢走|del)\s*#?(\d+)", s, engine.re.IGNORECASE)
    if m:
        return engine.PlayerCmd("todo_del", job_id=int(m.group(1)))
    if engine.re.fullmatch(r"(?:清|清除|清理)已完成", s):
        return engine.PlayerCmd("todo_clear_done")
    if engine.re.fullmatch(r"(?:自檢|測試|selfcheck)", s, engine.re.IGNORECASE):
        return engine.PlayerCmd("selfcheck")
    m = engine.re.fullmatch(r"(?:修復|保障|權限|fix)", s, engine.re.IGNORECASE)
    if m:
        return engine.PlayerCmd("protect")
    if engine.re.fullmatch(r"(?:復活|重開|救)\s*shizuku|shizuku\s*(?:復活|重開|救返)", s, engine.re.IGNORECASE):
        return engine.PlayerCmd("shizuku_revive")
    # 時間分配：[每日] hhmm至hhmm 分配 [留空N% 或 留空N分鐘] 項目[x比例]…
    m = engine.re.fullmatch(r"(?:每日|每天)\s*(\S+?)\s*[-–—~至到]\s*(\S+?)\s+分配\s*(?:留空\s*(\d+(?:\.\d+)?)\s*(\%|分鐘|分钟|分鐘|分锺|分鍾|分)\s*)?(.+)", s, engine.re.IGNORECASE)
    if m:
        r1, r2 = engine._read_start_tok(m.group(1)), engine._read_hhmm_of(m.group(2))
        if r1 and r2:
            b_pct, b_min = engine._alloc_buf(m.group(3), m.group(4))
            return engine.PlayerCmd("sched_alloc_daily", hour=r1[0], minute=r1[1],
                             hour2=r2[0], minute2=r2[1],
                             buf=b_pct, buf_min=b_min, ref=m.group(5).strip())
        return None
    m = engine.re.fullmatch(r"(\S+?)\s*[-–—~至到]\s*(\S+?)\s+分配\s*(?:留空\s*(\d+(?:\.\d+)?)\s*(\%|分鐘|分钟|分鐘|分锺|分鍾|分)\s*)?(.+)", s, engine.re.IGNORECASE)
    if m:
        r1, r2 = engine._read_start_tok(m.group(1)), engine._read_hhmm_of(m.group(2))
        if r1 and r2:
            b_pct, b_min = engine._alloc_buf(m.group(3), m.group(4))
            return engine.PlayerCmd("sched_alloc", hour=r1[0], minute=r1[1],
                             hour2=r2[0], minute2=r2[1],
                             buf=b_pct, buf_min=b_min, ref=m.group(5).strip())
        return None
    # 每日單鬧：鬧鐘 每日0734 標籤（用戶直覺寫法——2026-09-29）
    m = engine.re.match(r"^(?:鬧鐘|闹钟|alarm)\s*(每日|每天|everyday)\s*"
                 r"(\d{1,2}):?(\d{2})\s*(?!.*[-–—~至到])\s*(.*)$",
                 s, engine.re.IGNORECASE)
    if m:
        sh, sm = int(m.group(2)), int(m.group(3))
        if sh <= 23 and sm <= 59:
            return engine.PlayerCmd("sched_alarm_daily", hour=sh, minute=sm,
                             ref=m.group(4).strip())
        return None
    # 連環鬧：[每日] [鬧鐘/計時] hhmm-hhmm 每x[分鐘/小時] [文字]
    # 2026-10-03 用戶令：裸寫法（冇每日/鬧鐘前綴）都收；單位加小時；中文數字（每兩小時）
    m = engine.re.match(r"^(每日|每天|everyday)?\s*(?:鬧鐘|闹钟|alarm|計時|计时|timer)?\s*"
                 r"(\d{1,2}):?(\d{2})\s*[-–—~至到]\s*(\d{1,2}):?(\d{2})\s*"
                 r"每\s*" + engine._EVERY_NUM + r"\s*" + engine._EVERY_UNIT + r"\s*(.*)$",
                 s, engine.re.IGNORECASE)
    if m:
        sh, sm = int(m.group(2)), int(m.group(3))
        eh, em = int(m.group(4)), int(m.group(5))
        x = engine._every_minutes(m.group(6), m.group(7))
        if (x is not None
                and sh <= 23 and sm <= 59 and eh <= 23 and em <= 59
                and (eh, em) != (sh, sm) and 1 <= x <= 24 * 60):
            # end < start＝過午夜（例 2100-0000 報更），window 開去第二日
            return engine.PlayerCmd("series_daily" if m.group(1) else "series",
                              hour=sh, minute=sm, hour2=eh, minute2=em,
                              seconds=int(x * 60), ref=m.group(8).strip())
        return None
    # 每日 hhmm <計時 時長 | [隨機]播> [名/連結/標籤]
    m = engine.re.match(r"^(?:每日|每天|everyday)\s*", s, engine.re.IGNORECASE)
    if m:
        head = s[m.end():]                       # 每日 鬧鐘 0734 標籤
        r = engine._read_hhmm(engine.re.sub(r"^(?:鬧鐘|闹钟|alarm)\s*", "", head,
                             flags=engine.re.IGNORECASE))
        if r:
            hh, mm, rest = r
            # 每日 0734 鬧鐘 標籤（鬧鐘字眼喺時間後面都收）
            if (head[:2] in ("鬧鐘", "闹钟")
                    or engine.re.match(r"^(?:鬧鐘|闹钟|alarm)\s", rest,
                                engine.re.IGNORECASE)):
                label = engine.re.sub(r"^(?:鬧鐘|闹钟|alarm)\s*", "", rest,
                               flags=engine.re.IGNORECASE)
                return engine.PlayerCmd("sched_alarm_daily", hour=hh, minute=mm,
                                 ref=label.strip())
            tm = engine.re.match(r"計時\s*(.*)$", rest)
            if tm:
                seconds, end = engine._parse_duration(tm.group(1))
                if seconds > 0:
                    return engine.PlayerCmd("sched_timer_daily", hour=hh, minute=mm,
                                     ref=tm.group(1)[end:].strip(), seconds=seconds)
                return None
            nm = engine.re.match(r"(?:開導航|導航|去)\s*(.+)$", rest)
            if nm:
                return engine.PlayerCmd("sched_nav_daily", hour=hh, minute=mm, ref=nm.group(1).strip())
            npm = engine.re.match(r"網播\s*(.+)$", rest)
            if npm:
                # 網播＝開網頁＋播歌一條 job（組合號都收）
                inner = npm.group(1).strip()
                nm2 = engine.re.fullmatch(r"(\d+)", inner)
                if nm2:
                    return engine.PlayerCmd("sched_webplay_daily", hour=hh,
                                     minute=mm, ref=nm2.group(1))
                om2 = engine.re.fullmatch(r"(\S+)\s+(\S+)", inner)
                if om2:
                    return engine.PlayerCmd("sched_webplay_daily", hour=hh,
                                     minute=mm, ref=om2.group(1),
                                     extra=om2.group(2))
            wm = engine.re.match(r"(?:開網頁|網頁|開)\s*(.+)$", rest)
            if wm:
                return engine.PlayerCmd("sched_web_daily", hour=hh, minute=mm, ref=wm.group(1).strip())
            pm = engine.re.match(r"(隨機播放|隨機播|播(?:放)?)\s*(.*)$", rest)
            if pm:
                ref, sh = engine._strip_shuffle(pm.group(2))
                return engine.PlayerCmd("sched_daily", ref=ref, hour=hh, minute=mm,
                                 shuffle="隨機" in pm.group(1) or sh, vol=vol)
        return None
    # hhmm <計時 時長 | [隨機]播> …（一次）
    r0 = engine._read_hhmm(s)
    if r0:
        hh, mm, rest = r0
        tm = engine.re.match(r"計時\s*(.*)$", rest)
        if tm:
            seconds, end = engine._parse_duration(tm.group(1))
            if seconds > 0:
                return engine.PlayerCmd("sched_timer", hour=hh, minute=mm,
                                 ref=tm.group(1)[end:].strip(), seconds=seconds)
            return None
        nm = engine.re.match(r"(?:開導航|導航|去)\s*(.+)$", rest)
        if nm:
            return engine.PlayerCmd("sched_nav", hour=hh, minute=mm, ref=nm.group(1).strip())
        npm = engine.re.match(r"網播\s*(.+)$", rest)
        if npm:
            inner = npm.group(1).strip()
            nm2 = engine.re.fullmatch(r"(\d+)", inner)
            if nm2:
                return engine.PlayerCmd("sched_webplay", hour=hh,
                                 minute=mm, ref=nm2.group(1))
            om2 = engine.re.fullmatch(r"(\S+)\s+(\S+)", inner)
            if om2:
                return engine.PlayerCmd("sched_webplay", hour=hh,
                                 minute=mm, ref=om2.group(1),
                                 extra=om2.group(2))
        wm = engine.re.match(r"(?:開網頁|網頁|開)\s*(.+)$", rest)
        if wm:
            return engine.PlayerCmd("sched_web", hour=hh, minute=mm, ref=wm.group(1).strip())
        pm = engine.re.match(r"(隨機播放|隨機播|播(?:放)?)\s*(.*)$", rest)
        if pm:
            ref, sh = engine._strip_shuffle(pm.group(2))
            return engine.PlayerCmd("sched_once", ref=ref, hour=hh, minute=mm,
                             shuffle="隨機" in pm.group(1) or sh, vol=vol)
        return None  # 淨時間行：留返畀批次繼承用
    m = engine.re.fullmatch(r"(?:開導航|導航|nav|去)\s*(.*)", s, engine.re.IGNORECASE)
    if m:
        if not m.group(1).strip():
            return engine.PlayerCmd("dests")  # 淨「導航」：顯示地點清單同用法
        return engine.PlayerCmd("nav", ref=m.group(1).strip())
    # [隨機]播 [名/連結]（「播放」要排喺「播」前面，否則「放」會被食入名）
    if engine.re.fullmatch(r"組合", s):
        return engine.PlayerCmd("combo_list")
    dm = engine.re.fullmatch(r"刪組合\s*(\d+)", s)
    if dm:
        return engine.PlayerCmd("combo_del", ref=dm.group(1))
    wp = engine.re.match(r"^網播\s*(.+)$", s)
    if wp:
        inner = wp.group(1).strip()
        # 組合定義：網播 1=網頁+歌單
        dm2 = engine.re.fullmatch(r"(\d+)\s*=\s*(\S+)\s*\+\s*(\S+)", inner)
        if dm2:
            return engine.PlayerCmd("combo_set", ref=dm2.group(1),
                             extra=f"{dm2.group(2)}|{dm2.group(3)}")
        # 組合號執行：網播 1
        nm3 = engine.re.fullmatch(r"(\d+)", inner)
        if nm3:
            return engine.PlayerCmd("webplay", ref=nm3.group(1))
        om3 = engine.re.fullmatch(r"(\S+)\s+(\S+)", inner)
        if om3:
            return engine.PlayerCmd("webplay", ref=om3.group(1),
                             extra=om3.group(2))
    m = engine.re.match(r"^/?(隨機播放|隨機播|播放|播|play)\s*(.*)$", s, engine.re.IGNORECASE)
    if m:
        ref, sh = engine._strip_shuffle(m.group(2))
        return engine.PlayerCmd("play", ref=ref, shuffle="隨機" in m.group(1) or sh,
                         vol=vol)
    return None
