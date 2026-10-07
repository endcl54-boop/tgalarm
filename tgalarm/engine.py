# ruff: noqa: F401  —— 呢塊 import 係命名空間契約：域檔經 engine.X 引用，engine 自己未必用到
"""tgalarm 引擎中樞（S13 batch 拆分後）：狀態／設定／路徑／jobs 倉／TG 發送／語音／共用格式化。域模組（同目錄 *.py）全部經 engine.X 延遲綁定存取呢度——bot shim patch engine.X 對全模組生效。各域本體見同目錄檔案。"""
from __future__ import annotations

import asyncio
import datetime as dt
import fcntl
import json
import logging
import os
import random
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass

"""
tgalarm engine（S13 batch 遷入；bot.py 而家係薄殼 shim）——
Telegram 鬧鐘・計時器機械人（Android Termux 直連系統時鐘）

架構（最短路徑 = 最快響應）：
    Telegram 訊息 → 長輪詢落手機 Termux → 解析中文指令
    → `am start` Intent → 系統時鐘 App 開計時器 / 鬧鐘

指令文法（中文 / 英文混搭都得）：
    計時 25分鐘            計時 1小時30分鐘      計時 90秒
    計時 1個半鐘           計時 半小時           計時 10分鐘 杯麵
    計時 3天               計時 1天半            計時 半天
    計時到 18:30 / 1830   倒數到 18:30 開會
    計時 明天 1830        計時 後天 0700        計時 0925 1830（mmdd）
    鬧鐘 07:00 / 0700     鬧鐘 7:30 起身

播放 YouTube 歌單（可自定義命名）：
    播 [名/連結]           停
    2130 播 [名]          每日 0700 播 [名]
    音量40% 播 [名]       0700 音量40% 播 [名]
    歌單 名 連結（儲存）    歌單 / 播程 / 取消播 編號
    timer 25m             alarm 07:00

時間分配快進：
    完成 / 早完成        提早做完而家呢段 → 即刻快進下一階段（舊倒計時撳停就得）

WhatsApp 相搬移（純 Python，毫秒内動作）：
    搬相                  將最近夜更時段（23:00–07:00）WhatsApp 相（包自己傳出 Sent
                          嘅）搬去系統相簿 WA_Night；防撞名自動加 -1 -2…
    搬相預覽              齋列出符合嘅相，唔郁真身
    搬相 HHMM HHMM        自訂任何時段（當日 0900 1200／跨夜 2300 0700），
                          之後加「預覽」都食——搬最近一次出現嘅嗰個窗
    搬相（分類制）        讀圖自動判崗位，歸檔 BG巡邏相片記錄／
                          YYYY M月／YYYY-MM-DD／Shift_A(07-15)B(15-23)C(23-07)／崗位
    搬回／搬返            將分類樹（＋舊 WA_Night）全數遞歸搬返 WhatsApp Images

設定來源（優先次序：環境變數 > ~/.tgalarm/config）：
    BOT_TOKEN          必填，向 @BotFather 申請（setup.sh 會問你一次）
    ALLOWED_CHAT_IDS   白名單；留空 = 第一個 send 訊息嘅人自動成為擁有者
    DRY_RUN=1          測試模式：淨係打印 intent，唔真正呼叫系統
    SKIP_UI=0          預設 skip_ui=true；某啲廠牌時鐘要開返 UI 先 work
"""


logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("tgalarm")

# S13 batch（docs/modularization-plan.md）：本檔=tgalarm 引擎模組；
# 財務防護域（S1 試刀）喺 tgalarm.finance。

# ---------------- 設定（環境變數 > 設定檔） ----------------
CONFIG_PATH = os.path.expanduser(os.environ.get("TGALARM_CONFIG", "~/.tgalarm/config"))
JOBS_PATH = os.path.expanduser(os.environ.get("TGALARM_JOBS", "~/.tgalarm/jobs.json"))
LOCK_PATH = os.path.expanduser(os.environ.get("TGALARM_LOCK", "~/.tgalarm/bot.lock"))
SEAL_LAST_PATH = os.path.expanduser("~/.tgalarm/seal_last.json")
COMBOS_PATH = os.path.expanduser(
    os.environ.get("TGALARM_COMBOS", "~/.tgalarm/combos.json"))
QUIET_PATH = os.path.expanduser(
    os.environ.get("TGALARM_QUIET", "~/.tgalarm/quiet.json"))
TAKEAWAY_PATH = os.path.expanduser(
    os.environ.get("TGALARM_TAKEAWAY", "~/.tgalarm/takeaway.json"))
PLAYLISTS_PATH = os.path.expanduser(os.environ.get("TGALARM_PLAYLISTS", "~/.tgalarm/playlists.json"))
DESTINATIONS_PATH = os.path.expanduser(os.environ.get("TGALARM_DESTINATIONS", "~/.tgalarm/destinations.json"))
WEBS_PATH = os.path.expanduser(os.environ.get("TGALARM_WEBS", "~/.tgalarm/webs.json"))
COUNTDOWNS_PATH = os.path.expanduser(
    os.environ.get("TGALARM_COUNTDOWNS", "~/.tgalarm/countdowns.json"))
TODO_PATH = os.path.expanduser(os.environ.get("TGALARM_TODO", "~/.tgalarm/todo.json"))


