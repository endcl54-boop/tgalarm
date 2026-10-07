"""sched：排程引擎（_arm／_fire_later／牆鐘等待／單例鎖／wake lock）。
共享狀態全部經 engine.X 延遲綁定（測試 patch engine.X 對呢度生效）。"""
from __future__ import annotations

from . import core, engine


def _arm(job: dict) -> None:
    """為 job 建立到點觸發嘅 asyncio 任務。"""
    when = engine.dt.datetime.fromisoformat(job["next"])
    delay = max(0.0, (when - engine.dt.datetime.now()).total_seconds())
    engine._TASKS[job["id"]] = engine.asyncio.get_event_loop().create_task(engine._fire_later(job, delay))



async def _wait_wall(target: engine.dt.datetime, chunk: float = 30.0) -> None:
    """瞓到 target（牆鐘制）。

    電話深度睡眠會凍結 CLOCK_MONOTONIC——asyncio.sleep 一覗瞓過夜，
    24 小時 sleep 實際要 24小時+凍結總時長 先響（2026-09-27 實證：
    導航 0732 遲咗 14分51秒＝夜裡 suspend 總時長）。改每 chunk 對
    牆鐘重算剩低：suspend 期間牆鐘照行，醒返即刻追上進度；
    遲到上限 ≈ 一個 chunk。"""
    while True:
        rem = (target - engine.dt.datetime.now()).total_seconds()
        if rem <= 0:
            return
        await engine.asyncio.sleep(min(rem, chunk))



