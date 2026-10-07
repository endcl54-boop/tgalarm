"""app：Telegram 入口層（_on_message／_on_start／main／HELP）。
組合根：識所有域（經 engine re-export）；共享名經 engine.X 延遲綁定。"""
from __future__ import annotations

from . import engine

HELP = (
    "🤖 指令格式：\n"
    "⏱ 計時器（直接落手機時鐘 app，系統自己響——深度睡眠都準時）：\n"
    "・計時 25分鐘 攞集運（時鐘app響＋到點讀你聽；取消 N 淨刪語音）\n"
    "・計時到 18:30 或 1830（倒數到指定時間）\n"
    "・計時 明天 1830 / 後天 0700 / 0925 1830（連日期都收）\n"
    "・外賣模式：「外賣」即刻開（hhmm 後數字＝單號）；「外賣結束」收工；「每日1100 外賣」／「每日1400 外賣結束」＝日日自動開/收（冇每日＝一次）\n"
    "🎯 專注：專注 25（工作/休息循環，系統計時器響）・專注結束\n"
    "💧 提醒 每60分 飲水（每 N 分 TG 提；取消 N 收）　🔋 電量／電量守 20／電量守完\n"
    "🎧 耳機（即查藍牙耳機電量）・耳機守 60（≤60% 提你叉電）・耳機守完\n"
    "📅 倒數 考試 2027-05-04／倒數 聖誕 12-25（每年）／倒數（清單）　🎲 分組 3 阿明,阿強,阿寶\n"
    "⏰ 鬧鐘（直接落手機時鐘 app，系統自己響）：\n"
    "・鬧鐘 07:00 或 0700　・鬧鐘 1730 起身　・鬧鐘 每日0734 標籤＝日日\n"
    "・連環鬧：鬧鐘 0900-1700 每60分鐘 轉位；過午夜都得（2100-0000 報更）；可拆兩行寫；頭加「每日」＝日日\n"
    "（後面加文字會變成標籤，例如：計時 10分鐘 杯麵）\n"
    "📦 批次輸入：一次過 send 幾行，每行一個指令\n"
    "　（之後每行淨係打時間都得，會繼承上面嘅計時/鬧鐘）\n"
    "🎵 播 YouTube 歌單：\n"
    "・播 [名/連結]　・隨機播 [名]　・停　・2130 播 [名]\n"
    "・音量40% 播 [名]／0700 音量40% 播 [名]＝開播前校好媒體音量（最大聲嘅 %）\n"
    "・每日 0700 播 [名] 隨機　・每日 0900 計時 25分鐘（計時排程）\n"    "・0730 網播 新聞 loHouse＝開網頁＋播歌一條 job；頭加每日＝日日\n"    "・calm＝即刻開 Calm　・每日2130 calm＝日日叫你＋自動開\n"    "・靜音 2300 0730＝日日呢段唔出聲（TG照出）・取消靜音\n"
    "・歌單 名 連結（儲存）　・歌單/排程（列表）\n"
    "・管理：取消 N・暫停 N・繼續 N・暫停排程＝全部停・繼續排程＝全部恢復・改 N 1830\n"
    "・排定日期：1005 暫停排程 3（10月5日起停 #3）・1012 繼續排程（全部恢復）；號碼可多個/省略\n"
    "🧭 導航（Google Maps）：\n"
    "・地點 公司 沙田石門安群街1號（儲地點）　・導航 公司 [步行]（預設巴士）\n"
    "・0830 導航 公司　・每日 0800 導航 公司　・地點（清單）・刪地點 公司\n"
    "🌐 網頁：・網頁 新聞 https://…（儲）・開網頁 新聞　・0830 開網頁 新聞・每日 0900 開網頁 新聞\n"
    "🔒 封印（衝動防線）：封印 za 到 2026-10-15（停用，點入開唔到）・封印到1001（續封上次）・解封 [名]\n"
    "🛡 財務防護：層數（本週配額）・活動 X（開始）・活動完・提議（抗無聊）・使咗/洗左 50 午餐（記開銷，可加 想要）\n📋 待辦（自動置頂，撳按鈕打勾）：\n"
    "・待辦 牛奶、交電費（加項目）　・待辦（睇清單）\n"
    "・完成 2　・未做 2　・刪 2　・清除已完成\n"
    "🧩 時間分配（到點自動連環計時）：\n"
    "・1930至2230 分配 留空10% 温習x2、做功課、沖涼\n"
    "・留空可寫%或分鐘（留空30分鐘），唔寫都得；加「每日」喺頭=日日咁玩；x2=佔兩份時間，冇寫=一份\n"
    "🔊 語音：全線任務到點廣東話旁白・下一個（隨問隨讀）・講 [文字]\n🩺 深夜冇反應/遲響？send「自檢」驗證；「修復」即彈保障設定頁\n"
    "🌙 搬相：「搬相」搬最近夜更時段（23:00–07:00）；「搬相 HHMM HHMM」自訂時段——讀圖自動分崗位，歸檔 BG巡邏相片記錄／月份／日期／Shift_A/B/C／崗位；「搬相預覽」齋睇；「搬回」全數搬返 WhatsApp Images\n"
    "⏩ 分配快進：「完成」提早做完而家呢段即刻入下階段；最後段就提早收工"
    "\n🧠 問 Google AI：「ai 點樣由旺角去銅鑼灣？」或「問 明天適合洗車嗎」"
    "\n💱 匯率 100美金（淨「匯率」＝主要貨幣表）　🌍 時間 東京"
    "\n🎲 骰仔（骰仔 20）　🎯 揀 飲茶/壽司/拉麵　🔐 密碼 16　💪 打氣"
    "🎲 大話骰：「大話」開枱，3個4 叫牌，「開！」攤牌；起手 3個起／齋2個起／叫1即齋；計分制「3個4齋」齋叫「劈」雙倍"
    "\n🌤 天氣：「天氣」即時查（自動帶你嗰邊／屋企佐敦讀數）；「排程」可加每日天氣簡報"
)