def _read_config_file() -> dict:
    cfg = {}
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    cfg[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    except OSError as e:
        log.warning("讀唔到設定檔 %s：%s", CONFIG_PATH, e)
    return cfg


BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip() or _read_config_file().get("BOT_TOKEN", "").strip()
GEMINI_API_KEY = (os.environ.get("GEMINI_API_KEY", "").strip()
                  or _read_config_file().get("GEMINI_API_KEY", "").strip())
PATROL_ROOT = (os.environ.get("PATROL_ROOT", "").strip()
               or _read_config_file().get("PATROL_ROOT", "").strip()
               or "/storage/emulated/0/Pictures/BG巡邏相片記錄")
PATROL_POSTS = [p.strip() for p in (
    os.environ.get("PATROL_POSTS", "").strip()
    or _read_config_file().get("PATROL_POSTS", "").strip()
    or "Ch,CP1,Platform,T74,T76,T78,T80,T82,T84").split(",") if p.strip()]
# Gemini 轉播站（2026-10-04 實證：HK 電話直連 Google＝400 location not supported；
# 經 tailnet 叫沙盒轉播就通。空＝直連（外地網絡先用）
GEMINI_RELAY = (os.environ.get("GEMINI_RELAY", "").strip()
                or _read_config_file().get("GEMINI_RELAY", "").strip())
DRY_RUN = os.environ.get("DRY_RUN", "") == "1" or "--dry-run" in sys.argv
SKIP_UI = (os.environ.get("SKIP_UI") or _read_config_file().get("SKIP_UI", "1")) != "0"


def _allowed_ids() -> set:
    """逐次讀取：改咗設定檔唔使重啟即時生效。環境變數優先。"""
    raw = os.environ.get("ALLOWED_CHAT_IDS", "") or _read_config_file().get("ALLOWED_CHAT_IDS", "")
    return {int(x) for x in raw.replace("，", ",").split(",") if x.strip()}


def _bind_owner(chat_id: int) -> None:
    """把首個用戶寫入設定檔做擁有者。"""
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    lines, done = [], False
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("ALLOWED_CHAT_IDS"):
                    line = f"ALLOWED_CHAT_IDS={chat_id}\n"
                    done = True
                lines.append(line)
    except FileNotFoundError:
        pass
    if not done:
        lines.append(f"ALLOWED_CHAT_IDS={chat_id}\n")
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        f.writelines(lines)
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass
    log.info("已自動綁定擁有者 chat_id=%s → %s", chat_id, CONFIG_PATH)

# ---------------- 指令解析 ----------------

_DUR = re.compile(
    r"(\d+(?:\.\d+)?)\s*(天|日|days?|d|小時|個鐘|鐘頭|鐘|hours?|hrs?|h|分鐘|分|mins?|m|秒鐘|秒|secs?|s)",
    re.IGNORECASE,
)
# 支援「18:30」「18：30」「18.30」同「1830 / 730」（最尾兩位=分，前面=時）兩種寫法
_TIME = re.compile(r"(?:(\d{1,2})\s*[:：.]\s*(\d{1,2})|(?<!\d)(\d{3,4})(?!\d))")


def _unit_seconds(unit: str) -> int:
    u = unit.lower()
    if u in ("天", "日", "d", "day", "days"):
        return 86400
    if u in ("小時", "個鐘", "鐘頭", "鐘", "h", "hr", "hrs", "hour", "hours"):
        return 3600
    if u in ("分鐘", "分", "m", "min", "mins"):
        return 60
    return 1  # 秒家族


def _next_occurrence(now: dt.datetime, hour: int, minute: int) -> dt.datetime:
    """今日嘅 hour:minute；已過咗就聽日同一時間。"""
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += dt.timedelta(days=1)
    return target


def _parse_duration(rest: str) -> tuple:
    """回傳 (秒數, 消耗到邊個字位)。未能解析回傳 (0, 0)。
    淨 1-2 位數字＝分鐘（「計時 25」＝25分鐘——減阻力；
    3-4 位保留畀 hhmm：「計時 700」＝計時到 07:00）。"""
    m = re.match(r"\s*(\d{1,2})(?=\s|$)", rest)
    if m and not re.match(r"\s*[a-zA-Z]", rest[m.end():]):
        return int(m.group(1)) * 60, m.end()   # 後面跟英文（2 days）→唔當分鐘
    # 「N個半鐘/天」「N個半小時/日」
    m = re.match(r"(\d+(?:\.\d+)?)\s*個?半\s*(小時|個?鐘|天|日)", rest)
    if m:
        unit = 86400 if m.group(2) in ("天", "日") else 3600
        return int(float(m.group(1)) * unit + unit // 2), m.end()
    # 開頭就係「半小時」「半個鐘」「半天」「半日」
    m = re.match(r"半\s*(小時|個鐘|鐘|天|日)", rest)
    if m:
        return 43200 if m.group(1) in ("天", "日") else 1800, m.end()
    total, end, last_unit = 0.0, 0, 0
    for dm in _DUR.finditer(rest):
        if rest[end:dm.start()].strip():  # 中間隔住非空白 = 唔再係時長
            break
        secs = _unit_seconds(dm.group(2))
        total += float(dm.group(1)) * secs
        last_unit, end = secs, dm.end()
    # 「1小時半」「1天半」：時長後緊貼一個「半」= 上一單位嘅一半
    if last_unit in (3600, 86400) and rest[end:end + 1] == "半":
        total += last_unit / 2
        end += 1
    return (int(total), end) if total > 0 else (0, 0)


def _read_hhmm_of(tok: str):
    """讀單一時間 token（19:30 / 1930）。回傳 (時, 分) 或 None。"""
    m = re.fullmatch(r"(?:(\d{1,2})[:：.](\d{1,2})|(\d{3,4}))", tok)
    if not m:
        return None
    if m.group(3):
        v = m.group(3)
        hh, mm = int(v[:-2]), int(v[-2:])
    else:
        hh, mm = int(m.group(1)), int(m.group(2))
    if hh > 23 or mm > 59:
        return None
    return hh, mm


def _read_start_tok(tok: str):
    """分配開始時間：「現在／而家／now」＝即刻上車（用而家時間），否則當 hhmm 讀。"""
    if re.fullmatch(r"現在|而家|now", tok, re.IGNORECASE):
        n = dt.datetime.now()
        return n.hour, n.minute
    return _read_hhmm_of(tok)


def _read_hhmm(rest: str):
    """由字頭讀 HH:MM / hhmm，回傳 (時, 分, 剩餘字串) 或 None。
    淨 1-2 位數字＝整點（「鬧鐘 7」＝07:00）。"""
    t = re.match(r"(\d{1,2})(?=\s|$)", rest)
    if t:
        hh = int(t.group(1))
        if hh <= 23:
            return hh, 0, rest[t.end():].strip()
        return None
    t = _TIME.match(rest)
    if not t:
        return None
    if t.group(1) is not None:
        hh, mm = int(t.group(1)), int(t.group(2))
    else:  # hhmm 寫法：730 → 07:30、1830 → 18:30
        digits = t.group(3)
        hh, mm = int(digits[:-2]), int(digits[-2:])
    if hh > 23 or mm > 59:
        return None
    return hh, mm, rest[t.end():].strip()


_REL_DAYS = ((r"大後天", 3), (r"後天", 2), (r"明天|聽日|tmr|tomorrow", 1))
MAX_TIMER_SECONDS = 99999 * 3600  # 計時硬上限 99999 小時（約 11.4 年），超過直接拒絕


def _read_datetime_target(rest: str, now: dt.datetime):
    """解析「[日期] hhmm」目標時刻，回傳 (datetime, label) 或 None。

    日期（可省略）：明天/聽日/後天/大後天，或 mmdd（過咗計出年）。
    省略日期：沿用原有今日/聽日（過咗計聽日）邏輯。
    外賣模式（2026-10-02 用戶令）：hhmm 後面任何數字＝單號（幾多位都收），
    蓋過 mmdd 解析——「計時 1005 1830」＝今日 10:05 單號1830。
    非外賣：mmdd hhmm 嚴謹制，日期唔存在（1530 1727／0931）明確拒絕。
    """
    if _TAKEAWAY.get("on"):
        day_off = None
        for pat, days in _REL_DAYS:
            m = re.match(r"(?:" + pat + r")\s*", rest, re.IGNORECASE)
            if m:
                rest = rest[m.end():]
                day_off = days
                break
        r = _read_hhmm(rest)
        if not r:
            return None
        hh, mm, label = r
        ts = label.replace(" ", "")
        if ts.isdigit():
            label = f"單號{ts}"               # 任何數字都收，加「單號」兩字
        if day_off is not None:
            d = now.date() + dt.timedelta(days=day_off)
            return dt.datetime(d.year, d.month, d.day, hh, mm), label
        return _next_occurrence(now, hh, mm), label
    for pat, days in _REL_DAYS:
        m = re.match(r"(?:" + pat + r")\s*", rest, re.IGNORECASE)  # 要包 (?:) 先至頭尾夾得啱
        if m:
            r = _read_hhmm(rest[m.end():])
            if not r:
                return None
            hh, mm, label = r
            d = now.date() + dt.timedelta(days=days)
            return dt.datetime(d.year, d.month, d.day, hh, mm), label
    m = re.match(r"(?<!\d)(\d{4})(?!\d)\s*", rest)
    if m:
        r = _read_hhmm(rest[m.end():])
        if r:  # 後面跟住時間先當 mmdd；冇就留返畀 hhmm 規則（如「計時 1230」= 12:30）
            hh, mm, label = r
            tok = m.group(1)
            month, day = int(tok[:2]), int(tok[2:])
            try:
                target = dt.datetime(now.year, month, day, hh, mm)
            except ValueError:
                # 嚴謹制（2026-10-02 用戶令恢復）：mmdd hhmm 兩 token 就係日期語法，
                # 日期唔存在（1530 1727／0931 1830）明確拒絕——唔再靜靜當 hhmm＋標籤
                #（要 hhmm＋數字，開外賣模式，數字會變單號）
                return None
            while target <= now:
                try:
                    target = target.replace(year=target.year + 1)
                except ValueError:  # 0229 跳水：直接去下個閏年
                    target = target.replace(year=target.year + 4)
            return target, label
    r = _read_hhmm(rest)
    if r:
        hh, mm, label = r
        return _next_occurrence(now, hh, mm), label
    return None


@dataclass
class Parsed:
    kind: str                 # "timer" | "alarm"
    seconds: int | None       # timer 用：倒數秒數
    fire_at: dt.datetime      # 預計觸發時間（顯示用）
    label: str = ""
    hour: int | None = None   # alarm 用
    minute: int | None = None


def parse_command(text: str, now: dt.datetime | None = None) -> Parsed | None:
    """將一句中文指令解析成結構化資料；唔識解析回傳 None。"""
    now = now or dt.datetime.now()
    s = re.sub(r"\s+", " ", text.strip().lower())

    # 1) 計時到 [日期] HH:MM / 倒數到 … → 計時器，秒數=目標−而家
    m = re.match(r"^/?(?:計時到|倒數到|timer\s+to|timer\s+until)\s*", s)
    if m:
        r = _read_datetime_target(s[m.end():], now)
        if not r:
            return None
        target, label = r
        return Parsed("timer", int((target - now).total_seconds()), target, label, target.hour, target.minute)

    # 2) 鬧鐘 HH:MM [標籤]
    m = re.match(r"^/?(?:鬧鐘|闹钟|alarm)\s*", s)
    if m:
        if re.match(r"\d{1,2}:?\d{2}\s*[-–—~至到]", s[m.end():]):
            return None      # 範圍寫法要跟「每x分鐘」：鬧鐘 2100-0000 每60分鐘 報更
        r = _read_hhmm(s[m.end():])
        if not r:
            return None
        hh, mm, label = r
        return Parsed("alarm", None, _next_occurrence(now, hh, mm), label, hh, mm)

    # 3) 計時 <時長> [標籤]；如果唔係時長而係 HH:MM/hhmm → 當「計時到」處理
    m = re.match(r"^/?(?:計時|计时|timer|countdown)\s*", s)
    if m:
        rest = s[m.end():]
        if re.match(r"\d{1,2}:?\d{2}\s*[-–—~至到]", rest):
            return None      # 淨範圍冇「每x分鐘」唔識做（避免誤設單一計時器）
        seconds, end = _parse_duration(rest)
        if seconds > 0:
            return Parsed("timer", seconds, now + dt.timedelta(seconds=seconds), rest[end:].strip())
        r = _read_datetime_target(rest, now)
        if r:
            target, label = r
            return Parsed("timer", int((target - now).total_seconds()), target, label, target.hour, target.minute)
        return None

    return None


def split_commands(text: str) -> list:
    """批次輸入：隔行一個指令；去除空行同前後空白。"""
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


_PREFIX_TIMER = re.compile(r"^/?(?:計時到|倒數到|計時|计时|timer|countdown)", re.IGNORECASE)
_PREFIX_ALARM = re.compile(r"^/?(?:鬧鐘|闹钟|alarm)", re.IGNORECASE)


_CN_DIG = {"一": 1, "二": 2, "兩": 2, "两": 2, "三": 3, "四": 4,
           "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_EVERY_NUM = r"(\d+(?:\.\d+)?|[一二兩两三四五六七八九十]+)"
_EVERY_UNIT = r"(小時|小时|分鐘|分钟|分|min|hours?|hr|h)"


def _cn_num(tok: str) -> float | None:
    """中文數字→數值：一~九、兩、十、X十、X十Y。"""
    if tok in _CN_DIG:
        return float(_CN_DIG[tok])
    if tok == "十":
        return 10.0
    m = re.fullmatch(r"([一二兩两三四五六七八九])?十([一二三四五六七八九])?", tok)
    if m:
        tens = _CN_DIG.get(m.group(1), 1) if m.group(1) else 1
        return float(tens * 10 + (_CN_DIG[m.group(2)] if m.group(2) else 0))
    return None


def _every_minutes(num_tok: str, unit: str) -> float | None:
    """「每X 單位」→ 分鐘數；唔識解回 None。"""
    if num_tok[0].isdigit():
        n = float(num_tok)
    else:
        cn = _cn_num(num_tok)
        if cn is None:
            return None
        n = cn
    if unit in ("小時", "小时") or unit.startswith("h"):
        n *= 60
    return n


_SERIES_RANGE = re.compile(
    r"^(每日|每天|everyday)?\s*(?:鬧鐘|闹钟|alarm|計時|计时|timer)\s+"
    r"\d{1,2}:?\d{2}\s*[-–—~至到]\s*\d{1,2}:?\d{2}$", re.IGNORECASE)
_SERIES_EVERY = re.compile(
    r"^每\s*" + _EVERY_NUM + r"\s*" + _EVERY_UNIT + r"\s*\S*$", re.IGNORECASE)


def _merge_series_lines(lines: list) -> list:
    """兩行寫法（例：計時 2100-0000 ↔ 每60分鐘 報更）合成一條 series。"""
    out, i = [], 0
    while i < len(lines):
        if (i + 1 < len(lines) and _SERIES_RANGE.match(lines[i])
                and _SERIES_EVERY.match(lines[i + 1])):
            out.append(lines[i].rstrip() + " " + lines[i + 1].strip())
            i += 2
            continue
        out.append(lines[i])
        i += 1
    return out


def parse_lines(text: str, now: dt.datetime | None = None) -> list:
    """批次解析，回傳 [(原行, Parsed 或 None), ...]。

    「裸行」（淨係時間或時長，例如 "1900"、"25分鐘"）會繼承同一訊息入面
    最近一個明確指令嘅關鍵字（計時/鬧鐘）；「待辦 xxx」之後嘅裸行就當係
    加更多待辦項目（摺衫、還書……）；未有任何關鍵字就當睇唔明。
    """
    now = now or dt.datetime.now()
    out, ctx = [], None
    for ln in _merge_series_lines(split_commands(text)):
        pp = parse_player(ln)
        if pp:
            if pp.action == "todo_add":
                ctx = "待辦"  # 「待辦 較鬧鐘」之後，每行裸字自動變待辦項目
            out.append((ln, pp))
            continue
        p = parse_command(ln, now)
        if p:
            if _PREFIX_TIMER.match(ln):
                ctx = "計時"
            elif _PREFIX_ALARM.match(ln):
                ctx = "鬧鐘"
            out.append((ln, p))
            continue
        if ctx == "待辦" and ln.strip():
            out.append((ln, PlayerCmd("todo_add", ref=ln.strip())))
            continue
        if ctx and ctx != "待辦":
            p = parse_command(f"{ctx} {ln}", now)
            if p:
                out.append((ln, p))
                continue
        out.append((ln, None))
    return out


@dataclass
class PlayerCmd:
    """YouTube 歌單 / 排程指令。ref=名、連結、標籤或編輯內容。"""
    action: str              # play/stop/jobs/cancel/cancel_all/listpl/savepl/delpl/setdef
                             # sched_once/sched_daily/sched_timer/sched_timer_daily
                             # pause/resume/edit
    ref: str = ""
    url: str = ""
    extra: str = ""          # wamove：自訂時段「sh sm eh em」（parse 驗證後嘅四個整數）
    hour: int | None = None
    minute: int | None = None
    job_id: int | None = None
    shuffle: bool = False
    vol: int | None = None      # 音量x%：開播前設媒體音量（最大聲嘅百分比）
    seconds: int | None = None  # sched_timer 用
    hour2: int | None = None    # sched_alloc：結束時間
    minute2: int | None = None
    buf: int = 0                # sched_alloc：留空百分比
    buf_min: int = 0            # sched_alloc：留空分鐘（同 buf 二擇一）


def _strip_shuffle(ref: str) -> tuple:
    """由名/連結尾部拆走「隨機 / random」標記，回傳 (淨 ref, 有冇標記)。"""
    m = re.search(r"\s*(?:隨機|random)\s*$", ref, re.IGNORECASE)
    if m:
        return ref[:m.start()].strip(), True
    return ref.strip(), False


def run_intent(cmd: list, timeout: float = 10.0) -> tuple:
    """執行 am intent；回傳 (成功與否, 系統輸出)。DRY_RUN 只打印。

    timeout=10 對深睡冷啟動夠；但 2026-09-30 logcat 實證：夜間 low memory
    killer 連 deskclock 都殺（03:36 am_kill），記憶體壓力下冷啟動可以遠超
    10 秒——鐘聲類調用傳 60。"""
    if DRY_RUN:
        log.info("DRY_RUN: %s", shlex.join(cmd))
        return True, "DRY_RUN " + shlex.join(cmd)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout)
        out = (r.stdout + r.stderr).strip()
        ok = r.returncode == 0 and "Error" not in out
        if not ok:
            log.warning("intent 失敗 rc=%s: %s", r.returncode, out)
        return ok, out
    except subprocess.TimeoutExpired:
        # 電話 load 高嗰陣 am 起身慢；唔使成段 command 嚇人
        return False, "系統開時鐘 App 超時（電話太攰），請再試一次"
    except FileNotFoundError:
        return False, "搵唔到 `am` 指令 —— 呢個 bot 要喺 Android Termux 行"
    except Exception as e:
        return False, str(e)


# ---------------- 顯示用工具 ----------------

def fmt_duration(sec: int) -> str:
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    parts = [f"{h}小時" if h else "", f"{m}分鐘" if m else "", f"{s}秒" if s else ""]
    return "".join(parts) or "0秒"


def day_label(fire_at: dt.datetime, now: dt.datetime) -> str:
    """日子叫法：今日/聽日/後日/大後日，再遠就寫幾月幾日。
    體貼位：第二日嘅凌晨（00:00–05:59）口語係「今晚」（今晚凌晨），
    唔係「聽日」——「聽日 00:15」會令人以為遲一日。"""
    d = (fire_at.date() - now.date()).days
    if d == 1 and fire_at.hour < 6:
        return "今晚"
    return {0: "今日", 1: "聽日", 2: "後日", 3: "大後日"}.get(d, f"{fire_at.month}月{fire_at.day}日")


# ---------------- YouTube 歌單播放 + 排程 ----------------

def _load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError, OSError):
        return default


_TAKEAWAY = {"on": False}      # _load_json 定義後即刻載入（見下）


def _save_json(path, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)

_TAKEAWAY = _load_json(TAKEAWAY_PATH, {"on": False})
_QUIET_CHECK = None                     # quiet 域 import 期註冊（靜音時段）


# ---- 隨機分組 ----

def _groups_handle(t: str):
    m = re.fullmatch(r"分組\s*(\d{1,2})\s+(.+)", t)
    if not m:
        return None
    k = int(m.group(1))
    names = [x.strip() for x in re.split(r"[,，、]", m.group(2)) if x.strip()]
    if k < 1 or k > 20 or len(names) < k:
        return f"❓ 用法：分組 3 阿明,阿強,阿寶,小明,阿偉（{len(names)}個人分唔到 {k} 組）"
    random.shuffle(names)
    groups = [[] for _ in range(k)]
    for i, n in enumerate(names):
        groups[i % k].append(n)
    lines = ["🎲 分組結果："]
    for i, g in enumerate(groups, 1):
        lines.append(f"{i}組：{'、'.join(g)}")
    return "\n".join(lines)


# ---- TG inline keyboard 導航確認 ----
# 2026-09-25 實測：Telegram 喺前景嗰陣，termux-dialog 會俾人彈交代收
# （raw code -2）。所以主確認改 TG 按鈕（Telegram 點都搶唔走自己個 chat），
# 彈窗留返做其他環境嘅快路。_PENDING_NAVS 記住手動導航 job 畀 callback 用。
_PENDING_NAVS: dict = {}


# ---- 大話骰（liar.py 引擎：數學層+神經網絡，純本地 <1ms）----
try:
    import liar as _liar
except Exception:
    _liar = None
_LIAR_GAMES: dict = {}
if _liar is not None:
    _liar.CAREER_PATH = os.path.expanduser(
        os.environ.get("TGALARM_LIAR_CAREER", "~/.tgalarm/liar_career.json"))


# Termux 固 TZPATH 指 /usr/share（唔存在）——指返 PREFIX 下成功
try:
    import zoneinfo as _zi
    _zp = os.path.join(os.environ.get("PREFIX", "/usr"), "share", "zoneinfo")
    if os.path.isdir(_zp):
        _zi.reset_tzpath((_zp,))
except Exception:
    pass


_PL_CACHE: dict = {}            # list_id -> (timestamp, [videoId])；session 快取


_TASKS: dict = {}   # job_id -> asyncio.Task
_APP = None         # telegram Application（恢復排程/到點回覆用）

# ─── 網絡閃斷韌性 ─────────────────────────────────────────────
# 手機流動網絡（尤其 Private DNS 嚴格模式）會有秒級閃斷；
# 到點訊息一碰 NetworkError 就 drop 會漏鬧鐘 → 退避重試保證送達。
_NET_RETRY_BACKOFF = (5, 20, 45)  # 嘗試 3 次之間嘅等待秒數


def _err_kind(e: Exception) -> str:
    """分類 telegram 錯誤：'net'（閃斷可重試）/ 'ratelimit' / 'other'。
    靠類名同屬性判斷，裝置外（冇裝 telegram）都 work。"""
    name = e.__class__.__name__
    if name == "RetryAfter" or hasattr(e, "retry_after"):
        return "ratelimit"
    if "NetworkError" in name or "TimedOut" in name:
        return "net"
    return "other"


async def _send_safe(chat_id: int, text: str, label: str = "訊息",
                     markup=None) -> bool:
    """到點訊息發送：閃斷退避重試（5s→20s→45s），唔再一碰就 drop。回傳最終成敗。"""
    if _APP is None:
        return False
    last = None
    for i in range(len(_NET_RETRY_BACKOFF)):
        try:
            await _APP.bot.send_message(chat_id, text, reply_markup=markup)
            if i:
                log.info("%s重試後已送出", label)
            return True
        except Exception as e:
            last = e
            kind = _err_kind(e)
            if kind == "ratelimit":
                wait = min(float(getattr(e, "retry_after", _NET_RETRY_BACKOFF[i])) + 1, 90)
                log.info("Telegram 限流：%s %.0f 秒後重試", label, wait)
                await asyncio.sleep(wait)
            elif kind == "net":
                if i + 1 >= len(_NET_RETRY_BACKOFF):
                    break
                log.info("網絡閃斷，%s %d 秒後重試（第 %d/%d 次）",
                         label, _NET_RETRY_BACKOFF[i], i + 2, len(_NET_RETRY_BACKOFF))
                await asyncio.sleep(_NET_RETRY_BACKOFF[i])
            else:
                log.warning("%s發送失敗：%s", label, e)
                return False
    log.warning("%s重試後仍未能送出（網絡持續異常）：%s", label, last)
    return False


async def _on_error(update, context) -> None:
    """統一收拾長輪詢網絡噪音（PTB 會自動重連）；真 bug 仍然照報。"""
    err = getattr(context, "error", None)
    if err is not None and _err_kind(err) == "net":
        log.info("網絡閃斷（%s）——長輪詢會自動重連", err.__class__.__name__)
    else:
        log.error("未捕捉錯誤：%r", err, exc_info=err)
_NIGHT_START, _NIGHT_END = 23, 7   # 夜更時段 23:00 → 翌日 07:00


# 崗位資料夾套裝：搬相真搬時自動開定，用戶 USB 拖入即分好（2026-10-06 用戶令）
_PATROL_POSTS = ("Ch", "Platform", "T74", "T76",
                 "T78", "T80", "T82", "T84")


_SPEECH_JUNK = re.compile(r"[^\w\s，。、：；！？%度分鐘點]")


def _speech_scrub(text: str) -> str:
    """剷走 emoji／符號／markdown，淨返 TTS 讀得順嘅字。"""
    text = re.sub(r"[\U00010000-\U0010FFFF]|[\u2600-\u27BF]"
                  r"|\[[^\]]*\]|[「」『』（）【】*`_#>/\\]", "", str(text))
    text = _SPEECH_JUNK.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _cjk_when(x: dt.datetime, now: dt.datetime | None = None) -> str:
    """時間→廣東話讀法：聽日朝早7點32分／今日下晝6點正。"""
    now = now or dt.datetime.now()
    d = (x.date() - now.date()).days
    if d == 0:
        day = "今日"
    elif d == 1:
        day = "聽日"
    elif d == 2:
        day = "後日"
    else:
        return f"{x.month}月{x.day}日"
    h = x.hour
    part = ("朝早" if 5 <= h < 11 else "中午" if 11 <= h < 13
            else "下晝" if 13 <= h < 19 else "夜晚" if 19 <= h < 23
            else "凌晨")
    h12 = h % 12 or 12
    mm = x.minute
    minute_txt = "正" if mm == 0 else (f"零{mm}分" if mm < 10 else f"{mm}分")
    return f"{day}{part}{h12}點{minute_txt}"


async def _say(text: str, delay: float = 0.0) -> None:
    """termux-tts-speak（Termux:API）廣東話讀出——失敗靜靜記 log 唔阻任務。

    ALARM 音訊流（同鐘聲同級，唔會畀通知靜音/DND 食咗）；delay＝避開
    同一秒 1 秒鐘鐘聲（2026-09-29 20:15 實證：同秒雙聲，TTS 畀鐘聲冚到）。"""
    text = (text or "").strip()
    if not text:
        return
    if _QUIET_CHECK is not None and _QUIET_CHECK():
        log.info("🔇 靜音時段——唔出聲：%s", text[:30])
        return
    if delay:
        await asyncio.sleep(delay)
    # vivo 會背景清理 Termux:API——凍啟動第一下會吊住（2026-09-29 實證）。
    # 預熱：先發個平價 API call 拉醒 termux-api process（生時 1-2 秒）
    try:
        await asyncio.to_thread(subprocess.run, ["termux-battery-status"],
                                timeout=12)
    except Exception:
        pass                                  # 拉唔醒都照講（底下行 retry）
    # 凍啟動＋引擎暖機可以超過 30 秒 → 90 秒＋重試一次
    for attempt in (1, 2):
        try:
            await asyncio.to_thread(
                subprocess.run,
                ["termux-tts-speak", "-r", "0.9", "-s", "ALARM", text],
                timeout=90)
            log.info("TTS 已讀（第%s次）：%.30s", attempt, text)
            return
        except Exception as exc:
            log.warning("TTS 第%s次失敗：%s", attempt, str(exc)[:100])
    log.warning("TTS 兩次都失敗，放棄：%s", text[:40])


# ---- core registry（藍圖接縫：域經 engine.X 存取，單一路徑）----
# ---- 域模組（verbatim 拆出；呢度 re-export 保持 bot.X 相容）----
from . import alarms as _alarms_mod
from . import android as _android_mod
from . import app as _app_mod
from . import calm as _calm_mod
from . import exec as _exec_mod
from . import finance as _finance_mod
from . import fun as _fun_mod
from . import guards as _guards_mod
from . import jobs as _jobs_mod
from . import nav as _nav_mod
from . import parse as _parse_mod
from . import patrol as _patrol_mod
from . import player as _player_mod
from . import quiet as _quiet_mod
from . import sched as _sched_mod
from . import takeaway as _takeaway_mod
from . import todo as _todo_mod
from . import weather as _weather_mod
from . import web as _web_mod
from .core import (  # registry 別名（same dict object；bot.X 測試路徑用）
    FIRE_HANDLERS,
    JOB_FORMATTERS,
)

_calm_handle = _calm_mod.handle
_combos = _web_mod._combos
_quiet_handle = _quiet_mod.handle
_quiet_in_window = _quiet_mod.in_window
_findef_route = _finance_mod.route
_findef_api = _finance_mod.api

_LOCK_FH = _sched_mod._LOCK_FH
_acquire_singleton = _sched_mod._acquire_singleton
_arm = _sched_mod._arm
_fire_later = _sched_mod._fire_later
_hold_wake_lock = _sched_mod._hold_wake_lock
_wait_wall = _sched_mod._wait_wall
HELP = _app_mod.HELP
_ensure_owner = _app_mod._ensure_owner
_on_message = _app_mod._on_message
_on_start = _app_mod._on_start
main = _app_mod.main
_execute = _exec_mod._execute
_execute_player = _exec_mod._execute_player
_add_job = _jobs_mod._add_job
_add_simple_job = _jobs_mod._add_simple_job
_clear_jobs = _jobs_mod._clear_jobs
_edit_job = _jobs_mod._edit_job
_fmt_job_content = _jobs_mod._fmt_job_content
_fmt_jobs = _jobs_mod._fmt_jobs
_jobs = _jobs_mod._jobs
_next_task_line = _jobs_mod._next_task_line
_pause_all = _jobs_mod._pause_all
_pause_job = _jobs_mod._pause_job
_remove_job = _jobs_mod._remove_job
_replaced_note = _jobs_mod._replaced_note
_restore_jobs = _jobs_mod._restore_jobs
_resume_all = _jobs_mod._resume_all
_resume_job = _jobs_mod._resume_job
parse_player = _parse_mod.parse_player
DAILY = _alarms_mod.DAILY
_add_bell = _alarms_mod._add_bell
_cd_abs = _alarms_mod._cd_abs
_countdown_days = _alarms_mod._countdown_days
_countdown_handle = _alarms_mod._countdown_handle
_countdowns = _alarms_mod._countdowns
_focus_handle = _alarms_mod._focus_handle
_nag_handle = _alarms_mod._nag_handle
alarm_intent_cmd = _alarms_mod.alarm_intent_cmd
timer_intent_cmd = _alarms_mod.timer_intent_cmd
_BAL_TIP = _player_mod._BAL_TIP
_PL_CACHE_TTL = _player_mod._PL_CACHE_TTL
_PL_DISK = _player_mod._PL_DISK
_UA = _player_mod._UA
_YT_CANDIDATES = _player_mod._YT_CANDIDATES
_YT_PKG = _player_mod._YT_PKG
_autoplay_url = _player_mod._autoplay_url
_dedupe = _player_mod._dedupe
_fetch = _player_mod._fetch
_fmt_playlists = _player_mod._fmt_playlists
_is_bal_denied = _player_mod._is_bal_denied
_is_yt_url = _player_mod._is_yt_url
_media_vol_max = _player_mod._media_vol_max
_play = _player_mod._play
_playlist_videos = _player_mod._playlist_videos
_playlist_videos_html = _player_mod._playlist_videos_html
_playlist_videos_rss = _player_mod._playlist_videos_rss
_playlists = _player_mod._playlists
_resolve_playlist = _player_mod._resolve_playlist
_set_media_volume = _player_mod._set_media_volume
_silence_wav = _player_mod._silence_wav
_stop = _player_mod._stop
_takeaway_handle = _takeaway_mod._takeaway_handle
_takeaway_set = _takeaway_mod._takeaway_set
_BT_ADAPTER = _guards_mod._BT_ADAPTER
_BT_SYSUI = _guards_mod._BT_SYSUI
_PKG_ALIAS = _guards_mod._PKG_ALIAS
_batt_line = _guards_mod._batt_line
_battery_chg = _guards_mod._battery_chg
_battery_handle = _guards_mod._battery_handle
_battery_status = _guards_mod._battery_status
_battery_status_once = _guards_mod._battery_status_once
_bthead_handle = _guards_mod._bthead_handle
_bthead_line = _guards_mod._bthead_line
_fg_pkg = _guards_mod._fg_pkg
_headset_levels = _guards_mod._headset_levels
_parse_bt_battery = _guards_mod._parse_bt_battery
_parse_bt_connected = _guards_mod._parse_bt_connected
_pkg_search = _guards_mod._pkg_search
_say_hammer = _guards_mod._say_hammer
_seal_jobs = _guards_mod._seal_jobs
_WA_DEST = _patrol_mod._WA_DEST
_WA_EXTS = _patrol_mod._WA_EXTS
_WA_MEDIA_CANDIDATES = _patrol_mod._WA_MEDIA_CANDIDATES
_gemini_classify = _patrol_mod._gemini_classify
_patrol_shift = _patrol_mod._patrol_shift
_wa_dirs = _patrol_mod._wa_dirs
_wa_move = _patrol_mod._wa_move
_wa_night_window = _patrol_mod._wa_night_window
_wa_recent_window = _patrol_mod._wa_recent_window
_wa_return = _patrol_mod._wa_return
_wa_scan = _patrol_mod._wa_scan
_NAV_MODES = _nav_mod._NAV_MODES
_NAV_MODE_LABEL = _nav_mod._NAV_MODE_LABEL
_dests = _nav_mod._dests
_fmt_dests = _nav_mod._fmt_dests
_mode_label = _nav_mod._mode_label
_nav_confirm_notify = _nav_mod._nav_confirm_notify
_nav_dialog_block = _nav_mod._nav_dialog_block
_nav_dialog_task = _nav_mod._nav_dialog_task
_nav_go_script_path = _nav_mod._nav_go_script_path
_nav_keyboard = _nav_mod._nav_keyboard
_nav_keyboard_msg = _nav_mod._nav_keyboard_msg
_nav_run_go = _nav_mod._nav_run_go
_nav_target = _nav_mod._nav_target
_nav_uri = _nav_mod._nav_uri
_nav_write_go_script = _nav_mod._nav_write_go_script
_on_nav_callback = _nav_mod._on_nav_callback
_open_nav = _nav_mod._open_nav
ADB_TARGET = _android_mod.ADB_TARGET
_ADB_CACHE = _android_mod._ADB_CACHE
_ADB_TTL = _android_mod._ADB_TTL
_RISH_CACHE = _android_mod._RISH_CACHE
_RISH_TTL = _android_mod._RISH_TTL
_adb_lane_available = _android_mod._adb_lane_available
_adb_lane_probe = _android_mod._adb_lane_probe
_adb_shell = _android_mod._adb_shell
_rish_available = _android_mod._rish_available
_rish_probe = _android_mod._rish_probe
_shell_priv_exec = _android_mod._shell_priv_exec
_fmt_webs = _web_mod._fmt_webs
_web_target = _web_mod._web_target
_webs = _web_mod._webs
web_intent_cmd = _web_mod.web_intent_cmd
_GPS_CACHE = _weather_mod._GPS_CACHE
_HKO_CURRENT_URL = _weather_mod._HKO_CURRENT_URL
_HKO_FND_URL = _weather_mod._HKO_FND_URL
_HKO_KEYS = _weather_mod._HKO_KEYS
_HKO_STATIONS = _weather_mod._HKO_STATIONS
_HKO_UA = _weather_mod._HKO_UA
_HOME = _weather_mod._HOME
_HOME_NEAR = _weather_mod._HOME_NEAR
_gps_fix = _weather_mod._gps_fix
_hko_current = _weather_mod._hko_current
_hko_district_line = _weather_mod._hko_district_line
_hko_fetch = _weather_mod._hko_fetch
_hko_flat = _weather_mod._hko_flat
_hko_fnd = _weather_mod._hko_fnd
_hko_section = _weather_mod._hko_section
_nearest_station = _weather_mod._nearest_station
_weather_report = _weather_mod._weather_report
_add_alloc_job = _todo_mod._add_alloc_job
_alloc_advance = _todo_mod._alloc_advance
_alloc_breakdown = _todo_mod._alloc_breakdown
_alloc_buf = _todo_mod._alloc_buf
_alloc_ff = _todo_mod._alloc_ff
_alloc_reflow = _todo_mod._alloc_reflow
_alloc_remaining_end = _todo_mod._alloc_remaining_end
_alloc_segments = _todo_mod._alloc_segments
_fire_alloc = _todo_mod._fire_alloc
_fmt_todos = _todo_mod._fmt_todos
_on_todo_callback = _todo_mod._on_todo_callback
_refresh_todo = _todo_mod._refresh_todo
_schedule_todo_refresh = _todo_mod._schedule_todo_refresh
_todo_add = _todo_mod._todo_add
_todo_clear_done = _todo_mod._todo_clear_done
_todo_del_idx = _todo_mod._todo_del_idx
_todo_keyboard = _todo_mod._todo_keyboard
_todo_speech = _todo_mod._todo_speech
_todo_toggle_idx = _todo_mod._todo_toggle_idx
_todos = _todo_mod._todos
_FX_ALIAS = _fun_mod._FX_ALIAS
_FX_URL = _fun_mod._FX_URL
_LIAR_DICE_RE = _fun_mod._LIAR_DICE_RE
_PEP = _fun_mod._PEP
_TIME_ZONES = _fun_mod._TIME_ZONES
_ai_mode_answer = _fun_mod._ai_mode_answer
_dice_reply = _fun_mod._dice_reply
_fx_code = _fun_mod._fx_code
_fx_parse = _fun_mod._fx_parse
_fx_reply = _fun_mod._fx_reply
_liar_handle = _fun_mod._liar_handle
_password_reply = _fun_mod._password_reply
_pick_reply = _fun_mod._pick_reply
_serpapi_key = _fun_mod._serpapi_key
_time_reply = _fun_mod._time_reply