async def _fire_later(job: dict, delay: float) -> None:
    try:
        if delay > 0:
            await engine._wait_wall(engine.dt.datetime.now() + engine.dt.timedelta(seconds=delay))
        else:
            await engine.asyncio.sleep(0)        # 保持讓路語義同舊 delay=0 一致
    except engine.asyncio.CancelledError:
        return
    now = engine.dt.datetime.now()
    jtype = job.get("type", "play")
    defer_msg = False          # nav 彈窗先行時：訊息喺延遲任務送，唔喺度送
    if jtype in core.FIRE_HANDLERS:
        # S13 收口（藍圖接縫）：已註冊型別經 core 註冊表派發
        # （takeaway_on/off 本體喺 takeaway.py；未註冊型別照行下面鏈）
        await core.FIRE_HANDLERS[jtype](job, now)
        return
    if jtype in ("sched_pause", "sched_resume"):   # 排定日期暫停/繼續（2026-10-04）
        ids = job.get("ids") or []
        if jtype == "sched_pause":
            if ids:
                done = [i for i in ids if engine._pause_job(i) is True]
                msg = (("⏸（排定）已暫停 " + "、".join(f"#{i}" for i in done))
                       if done else "⏸（排定）指定任務唔喺度／暫停緊")
            else:
                n, _tot = engine._pause_all()
                msg = f"⏸（排定）已暫停全部排程（{n} 個）"
        else:
            if ids:
                done = [i for i in ids if engine._resume_job(i, now) is not None]
                msg = (("▶️（排定）已恢復 " + "、".join(f"#{i}" for i in done))
                       if done else "▶️（排定）指定任務唔存在／冇暫停緊")
            else:
                n = engine._resume_all(now)
                msg = f"▶️（排定）已恢復 {n} 個排程"
        await engine._send_safe(job["chat_id"], msg, "排定暫停/繼續")
        engine._TASKS.pop(job["id"], None)
        engine._save_json(engine.JOBS_PATH, [j for j in engine._jobs() if j["id"] != job["id"]])
        return
    if jtype == "alloc":
        await engine._fire_alloc(job)
        return
    if jtype == "bell":
        if job.get("bell") == "timer":      # 純語音提醒（用戶令 2026-09-29）
            await engine._say(job.get("label") or "時間到", delay=4)
            await engine._send_safe(job["chat_id"],
                             f"⏰ {job.get('label') or '時間到'}", "語音提醒")
        else:                               # 鬧鐘後備：開 1 秒鐘保證有聲
            lbl = job.get("label") or "時間到"
            ok, info = False, ""
            for gap in (4, 10, 25):        # 深睡冷啟動重試三波
                await engine._wait_wall(now + engine.dt.timedelta(seconds=gap))
                ok, info = await engine.asyncio.to_thread(
                    engine.run_intent, engine.timer_intent_cmd(1, lbl), 60)
                if ok:
                    break
                engine.log.warning("鐘聲意圖第%s波失敗：%s", gap, str(info)[:90])
            if not ok:
                engine.log.error("鐘聲三波全滅（%s）——TTS 連環錘頂上", lbl)
                engine.asyncio.create_task(engine._say_hammer(lbl))
            await engine._send_safe(job["chat_id"],
                             (f"⏰ {lbl}" if ok
                              else f"❌ 鐘聲開唔到（時鐘 app 三波都超時）——"
                                   f"語音連環叫緊你：{info[:80]}"),
                             "鬧鐘/計時到點")
        engine._TASKS.pop(job["id"], None)
        if job.get("daily"):
            job["next"] = engine._next_occurrence(now, job["hh"], job["mm"]).isoformat()
            jobs = engine._jobs()
            for j in jobs:
                if j["id"] == job["id"]:
                    j["next"] = job["next"]
            engine._save_json(engine.JOBS_PATH, jobs)
            engine._arm(job)
            return
        engine._save_json(engine.JOBS_PATH, [j for j in engine._jobs() if j["id"] != job["id"]])
        return
    if jtype == "series":
        secs = int(job.get("every") or job.get("seconds") or 60)
        lbl = job.get("label") or "時間到"
        ok, info = False, ""
        for gap in (0, 10, 25):            # 深睡冷啟動重試三波
            if gap:
                await engine._wait_wall(now + engine.dt.timedelta(seconds=gap))
            ok, info = await engine.asyncio.to_thread(
                engine.run_intent, engine.timer_intent_cmd(1, lbl), 60)
            if ok:
                break
            engine.log.warning("連環鬧意圖第%s波失敗：%s", gap, str(info)[:90])
        if not ok:
            engine.log.error("連環鬧鐘聲三波全滅（%s）——TTS 連環錘頂上", lbl)
            engine.asyncio.create_task(engine._say_hammer(lbl))
        msg = (f"⏰ {lbl}" if ok
               else f"❌ 鐘聲開唔到（三波超時）——語音連環叫緊你：{info[:80]}")
        await engine._send_safe(job["chat_id"], msg, "連環鬧")
        await engine._say(lbl, delay=4 if ok else 1)
        fire_dt = engine.dt.datetime.fromisoformat(job["next"])
        nxt = fire_dt + engine.dt.timedelta(seconds=secs)
        we = job.get("window_end")
        if we:
            end_dt = engine.dt.datetime.fromisoformat(we)
        else:
            # 錨點＝呢一輪 series 嘅起點（向前搵最近一次 hh:mm），
            # 唔可以用 fire_dt 直接管——尾響（跨午夜後）會錨去聽日（2026-09-28 實證：
            # #8 20:15–07:15 尾響 07:15 之後錨咗去聽日，多響成日）
            span = engine.dt.timedelta(minutes=((job["end_hh"] * 60 + job["end_mm"])
                                         - (job["hh"] * 60 + job["mm"])) % 1440)
            start_dt = fire_dt.replace(hour=job["hh"], minute=job["mm"],
                                       second=0, microsecond=0)
            if start_dt > fire_dt:
                start_dt -= engine.dt.timedelta(days=1)
            end_dt = start_dt + span
            job["window_end"] = end_dt.isoformat()
        if nxt <= end_dt:
            new_next = nxt
        elif job.get("daily"):
            new_next = (fire_dt + engine.dt.timedelta(days=1)).replace(
                hour=job["hh"], minute=job["mm"], second=0, microsecond=0)
            job.pop("window_end", None)     # 聽日重開新 window
        else:
            new_next = None
        if new_next:
            job["next"] = new_next.isoformat()
            jobs = engine._jobs()
            for j in jobs:
                if j["id"] == job["id"]:
                    j["next"] = job["next"]
                    we2 = job.get("window_end")
                    if we2:
                        j["window_end"] = we2      # 要 persist，唔係淨同步 next
                    else:
                        j.pop("window_end", None)
            engine._save_json(engine.JOBS_PATH, jobs)
            engine._TASKS.pop(job["id"], None)
            engine._arm(job)
        else:
            engine._save_json(engine.JOBS_PATH, [j for j in engine._jobs() if j["id"] != job["id"]])
            engine._TASKS.pop(job["id"], None)
        return
    if jtype == "weather":
        wok, report = await engine.asyncio.to_thread(engine._weather_report)
        msg = ("🌤 " + report) if wok else f"❌ 天氣攞唔到：{report[:120]}"
        await engine._send_safe(job["chat_id"], msg, "天氣簡報")
        if wok:
            await engine._say(engine._speech_scrub(report)[:140])
        if job.get("daily"):
            job["next"] = engine._next_occurrence(now, job["hh"], job["mm"]).isoformat()
            jobs = engine._jobs()
            for j in jobs:
                if j["id"] == job["id"]:
                    j["next"] = job["next"]
            engine._save_json(engine.JOBS_PATH, jobs)
            engine._TASKS.pop(job["id"], None)
            engine._arm(job)
        else:
            engine._save_json(engine.JOBS_PATH, [j for j in engine._jobs() if j["id"] != job["id"]])
            engine._TASKS.pop(job["id"], None)
        return
    if jtype == "timer":
        ok, info = engine.run_intent(engine.timer_intent_cmd(job["seconds"], job.get("label", "")))
        await engine._say(f"開始 {engine._speech_scrub(engine._fmt_job_content(job))}")
        how = engine._fmt_job_content(job)
    elif jtype == "nav":
        label = job.get("label") or job.get("url")
        defer_msg = False
        if not engine.DRY_RUN:
            engine._shell_priv_exec("input keyevent KEYCODE_WAKEUP")  # 著螢幕
            engine.asyncio.create_task(engine._nav_keyboard_msg(job["chat_id"], job))
            defer_msg = True
        if defer_msg:
            # TG 掣制確認係主路（彈窗已停用：Telegram 前景會攔截佢）
            ok, info = True, "TG 掣確認"
            how = f"開導航去「{label}」——撳 TG 掣「🗺 開地圖」先會開"
            await engine._say(f"開導航去{engine._speech_scrub(label)}")

            async def _nav_late(job=job):
                await engine.asyncio.sleep(5)     # 掣後聲音提示
                engine._nav_confirm_notify(job)
            engine.asyncio.create_task(_nav_late())
        else:
            ok, info = engine._nav_confirm_notify(job)
            if ok:
                how = f"開導航去「{label}」——彈窗問緊你，撳【是】先會開地圖"
            else:
                # 通知路出唔到（例如 Termux:API 冇反應）→ 退返舊路直接開
                engine.log.info("導航確認通知失敗，直接開：%s", info[:80])
                if engine.shutil.which("rish"):
                    # fire 前強制重探：你可能啱啱喺 Shizuku app 重啟咗 server，
                    # 唔好跟 10 分鐘 TTL 舊快取（每次 fire 至多探一次，JVM 開銷值得）
                    engine._RISH_CACHE["ok"] = engine._rish_probe()
                    engine._RISH_CACHE["t"] = now.timestamp()
                ok, info = engine._open_nav(job.get("url") or job.get("label", ""),
                                     job.get("mode", "d"))
                how = f"開導航去「{label}」（彈窗通知出唔到，直接開咗）"
                if not engine._rish_available() and not engine._adb_lane_available():
                    how += ("\n⚠️ Shizuku 同 adb lane 都冇行——導航可能彈唔出！"
                            "入 Shizuku app 撳「啟動」，或者 send「復活Shizuku」")
    elif jtype == "nag":
        await engine._send_safe(job["chat_id"],
                         f"💧 {job.get('label') or '提醒時間到'}", "習慣提醒")
        await engine._say(job.get("label") or "提醒時間到")
        nxt = now + engine.dt.timedelta(seconds=int(job.get("every") or 3600))
        job["next"] = nxt.isoformat()
        jobs = engine._jobs()
        for j in jobs:
            if j["id"] == job["id"]:
                j["next"] = job["next"]
        engine._save_json(engine.JOBS_PATH, jobs)
        engine._TASKS.pop(job["id"], None)
        engine._arm(job)
        return
    elif jtype == "focus":
        # 鐵閘：job 已被剷（專注結束/開新 session）→ 呢下 fire 係殭屍：
        # 唔落鐘、唔出聲、唔再 arm——ccd9f61 就係漏咗呢閘先無限接力
        if not any(x["id"] == job["id"] for x in engine._jobs()):
            engine._TASKS.pop(job["id"], None)
            engine.log.info("殭屍 focus fire 已攔（job #%s 已剷）", job["id"])
            return
        # 牆鐘錨定：位置由 session_start 重算，next 永遠寫未來——
        # 重啟/復活＝重算重返崗位，唔盲殺（用戶否決）唔預落（用戶否決）
        start = engine.dt.datetime.fromisoformat(job["session_start"])
        old_next = engine.dt.datetime.fromisoformat(job["next"])
        wmin, bmin = int(job.get("wmin", 25)), int(job.get("bmin", 5))
        elapsed = (now - start).total_seconds() / 60.0
        segs, acc, k = [], 0.0, 0          # (起分鐘, 迄分鐘, 名)
        while acc <= elapsed or not segs:   # 負延遲邊角都保證有段
            dur = wmin if k % 2 == 0 else bmin
            nm = (f"🎯 專注{k // 2 + 1}" if k % 2 == 0
                  else f"☕ 休息{k // 2 + 1}")
            segs.append((acc, acc + dur, nm))
            acc += dur
            k += 1
        s0, s1, nm = segs[-1]
        tag = f"（{job.get('label')}）" if job.get("label") else ""
        st = start + engine.dt.timedelta(minutes=s0)
        en = start + engine.dt.timedelta(minutes=s1)
        job["next"] = en.isoformat()       # 永遠未來——殭屍循環物理上不可能
        is_work = (s1 - s0) == wmin
        if st < old_next:
            # 呢段計時器上次已落咗（bot 凍緊嗰陣時鐘 app 照行）——淨係返崗位
            await engine._send_safe(job["chat_id"],
                             f"♻️ bot 返到崗位：{nm}{tag}行緊——{en:%H:%M} 響鐘轉下段",
                             "專注模式")
        else:
            remain = round((en - now).total_seconds())
            if remain >= 60:               # 段尾碎鐘唔落
                tl = (f"專注 {job.get('label', '')}".strip() if is_work
                      else "休息完再開工")
                ok, info = await engine.asyncio.to_thread(
                    engine.run_intent, engine.timer_intent_cmd(remain, tl))
                if (now - st).total_seconds() < 120:
                    how = (f"🎯 開始專注 {wmin} 分鐘" if is_work
                           else f"☕ 休息 {bmin} 分鐘")
                else:
                    how = f"♻️ bot 復活接軌：{nm} 餘下 {remain // 60} 分鐘"
                if is_work and job.get("label"):
                    how += f"（{job['label']}）"
                msg = (how + "\n⏱ 已落時鐘 app（深度睡眠都準時）" if ok
                       else f"❌ {how}失敗：{info[:80]}")
                await engine._send_safe(job["chat_id"], msg, "專注模式")
                await engine._say(engine._speech_scrub(how))
        jobs = engine._jobs()
        for j in jobs:
            if j["id"] == job["id"]:
                j["next"] = job["next"]
        engine._save_json(engine.JOBS_PATH, jobs)
        engine._TASKS.pop(job["id"], None)
        engine._arm(job)
        return
    elif jtype == "bthead":
        thr = int(job.get("thr", 60))
        ok, data = await engine.asyncio.to_thread(engine._headset_levels)
        msg = None
        if not ok:
            msg = f"❌ 耳機守攞唔到讀數：{data[:80]}"
            job["alerted"] = False
        else:
            for name, level in data:
                if (level is not None and level <= thr
                        and not job.get("alerted")):
                    job["alerted"] = True
                    msg = f"🎧 {name} 耳機得 {level}%（≤{thr}%）——記得叉電！"
                    await engine._say(f"耳機得{level}厘，記得叉電")
                    break
            if all(level is None or level > thr + 5 for _n, level in data):
                job["alerted"] = False
        if msg:
            await engine._send_safe(job["chat_id"], msg, "耳機守")
        jobs = engine._jobs()
        for j in jobs:
            if j["id"] == job["id"]:
                j["alerted"] = job.get("alerted", False)
        nxt = now + engine.dt.timedelta(minutes=10)
        job["next"] = nxt.isoformat()
        for j in jobs:
            if j["id"] == job["id"]:
                j["next"] = job["next"]
        engine._save_json(engine.JOBS_PATH, jobs)
        engine._TASKS.pop(job["id"], None)
        engine._arm(job)
        return
    elif jtype == "battery":
        pct, chg, temp = await engine.asyncio.to_thread(engine._battery_status)
        thr = int(job.get("thr", 20))
        msg = None
        if pct is None:
            msg = f"❌ 電量守攞唔到讀數：{str(temp)[:80]}"
        elif pct <= thr and not chg and not job.get("alerted"):
            job["alerted"] = True
            msg = f"🔋 電量得 {pct}%（≤{thr}%、冇充電）——記得叉電！"
            await engine._say(f"電量得{pct}厘，記得叉電")
        elif pct > thr + 5 or chg:
            job["alerted"] = False
        if msg:
            await engine._send_safe(job["chat_id"], msg, "電量守")
        jobs = engine._jobs()
        for j in jobs:
            if j["id"] == job["id"]:
                j["alerted"] = job.get("alerted", False)
        engine._save_json(engine.JOBS_PATH, jobs)
        nxt = now + engine.dt.timedelta(minutes=10)   # 2026-10-06 改密：一個鐘太空檔（用戶今朝 07:31 拔線前後個案）
        job["next"] = nxt.isoformat()
        for j in jobs:
            if j["id"] == job["id"]:
                j["next"] = job["next"]
        engine._save_json(engine.JOBS_PATH, jobs)
        engine._TASKS.pop(job["id"], None)
        engine._arm(job)
        return
    elif jtype == "seal":
        # 封印：到期（until 當日全日有效，翌日 00:00 過氣）→ pm enable 復活；
        # 淨巡邏貨先做 25 秒前景偵測（停用咗嘅唔使理）
        active = [x for x in job.get("apps", [])
                  if x["until"] >= now.date().isoformat()]
        expired = [x for x in job.get("apps", [])
                   if x["until"] < now.date().isoformat()]
        if expired:
            for x in expired:
                if x.get("mode") == "disabled":
                    oke, oute = engine._shell_priv_exec(
                        f"pm enable --user 0 {x['pkg']}")
                    if not oke:
                        engine.log.warning("解封 pm enable 失敗：%s %s",
                                    x["pkg"], str(oute)[:60])
            await engine._send_safe(job["chat_id"],
                             "🔓 到期解封：" + "、".join(x["label"] for x in expired),
                             "封印")
            await engine._say("解封喇")
        if not active:
            engine._TASKS.pop(job["id"], None)
            engine._save_json(engine.JOBS_PATH, [j for j in engine._jobs() if j["id"] != job["id"]])
            return
        patrol = [x for x in active if x.get("mode", "patrol") == "patrol"]
        if patrol:
            fg = await engine.asyncio.to_thread(engine._fg_pkg)
            hit = next((x for x in patrol if fg and x["pkg"] == fg), None)
            if hit:
                ok2, _ = await engine.asyncio.to_thread(
                    engine._shell_priv_exec, f"am force-stop {hit['pkg']}")
                if not ok2:
                    await engine.asyncio.to_thread(
                        engine._shell_priv_exec, "input keyevent KEYCODE_HOME")
                engine.log.info("封印命中：%s（force-stop=%s）", hit["pkg"], ok2)
                await engine._send_safe(job["chat_id"],
                                 f"🔒 封印緊「{hit['label']}」（到 {hit['until']}）"
                                 "——專注返正嘢",
                                 "封印")
                await engine._say("封印緊，專注返正嘢")
            job["next"] = (now + engine.dt.timedelta(seconds=25)).isoformat()
        else:
            # 全部停用咗：唔使巡，等到期翌日 00:01 解封
            nxt_date = min(engine.dt.date.fromisoformat(x["until"])
                           for x in active) + engine.dt.timedelta(days=1)
            job["next"] = engine.dt.datetime.combine(nxt_date,
                                              engine.dt.time(0, 1)).isoformat()
        jobs = engine._jobs()
        for j in jobs:
            if j["id"] == job["id"]:
                j["next"] = job["next"]
                j["apps"] = active
        engine._save_json(engine.JOBS_PATH, jobs)
        engine._TASKS.pop(job["id"], None)
        engine._arm(job)
        return
    elif jtype == "webplay":    # 網播：開網頁→即刻播歌（2026-10-07 用戶令）
        if not engine.DRY_RUN:
            engine._shell_priv_exec("input keyevent KEYCODE_WAKEUP")
        okw, _infow = engine.run_intent(
            engine.web_intent_cmd(job.get("url", "")))
        if job.get("vol") is not None:
            await engine.asyncio.to_thread(engine._set_media_volume,
                                           job["vol"])
        ok, info = engine._play(job.get("playlist", ""),
                                job.get("shuffle", False))
        how = f"網播「{job.get('label')}」" + ("" if okw else "（網頁開唔到）")
    elif jtype == "web":
        if not engine.DRY_RUN:
            engine._shell_priv_exec("input keyevent KEYCODE_WAKEUP")  # 著螢幕
        wurl = job.get("url") or job.get("label", "")
        ok, info = engine.run_intent(engine.web_intent_cmd(wurl))
        how = f"開網頁「{job.get('label')}」{wurl}"
        await engine._say(f"開網頁{engine._speech_scrub(job.get('label') or '')}")
    else:
        if job.get("vol") is not None:
            await engine.asyncio.to_thread(engine._set_media_volume, job["vol"])
        ok, info = engine._play(job["url"], job.get("shuffle", False))
        how = ("隨機開始播放" if job.get("shuffle") else "開始播放") + f"「{job['label']}」"
    if ok and info == "NO_AUTOLIST":
        msg = f"🔶 到點！開咗歌單頁「{job['label']}」，攞唔到首條片做自動播放，撳 ▶ 開始"
    elif ok:
        msg = f"⏰ 到點！{how}"
    else:
        msg = f"❌ 排程執行失敗：{info[:150]}" + (engine._BAL_TIP if engine._is_bal_denied(info) else "")
    if not defer_msg:
            await engine._send_safe(job["chat_id"], msg, "排程到點訊息")
    if job.get("daily"):
        job["next"] = engine._next_occurrence(now, job["hh"], job["mm"]).isoformat()
        jobs = engine._jobs()
        for j in jobs:
            if j["id"] == job["id"]:
                j["next"] = job["next"]
        engine._save_json(engine.JOBS_PATH, jobs)
        engine._TASKS.pop(job["id"], None)
        engine._arm(job)
    else:
        engine._save_json(engine.JOBS_PATH, [j for j in engine._jobs() if j["id"] != job["id"]])
        engine._TASKS.pop(job["id"], None)