async def _ensure_owner(update) -> bool:
    """白名單檢查 + 首次使用自動綁定。回傳 True = 可以繼續。"""
    cid = update.effective_chat.id
    allowed = engine._allowed_ids()
    if not allowed:
        engine._bind_owner(cid)
        await update.message.reply_text(
            f"✅ 已自動綁定你做擁有者（chat_id={cid}）\n"
            "由而家起淨係你嘅帳號可以指揮呢隻 bot。\n"
            f"（想加人/換人：改 {engine.CONFIG_PATH} 入面嘅 ALLOWED_CHAT_IDS，唔使重啟）"
        )
        return True
    if cid not in allowed:
        engine.log.warning("未授權存取 chat_id=%s", cid)
        await update.message.reply_text("⛔ 呢隻 bot 已綁定咗其他擁有者。")
        return False
    return True



async def _on_start(update, context):
    if not await engine._ensure_owner(update):
        return
    await update.message.reply_text("👋 準備就緒！\n" + engine.HELP)



async def _on_message(update, context):
    if not update.message or not update.message.text:
        return
    if not await engine._ensure_owner(update):
        return

    t = update.message.text.strip()
    if t in ("天氣", "天气", "weather") or t.startswith("天氣 "):
        await update.message.reply_text("🌤 查緊天氣…")
        wok, rep = await engine.asyncio.to_thread(engine._weather_report)
        await update.message.reply_text(("🌤 " + rep) if wok
                                        else f"❌ 天氣攞唔到：{rep[:150]}")
        return
    m = engine.re.fullmatch(r"(骰仔|dice)(?:\s+(\d{1,3}))?", t, engine.re.IGNORECASE)
    if m:
        await update.message.reply_text(engine._dice_reply(m.group(2) or ""))
        return
    if t.startswith(("揀 ", "揀")):
        await update.message.reply_text(engine._pick_reply(t[1:].strip()))
        return
    if t.startswith("密碼"):
        await update.message.reply_text(
            engine._password_reply(t[2:].replace(" ", "")), parse_mode="Markdown")
        return
    if t == "打氣" or t.startswith("打氣 "):
        await update.message.reply_text("💪 " + engine._PEP[engine.dt.datetime.now().microsecond % len(engine._PEP)])
        return
    if t.startswith("時間 ") or t == "時間":
        await update.message.reply_text(engine._time_reply(t[2:].strip()))
        return
    m = engine.re.fullmatch(r"([\u4e00-\u9fff\w]{1,12})時間", t)
    if m:
        await update.message.reply_text(engine._time_reply(m.group(1)))
        return
    _cid0 = update.effective_chat.id if getattr(update, "effective_chat", None) else 0
    _tw = engine._takeaway_handle(t, _cid0)
    if _tw is not None:
        await update.message.reply_text(_tw)
        return
    _fd = engine._findef_route(t)
    if _fd is not None:
        _okfd, repfd = await engine.asyncio.to_thread(engine._findef_api, _fd[0], _fd[1])
        await update.message.reply_text(repfd)
        return
    _cm = engine._calm_handle(t, _cid0)
    if _cm is not None:
        await update.message.reply_text(_cm)
        return
    _qm = engine._quiet_handle(t)
    if _qm is not None:
        await update.message.reply_text(_qm)
        return
    _cd = engine._countdown_handle(t, _cid0)
    if _cd is not None:
        await update.message.reply_text(_cd)
        return
    _gp = engine._groups_handle(t)
    if _gp is not None:
        await update.message.reply_text(_gp)
        return
    if t in ("下一個", "下一個任務", "next"):
        line = engine._next_task_line()
        await engine._say(line)
        await update.message.reply_text("🔊 " + line)
        return
    m = engine.re.fullmatch(r"(?:講|讀|tts)\s+(.+)", t, engine.re.IGNORECASE)
    if m:
        said = engine._speech_scrub(m.group(1))
        await engine._say(said)
        await update.message.reply_text(f"🔊 讀咗：{said[:60]}")
        return
    for _h in (engine._nag_handle, engine._focus_handle, engine._bthead_handle, engine._battery_handle):
        _hr = _h(t, _cid0)
        if _hr is not None:
            await update.message.reply_text(_hr)
            return
    _lcid = update.effective_chat.id if getattr(update, "effective_chat", None) else None
    if (_lcid and engine._LIAR_GAMES.get(_lcid)) or t.startswith("大話"):
        _r = engine._liar_handle(_lcid, t)
        if _r is not None:
            await update.message.reply_text(_r)
            return
    if t.startswith("匯率"):
        await update.message.reply_text("💱 查緊匯率…")
        rep = await engine.asyncio.to_thread(engine._fx_reply, t[2:].strip())
        await update.message.reply_text(rep)
        return
    if t.lower().startswith("ai ") or t.startswith("問 "):
        parts = t.split(None, 1)
        q = parts[1].strip() if len(parts) > 1 else ""
        if not q:
            await update.message.reply_text("用法：ai <問題>（例：ai 旺角去銅鑼灣點去最快？）")
            return
        await update.message.reply_text("🔎 問緊 Google AI Mode，可能要十幾秒…")
        _ok, ans = await engine.asyncio.to_thread(engine._ai_mode_answer, q)
        await update.message.reply_text(ans)
        return

    now = engine.dt.datetime.now()
    items = engine.parse_lines(update.message.text, now)
    if not items:
        return

    results = []
    for ln, p in items:
        if isinstance(p, engine.PlayerCmd):
            if p.action in ("wamove", "wareturn"):      # 讀圖分類需時，唔好閉塞 loop
                results.append(await engine.asyncio.to_thread(
                    engine._execute_player, p, update.effective_chat.id, now))
            else:
                results.append(engine._execute_player(p, update.effective_chat.id, now))
            if p.action == "todo":
                engine.asyncio.create_task(engine._say(engine._todo_speech()))
        elif p:
            results.append(engine._execute(p, now, update.effective_chat.id))
        else:
            # 逐行後備：外賣／財務文法淨係喺成句比對有接（4753/4757），
            # 多行訊息逐行都要識（2026-10-07 用戶三報個案：兩行一齊 send 全❓）
            _tk = engine._takeaway_handle(ln, update.effective_chat.id)
            if _tk is not None:
                results.append(_tk)
                continue
            _fdl = engine._findef_route(ln)
            if _fdl is not None:
                _okf, _repf = await engine.asyncio.to_thread(engine._findef_api, _fdl[0], _fdl[1])
                results.append(_repf)
            else:
                results.append(f"❓ 睇唔明：{ln}")

    reply = "\n".join(results)
    if len(items) == 1 and results[0].startswith("❓"):
        reply += "\n\n" + engine.HELP  # 單行失敗先彈完整格式說明，批次就逐行標示
    if reply.strip():
        await update.message.reply_text(reply)



