# PROGRESS — 專案現狀＆交接手冊

> 新 agent／新機器接手：由呢份文件開始。最後更新：2026-09-25。

## 現狀（全部已上線＋真機實測）

| 功能 | 狀態 |
|---|---|
| 鬧鐘/計時（系統時鐘 intent） | ✅ |
| 連環鬧 `鬧鐘/計時 hhmm-hhmm 每x分鐘 [文字]`（過午夜／兩行寫法／每日） | ✅ |
| 排程（每日/一次、暫停/繼續/改、重啟恢復、去重取代） | ✅ |
| 時間分配（留空語義：先斬留空、餘額再分、留空永遠尾） | ✅ |
| 導航：**TG 撳掣確認**（🗺 開地圖／✖ 唔去）→ clear-task 開 Maps | ✅ 彈窗已退役 |
| 天氣：`天氣` 隨問隨答＋每日 11:00/18:30 簡報（Open-Meteo 免 key） | ✅ |
| AI：`ai <問題>`（SerpAPI Google AI Mode） | ✅ |
| 待辦、深夜相搬運（wa_night_mover）、搬相 | ✅ |
| wake lock 啟動即攞 | ✅（Android 準時關鍵） |
| 測試 | 262 passed（`python -m pytest test_bot.py -q`） |

## 部署現況

- 生產機：一部 Android（Termux，uid 10430），bot 常駐單進程
  - 啟動：`cd ~/telegram-alarm-bot && (setsid nohup python3 bot.py > bot.log 2>&1 < /dev/null &)`
  - 重啟前殺：`pkill -f "[p]ython3 bot.py"`（**bracket trick，唔可以同啟動擺同一條 shell**）
  - 驗證：`pgrep -fc "[p]ython3 bot.py"`＝1＋log 見「Bot 啟動」＋「wake lock 攞到」
- 資料（喺電話，唔入 repo）：`~/.tgalarm/`（config 600 有 BOT_TOKEN/SERPAPI_KEY；jobs.json；playlists.json）
- 手動導航／排程導航都行 TG keyboard callback（`nav:go/no:<id>`）

## 開發沙盒重建（新 sandbox 接手步驟）

1. `git clone https://github.com/endcl54-boop/tgalarm.git`
2. 連生產機：Tailscale userspace（`--socks5-server=127.0.0.1:1055`）＋ SSH
   經 ProxyCommand socks5 shim → 電話 port 8022（Termux sshd）。
   **詳細 IP／key 唔入 public repo**——向项目擁有人攞（佢知擺邊）。
3. git ident 每次重設：`git config user.name/email`（跟歷史紀錄）

## 工作守則（項目擁有人明示嘅規矩）

- 廣東話回覆；紀錄只寫 diff/測試可以核證嘅嘢，**唔准作故事**
- 唔好叫用戶手動撳設定——優先遠端搞掂；連線失敗先檢查沙盒自己
- commit message 照歷史風格（粵語＋重點＋測試數）
- 導航確認唔好走回頭用彈窗／橫幅（實測會俾 Telegram 前景攔截）
- 沙盒快照會回捲：重要嘢即刻 commit＋push；部署後 md5 兩邊對

## 已知未做／下一步候選

- crontab 守護（bot 死咗自動拉起）——未設
- ZA Bank 主線（等擁有人先手動 Geto UI 試）
- 時鐘鬧鐘「自動停」加強（用戶暫未要求）
