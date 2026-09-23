# Telegram 鬧鐘・計時器・歌單 Bot —— 逆向學習路徑 × 開發路線圖

> **目標一**：喺 Telegram 發指令 → 手機即時開計時器/鬧鐘
> **目標二**：喺 Telegram 發指令 → 手機即時/定時/每日播放 YouTube 歌單（可自定義）
> **平台**：Android ｜ **開發者**：AI（你負責攞 token、裝 Termux、測試）

---

## 0. 一句話架構

```
你手機 Telegram App ──發訊息──▶ Telegram 伺服器
                                     │ 長輪詢 (~0.5–1s)
                                     ▼
                  同一部手機 Termux 嘅 Python bot
                                     │ am start Intent (~0.2s)
                                     ▼
                        系統時鐘 App 開計時器/鬧鐘 🔔
```

**冇伺服器、冇自建 App、冇推送延遲。** 呢個就係「最短路徑」同「最快響應」重疊嘅原因。

---

## 1. 終點定義（逆向規劃嘅起點）

| # | Done 標準 | 驗證方法 |
|---|-----------|----------|
| D1 | 發「計時 25分鐘」→ 系統時鐘開始 25:00 倒數 | 肉眼睇時鐘 App |
| D2 | 發「計時到 18:30」→ 自動計算差距秒數開倒數 | 同上 |
| D3 | 發「鬧鐘 07:00」→ 鬧鐘列表出現 07:00 | 打開時鐘 App 鬧鐘頁 |
| D4 | 指令 → 觸發延遲 ≤ 2 秒 | 計時 |
| D5 | 熄屏、鎖屏 bot 都繼續運作 | 熄屏發指令測試 |
| D6 | 重開機後 bot 自動復活 | 重開機測試 |

---

## 2. 逆向拆解：由終點倒退回起點

| 里程碑 | 要達成嘅能力 | 需要嘅知識 |
|--------|--------------|-----------|
| **M5** 24/7 長駐 | wake-lock、電池白名單、Termux:Boot 開機自啟 | Android 電池管理、Termux 生態 |
| **M4** 系統整合 ⬅ 靠 D1–D3 驗收 | 用 `am start` 發 `SET_TIMER` / `SET_ALARM` Intent | Android Intent、AlarmClock 常數 |
| **M3** 指令文法 | 中文時長/HH:MM 解析、「倒數到」時間推算 | Python 正則、datetime |
| **M2** Bot 骨架 | BotFather 攞 token、長輪詢收發訊息、首次對話自動綁定擁有者 | Telegram Bot API、python-telegram-bot |
| **M1** 執行環境 | Termux（F-Droid 版）+ Python 3 | Termux 基本指令 |

> 正向行：**M1 → M2 → M3 → M4 → M5**。M1–M4 嘅程式已經寫好（見 `bot.py`），M5 係手機設定。

---

## 3. 路徑 A：最短路徑 🟢（本次交付，剩返 ~20 分鐘係你做）