def main():
    if not engine._acquire_singleton():
        engine.log.info("已有 bot instance 行緊（singleton lock）——呢條即刻退出")
        return
    if not engine.BOT_TOKEN:
        engine.sys.exit(
            "未設定 BOT_TOKEN。\n"
            "最簡單：行 bash setup.sh，佢會問你一次 token 然後全部自動搞掂；\n"
            "或者手動：export BOT_TOKEN=\"你嘅token\" 再 python bot.py"
        )
    from telegram.ext import (
        Application,
        CallbackQueryHandler,
        CommandHandler,
        MessageHandler,
        filters,
    )

    app = Application.builder().token(engine.BOT_TOKEN).post_init(engine._restore_jobs).build()
    app.add_handler(CommandHandler("start", engine._on_start))
    app.add_handler(CommandHandler("help", engine._on_start))
    app.add_handler(CallbackQueryHandler(engine._on_todo_callback, pattern=r"^todo:"))
    app.add_handler(CallbackQueryHandler(engine._on_nav_callback, pattern=r"^nav:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, engine._on_message))
    app.add_error_handler(engine._on_error)
    engine.log.info("Bot 啟動（長輪詢模式，DRY_RUN=%s，config=%s）", engine.DRY_RUN, engine.CONFIG_PATH)
    if not engine.DRY_RUN:
        engine._hold_wake_lock()
    app.run_polling(drop_pending_updates=True)
    try:
        engine.subprocess.run(["termux-wake-unlock"], capture_output=True, timeout=10)
    except Exception:
        pass



if __name__ == "__main__":
    main()
