# tgalarm 維運手冊（2026-10-07 用戶令：根治時間黑洞——持久化版）

## 🚨 第零規矩（用戶三次震怒後落死——優先過晒下面所有嘢）

1. **repo 檔案一律絕對路徑**：`/home/user/telegram-alarm-bot/bot.pyz`——永遠唔准裸寫 `bot.pyz`／`tgalarm/...`。
2. **部署/probe 淨准行 `./deploy.sh`**——手打任何 `md5sum bot.pyz && ssh ...` 呢類部署鏈＝違規。
3. **一個 bash call 一個目的**：唔准將 md5/git/pack/scp 砌埋一條十步 && 鏈——長鏈就係錯 cwd 事故溫床。

## 每輪紀律（硬規矩）

1. **開場第一 call＝`./self_check.sh`**——偵測到即救（HEAD/identity/key/core/ruff/ssh）。
2. **pytest 一發制**：全套 `pytest test_bot.py test_arch.py` 淨 push 前行一次（唔好同輪二連）。
3. **真機部署/probe 一律 `./deploy.sh`**——唔再手打 compound ssh；probe 失敗佢自動修復×3。
4. **remote call 必包 timeout**：手打 ssh 都要 `timeout 25 ssh ...`；ssh 內面永遠唔帶 sleep＋背景邏輯——叫電話側 `restart_bot.sh`／`status_bot.sh`。
5. **patch 三步規矩**：①patch 前 git 狀態確認乾淨②patch 後即場 syntax＋grep 計數驗證③失敗即 `git checkout -- <檔>` 還原重嚟——永唔留半成品。
6. **commit 前驗 parent**：`git log --format="%h %p" -1` 對 origin/main tip；identity 抹咗就補（self_check 會救）。

## 沙盒重置變種清單（self_check 自動救齊）

| 變種 | 處方（已自動化） |
|---|---|
| HEAD 老返 | soft-reset origin/main 重排 |
| identity 抹 | agent/agent@local 補返 |
| remote 抹 | token 重建 |
| core/ 被食 | `git checkout origin/main -- tgalarm/core/__init__.py` |
| ruff 失蹤 | pip install ruff |
| key 0644 | chmod 600 |
| ts 隧道斷 | `~/ts_up.sh`（chmod +x 先） |

## 檔案地圖

- `deploy.sh`——一鍵部署＋標準 probe＋自動修復×3
- `self_check.sh`——開場自檢＋自動救
- `restart_bot.sh`／`status_bot.sh`——電話側（repo 有副本；改咗要 scp 過去）
- `pack.py`——bot.pyz 打包（liar.py 入 pyz 根）
- `tools/split_engine.py`——真拆分割器（域 header 空行修補未入，重跑要跟 ruff --fix＋全驗）
- `docs/modularization-plan.md`——13 步收官記錄

## 已知邊界

- 真機重啟驗證要等用戶方便（唔准擅自重啟）；boot script v2（等網＋防雙開）下次重啟自然生效。
- probe 淨驗 PID＋getUpdates 200；功能級驗證靠 pytest＋個別回合手動斷言。
