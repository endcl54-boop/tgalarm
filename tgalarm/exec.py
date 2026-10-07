"""exec：指令執行器（_execute_player／_execute——PlayerCmd／dict 指令分派到各域）。"""
from __future__ import annotations

from . import engine


def _execute_player(cmd: engine.PlayerCmd, chat_id: int, now: engine.dt.datetime) -> str:
    a = cmd.action
    if a == "wareturn":
        return engine._wa_return(now, preview=(cmd.ref == "preview"))
    if a == "wamove":
        if cmd.ref == "bad":
            return ("❓ 用法：「搬相 HHMM HHMM」自訂任何時段——當日"
                    "（例：搬相 0900 1200）或跨夜（例：搬相 2300 0700）都得；"
                    "淨「搬相」＝最近夜更時段。加「預覽」＝齋睇唔搬")
        win = None
        if cmd.extra:
            sh, sm, eh, em = (int(x) for x in cmd.extra.split())
            win = engine._wa_recent_window(now, sh, sm, eh, em)
            if win is None:
                return "❓ 起同終一樣，唔知你想搬幾耐——例：搬相 0900 1200"
        return engine._wa_move(now, preview=(cmd.ref == "preview"), window=win)
    if a == "alloc_done":
        return engine._alloc_advance(chat_id, now)
    if a == "vol_bad":
        return "❓ 音量要 0–100。例：音量40% 播 lofi／0700 音量40% 播 lofi"
    if a == "play":
        url, info = engine._resolve_playlist(cmd.ref)
        if url is None:
            return "❓ " + info
        vol_note = ""
        if cmd.vol is not None:
            okv, det = engine._set_media_volume(cmd.vol)
            vol_note = ("\n🔊 " if okv else "\n⚠️ ") + det
        ok, out = engine._play(url, cmd.shuffle)
        if ok:
            tag = f"「{info}」" if info else ""
            if out == "NO_AUTOLIST":
                return (f"🔶 開咗歌單頁{tag}，但攞唔到首條片做自動播放，"
                        f"喺 app 撳 ▶ 開始{vol_note}")
            how = "🔀 隨機開始播放" if cmd.shuffle else "▶️ 開始播放"
            return f"{how}{tag}" + ("（DRY_RUN）" if engine.DRY_RUN else "") + vol_note
        return "❌ 開唔到 YouTube（有冇裝 YouTube app？）：" + out[:150]
    if a == "stop":
        ok, how = engine._stop()
        if not ok:
            return "❌ 停唔到：" + how[:150]
        if how == "home":
            return ("⏸ 已切去主畫面（非 Premium 嘅 YouTube 入背景會自動暫停；"
                    "如果仲響緊，喺 app 手停，或者裝 Termux:API 我幫你用靜音搶焦點）")
        return "⏹ 已停止播放"
    if a in ("sched_once", "sched_daily"):
        url, info = engine._resolve_playlist(cmd.ref)
        if url is None:
            return "❓ " + info
        job, replaced = engine._add_job(cmd, chat_id, now, url=url)
        kind = "每日" if a == "sched_daily" else "一次"
        when = f"{engine.day_label(job['next_dt'], now)} {cmd.hour:02d}:{cmd.minute:02d}"
        shuf = " 🔀隨機" if cmd.shuffle else ""
        voln = f" 🔊{cmd.vol}%" if cmd.vol is not None else ""
        msg = f"🗓 已排程（{kind}{shuf}{voln} #{job['id']}）：{when} 播「{job['label']}」"
        return msg + engine._replaced_note(replaced)
    if a in ("series", "series_daily"):
        job, replaced = engine._add_job(cmd, chat_id, now, seconds=cmd.seconds)
        kind = "每日" if a == "series_daily" else "今日"
        span = ((cmd.hour2 * 60 + cmd.minute2)
                - (cmd.hour * 60 + cmd.minute)) % 1440
        n = span * 60 // cmd.seconds + 1
        msg = (f"⏰ 已排連環鬧（{kind} #{job['id']}）："
               f"{cmd.hour:02d}:{cmd.minute:02d}–{cmd.hour2:02d}:{cmd.minute2:02d} "
               f"每{cmd.seconds // 60}分鐘 響「{job['label'] or '時間到'}」（共 {n} 響）")
        return msg + engine._replaced_note(replaced)
    if a == "sched_alarm_daily":
        lbl = cmd.ref or "時間到"
        ok, info = engine.run_intent(engine.alarm_intent_cmd(cmd.hour, cmd.minute, lbl,
                                               days=engine.DAILY))
        if ok:
            echo = engine._add_bell(chat_id,
                             engine._next_occurrence(now, cmd.hour, cmd.minute),
                             lbl, "timer", daily=True)
            return (f"⏰ 已落手機時鐘 app：每日 {cmd.hour:02d}:{cmd.minute:02d}"
                    f" 響「{lbl}」——日日自動響，取消喺時鐘 app"
                    "（重設同時間會疊多個，都喺 app 剷）\n"
                    f"🔊 到點 bot 仲會讀你聽（#{echo['id']}，「取消 {echo['id']}」刪）")
        job, replaced = engine._add_job(cmd, chat_id, now)   # app 設唔到 → bot 守返
        when = f"{engine.day_label(job['next_dt'], now)} {cmd.hour:02d}:{cmd.minute:02d}"
        msg = (f"⏰ 每日鬧鐘（#{job['id']}）：日日 {cmd.hour:02d}:{cmd.minute:02d}"
               f" 響「{lbl}」——下次 {when}；「取消 {job['id']}」刪"
               f"（時鐘 app 設唔到：{str(info)[:60]}——bot 排程守返）")
        return msg + engine._replaced_note(replaced)
    if a in ("sched_timer", "sched_timer_daily"):
        job, replaced = engine._add_job(cmd, chat_id, now, seconds=cmd.seconds)
        kind = "每日" if a == "sched_timer_daily" else "一次"
        when = f"{engine.day_label(job['next_dt'], now)} {cmd.hour:02d}:{cmd.minute:02d}"
        msg = f"🗓 已排程（{kind} #{job['id']}）：{when} {engine._fmt_job_content(job)}"
        return msg + engine._replaced_note(replaced)
    if a in ("sched_nav", "sched_nav_daily"):
        dest, mode, shown = engine._nav_target(cmd.ref)
        job, replaced = engine._add_job(cmd, chat_id, now, url=dest, mode=mode, label=shown)
        kind = "每日" if a == "sched_nav_daily" else "一次"
        when = f"{engine.day_label(job['next_dt'], now)} {cmd.hour:02d}:{cmd.minute:02d}"
        msg = (f"🗓 已排程（{kind} #{job['id']}）：{when} "
               f"導航去「{job['label']}」（{engine._mode_label(mode)}）")
        return msg + engine._replaced_note(replaced)
    if a == "webplay":
        # 網播：開網頁→即刻播歌（2026-10-07 用戶令；一條指令兩動作）
        wurl, werr = engine._web_target(cmd.ref)
        if not wurl:
            return werr
        plurl, plerr = engine._resolve_playlist(cmd.extra)
        if not plurl:
            return plerr
        if not engine.DRY_RUN:
            engine._shell_priv_exec("input keyevent KEYCODE_WAKEUP")
        okw, infow = engine.run_intent(engine.web_intent_cmd(wurl))
        okp, outp = engine._play(plurl, cmd.shuffle)
        wnote = "" if okw else f"\n⚠️ 網頁開唔到：{infow[:80]}"
        if okp:
            return f"🌐 開網頁「{cmd.ref}」＋▶️ 播「{cmd.extra}」{wnote}"
        return f"🌐 網頁開咗，但❌ 播唔到：{outp[:120]}" + wnote
    if a in ("sched_webplay", "sched_webplay_daily"):
        wurl, werr = engine._web_target(cmd.ref)
        if not wurl:
            return werr
        plurl, plerr = engine._resolve_playlist(cmd.extra)
        if not plurl:
            return plerr
        label = f"{cmd.ref}＋{cmd.extra}"
        job, replaced = engine._add_job(cmd, chat_id, now, url=wurl,
                                        label=label, pl=plurl)
        kind = "每日" if a == "sched_webplay_daily" else "一次"
        when = f"{engine.day_label(job['next_dt'], now)} {cmd.hour:02d}:{cmd.minute:02d}"
        msg = (f"🗓 已排程（{kind} #{job['id']}）：{when} 網播"
               f"「{cmd.ref}＋{cmd.extra}」＝開網頁→即刻播歌")
        return msg + engine._replaced_note(replaced)
    if a in ("sched_web", "sched_web_daily"):
        url, err = engine._web_target(cmd.ref)
        if not url:
            return err
        label = (cmd.ref if url != cmd.ref
                 else url.split("//", 1)[-1][:30].rstrip("/"))
        job, replaced = engine._add_job(cmd, chat_id, now, url=url, label=label)
        kind = "每日" if a == "sched_web_daily" else "一次"
        when = f"{engine.day_label(job['next_dt'], now)} {cmd.hour:02d}:{cmd.minute:02d}"
        msg = f"🗓 已排程（{kind} #{job['id']}）：{when} 開網頁「{job['label']}」"
        return msg + engine._replaced_note(replaced)
    if a in ("sched_alloc", "sched_alloc_daily"):
        if not (0 <= cmd.buf <= 90):
            return "❓ 留空要 0-90% 之內"
        daily = a == "sched_alloc_daily"
        s0 = engine.dt.datetime(now.year, now.month, now.day, cmd.hour, cmd.minute)
        e0 = engine.dt.datetime(now.year, now.month, now.day, cmd.hour2, cmd.minute2)
        if e0 <= s0:
            e0 += engine.dt.timedelta(days=1)  # 過夜（例如 2200-0200）
        total = int((e0 - s0).total_seconds())
        if cmd.buf_min * 60 > total - 60:
            return f"❓ 留空 {cmd.buf_min}分鐘太多——個 window 先得 {engine.fmt_duration(total)}"
        segs, err = engine._alloc_segments(cmd.ref, cmd.buf, total, cmd.buf_min)
        if segs is None:
            return "❓ " + err
        job, replaced = engine._add_alloc_job(chat_id, now, cmd.hour, cmd.minute,
                                       cmd.hour2, cmd.minute2, daily, segs,
                                       cmd.buf, cmd.buf_min)
        kind = "每日" if daily else "一次"
        av = total - sum(s2["seconds"] for s2 in segs)
        if cmd.buf_min:
            buf_label = f"留空 {cmd.buf_min}分鐘"
        else:
            buf_label = f"留空 {cmd.buf}%"
        when = f"{engine.day_label(job['next_dt'], now)} {cmd.hour:02d}:{cmd.minute:02d}"
        lines = [(f"🧩 時間分配（{kind} #{job['id']}）：{when}→{cmd.hour2:02d}:{cmd.minute2:02d}"
                  f"（{engine.fmt_duration(total)}・{buf_label}＝{engine.fmt_duration(av)}隨你用）"),
                 engine._alloc_breakdown(job)]
        return "\n".join(lines) + engine._replaced_note(replaced)
    if a == "selfcheck":
        nxt = now + engine.dt.timedelta(minutes=2)
        test_cmd = engine.PlayerCmd("sched_timer", hour=nxt.hour, minute=nxt.minute,
                             seconds=90, ref="自檢測試")
        job, _ = engine._add_job(test_cmd, chat_id, now, seconds=90)
        return ("🩺 自檢已排：兩分鐘後（"
                f"{nxt:%H:%M}）你應該同時見到——\n"
                "① 呢度彈「⏰ 到點」訊息\n"
                "② 時鐘 app 彈出 90 秒計時器\n"
                "❗ 兩樣都冇 → bot 被系統殺咗（send「修復」開保障設定）\n"
                "❗ 有訊息冇計時器/冇導航 → 背景彈窗被擋：\n"
                "　• vivo/Funtouch：要開「後台彈出界面」（設定→應用與權限→權限管理→其他權限）\n"
                "　• 其他機：「喺其他應用上層顯示」要開\n"
                "（試埋熄螢幕等，最似你半夜放工狀態）")
    if a == "shizuku_revive":
        if engine._rish_available():
            return "✅ Shizuku 本來就行緊（rish 探到 uid=2000），唔使救。"
        if not engine._adb_lane_available():
            return ("❌ adb lane（127.0.0.1:5555）都唔喺度，救唔到。\n"
                    "手動救：開 Shizuku app →「透過無線調試啟動」，跟個 dialog 配對一次。")
        ok, out = engine._adb_shell("sh /sdcard/Android/data/"
                             "moe.shizuku.privileged.api/start.sh", timeout=30)
        engine._RISH_CACHE["t"], engine._RISH_CACHE["ok"] = 0.0, False   # 清快取，真探一單
        if engine._rish_available():
            return "✅ Shizuku 復活咗！rish 探返到 uid=2000。"
        if not ok:
            return (f"⚠️ start.sh 行唔到：{out[:90]}\n"
                    "開一次 Shizuku app 嘅「無線調試」頁等佢寫返個 start.sh，再 send「復活Shizuku」。")
        return (f"ℹ️ start.sh 有行（{out[:60]}）但 rish 仲未探到。\n"
                "開一次 Shizuku app 睇下狀態，唔得再 send「復活Shizuku」。")
    if a == "protect":
        engine.run_intent(["am", "start", "-a", "android.settings.APPLICATION_DETAILS_SETTINGS",
                    "-d", "package:com.termux"])
        engine.run_intent(["am", "start", "-a", "android.settings.action.MANAGE_OVERLAY_PERMISSION",
                    "-d", "package:com.termux"])
        engine.run_intent(["am", "start", "-a", "android.settings.IGNORE_BATTERY_OPTIMIZATION_SETTINGS"])
        return ("🔧 已幫你彈出設定頁，逐項撥好（解決深夜遲響/唔響/導航彈唔出）：\n"
                "① 電池 → 揀「無限制」（最緊要：Termux 唔被省電壓）\n"
                "② 通知 → 允許（冇常駐通知 → 系統易殺、wakelock 失效）\n"
                "③ 喺其他應用上層顯示 → 允許（鎖屏彈計時器要用）\n"
                "④〔vivo/Funtouch 必做〕「後台彈出界面」＋「鎖屏顯示」→ 允許\n"
                "　路徑：設定→應用與權限→權限管理→其他權限→搵 Termux；\n"
                "　或 i管家→應用管理→權限管理→應用→Termux（同名開關喺度）\n"
                "⑤〔小米/華為/OPPO〕自啟動、後台活動、彈出視窗 → 允許\n"
                "⑥〔終極·唔使靠廠權限〕裝 Shizuku＋入 app「在終端應用程式使用」匯出\n"
                "　rish 兩個檔案，裝落 Termux——bot 會自動改用 adb 身份彈窗，背景閘完全繞過\n"
                "撥好之後熄屏鎖機，send「自檢」等 3 分鐘驗證一次")
    if a == "jobs":
        return engine._fmt_jobs(now)
    if a == "cancel":
        if engine._remove_job(cmd.job_id):
            return f"🗑 已取消 #{cmd.job_id}"
        return f"搵唔到 #{cmd.job_id}。send「排程」睇編號"
    if a == "pause":
        r = engine._pause_job(cmd.job_id)
        if r is True:
            return f"⏸ 已暫停 #{cmd.job_id}"
        if r == "already":
            return f"#{cmd.job_id} 本身就暫停緊。"
        return f"搵唔到 #{cmd.job_id}。send「排程」睇編號"
    if a == "resume":
        nxt = engine._resume_job(cmd.job_id, now)
        if nxt is None:
            return f"搵唔到 #{cmd.job_id}。send「排程」睇編號"
        return f"▶️ 已恢復 #{cmd.job_id}（{engine.day_label(nxt, now)} {nxt:%H:%M} 觸發）"
    if a == "pause_all":
        n, total = engine._pause_all()
        if total == 0:
            return "而家冇排程。"
        if n == 0:
            return "全部排程都暫停緊。"
        return f"⏸ 已暫停全部排程（{n} 個；「繼續排程」一次過恢復）"
    if a == "resume_all":
        n = engine._resume_all(now)
        if n == 0:
            return "冇暫停緊嘅排程。"
        return f"▶️ 已恢復 {n} 個排程"
    if a in ("pause_date", "resume_date"):
        mm, dd = cmd.hour, cmd.minute
        try:
            tgt = now.replace(month=mm, day=dd, hour=0, minute=5,
                              second=0, microsecond=0)
        except ValueError:
            return f"❌ 日期唔存在：{mm:02d}{dd:02d}（例：1005＝10月5日）"
        if tgt < now.replace(hour=0, minute=0, second=0, microsecond=0):
            try:
                tgt = tgt.replace(year=now.year + 1)
            except ValueError:                     # 0229
                tgt = tgt.replace(year=now.year + 4)
        ids = [int(x) for x in engine.re.findall(r"\d+", cmd.extra or "")]
        if ids:
            have = {j["id"] for j in engine._jobs()}
            missing = [i for i in ids if i not in have]
            if missing:
                return ("搵唔到 " + "、".join(f"#{i}" for i in missing)
                        + "。send「排程」睇編號")
        act = "暫停" if a == "pause_date" else "繼續"
        tgt_txt = f"{tgt.month}月{tgt.day}日"
        if tgt.year > now.year:
            tgt_txt += f"（{tgt.year}）"
        tgt_ids = "、".join(f"#{i}" for i in ids) if ids else "全部"
        if tgt.date() == now.date():               # 今日＝即刻生效
            if a == "pause_date":
                if ids:
                    n = sum(1 for i in ids if engine._pause_job(i) is True)
                    return f"⏸ 今日（{tgt_txt}）已暫停 {tgt_ids}（{n} 個）"
                n, _t = engine._pause_all()
                return f"⏸ 今日（{tgt_txt}）已暫停全部排程（{n} 個）"
            if ids:
                n = sum(1 for i in ids if engine._resume_job(i, now) is not None)
                return f"▶️ 今日（{tgt_txt}）已恢復 {tgt_ids}（{n} 個）"
            n = engine._resume_all(now)
            return f"▶️ 今日（{tgt_txt}）已恢復 {n} 個排程"
        engine._add_simple_job(chat_id, {
            "type": "sched_pause" if a == "pause_date" else "sched_resume",
            "ids": ids, "label": f"排定{act}", "chat_id": chat_id,
            "hh": 0, "mm": 5, "next": tgt.isoformat()})
        return (f"🗓 已排定：{tgt_txt} {act} {tgt_ids}"
                f"（當日 00:05 生效；「排程」見到，可「取消 N」）")
    if a == "edit":
        ok, info = engine._edit_job(cmd.job_id, cmd.ref, now)
        return f"✏️ #{cmd.job_id}：{info}" if ok else f"❌ {info}"
    if a == "cancel_all":
        return f"🗑 已取消全部 {engine._clear_jobs()} 個排程"
    if a == "listpl":
        return engine._fmt_playlists()
    if a == "savepl":
        if not engine._is_yt_url(cmd.url):
            return "❓ 連結唔似 YouTube（要 youtube.com / youtu.be 開頭）"
        pl = engine._playlists()
        pl.setdefault("lists", {})[cmd.ref] = cmd.url
        if not pl.get("default"):
            pl["default"] = cmd.ref
        engine._save_json(engine.PLAYLISTS_PATH, pl)
        warn = "" if "list=" in cmd.url else "\n（提提你：連結冇 list=，似單一影片多過歌單）"
        return f"💾 已儲存歌單「{cmd.ref}」{warn}"
    if a == "delpl":
        pl = engine._playlists()
        if cmd.ref in pl.get("lists", {}):
            del pl["lists"][cmd.ref]
            if pl.get("default") == cmd.ref:
                pl["default"] = next(iter(pl["lists"]), "")
            engine._save_json(engine.PLAYLISTS_PATH, pl)
            return f"🗑 已刪歌單「{cmd.ref}」"
        return f"搵唔到歌單「{cmd.ref}」"
    if a == "setdef":
        pl = engine._playlists()
        if cmd.ref in pl.get("lists", {}):
            pl["default"] = cmd.ref
            engine._save_json(engine.PLAYLISTS_PATH, pl)
            return f"⭐ 預設歌單 = 「{cmd.ref}」"
        return f"搵唔到歌單「{cmd.ref}」"
    if a == "dests":
        return engine._fmt_dests()
    if a == "savedest":
        d = engine._dests()
        d[cmd.ref] = cmd.url
        engine._save_json(engine.DESTINATIONS_PATH, d)
        return f"📍 已儲存地點「{cmd.ref}」＝「{cmd.url}」"
    if a == "deldest":
        d = engine._dests()
        if cmd.ref in d:
            del d[cmd.ref]
            engine._save_json(engine.DESTINATIONS_PATH, d)
            return f"🗑 已刪地點「{cmd.ref}」"
        return f"搵唔到地點「{cmd.ref}」"
    if a == "webs":
        return engine._fmt_webs()
    if a == "saveweb":
        u = cmd.url.strip()
        if not u.lower().startswith(("http://", "https://")):
            return "❓ 連結要齊 http(s):// 開頭。例：網頁 新聞 https://news.rthk.hk"
        w = engine._webs()
        w[cmd.ref] = u
        engine._save_json(engine.WEBS_PATH, w)
        return f"🔗 已儲存網頁「{cmd.ref}」＝{u}"
    if a == "delweb":
        w = engine._webs()
        if cmd.ref in w:
            del w[cmd.ref]
            engine._save_json(engine.WEBS_PATH, w)
            return f"🗑 已刪網頁「{cmd.ref}」"
        return f"搵唔到網頁「{cmd.ref}」。send「網頁」睇清單"
    if a == "web":
        url, err = engine._web_target(cmd.ref)
        if not url:
            return err
        if not engine.DRY_RUN:
            engine._shell_priv_exec("input keyevent KEYCODE_WAKEUP")  # 著螢幕
        ok, info = engine.run_intent(engine.web_intent_cmd(url))
        if ok:
            shown = cmd.ref if url == cmd.ref.strip() else f"{cmd.ref}（{url}）"
            return f"🌐 開緊網頁：{shown}"
        return f"❌ 開唔到網頁：{info[:120]}"
    if a == "nav":
        dest, mode, shown = engine._nav_target(cmd.ref)
        if not engine.DRY_RUN:
            # 同到點排程一樣：彈窗先行；通知＋TG 訊息遲 3 秒——
            # 同一秒出會搶焦點攬死彈窗（2026-09-25 用戶實測 Telegram 橫額會攔截）
            fake = {"id": f"m{int(now.timestamp()) % 100000}", "type": "nav",
                    "url": dest, "mode": mode, "label": shown, "chat_id": chat_id}
            try:
                engine.asyncio.create_task(engine._nav_keyboard_msg(chat_id, fake))

                async def _manual_nav_late(fake=fake):
                    await engine.asyncio.sleep(5)
                    engine._nav_confirm_notify(fake)   # 聲＋震提示
                engine.asyncio.create_task(_manual_nav_late())
                return ""      # 確認就係 TG 掣個訊息，免重複
            except RuntimeError:
                pass           # 冇 running loop（同步測試）→ 落返下面後備
            wok, _winfo = engine._nav_confirm_notify(fake)
            if wok:
                return (f"🧭 導航去「{shown}」（{engine._mode_label(mode)}）——"
                        "彈窗問緊你，撳【是】先會開地圖")
        ok, out = engine._open_nav(dest, mode)
        if ok:
            extra = "（彈窗出唔到，直接開）" if not engine.DRY_RUN else ""
            tag = f"開緊導航去「{shown}」（{engine._mode_label(mode)}）"
            return f"🧭 {tag}" + extra + ("（DRY_RUN）" if engine.DRY_RUN else "")
        return "❌ 開唔到 Google Maps（有冇裝 Maps app？）：" + out[:150]
    if a == "seal_list":
        js = engine._seal_jobs()
        if not js:
            return "🔒 而家冇嘢被封印。例：封印 za 到 2026-10-15"
        lines = ["🔒 封印中"]
        for j in js:
            for ap in j.get("apps", []):
                badge = ("⛔" if ap.get("mode") == "disabled" else "👁")
                lines.append(f"・{badge} {ap['label']} → {ap['until']}"
                             f"{'（已過期）' if ap['until'] < now.date().isoformat() else ''}")
        lines.append("（解封 [名] 提早開放；解封 全部）")
        return "\n".join(lines)
    if a == "seal_again":
        last = engine._load_json(engine.SEAL_LAST_PATH, [])
        cmd.ref = "、".join(last or ["za", "shacom"])
        a = "seal_add"          # 續封上次組合（冇紀錄＝預設 za＋shacom）
    if a == "seal_add":
        if not engine._shell_priv_exec("true")[0]:
            return ("❓ 封印要 rish／adb lane 先閂到人 app——入 Shizuku 撳「啟動」"
                    "或者 send「復活Shizuku」再試")
        kws = [k for k in engine.re.split(r"[、，,;\s]+", cmd.ref) if k]
        try:
            until = engine.dt.datetime.strptime(cmd.url, "%Y-%m-%d").date()
        except ValueError:
            return "❓ 日期格式：封印 za 到 2026-10-15"
        if until < now.date():
            return "❓ 個日子已經過咗喎"
        found, missing = [], list(kws)
        for kw in kws:
            pkgs = engine._pkg_search(kw)
            for p in pkgs:
                # 停用（disable-user）＝真封印：圖示灰、點入開唔到，唔使巡邏；
                # pm 唔行（lane 死）先退 25 秒巡邏 force-stop 模式
                okd, _ = engine._shell_priv_exec(f"pm disable-user --user 0 {p}")
                found.append({"pkg": p, "label": p,
                              "until": until.isoformat(),
                              "mode": "disabled" if okd else "patrol"})
                if kw in missing:
                    missing.remove(kw)
        if not found:
            return f"❓ 搾唔到 {cmd.ref} 呢個 app——試埋全名（pm list 嘅 package 字眼）"
        job = next((j for j in engine._seal_jobs()), None)
        patrol_n = sum(1 for f in found if f["mode"] == "patrol")
        nxt = (now if patrol_n else
               engine.dt.datetime.combine(until + engine.dt.timedelta(days=1),
                                   engine.dt.time(0, 1))).isoformat()
        if job:
            jobs = engine._jobs()
            merged = found + [x for x in job.get("apps", [])
                              if x["pkg"] not in {f["pkg"] for f in found}]
            patrol_n = sum(1 for f in merged if f.get("mode") == "patrol")
            nxt = (now if patrol_n else
                   engine.dt.datetime.combine(until + engine.dt.timedelta(days=1),
                                       engine.dt.time(0, 1))).isoformat()
            for j in jobs:
                if j["id"] == job["id"]:
                    j["apps"] = merged
                    j["next"] = nxt
            engine._save_json(engine.JOBS_PATH, jobs)
            engine._TASKS.pop(job["id"], None)
            engine._arm(job)
            jid = job["id"]
        else:
            nj = engine._add_simple_job(chat_id, {
                "type": "seal", "apps": found, "chat_id": chat_id,
                "hh": now.hour, "mm": now.minute, "next": nxt,
                "label": "封印"})
            jid = nj["id"]
        dis = sum(1 for f in found if f["mode"] == "disabled")
        engine._save_json(engine.SEAL_LAST_PATH, kws)
        msg = (f"🔒 封印生效（#{jid}）："
               + "、".join(f"{f['label']}→{f['until']}" for f in found)
               + (f"\n⛔ {dis} 個已停用（圖示變灰、點入開唔到）" if dis else "")
               + (f"\n👁 {patrol_n} 個巡邏中（pm 唔行，開即閂）"
                  if patrol_n else "")
               + "\n提早開放 send「解封 " + kws[0] + "」")
        if missing:
            msg += f"\n⚠️ 搾唔到：{('、'.join(missing))}"
        return msg
    if a == "seal_off":
        js = engine._seal_jobs()
        if not js:
            return "而家冇嘢被封印。"
        kws = [k for k in engine.re.split(r"[、，,;\s]+", cmd.ref) if k]
        removed, left_apps = [], []
        for j in js:
            for ap in j.get("apps", []):
                if not kws or any(k.lower() in ap["pkg"].lower() for k in kws):
                    removed.append(ap["label"])
                    if ap.get("mode") == "disabled":
                        oke, oute = engine._shell_priv_exec(
                            f"pm enable --user 0 {ap['pkg']}")
                        if not oke:
                            engine.log.warning("解封 pm enable 失敗：%s %s",
                                        ap["pkg"], str(oute)[:60])
                else:
                    left_apps.append(ap)
        if not removed:
            return f"❓ 封印名單入面冇 {cmd.ref}"
        jobs = engine._jobs()
        for j in jobs:
            if j.get("type") == "seal":
                if not left_apps:
                    engine._remove_job(j["id"])
                else:
                    j["apps"] = left_apps
        engine._save_json(engine.JOBS_PATH, [j for j in engine._jobs()
                               if j.get("type") != "seal" or j.get("apps")])
        return "🔓 已解封：" + "、".join(removed)
    if a == "todo":
        engine._schedule_todo_refresh(chat_id)
        return engine._fmt_todos()
    if a == "todo_add":
        n = engine._todo_add(cmd.ref)
        if not n:
            return "❓ 俾個項目名先，例：待辦 牛奶"
        engine._schedule_todo_refresh(chat_id)
        return f"📋 已加入 {n} 項待辦"
    if a in ("todo_done", "todo_undone"):
        done = a == "todo_done"
        text = engine._todo_toggle_idx(cmd.job_id, done)
        if text is None:
            return f"搵唔到第 {cmd.job_id} 項。send「待辦」睇清單"
        engine._schedule_todo_refresh(chat_id)
        return f"✅ 「{text}」完成，正！" if done else f"☐ 「{text}」標返做未完成"
    if a == "todo_del":
        text = engine._todo_del_idx(cmd.job_id)
        if text is None:
            return f"搵唔到第 {cmd.job_id} 項。send「待辦」睇清單"
        engine._schedule_todo_refresh(chat_id)
        return f"🗑 已刪「{text}」"
    if a == "todo_clear_done":
        n, left = engine._todo_clear_done()
        if not n:
            return "冇已完成項目"
        engine._schedule_todo_refresh(chat_id)
        return f"🧹 清咗 {n} 項已完成；仲有 {left} 項未完成"
    return "🤔 睇唔明"



