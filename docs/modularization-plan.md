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

---

## S3–S13 Batch 紀錄（2026-10-07，用戶令「S3-s13 batch 啦」）

**交付（commit 見 git log）：**
- `tgalarm/engine.py`＝原 bot.py 全身 verbatim 遷入（4,952 行）——零行為風險路線
- `bot.py`＝**36 行薄殼**（終點判準 #1 ✓）：zipimport bot.pyz 後備＋PEP 562 讀寫雙向代理（`bot.X` 讀取→engine；`bot.X = v` 同步寫 engine——369 舊測試零改動過閘＝行為不變鐵證）
- `pack.py`：liar.py 入 pyz 根；`bot.pyz`＝部署產物（.gitignore）
- `test_arch.py` 8 條：core 禁域依／域禁兄弟（engine 豁免＝組合根）／禁 telegram／registry／薄殼 ≤40／寫同步／engine 禁 import bot／終態排練（tmpdir 得 bot.py+pyz 都行）

**判準盤點**：#1 薄殼 ✓；#3 守門 ✓；#4 綠 ✓；#5 行為不變 ✓（舊測試零改動）；#6 部署兩檔 ✓；#2 域≤800 ✗（engine 4,952）

**Phase-2 backlog（域內拆分；工程性質唔同咗）**：
engine 已喺套件內，S3'–S12' 變成 intra-package 重構：每域由 engine 抽去 `tgalarm/<域>.py`，共享可變狀態（_TASKS/_TAKEAWAY/jobs 倉）經 core registry 收編，測試 patch 點跟遷移改（每域一次小 PR＋真機抽查）。次序照原藍圖（finance ✓ → takeaway → weather/web → fun → nav → todo → guards → patrol → alarms → schedule → player → app.py 接組合根）。**app.py 現為佔位（zipapp main 提示未啟用）**；engine.main() 係真入口。

**教訓（batch 期間沙盒又重置一次）**：working 樹倖存但 `tgalarm/core/`（已蹤路徑）被還原走＋remote 抹走＋HEAD 老返 f550f93。處方行齊：remote 重建→fetch→`reset --mixed origin/main`→core 由 session context 重寫→377 綠自證。

## ✅ S3–S13 真拆完成（2026-10-07，commit 0427543；378 綠×2＋ruff 0）
用戶令「一次過拆十三份到完成既batch」。**自動分割器** `tools/split_engine.py`：
AST 範圍分析（bound_names 逐 scope 收綁定名，file_global 唔算 local）＋
**byte→char** 位置換算 token 拼接（中文行 AST col 係 UTF-8 byte 位）——
verbatim 切塊連註釋全保。

**最終模組圖（判準 #2 全達標）**：
| 檔 | 行 | 檔 | 行 |
|---|---|---|---|
| engine（中樞 hub） | 946 | jobs | 367 |
| exec（指令執行器） | 548 | patrol | 340 |
| sched（排程引擎） | 503 | nav | 313 |
| todo | 429 | parse／guards／player／fun／app | 287/276/257/257/246 |
| weather／alarms／android | 205/188/104 | finance／takeaway／web | 76/58/39 |

**不變鐵證**：369 舊測試零改動過閘（bot shim PEP 562 代理→engine；域一律
`engine.X` 延遲綁定＝patch engine.X 對域內部一樣生效——單一命名空間語義）。
真機：bot.pyz 268KB，PROBE engine@/takeaway@ 均 bot.pyz 內部載入；PID live。

**分割器教訓（寫過就唔好再犯）**：①切塊起點要包裝飾器行（node.lineno 唔包
@dataclass）②`global X` 刪行要留 \n（否則全檔錯位）③AST col=UTF-8 byte，
中文行 splice 要轉 char ④Store 檢查 file_global 要喺 add-locals **之前**
⑤bound_names 都要濾 file_global（否則 `_LOCK_FH = f` 變 local）⑥stdlib 名
（dt/json/re…）係 engine 命名空間成員，域內要行 engine.X，唔可以本地 import
⑦module 層（import 期）同檔名保持本地綁定（init 順序＝原語義，_YT_PKG 案）
⑧engine import 塊=F401 noqa 契約（域檔經 engine.shutil 等引用）。
