# tgalarm 🤖⏰

**Telegram 鬧鐘・排程・天氣・導航 Bot —— 你部舊 Android＋Termux 就係成個系統**

> 冇伺服器、冇雲端、冇月費。零依賴部署喺手機入面，Telegram 一句話，
> 手機即刻較鬧鐘、報天氣、開導航、播歌單、報更提醒。

```
你（任何地方）Telegram App ──▶ Telegram 伺服器
                                 │ 長輪詢 (~0.5–1s)
                                 ▼
            你部 Android 入面 Termux 嘅 Python bot
                 │                   │
        am start Intent          Open-Meteo / SerpAPI
                 ▼                   ▼
     系統時鐘🔔・Google Maps🗺   天氣／AI 答案
```

## 功能

| | 指令例 | 説明 |
|---|---|---|
| ⏰ 鬧鐘/計時 | `鬧鐘 0700`・`計時 25分鐘`・`計時到 1830` | 經系統時鐘 app 響——大聲、可靠 |
| 🔁 連環鬧 | `鬧鐘 2100-0000 每60分鐘 報更` | 範圍內定時響；**過午夜都得**；可拆兩行寫；頭加「每日」＝日日 |
| 🗓 排程 | `每日 0700 播 lofi`・`0830 導航 公司` | 每日/一次；暫停・繼續・改時間；重啟自動恢復 |
| 🧩 時間分配 | `1930至2230 分配 留空10% 温習x2、沖涼` | 到點連環計時，留空時間最尾分 |
| 🧭 導航 | `導航 公司`・`地點 公司 <地址>` | **TG 撳掣確認先開**（🗺 開地圖／✖ 唔去）；adb/rish/open-url 三層後備 |
| 🌤 天氣 | `天氣` | Open-Meteo 免 API key：而家＋今日聽日＋帶遮建議；可排每日定時簡報 |
| 🧠 AI 问答 | `ai 香港明天要帶遮嗎` | Google AI Mode（經 SerpAPI，附來源） |
| 📋 待辦 | `待辦 交電費`・`完成 2` | 自動置頂，TG 撳掣打勾 |
| 🌙 深夜相 | `搬相`・`搬相預覽` | WhatsApp 23:00–07:00 嘅相自動搬入相簿按日歸檔 |
| 🩺 自檢 | `自檢`・`修復` | 排程唔響？一鍵驗證＋跳保障設定頁 |

## 30 秒安裝（Android + Termux）

```bash
# 1. 裝 Termux（GitHub release 版）
# 2. Termux 入面：
pkg install -y git python && termux-setup-storage
git clone https://github.com/<你>/tgalarm.git && cd tgalarm
bash setup.sh        # 問你攞一次 BotFather token，之後全自動
# 3. 搞掂。termux-wake-lock 已自動攞，重啟後用 crontab 守護復活
```

設定檔喺 `~/.tgalarm/config`（權限 600），token／API key 全部唔使寫入代碼：

| 變數 | 必填 | 説明 |
|---|---|---|
| `BOT_TOKEN` | ✅ | @BotFather 申請 |
| `ALLOWED_CHAT_IDS` | 建議 | 白名單；首次使用自動綁定擁有者 |
| `SERPAPI_KEY` | 可選 | `ai` 功能用（免費 100 次/月） |
| `SKIP_UI` | 可選 | `0`＝計時器要撳開 app 確認 |

## 點解準時？（Android 排程嘅真相）

排程唔準嘅主因唔係調度器，係**系統凍結 Termux**。所以：
- 啟動即攞 `termux-wake-lock`（退出先放）
- 排程用「下一個鐘點絕對時間」計算，唔會累積飄移
- 長輪詢即時收指令，熄屏照運作

## 測試

```bash
python -m pytest test_bot.py -q   # 262 tests，全程 mock，唔使 token 唔使手機
```

## 安全設計

- Token／key 只存 `~/.tgalarm/config`（600），git 歷史零密件
- chat 白名單，陌生人不會被綁定
- 導航要確認先開（防誤觸）；所有 shell 調用零 user input 拼接

## License

MIT