def _hold_wake_lock() -> bool:
    """攞 Android wake lock：唔俾系統凍結計時器（呢樣先係 Android 準唔準嘅關鍵，
    換 cron 都救唔到 Doze 凍結）。2026-09-25 加：之前一直冇攞。"""
    try:
        r = engine.subprocess.run(["termux-wake-lock"], capture_output=True, timeout=10)
        ok = r.returncode == 0
        engine.log.info("wake lock %s", "攞到" if ok else f"攞唔到 rc={getattr(r, 'returncode', '?')}")
        return ok
    except Exception as e:
        engine.log.info("wake lock 攞唔到：%s", e)
        return False



_LOCK_FH = None   # singleton lock file handle——揸到 process 死，核心自動解鎖



def _acquire_singleton(path: str | None = None) -> bool:
    """單例鎖（flock）：第二條 instance 即刻退出。

    實例倍增（bashrc hook／boot／shortcut／restart 重疊）會令兩條
    getUpdates 互搶 updates——409 Conflict 之外仲會令訊息調轉序處理
    （「專注結束」先行、「專注 25」後到＝鬼計時器——2026-09-29 12:38
    用戶實證）。"""
    p = path or engine.LOCK_PATH
    engine.os.makedirs(engine.os.path.dirname(p), exist_ok=True)
    f = open(p, "w")
    try:
        engine.fcntl.flock(f, engine.fcntl.LOCK_EX | engine.fcntl.LOCK_NB)
    except OSError:
        f.close()
        return False

    engine._LOCK_FH = f
    f.seek(0)
    f.write(str(engine.os.getpid()))
    f.truncate()
    return True