def _execute(p: engine.Parsed, now: engine.dt.datetime, chat_id: int = 0) -> str:
    """執行一條已解析指令，回傳結果描述文字。"""
    tag = f"（{p.label}）" if p.label else ""
    tail = "（DRY_RUN 未真正設定）" if engine.DRY_RUN else ""
    if p.kind == "timer":
        if p.seconds > engine.MAX_TIMER_SECONDS:
            return f"⚠️ 超過計時上限 99999 小時（你設咗 {engine.fmt_duration(p.seconds)}），冇設定到"
        adj = ""
        if engine._TAKEAWAY.get("on"):
            cut = min(300, max(0, p.seconds - 60))   # 至少留 1 分鐘
            if cut > 0:
                old_s = p.seconds
                p.seconds -= cut
                p.fire_at -= engine.dt.timedelta(seconds=cut)
                adj = (f"🛵 外賣模式：{engine.fmt_duration(old_s)} → "
                       f"{engine.fmt_duration(p.seconds)}（提早響）\n")
        day = engine.day_label(p.fire_at, now)
        when = f"{p.fire_at:%H:%M}" if day == "今日" else f"{day} {p.fire_at:%H:%M}"
        if engine.DRY_RUN:
            return f"{adj}⏱ 計時器 {engine.fmt_duration(p.seconds)}{tag}，{when} 響＋到點讀你聽{tail}"
        # 2026-09-29 用戶令：計時雙軌——時鐘 app（保證響，深睡都準）
        # ＋bot 到點廣東話讀出標籤（bot 死都仲有鐘聲，生就連內容都讀）
        ok, info = engine.run_intent(engine.timer_intent_cmd(p.seconds, p.label))
        job = engine._add_bell(chat_id, p.fire_at, p.label or "時間到", "timer")
        if ok:
            return (f"{adj}⏱ 已落時鐘 app：計時 {engine.fmt_duration(p.seconds)}{tag}"
                    f"——{when} 響＋到點讀你聽🔊"
                    f"（#{job['id']} 淨撤語音；app 個喺 app 剷）{tail}")
        return (f"{adj}🔊 時鐘 app 設唔到（{str(info)[:40]}）"
                f"——語音提醒照排：{when} 讀你聽"
                f"（#{job['id']}，「取消 {job['id']}」刪）{tail}")
    if engine.DRY_RUN:
        return f"⏰ 鬧鐘 {engine.day_label(p.fire_at, now)} {p.hour:02d}:{p.minute:02d}{tag}{tail}"
    ok, info = engine.run_intent(engine.alarm_intent_cmd(p.hour, p.minute, p.label))
    if ok:
        echo = engine._add_bell(chat_id, p.fire_at, p.label or "時間到", "timer")
        return (f"⏰ 已落手機時鐘 app：鬧鐘 {p.hour:02d}:{p.minute:02d}{tag}"
                "——系統自己響（深度睡眠都準時；取消喺時鐘 app）\n"
                f"🔊 到點 bot 仲會讀你聽（#{echo['id']} 淨撤語音）")
    job = engine._add_bell(chat_id, p.fire_at, p.label, "alarm")
    return (f"⏰ 鬧鐘 {engine.day_label(p.fire_at, now)} {p.hour:02d}:{p.minute:02d}{tag}"
            f"（#{job['id']}，「取消 {job['id']}」可刪）"
            f"（時鐘 app 設唔到：{info[:60]}——bot 排程守返）{tail}")
