# 模組化藍圖（2026-10-07 拍板）

## 拍板紀錄（用戶 ask_user 確認）
- 部署形態：**zipapp 單檔**——電話一檔 `bot.pyz` scp＋重啟指令不變；三個復活腳本零改動
- 切法：**按功能域**（domain modules＋薄 core）
- 節奏：**逐階段上機＋凍結**（每遷移一域＝上機驗一次；期間零新功能）

## 完成判準（終點驗收）
1. `bot.py` 薄殼 ≤100 行（shim＋組裝）
2. 最大單模組 ≤~800 行；域之間零互相 import
3. 依賴守門測試（禁循環 import、禁域互依）
4. 全套測試綠＋ruff 0（369 為基線，只增不減）
5. TG 行為 100% 不變（真機文法抽查清單全過）
6. 部署 ≤2 步＋bundle 回滾錨點每階段一個

## 依賴規則（守門測試會鎖死）
- `core/`：config／路徑／jobs 倉／TG 發送／語音／排程引擎／Android 執行 lane／鑑權。**唔准 import 任何域**
- 域模組：只准 `from . import core`；**域之間唔准互相 import**（要協作經 app 註冊）
- `app.py`：文法派發＋fire 派發＋handler 註冊；唯一識所有域嘅地方

## Strangler 接縫（現有 pattern 正式化）
- **文法前哨**：域輸出 `handle(t, chat_id) -> str|None`，app 按註冊序逐個問（`_takeaway_handle`／`_findef_route` 已經係呢個 pattern）
- **fire 註冊表**：`core.FIRE_HANDLERS[job_type] -> async fn(job, now)`；`_fire_later` 隨遷移逐步縮細
- **job 內容格式**：`_fmt_job_content` 同樣註冊表化

## zipapp 部署設計
- repo `bot.py`＝10 行 shim：試 `import tgalarm`（開發態用 repo 目錄）；ImportError 就將 `bot.pyz` 插入 sys.path 再 import（zipimport）
- 打包：`python3 -m zipapp . -o bot.pyz -m "tgalarm.app:main"`（淨包 tgalarm/＋liar.py）
- 電話：`bot.py` shim scp 一次（md5 長穩）；之後每階段淨 scp `bot.pyz`；boot/bashrc/shortcut 三腳本照行 `python3 bot.py` 零改動
- 回滾：上機前舊 `bot.pyz` 改名 `.prev` 留住

## 遷移次序（依賴鑑證草案；每域最終歸位喺該階段 PR 確定）
鑑證基數：頂層 242 符號／4,414 行；未分類 96 個多為路徑常數＋共用解析器（歸 core）

| 階段 | 域 | 約行數 | 附註 |
|---|---|---|---|
| S1 | core/基建＋registry＋守門測試＋zipapp 打包 | — | 先有路軌；finance 試刀 |
| S2 | finance（GAS2 財務防護） | 57 | 最細、pattern 現成 |
| S3 | takeaway（外賣模式） | 51 | pre-hook pattern 原產地 |
| S4 | weather＋web | 53 | 葉域 |
| S5 | fun（骰仔/密碼/打氣/匯率/ai/liar 殼） | 180 | |
| S6 | nav（導航/地點） | 244 | |
| S7 | todo/alloc | 345 | |
| S8 | guards（電量/耳機） | 138 | |
| S9 | patrol（搬相/搬回） | 大函數體 | `docs` 外 `_wa_*` 函數體大 |
| S10 | alarms（鬧鐘/計時/連環/專注/倒數） | 154＋解析 | 共用解析器落 core |
| S11 | schedule（jobs 文法/暫停/恢復/列表） | 282 | |
| S12 | player（播歌/live/歌單/音量） | 904 | 最大域，一域一 PR |
| S13 | app.py＋_fire_later 縮細＋bot.py 薄殼化 | — | 引擎最後收口 |

## 每階段驗收清單（模板）
- [ ] pytest 全綠＋ruff 0
- [ ] 依賴守門測試綠（新域無違規）
- [ ] zipapp 打包成功＋本地 shim 行到
- [ ] scp 上機＋重啟＋PID/md5 紀錄
- [ ] 該域文法真機抽查 ≥1 條＋一條回歸抽查（唔同域）
- [ ] bundle 錨點＋notes 更新

## 凍結令（用戶 2026-10-07 批）
重構期間**零新功能**：undo 接線、開機持久化、任何新文法——全部排隊，S13 完先開波。修 bug（行為不變）可以。

## 回滾
- 每階段 push 後 `git bundle create tgalarm-<sha>.bundle --all`
- 電話端 `bot.pyz.prev`＋bundle 雙保險；任何階段炸 → 沙盒 `git reset` 返上階段 sha＋scp 返 prev