| 步驟 | 內容 | 預計時間 | 資源 |
|------|------|----------|------|
| A1 | 裝 Termux（F-Droid/GitHub 版，**唔好**用 Play Store 停更版） | 5 min | [termux.dev](https://termux.dev/) · [wiki](https://wiki.termux.com/wiki/Main_Page) |
| A2 | @BotFather `/newbot` 攞 token（複製住先） | 3 min | [BotFather](https://t.me/BotFather) · [Bot API](https://core.telegram.org/bots/api) |
| A3 | 將 `setup.sh` 傳入手機（Telegram 傳俾自己 → 存 Download），Termux 行：`termux-setup-storage && cp /sdcard/Download/setup.sh ~ && bash setup.sh`；腳本會**問你貼一次 token**，之後全自動：裝依賴 → 設自啟 → 起動 bot | 5 min | 本 repo |
| A4 | Telegram 開 bot send /start（**自動綁定擁有者，唔使查 chat_id**），再 send「計時 1分鐘」驗收 D1–D4 | 2 min | — |
| A5 | 手機設定 Termux 電池「無限制」搞掂 D5；（可選）裝 Termux:Boot 開一次搞掂 D6（腳本 setup.sh 已自動放好） | 5 min | [Termux:Boot](https://wiki.termux.com/wiki/Termux:Boot) |

> 全程唔使開任何檔案改設定。想換 token：`TG_TOKEN="新token" bash setup.sh`；想換擁有者/加人：改 `~/.tgalarm/config` 嘅一行就得，唔使重啟。
>
> 🔄 **更新 bot**：重新下載 `setup.sh` 行一次就升級完（token 同擁有者綁定會保留，唔使再入）。
>
> 🔧 **常見錯誤**：`ERROR: Installing pip is forbidden` —— 舊版腳本會撞呢個 Termux 限制，新版 setup.sh 已修正，重新下載行一次就得（重跑安全，已裝嘅嘢會跳過）。

**學習成本：零程式基礎都做得到**——全程互動式，唯一要輸入嘅嘢係一次 Bot token，所有程式邏輯已經完成並通過 191 個單元測試。

---

## 4. 路徑 B：最快響應時間 🔵（延遲分析 + 優化）

指令由按下發送到鬧鐘出現，逐段延遲預算：

| 延遲段 | 本方案（手機本地 bot） | 要租伺服器嘅方案 |
|--------|------------------------|------------------|
| 你 → Telegram 伺服器 | ~50–200 ms（HK 網絡） | 一樣 |
| Telegram → bot | 長輪詢 ~0.5–1 s | Webhook ~0.3 s（但伺服器→手機要靠 FCM，+1–3 s） |
| 指令解析 | < 10 ms | 一樣 |
| `am` Intent → 時鐘 | ~200–500 ms | FCM → App → AlarmManager: +1 s 以上 |
| **合計** | **≈ 1–2 s ✅** | ≈ 2–5 s ❌ 仲慢仲複雜 |

**結論：本地長輪詢已經係物理上最快**，因為訊息一落手機就直接變 Intent，中間零跳轉。再要榨乾延遲咪做呢 4 樣：

1. `termux-wake-lock` 長開（防熄屏休眠，腳本已包）
2. 手機設定 → Termux → 電池 → **無限制**（小米/華為另開「自啟動」+鎖定後台）
3. Intent 預設 `SKIP_UI=true`——唔彈時鐘 App 畫面（某啲廠牌要 `SKIP_UI=0`）
4. bot 進程長駐，唔好逐次起動（`run_polling` 本身就係）

---

## 5. 路徑 C（延伸，如有朝想自製 App）

如果將來想擺脫 Termux、做個真 Android App：Kotlin 基礎 → AlarmManager/AlarmClock API → 前台 Service 收 FCM → Material 介面。學習量約 2–4 星期，對比路徑 A 嘅 30 分鐘——**除非你要畀人用，否則唔值得**。

---

## 6. 指令文法表（已實作+已測試）

| 你打字 | 效果 | 系統動作 |
|--------|------|----------|
| 計時 25分鐘 | 25 分鐘倒數 | SET_TIMER 1500s |
| 計時 1小時30分 / 1.5小時 / 1個半鐘 | 90 分鐘倒數 | SET_TIMER 5400s |
| 計時 3天 / 半天 / 1天半 / 1天12小時 | 以日計時長（天・日・day・d） | 自動換算秒數 |
| 計時 90秒 | 90 秒倒數 | SET_TIMER 90s |
| 計時到 18:30 / 1830 | 由而家倒數到 18:30（過咗計聽日） | SET_TIMER（自動計秒數） |
| 計時 1830 | 同「計時到 18:30」（無時間單位嘅 3–4 位數會當時刻睇） | 同上 |
| 計時 明天/聽日 1830 | 倒數到指定日子時刻 | 同上 |
| 計時 後天/大後天 0700 | +2 日 / +3 日 | 同上 |
| 計時 0925 1830 | mmdd 指定日期＋時刻（過咗自動計出年） | 同上 |
| 計時 10分鐘 杯麵 | 同上，標籤「杯麵」 | MESSAGE extra |
| 鬧鐘 07:00 / 0700 | 系統鬧鐘 07:00（過咗計聽日） | SET_ALARM 07:00 |
| 鬧鐘 7:30 起身 | 同上，標籤「起身」 | SET_ALARM + MESSAGE |
| timer 25m / alarm 07:00 | 英文同效 | 同上 |
| 📦 多行輸入（每行一個指令） | 批次執行全部，空行自動略過 | 逐行回覆結果 |
| 📦 裸行繼承：`計時 1830`（換行）`1900` | 淨寫時間嘅行自動繼承上一行嘅「計時/鬧鐘」 | 同上 |
| 播 / 播 lofi / 播 \<url\> | 即刻播 YouTube（預設/指定歌單/直接連結） | VIEW intent 直開 YouTube app |
| 隨機播 [名] / 播 [名] 隨機 | 🔀 隨機抽一條做開場（之後跟歌單順序） | 抽全部 videoId 隨機揀 |
| 每日 0700 播 [名] 隨機 | 每日排程＋每次到點重新隨機開場 | 同上 |
| 每日 0900 計時 25分鐘 / 1830 計時 10分鐘 | ⏱ 計時器都收排程（每日/一次） | 到點出 SET_TIMER intent |
| 排程・取消 N・暫停 N・繼續 N・改 N | 排程管理：列表/刪除/暫停/恢復/就地編輯（時間・循環・內容） | `~/.tgalarm/jobs.json` |
| 同類型同時間新排程 | **自動取代**舊排程，唔會重複觸發 | 取代時會通知 |
| 停 | 停止播放 | force-stop YouTube |
| 2130 播 [名] | 一次性排程（過咗計聽日） | 到點自動開 YouTube |
| 每日 0700 播 [名] | 每日排程，重開機自動恢復 | 同上 |
| 歌單 名 url・歌單・預設歌單 名・刪歌單 名 | 自定義歌單管理 | `~/.tgalarm/playlists.json` |
| 地點 名 地址・導航 名 [步行]・地點・刪地點 名 | 自定義地點 + 即開 Google Maps 導航（google.navigation URI；連結直通；**預設 Transit 大眾運輸**，加「步行」先入步行模式） | `~/.tgalarm/destinations.json` |
| hhmm 導航 名・每日 hhmm 導航 名 [模式] | **定時導航**：到點自動開 Google Maps 導航（🧭 排程，同播/計時共存、同類同時間自動取代） | `~/.tgalarm/jobs.json` |
| 待辦 項目…・待辦・完成 N・未做 N・刪 N・清除已完成 | **置頂待辦清單**：自動發訊息兼釘喺聊天頂，每項一粒 ☐/✅ 按鈕直接撳，改動原地即時更新；「待辦 X」之後每行裸字自動變待辦項目（同計時/鬧鐘批次繼承一樣） | `~/.tgalarm/todo.json` |
| [每日] hhmm至hhmm 分配 [留空N%] 項目[x比例]… | **時間分配（time-blocking）**：按權重切開起止時間（預留 buffer 百分比），到點逐段自動彈 SET_TIMER 連環計時，跨日都得；🧩 入同一排程系統 | `~/.tgalarm/jobs.json` |

---

## 6.5 擴充目標：定時播 YouTube 歌單（逆向規劃 v2）

| 里程碑 | 能力 | 做法 |
|--------|------|------|
| **W4** 24/7 + 重開恢復 | 排程持久化、重開後自動重新武裝 | `jobs.json` + `post_init` 恢復（每日計下一次；過期一次排程開機後補播） |
| **W3** 定時觸發 | 一次/每日排程、取消、列表 | 每個 job 一個 `asyncio.sleep` 任務，零新依賴 |
| **W2** 播歌單 | 開 YouTube app 播 playlist | 抽出歌單第一條片 → 用 `watch?v=…&list=…` 直開播放器**自動播**（開 `playlist?list=` 頁唔會自動播） |
| **W1** 指令文法 | 播/停/排程/歌單管理 | 沿用批次解析，URL 大小寫保留 |

**路徑 A（最短）＝本次交付**：重用現有 24/7 bot 骨架，零新 token、零新依賴、零新裝置。
**路徑 B（最快響應）**：到點 → `am start` 直開 YouTube，**約 0.5–2 秒出聲**。對比 yt-dlp + mpv 串流方案要握手 buffering **3–10 秒**，仲要追 YouTube 改版 —— Intent 方案快、穩、免維護。
學習資源：[VIEW intent](https://developer.android.com/reference/android/content/Intent)、[YouTube playlist 連結格式](https://support.google.com/youtube/answer/57792)、[asyncio tasks](https://docs.python.org/3/library/asyncio-task.html)、[PTB post_init](https://docs.python-telegram-bot.org/en/stable/telegram.ext.applicationbuilder.html)。

---

## 7. 已知限制（設計取捨）

- **SET_TIMER** 要靠支援嘅時鐘 App——官方推薦 [Google「時鐘」](https://play.google.com/store/apps/details?id=com.google.android.deskclock)。廠牌自帶時鐘（如小米）可能唔認呢個 Intent；bot 會回報錯誤提示你。
- **iOS 行唔到呢條路**：Apple 唔准第三方設定系統鬧鐘，要用捷徑/App 內通知，係另一條學習路徑。
- `SET_ALARM` 用 `SKIP_UI=true` 跳過確認畫面；shell（Termux `am`）有隱含 SET_ALARM 權限，所以一般秒設。
- 重複鬧鐘（每日 07:00）、取消、列表查詢未喺 v1；Intent 方案寫唔到「邊個鬧鐘係我設過」，要做就要行路徑 C 用 AlarmManager 自建。
- **日期只限計時器**（明天/聽日/後天/大後天/mmdd）：鬧鐘 Intent 本身唔支援日期，係 Android 限制。計時**硬上限 99999 小時**（約 11 年），超過會直接拒絕、唔出 intent。
- **自動綁定機制**：裝完後第一個 send 訊息俾 bot 嘅帳號會成為擁有者，其他人會被拒絕——所以裝完**即刻**自己 send /start。
- **歌單播放要裝 YouTube app**（冇就自動 fallback 瀏覽器）；串流要網絡；熄屏下 YouTube app 起播行為視乎機型，建議實測一次。音量唔會自動調校——用系統媒體音量預設。
- **自動播放原理**：`playlist?list=` 連結 YouTube 只會開歌單頁；bot 會先在線抽歌單影片（**官方 RSS 優先**，頁面爬取後備），轉做 `watch?v=…&list=…` 先開。攞唔到（網絡錯誤/私人歌單）會照開歌單頁兼提示你手撳 ▶。
- **「停」係四層 fallback**：Termux 冇權直接殺其他 app，所以逐層試——①Termux:API 靜音搶音訊焦點（要裝 Termux:API，最乾淨）→ ②系統 am force-stop → ③PATH am → ④返主畫面（非 Premium 入背景即停）。想 100% 乾淨停：F-Droid 裝 **Termux:API** + `pkg install termux-api`，bot 會自動用第一招。

### 深夜/熄屏冇反應？

排程喺白日用緊電話時正常，但深夜唔響，多數係 Android 兩個嘢作怪。send `自檢` 一嘢驗證（兩分鐘後對返邊步甩）：

1. **bot 進程被殺/被凍結**（訊息都冇，或者遲幾分鐘補響）：設定 → 應用程式 → Termux → 電池 → **無限制**；部分品牌（小米/華為/OPPO/vivo）要另外開「背景活動允許」「自啟動」；Android 13+ 記得**通知權限**開返畀 Termux（冇常駐通知 → wakelock 都托唔住）。
2. **背景彈唔到介面**（有訊息冇計時器/冇播放）：設定 → 應用程式 → Termux → **「喺其他應用上層顯示」→ 允許**（Android 10+ 限制背景 app 開介面，呢個權限係官方逃生門）。
3. setup 已經有 `termux-wake-lock`；熄屏夜晚確保 Termux 喺通知欄有常駐通知，唔好被「深度清除」。
4. 一指令搞掂：send `修復` → bot 直接彈 Termux 應用詳情頁 + 電池優化清單畀你逐項撥（唔使自己掘設定）。

---

## 8. 檔案一覽

| 檔案 | 作用 |
|------|------|
| `setup.sh` | **唯一要傳上手機嘅檔案** 📦 內嵌 bot.py：問你一次 token，自動裝依賴、設自啟、起動 bot |
| `bot.py` | 主程式原始碼（已內嵌喺 setup.sh；獨立開發/測試用） |
| `test_bot.py` | 191 個單元測試（……同前，另加 fast-forward _rem 直撃 + _send_safe 十項 + 搬相 wamove 十二項），全數通過 ✅ |
| `requirements.txt` | Python 依賴（開發用；setup.sh 會自己裝） |

**下一步**：做 [第 3 節](#3-路徑-a最短路徑本次交付剩返-20-分鐘係你做) A1–A4，有咩卡關隨時貼錯誤訊息俾我。
