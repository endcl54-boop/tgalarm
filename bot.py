#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tgalarm — Telegram 鬧鐘・計時器機械人（Android Termux 直連系統時鐘）

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
    歌單 名 連結（儲存）    歌單 / 播程 / 取消播 編號
    timer 25m             alarm 07:00

時間分配快進：
    完成 / 早完成        提早做完而家呢段 → 即刻快進下一階段（舊倒計時撳停就得）

WhatsApp 夜更相（純 Python，毫秒内動作）：
    搬相                  將最近夜更時段（23:00–07:00）WhatsApp 相（包自己傳出 Sent
                          嘅）搬去系統相簿 WA_Night；防撞名自動加 -1 -2…
    搬相預覽              齋列出符合嘅相，唔郁真身

設定來源（優先次序：環境變數 > ~/.tgalarm/config）：
    BOT_TOKEN          必填，向 @BotFather 申請（setup.sh 會問你一次）
    ALLOWED_CHAT_IDS   白名單；留空 = 第一個 send 訊息嘅人自動成為擁有者
    DRY_RUN=1          測試模式：淨係打印 intent，唔真正呼叫系統
    SKIP_UI=0          預設 skip_ui=true；某啲廠牌時鐘要開返 UI 先 work
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import random
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("tgalarm")

# ---------------- 設定（環境變數 > 設定檔） ----------------
CONFIG_PATH = os.path.expanduser(os.environ.get("TGALARM_CONFIG", "~/.tgalarm/config"))
JOBS_PATH = os.path.expanduser(os.environ.get("TGALARM_JOBS", "~/.tgalarm/jobs.json"))
PLAYLISTS_PATH = os.path.expanduser(os.environ.get("TGALARM_PLAYLISTS", "~/.tgalarm/playlists.json"))
DESTINATIONS_PATH = os.path.expanduser(os.environ.get("TGALARM_DESTINATIONS", "~/.tgalarm/destinations.json"))
TODO_PATH = os.path.expanduser(os.environ.get("TGALARM_TODO", "~/.tgalarm/todo.json"))
_YT_PKG = "com.google.android.youtube"


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


HELP = (
    "🤖 指令格式：\n"
    "⏱ 計時器：\n"
    "・計時 25分鐘　・計時 1天12小時　・計時 90秒\n"
    "・計時到 18:30 或 1830（倒數到指定時間）\n"
    "・計時 明天 1830 / 後天 0700 / 0925 1830（連日期都收）\n"
    "⏰ 鬧鐘：\n"
    "・鬧鐘 07:00 或 0700　・鬧鐘 1730 起身\n"
    "（後面加文字會變成標籤，例如：計時 10分鐘 杯麵）\n"
    "📦 批次輸入：一次過 send 幾行，每行一個指令\n"
    "　（之後每行淨係打時間都得，會繼承上面嘅計時/鬧鐘）\n"
    "🎵 播 YouTube 歌單：\n"
    "・播 [名/連結]　・隨機播 [名]　・停　・2130 播 [名]\n"
    "・每日 0700 播 [名] 隨機　・每日 0900 計時 25分鐘（計時排程）\n"
    "・歌單 名 連結（儲存）　・歌單/排程（列表）\n"
    "・管理：取消 N・暫停 N・繼續 N・改 N 1830（同時間新排程會自動取代）\n"
    "🧭 導航（Google Maps）：\n"
    "・地點 公司 沙田石門安群街1號（儲地點）　・導航 公司 [步行]（預設巴士）\n"
    "・0830 導航 公司　・每日 0800 導航 公司　・地點（清單）・刪地點 公司\n"
    "📋 待辦（自動置頂，撳按鈕打勾）：\n"
    "・待辦 牛奶、交電費（加項目）　・待辦（睇清單）\n"
    "・完成 2　・未做 2　・刪 2　・清除已完成\n"
    "🧩 時間分配（到點自動連環計時）：\n"
    "・1930至2230 分配 留空10% 温習x2、做功課、沖涼\n"
    "・加「每日」喺頭=日日咁玩；x2=佔兩份時間，冇寫=一份\n"
    "🩺 深夜冇反應/遲響？send「自檢」驗證；「修復」即彈保障設定頁\n"
    "🌙 夜更相：「搬相」將 WhatsApp 夜更時段（23:00–07:00，包自己傳出嘅）搬去 WA_Night 相簿；「搬相預覽」齋睇唔搬\n"
    "⏩ 分配快進：「完成」提早做完而家呢段即刻入下階段；最後段就提早收工"
)

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
    """回傳 (秒數, 消耗到邊個字位)。未能解析回傳 (0, 0)。"""
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
    """由字頭讀 HH:MM / hhmm，回傳 (時, 分, 剩餘字串) 或 None。"""
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
    """
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
            month, day = int(m.group(1)[:2]), int(m.group(1)[2:])
            try:
                target = dt.datetime(now.year, month, day, hh, mm)
            except ValueError:
                return None  # 日期唔存在（如 0931），明確拒絕，唔好亂估
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
        r = _read_hhmm(s[m.end():])
        if not r:
            return None
        hh, mm, label = r
        return Parsed("alarm", None, _next_occurrence(now, hh, mm), label, hh, mm)

    # 3) 計時 <時長> [標籤]；如果唔係時長而係 HH:MM/hhmm → 當「計時到」處理
    m = re.match(r"^/?(?:計時|计时|timer|countdown)\s*", s)
    if m:
        rest = s[m.end():]
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


def parse_lines(text: str, now: dt.datetime | None = None) -> list:
    """批次解析，回傳 [(原行, Parsed 或 None), ...]。

    「裸行」（淨係時間或時長，例如 "1900"、"25分鐘"）會繼承同一訊息入面
    最近一個明確指令嘅關鍵字（計時/鬧鐘）；「待辦 xxx」之後嘅裸行就當係
    加更多待辦項目（摺衫、還書……）；未有任何關鍵字就當睇唔明。
    """
    now = now or dt.datetime.now()
    out, ctx = [], None
    for ln in split_commands(text):
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
    hour: int | None = None
    minute: int | None = None
    job_id: int | None = None
    shuffle: bool = False
    seconds: int | None = None  # sched_timer 用
    hour2: int | None = None    # sched_alloc：結束時間
    minute2: int | None = None
    buf: int = 0                # sched_alloc：留空百分比


def _strip_shuffle(ref: str) -> tuple:
    """由名/連結尾部拆走「隨機 / random」標記，回傳 (淨 ref, 有冇標記)。"""
    m = re.search(r"\s*(?:隨機|random)\s*$", ref, re.IGNORECASE)
    if m:
        return ref[:m.start()].strip(), True
    return ref.strip(), False


def parse_player(text: str) -> PlayerCmd | None:
    """解析歌單/排程相關指令；唔係嘅話回傳 None（交返畀計時/鬧鐘解析）。
    唔做 lower()——YouTube URL 大小寫敏感；英文關鍵字改用 IGNORECASE。"""
    s = re.sub(r"\s+", " ", text.strip())
    if re.fullmatch(r"/?(?:完成|完成咗|早完成|提早完成|下一階段|下階段|跳過|skip|next)\s*[！!]?", s, re.IGNORECASE):
        return PlayerCmd("alloc_done")
    if re.fullmatch(r"/?搬(?:whatsapp|wa)?相", s, re.IGNORECASE):
        return PlayerCmd("wamove")
    if re.fullmatch(r"/?搬(?:whatsapp|wa)?相\s*(?:預覽|preview|list)", s, re.IGNORECASE):
        return PlayerCmd("wamove", ref="preview")
    if re.fullmatch(r"/?(?:停|停止|停播|stop)", s, re.IGNORECASE):
        return PlayerCmd("stop")
    if re.fullmatch(r"/?(?:播程|排程|播放日程|日程|jobs)", s, re.IGNORECASE):
        return PlayerCmd("jobs")
    m = re.fullmatch(r"/?(?:取消播|取消|刪除排程)\s*#?(\d+)", s, re.IGNORECASE)
    if m:
        return PlayerCmd("cancel", job_id=int(m.group(1)))
    if re.fullmatch(r"/?取消全部(?:播|排程)?", s, re.IGNORECASE):
        return PlayerCmd("cancel_all")
    m = re.fullmatch(r"(?:暫停|暫停播|停用)\s*#?(\d+)", s, re.IGNORECASE)
    if m:
        return PlayerCmd("pause", job_id=int(m.group(1)))
    m = re.fullmatch(r"(?:繼續|恢復|繼續播|恢復播)\s*#?(\d+)", s, re.IGNORECASE)
    if m:
        return PlayerCmd("resume", job_id=int(m.group(1)))
    m = re.fullmatch(r"(?:改播|編輯|改)\s*#?(\d+)\s+(.+)", s, re.IGNORECASE)
    if m:
        return PlayerCmd("edit", job_id=int(m.group(1)), ref=m.group(2))
    if re.fullmatch(r"/?歌單", s, re.IGNORECASE):
        return PlayerCmd("listpl")
    m = re.fullmatch(r"(?:刪歌單|刪除歌單)\s*(\S+)", s, re.IGNORECASE)
    if m:
        return PlayerCmd("delpl", ref=m.group(1))
    m = re.fullmatch(r"(?:預設歌單|默認歌單)\s*(\S+)", s, re.IGNORECASE)
    if m:
        return PlayerCmd("setdef", ref=m.group(1))
    m = re.fullmatch(r"歌單\s+(\S+)\s+(https?://\S+)", s, re.IGNORECASE)
    if m:
        return PlayerCmd("savepl", ref=m.group(1), url=m.group(2))
    # 地點 / 導航
    if re.fullmatch(r"(?:地點|目的地|dests)", s, re.IGNORECASE):
        return PlayerCmd("dests")
    m = re.fullmatch(r"(?:刪地點|刪除地點|del_place)\s+(.+)", s, re.IGNORECASE)
    if m:
        return PlayerCmd("deldest", ref=m.group(1).strip())
    m = re.fullmatch(r"(?:地點|目的地|set_place)\s+([^\s＝=：:]+)\s*(?:[＝=：:]\s*)?(.+)", s, re.IGNORECASE)
    if m:
        return PlayerCmd("savedest", ref=m.group(1), url=m.group(2).strip())
    # 置頂待辦清單
    if re.fullmatch(r"(?:待辦|todo|todolist|清單)", s, re.IGNORECASE):
        return PlayerCmd("todo")
    m = re.fullmatch(r"待辦\s+(.+)", s, re.IGNORECASE)
    if m:
        return PlayerCmd("todo_add", ref=m.group(1).strip())
    m = re.fullmatch(r"(?:完成|做咗|完成咗|勾選|勾|✓|✔|done)\s*#?(\d+)", s, re.IGNORECASE)
    if m:
        return PlayerCmd("todo_done", job_id=int(m.group(1)))
    m = re.fullmatch(r"(?:未完成|未做|還原|undone)\s*#?(\d+)", s, re.IGNORECASE)
    if m:
        return PlayerCmd("todo_undone", job_id=int(m.group(1)))
    m = re.fullmatch(r"(?:刪|刪除|踢走|del)\s*#?(\d+)", s, re.IGNORECASE)
    if m:
        return PlayerCmd("todo_del", job_id=int(m.group(1)))
    if re.fullmatch(r"(?:清|清除|清理)已完成", s):
        return PlayerCmd("todo_clear_done")
    if re.fullmatch(r"(?:自檢|測試|selfcheck)", s, re.IGNORECASE):
        return PlayerCmd("selfcheck")
    m = re.fullmatch(r"(?:修復|保障|權限|fix)", s, re.IGNORECASE)
    if m:
        return PlayerCmd("protect")
    # 時間分配：[每日] hhmm至hhmm 分配 [留空N%] 項目[x比例]…
    m = re.fullmatch(r"(?:每日|每天)\s*(\S+?)\s*[-–—~至到]\s*(\S+?)\s+分配\s*(?:留空\s*(\d+)\s*%\s*)?(.+)", s, re.IGNORECASE)
    if m:
        r1, r2 = _read_start_tok(m.group(1)), _read_hhmm_of(m.group(2))
        if r1 and r2:
            return PlayerCmd("sched_alloc_daily", hour=r1[0], minute=r1[1],
                             hour2=r2[0], minute2=r2[1],
                             buf=int(m.group(3) or 0), ref=m.group(4).strip())
        return None
    m = re.fullmatch(r"(\S+?)\s*[-–—~至到]\s*(\S+?)\s+分配\s*(?:留空\s*(\d+)\s*%\s*)?(.+)", s, re.IGNORECASE)
    if m:
        r1, r2 = _read_start_tok(m.group(1)), _read_hhmm_of(m.group(2))
        if r1 and r2:
            return PlayerCmd("sched_alloc", hour=r1[0], minute=r1[1],
                             hour2=r2[0], minute2=r2[1],
                             buf=int(m.group(3) or 0), ref=m.group(4).strip())
        return None
    # 每日 hhmm <計時 時長 | [隨機]播> [名/連結/標籤]
    m = re.match(r"^(?:每日|每天|everyday)\s*", s, re.IGNORECASE)
    if m:
        r = _read_hhmm(s[m.end():])
        if r:
            hh, mm, rest = r
            tm = re.match(r"計時\s*(.*)$", rest)
            if tm:
                seconds, end = _parse_duration(tm.group(1))
                if seconds > 0:
                    return PlayerCmd("sched_timer_daily", hour=hh, minute=mm,
                                     ref=tm.group(1)[end:].strip(), seconds=seconds)
                return None
            nm = re.match(r"(?:開導航|導航)\s*(.+)$", rest)
            if nm:
                return PlayerCmd("sched_nav_daily", hour=hh, minute=mm, ref=nm.group(1).strip())
            pm = re.match(r"(隨機播放|隨機播|播(?:放)?)\s*(.*)$", rest)
            if pm:
                ref, sh = _strip_shuffle(pm.group(2))
                return PlayerCmd("sched_daily", ref=ref, hour=hh, minute=mm,
                                 shuffle="隨機" in pm.group(1) or sh)
        return None
    # hhmm <計時 時長 | [隨機]播> …（一次）
    r0 = _read_hhmm(s)
    if r0:
        hh, mm, rest = r0
        tm = re.match(r"計時\s*(.*)$", rest)
        if tm:
            seconds, end = _parse_duration(tm.group(1))
            if seconds > 0:
                return PlayerCmd("sched_timer", hour=hh, minute=mm,
                                 ref=tm.group(1)[end:].strip(), seconds=seconds)
            return None
        nm = re.match(r"(?:開導航|導航)\s*(.+)$", rest)
        if nm:
            return PlayerCmd("sched_nav", hour=hh, minute=mm, ref=nm.group(1).strip())
        pm = re.match(r"(隨機播放|隨機播|播(?:放)?)\s*(.*)$", rest)
        if pm:
            ref, sh = _strip_shuffle(pm.group(2))
            return PlayerCmd("sched_once", ref=ref, hour=hh, minute=mm,
                             shuffle="隨機" in pm.group(1) or sh)
        return None  # 淨時間行：留返畀批次繼承用
    m = re.fullmatch(r"(?:開導航|導航|nav)\s*(.*)", s, re.IGNORECASE)
    if m:
        if not m.group(1).strip():
            return PlayerCmd("dests")  # 淨「導航」：顯示地點清單同用法
        return PlayerCmd("nav", ref=m.group(1).strip())
    # [隨機]播 [名/連結]（「播放」要排喺「播」前面，否則「放」會被食入名）
    m = re.match(r"^/?(隨機播放|隨機播|播放|播|play)\s*(.*)$", s, re.IGNORECASE)
    if m:
        ref, sh = _strip_shuffle(m.group(2))
        return PlayerCmd("play", ref=ref, shuffle="隨機" in m.group(1) or sh)
    return None


# ---------------- Android Intent（純函數，方便測試） ----------------

def timer_intent_cmd(seconds: int, label: str) -> list:
    return [
        "am", "start", "-a", "android.intent.action.SET_TIMER",
        "--ei", "android.intent.extra.alarm.LENGTH", str(int(seconds)),
        "--es", "android.intent.extra.alarm.MESSAGE", label or "Telegram 計時器",
        "--ez", "android.intent.extra.alarm.SKIP_UI", "true" if SKIP_UI else "false",
    ]


def alarm_intent_cmd(hour: int, minute: int, label: str) -> list:
    return [
        "am", "start", "-a", "android.intent.action.SET_ALARM",
        "--ei", "android.intent.extra.alarm.HOUR", str(hour),
        "--ei", "android.intent.extra.alarm.MINUTES", str(minute),
        "--es", "android.intent.extra.alarm.MESSAGE", label or "Telegram 鬧鐘",
        "--ez", "android.intent.extra.alarm.SKIP_UI", "true" if SKIP_UI else "false",
    ]


def run_intent(cmd: list) -> tuple:
    """執行 am intent；回傳 (成功與否, 系統輸出)。DRY_RUN 只打印。"""
    if DRY_RUN:
        log.info("DRY_RUN: %s", shlex.join(cmd))
        return True, "DRY_RUN " + shlex.join(cmd)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
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
    except Exception as e:  # noqa: BLE001
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


def _save_json(path, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _is_yt_url(s: str) -> bool:
    return bool(re.match(r"https?://(www\.|m\.|music\.)?(youtube\.com|youtu\.be)/", s, re.IGNORECASE))


def _playlists() -> dict:
    return _load_json(PLAYLISTS_PATH, {"default": "", "lists": {}})


def _resolve_playlist(ref: str) -> tuple:
    """ref=「」→預設；名→連結；連結→直接用。回傳 (url, 顯示名) 或 (None, 錯誤訊息)。"""
    pl = _playlists()
    if not ref:
        name = pl.get("default", "")
        if not name:
            return None, "未設預設歌單。先 send：歌單 名稱 YouTube連結"
        ref = name
    if ref in pl.get("lists", {}):
        return pl["lists"][ref], ref
    if _is_yt_url(ref):
        return ref, ""
    return None, f"搵唔到歌單「{ref}」。send「歌單」睇現有歌單"


# ---------------- 導航（Google Maps） ----------------

def _dests() -> dict:
    return _load_json(DESTINATIONS_PATH, {})


# 用戶只用步行同公共交通：預設 transit，要打「步行」先轉行路
_NAV_MODES = {"步行": "w", "行路": "w", "walk": "w",
              "巴士": "r", "公共交通": "r", "公交": "r", "transit": "r"}
_NAV_MODE_LABEL = {"w": "行路", "r": "公共交通"}


def _mode_label(mode: str) -> str:
    return _NAV_MODE_LABEL.get(mode, mode)  # 舊 job 可能有 d/b，照樣顯示


def _nav_target(arg: str) -> tuple:
    """拆走尾部交通模式、查已儲地點名。回傳 (目的地查詢, mode, 顯示名)。"""
    parts = arg.strip().split()
    mode = "r"  # 預設：大眾運輸
    if len(parts) > 1 and parts[-1].lower() in _NAV_MODES:
        mode = _NAV_MODES[parts.pop().lower()]
    name = " ".join(parts)
    return _dests().get(name, name), mode, name


# ---- Shizuku / rish：用 adb shell 身份發 intent ----
# vivo/小米等廠就算攞齊「後台彈窗」權限，仍會對 Termux 呢類背景 app 靜默截糊；
# 但 rish 令指令以 shell（uid 2000）執行——shell 係特權 caller，唔經嗰道閘。
_RISH_CACHE = {"t": 0.0, "ok": False}
_RISH_TTL = 600.0  # 10 分鐘 TTL：Shizuku 重開機會停，用戶重啟之後快啲執返


def _rish_probe() -> bool:
    """真實探測：rish 喺 PATH + Shizuku 行緊（見到 uid=2000 先用得）。"""
    if not shutil.which("rish"):
        return False
    try:
        r = subprocess.run(["rish", "-c", "id"], capture_output=True, text=True, timeout=10)
        return r.returncode == 0 and "uid=2000" in (r.stdout + r.stderr)
    except Exception:  # noqa: BLE001
        return False


def _rish_available() -> bool:
    """帶 TTL 快取嘅可用性（負面都快取，免至每次導航都開 JVM 探測）。"""
    now = dt.datetime.now().timestamp()
    if now - _RISH_CACHE["t"] < _RISH_TTL:
        return _RISH_CACHE["ok"]
    _RISH_CACHE["ok"] = _rish_probe()
    _RISH_CACHE["t"] = now
    return _RISH_CACHE["ok"]


def _open_nav(dest: str, mode: str = "r") -> tuple:
    """開 Google Maps 導航，rish（Shizuku/adb shell）優先，三重後備：
    ⓪ rish＋喚醒螢幕（vivo/小米 背景閘剋星；有 Shizuku 一定行呢步）
    ① google.navigation VIEW ② MapsActivity 明部件開 https dir
    ③ https dir 交畀系統揀 app（Maps 有事嗰啲手機可以用瀏覽器檔）。
    純文字→google.navigation:q=…；連結/geo URI→直接開。"""
    import urllib.parse
    if re.match(r"^(https?:|geo:|google\.)", dest, re.IGNORECASE):
        uri = dest
    else:
        uri = f"google.navigation:q={urllib.parse.quote(dest)}&mode={mode}"
    base = ["am", "start", "-a", "android.intent.action.VIEW", "-d", uri]
    if _rish_available():
        ok, out = run_intent(["rish", "-c",
                              "input keyevent KEYCODE_WAKEUP; " + shlex.join(base)])
        if ok:
            log.info("導航已經 rish（adb shell 身份）發出")
            return ok, out
        log.info("rish 發送失敗，轉返普通 am：%s", out[:120])
    ok, out = run_intent(base)
    if ok:
        return ok, out
    tmode = {"r": "transit", "w": "walking", "d": "driving"}.get(mode, "transit")
    web = (f"https://www.google.com/maps/dir/?api=1&destination="
           f"{urllib.parse.quote(dest)}&travelmode={tmode}")
    ok, out = run_intent(["am", "start", "-n",
                          "com.google.android.apps.maps/com.google.android.maps.MapsActivity",
                          "-d", web])
    if ok:
        return ok, out
    return run_intent(["am", "start", "-a", "android.intent.action.VIEW", "-d", web])


def _fmt_dests() -> str:
    d = _dests()
    if not d:
        return ("📍 仲未有地點。send：地點 公司 沙田石門安群街1號\n"
                "之後可以：導航 公司・每日 0830 導航 公司・導航 公司 步行")
    lines = ["📍 已儲存地點："]
    for name, dest in d.items():
        disp = dest if len(dest) <= 40 else dest[:37] + "…"
        lines.append(f"・{name}：{disp}")
    lines.append("用法：導航 公司 [步行]（預設巴士）・0830 導航 公司・每日 0830 導航 公司・刪地點 公司")
    return "\n".join(lines)


# ---------------- 置頂待辦清單 ----------------

def _todos() -> dict:
    """結構：{items:[{id,text,done}], msg_id, chat_id, next_id}"""
    st = _load_json(TODO_PATH, {})
    st.setdefault("items", [])
    st.setdefault("next_id", 1)
    return st


def _todo_add(text: str) -> int:
    """加一項或多項（、「，；」分隔）。回傳加咗幾多項。"""
    parts = [p.strip() for p in re.split(r"[、，,;；]+", text) if p.strip()]
    if not parts:
        return 0
    st = _todos()
    for p in parts:
        st["items"].append({"id": st["next_id"], "text": p, "done": False})
        st["next_id"] += 1
    _save_json(TODO_PATH, st)
    return len(parts)


def _todo_toggle_idx(idx: int, done: bool):
    """按顯示位置（1-based）標記完成/未完成。回傳項目文字或 None。"""
    st = _todos()
    if not (1 <= idx <= len(st["items"])):
        return None
    st["items"][idx - 1]["done"] = done
    _save_json(TODO_PATH, st)
    return st["items"][idx - 1]["text"]


def _todo_del_idx(idx: int):
    st = _todos()
    if not (1 <= idx <= len(st["items"])):
        return None
    text = st["items"].pop(idx - 1)["text"]
    _save_json(TODO_PATH, st)
    return text


def _todo_clear_done() -> tuple:
    """清除已完成項目。回傳 (清咗幾多, 剩返幾多)。"""
    st = _todos()
    keep = [it for it in st["items"] if not it.get("done")]
    n = len(st["items"]) - len(keep)
    if n:
        st["items"] = keep
        _save_json(TODO_PATH, st)
    return n, len(keep)


def _fmt_todos() -> str:
    st = _todos()
    items = st["items"]
    if not items:
        return "📋 待辦清單空晒。send：待辦 牛奶、交電費"
    lines = ["📋 待辦清單"]
    for i, it in enumerate(items, 1):
        mark = "✅" if it.get("done") else "☐"
        lines.append(f"{i}. {mark} {it['text']}")
    left = sum(1 for it in items if not it.get("done"))
    lines.append(f"（仲有 {left} 項未完成・撳下面按鈕打勾，或 send「完成 2」「刪 2」）")
    return "\n".join(lines)


def _todo_keyboard():
    """每項一粒核取方塊按鈕。lazy import 等純函數測試唔使裝 telegram。"""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    rows = []
    for i, it in enumerate(_todos()["items"], 1):
        mark = "✅" if it.get("done") else "⬜"
        rows.append([InlineKeyboardButton(
            f"{mark} {i}. {it['text'][:24]}", callback_data=f"todo:{it['id']}")])
    return InlineKeyboardMarkup(rows) if rows else None


def _schedule_todo_refresh(chat_id: int) -> None:
    """喺同步 executor 入面排程更新置頂訊息（bot 未啟動就靜靜雞 skip）。"""
    if _APP is None:
        return
    try:
        asyncio.get_running_loop().create_task(_refresh_todo(chat_id))
    except RuntimeError:
        pass  # 冇 event loop（測試環境）


async def _refresh_todo(chat_id: int) -> None:
    """編輯置頂待辦訊息；訊息被刪/未存在就重發兼置頂。"""
    if _APP is None:
        return
    st, text, kb = _todos(), _fmt_todos(), _todo_keyboard()
    mid, cid = st.get("msg_id") or 0, st.get("chat_id") or chat_id
    if mid:
        try:
            await _APP.bot.edit_message_text(text, chat_id=cid, message_id=mid, reply_markup=kb)
            return
        except Exception as e:  # noqa: BLE001
            if "not modified" in str(e).lower():
                return
            log.warning("更新待辦訊息失敗（%s），重發", e)
    try:
        m = await _APP.bot.send_message(chat_id, text, reply_markup=kb)
        st["msg_id"], st["chat_id"] = m.message_id, chat_id
        _save_json(TODO_PATH, st)
        try:
            await _APP.bot.pin_chat_message(chat_id, m.message_id, disable_notification=True)
        except Exception as e:  # noqa: BLE001
            log.warning("置頂失敗（可能權限問題）：%s", e)
    except Exception as e:  # noqa: BLE001
        log.warning("待辦清單發送失敗：%s", e)


async def _on_todo_callback(update, context) -> None:
    """撳核取方塊 → 翻轉 done 並原地更新條訊息。"""
    q = update.callback_query
    m = re.fullmatch(r"todo:(\d+)", q.data or "")
    if not m:
        return
    iid = int(m.group(1))
    st = _todos()
    item = next((it for it in st["items"] if it["id"] == iid), None)
    if item is None:
        await q.answer("項目已經刪咗")
        return
    item["done"] = not item.get("done")
    _save_json(TODO_PATH, st)
    try:
        await q.edit_message_text(_fmt_todos(), reply_markup=_todo_keyboard())
    except Exception:  # noqa: BLE001  # "Message is not modified"
        pass
    await q.answer("✅ 完成！" if item["done"] else "☐ 還原咗，加油")


_UA = ("Mozilla/5.0 (Linux; Android 10) "
       "AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36")


def _fetch(url: str) -> str:
    """下載頁面文字（上限 2MB）。4 秒硬頂——畀面反應夠快，塞網即走後備。"""
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=4) as r:
        return r.read(2_000_000).decode("utf-8", "ignore")


def _dedupe(ids) -> list:
    seen, out = set(), []
    for vid in ids:
        if vid not in seen:
            seen.add(vid)
            out.append(vid)
    return out


def _playlist_videos_rss(list_id: str) -> list:
    """YouTube 官方 RSS：細、快、冇反爬；只得最近上傳，shuffle/自動播已夠用。"""
    try:
        xml = _fetch(f"https://www.youtube.com/feeds/videos.xml?playlist_id={list_id}")
        return _dedupe(re.findall(r"<yt:videoId>([\w-]{11})", xml))
    except Exception as e:  # noqa: BLE001
        log.warning("RSS 攞歌單失敗：%s", e)
        return []


def _playlist_videos_html(list_id: str) -> list:
    """後備：爬 playlist 頁面，兩套正則。"""
    try:
        html = _fetch(f"https://www.youtube.com/playlist?list={list_id}")
        ids = re.findall(r'"videoId"\s*:\s*"([\w-]{11})"', html)
        if not ids:
            ids = re.findall(r"watch\?v=([\w-]{11})", html)
        return _dedupe(ids)
    except Exception as e:  # noqa: BLE001
        log.warning("爬歌單頁失敗：%s", e)
        return []


_PL_CACHE: dict = {}            # list_id -> (timestamp, [videoId])；session 快取
_PL_CACHE_TTL = 6 * 3600        # 6 小時內重播 = 零網絡直達 am start


def _playlist_videos(list_id: str) -> list:
    """由 YouTube playlist 抽出全部 videoId（去重、保持順序；唔使 API key）。
    優先 6 小時 session 快取（上次成功嘅就算過期都攞嚟做後備），
    miss 先行官方 RSS，再失敗爬頁面。最快響應：第二次起唔出網。"""
    hit = _PL_CACHE.get(list_id)
    if hit and dt.datetime.now().timestamp() - hit[0] < _PL_CACHE_TTL:
        return hit[1]
    vids = _playlist_videos_rss(list_id) or _playlist_videos_html(list_id)
    if vids:
        _PL_CACHE[list_id] = (dt.datetime.now().timestamp(), vids)
        return vids
    return hit[1] if hit else []   # 網絡死檔：拎到舊快取總好過開返歌單頁


def _autoplay_url(url: str, shuffle: bool = False) -> tuple:
    """回傳 (用嚟開嘅 url, 係咪自動播格式)。
    YouTube app 開 playlist 頁只會停喺頁面；要 watch?v=<片>&list=<單> 先會自動播。
    shuffle=True 隨機抽一條做開場（之後跟歌單順序播）。"""
    m = re.search(r"[?&]list=([\w-]+)", url)
    if m and "watch?v=" not in url:
        vids = _playlist_videos(m.group(1))
        if vids:
            vid = random.choice(vids) if shuffle else vids[0]
            return f"https://www.youtube.com/watch?v={vid}&list={m.group(1)}", True
        return url, False
    # watch 連結 / youtu.be / 其他：YouTube app 會直接進入播放頁
    return url, ("watch?v=" in url or "youtu.be/" in url)


def _play(url: str, shuffle: bool = False) -> tuple:
    """優先直開 YouTube app（穩陣快），失敗先交畀系統揀 app。
    回傳 (成功與否, 訊息)；成功但只開到歌單頁（唔自動播）時訊息 = "NO_AUTOLIST"。"""
    target, auto = _autoplay_url(url, shuffle)
    ok, out = run_intent(["am", "start", "-a", "android.intent.action.VIEW",
                          "-d", target, _YT_PKG])
    if not ok:
        ok, out = run_intent(["am", "start", "-a", "android.intent.action.VIEW", "-d", target])
    if ok and not auto:
        out = "NO_AUTOLIST"
    return ok, out


def _silence_wav() -> str:
    """整定一段 0.3 秒無聲 WAV（俾 Termux:API 搶音訊焦點用）。"""
    path = os.path.expanduser("~/.tgalarm/silence.wav")
    if not os.path.exists(path):
        import wave
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(b"\x00\x00" * 2400)  # 0.3 秒無聲
    return path


def _stop() -> tuple:
    """停止播放，逐層嘗試（Termux 普通 uid 冇權直接殺人哋個 app）：
    1) Termux:API 搶音訊焦點（最乾淨、冇畫面跳動；要裝 Termux:API）
    2) /system/bin/am force-stop（普通 uid 多數被擋，部分機/adb 設定得）
    3) PATH am force-stop（termux-am 唔支援 force-stop）
    4) 返主畫面：非 Premium 嘅 YouTube 一入背景即暫停
    回傳 (成功與否, 用咗邊招)。"""
    if shutil.which("termux-media-player"):
        ok, _ = run_intent(["termux-media-player", "play", _silence_wav()])
        if ok:
            run_intent(["termux-media-player", "stop"])
            return True, "audio-focus"
    ok, out = run_intent(["/system/bin/am", "force-stop", _YT_PKG])
    if not ok:
        ok, out = run_intent(["am", "force-stop", _YT_PKG])
    if ok:
        return True, "force-stop"
    ok, out = run_intent(["am", "start", "-a", "android.intent.action.MAIN",
                          "-c", "android.intent.category.HOME"])
    if ok:
        return True, "home"
    return False, out


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


async def _send_safe(chat_id: int, text: str, label: str = "訊息") -> bool:
    """到點訊息發送：閃斷退避重試（5s→20s→45s），唔再一碰就 drop。回傳最終成敗。"""
    if _APP is None:
        return False
    last = None
    for i in range(len(_NET_RETRY_BACKOFF)):
        try:
            await _APP.bot.send_message(chat_id, text)
            if i:
                log.info("%s重試後已送出", label)
            return True
        except Exception as e:  # noqa: BLE001
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


def _jobs() -> list:
    return _load_json(JOBS_PATH, [])


def _fmt_job_content(j: dict) -> str:
    """列表/訊息用嘅排程內容描述。"""
    if j.get("type", "play") == "timer":
        tag = f"（{j['label']}）" if j.get("label") else ""
        return f"計時 {fmt_duration(j.get('seconds', 0))}{tag}"
    if j.get("type") == "nav":
        return f"導航去「{j['label']}」"
    if j.get("type") == "alloc":
        segs = j.get("segments", [])
        names = "、".join(s["text"] for s in segs)
        if len(names) > 24:
            names = names[:21] + "…"
        return f"分配 {names}（{len(segs)}項）"
    return f"播「{j['label']}」" + ("🔀" if j.get("shuffle") else "")


def _fmt_jobs(now: dt.datetime) -> str:
    jobs = _jobs()
    if not jobs:
        return "🗓 冇排程。例：每日 0700 播 lofi・2130 播・每日 0900 計時 25分鐘・每日 0800 導航 公司"
    lines = ["🗓 排程："]
    for j in jobs:
        kind = "每日" if j.get("daily") else "一次"
        icon = {"timer": "⏱", "nav": "🧭", "alloc": "🧩"}.get(j.get("type"), "🎵")
        if j.get("paused"):
            state = "（⏸已暫停）"
        else:
            nxt = dt.datetime.fromisoformat(j["next"])
            state = f"→ {day_label(nxt, now)} {nxt:%H:%M}"
        lines.append(f"#{j['id']} {icon}{kind} {j['hh']:02d}:{j['mm']:02d} {_fmt_job_content(j)} {state}")
    lines.append("管理：取消 N・暫停 N・繼續 N・改 N <時間/每日/一次/歌單/時長>")
    return "\n".join(lines)


def _fmt_playlists() -> str:
    pl = _playlists()
    if not pl.get("lists"):
        return "🎵 仲未有歌單。send：歌單 名稱 YouTube連結"
    lines = ["🎵 歌單："]
    for name in pl["lists"]:
        star = "（預設）" if name == pl.get("default") else ""
        lines.append(f"・{name}{star}")
    return "\n".join(lines)


def _arm(job: dict) -> None:
    """為 job 建立到點觸發嘅 asyncio 任務。"""
    when = dt.datetime.fromisoformat(job["next"])
    delay = max(0.0, (when - dt.datetime.now()).total_seconds())
    _TASKS[job["id"]] = asyncio.get_event_loop().create_task(_fire_later(job, delay))


_BAL_TIP = ("\n💡 背景啟動被擋：vivo/Funtouch 要開「後台彈出界面」（設定→應用與權限→"
            "權限管理→其他權限→Termux；或 i管家→應用管理→權限管理），兼開「鎖屏顯示」；"
            "其他機開「喺其他應用上層顯示」。詳細路徑 send「修復」")


def _is_bal_denied(info) -> bool:
    """am start 失敗訊息係咪似「背景唔俾彈 activity」類。"""
    txt = str(info).lower()
    return "securityexception" in txt or "background" in txt or "not allowed" in txt


async def _fire_later(job: dict, delay: float) -> None:
    try:
        await asyncio.sleep(delay)
    except asyncio.CancelledError:
        return
    now = dt.datetime.now()
    jtype = job.get("type", "play")
    if jtype == "alloc":
        await _fire_alloc(job)
        return
    if jtype == "timer":
        ok, info = run_intent(timer_intent_cmd(job["seconds"], job.get("label", "")))
        how = _fmt_job_content(job)
    elif jtype == "nav":
        if shutil.which("rish") and not DRY_RUN:
            # fire 前強制重探：你可能啱啱喺 Shizuku app 重啟咗 server，
            # 唔好跟 10 分鐘 TTL 舊快取（每次 fire 至多探一次，JVM 開銷值得）
            _RISH_CACHE["ok"] = _rish_probe()
            _RISH_CACHE["t"] = now.timestamp()
        ok, info = _open_nav(job.get("url") or job.get("label", ""), job.get("mode", "d"))
        how = f"開導航去「{job.get('label') or job.get('url')}」"
        if shutil.which("rish") and not _RISH_CACHE["ok"] and not DRY_RUN:
            how += ("\n⚠️ 但 Shizuku server 冇行緊——導航彈唔出！"
                    "入 Shizuku app 撳「啟動」，下次就會彈")
    else:
        ok, info = _play(job["url"], job.get("shuffle", False))
        how = ("隨機開始播放" if job.get("shuffle") else "開始播放") + f"「{job['label']}」"
    if ok and info == "NO_AUTOLIST":
        msg = f"🔶 到點！開咗歌單頁「{job['label']}」，攞唔到首條片做自動播放，撳 ▶ 開始"
    elif ok:
        msg = f"⏰ 到點！{how}"
    else:
        msg = f"❌ 排程執行失敗：{info[:150]}" + (_BAL_TIP if _is_bal_denied(info) else "")
    await _send_safe(job["chat_id"], msg, "排程到點訊息")
    if job.get("daily"):
        job["next"] = _next_occurrence(now, job["hh"], job["mm"]).isoformat()
        jobs = _jobs()
        for j in jobs:
            if j["id"] == job["id"]:
                j["next"] = job["next"]
        _save_json(JOBS_PATH, jobs)
        _TASKS.pop(job["id"], None)
        _arm(job)
    else:
        _save_json(JOBS_PATH, [j for j in _jobs() if j["id"] != job["id"]])
        _TASKS.pop(job["id"], None)


def _alloc_segments(items_text: str, buf_pct: int, total_sec: int) -> tuple:
    """按 留空% + 加權 切時間。回傳 (segments, 錯誤訊息)；segments=[{"text","seconds"}, …]。
    比例寫法：項目後面 x2 / ×2 / *2；冇就當 1。最後一項食埋剩尾秒數，總和啱啱好。"""
    parts = [p.strip() for p in re.split(r"[、，,／/；;]+", items_text) if p.strip()]
    if not parts:
        return None, "俾個項目清單先，例：`1930至2230 分配 温習、做功課`"
    items = []
    for p in parts:
        mm = re.fullmatch(r"(.+?)\s*[xX×*]\s*(\d+(?:\.\d+)?)", p)
        if mm:
            name, w = mm.group(1).strip(), float(mm.group(2))
            if not name or w <= 0:
                return None, f"項目「{p}」格式怪"
        else:
            name, w = p, 1.0
        items.append((name, w))
    avail = int(total_sec * (100 - buf_pct) / 100) // 60 * 60  # 對齊分鐘
    if avail < 60 * len(items):
        return None, f"留空 {buf_pct}% 之後得 {fmt_duration(avail)}，唔夠分畀 {len(parts)} 項（每項至少 1 分鐘）"
    W = sum(w for _, w in items)
    segs, used = [], 0
    for i, (name, w) in enumerate(items):
        if i == len(parts) - 1:
            secs = avail - used  # 最後一項食埋剩尾，總和啱啱好
        else:
            secs = int(avail * w / W) // 60 * 60
            used += secs
        segs.append({"text": name, "seconds": secs, "w": w})
    return segs, None


def _alloc_ff(now: dt.datetime, hh: int, mm: int, hh2: int, mm2: int,
              segments: list) -> tuple:
    """「而家仲喺個 block 入面」→ 即刻上車：照顧跨日（如 2300-0200 凌晨 01:xx），
    回傳 (由邊個 idx 開始, 該段淨返秒數)；唔喺窗內 / 全部段已過 → (None, None)。"""
    s0 = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    e0 = now.replace(hour=hh2, minute=mm2, second=0, microsecond=0)
    if e0 <= s0:
        e0 += dt.timedelta(days=1)  # 跨日 block
    for d in (0, -1):
        s_try = s0 + dt.timedelta(days=d)
        e_try = e0 + dt.timedelta(days=d)
        if not (s_try <= now < e_try):
            continue
        elapsed = (now - s_try).total_seconds()
        acc = 0.0
        for i, seg in enumerate(segments):
            acc += seg["seconds"]
            rem = acc - elapsed
            if rem >= 60:  # 淨返至少 1 分鐘 → 由呢段半路加入
                return i, int(rem)
        return None, None  # 仲喺窗內但全部段都過晒（剩 buffer 位）
    return None, None


def _add_alloc_job(chat_id: int, now: dt.datetime, hh: int, mm: int,
                   hh2: int, mm2: int, daily: bool, segments: list,
                   buf: int = 0) -> tuple:
    """新增分配排程；同時間嘅舊分配排程會被取代。
    如果而家已經喺起止時間窗內 → 即刻開飛（fast-forward），唔會推去下一轉。"""
    jobs = _jobs()
    replaced = [j["id"] for j in jobs
                if j.get("type") == "alloc" and j["hh"] == hh and j["mm"] == mm]
    for rid in replaced:
        t = _TASKS.pop(rid, None)
        if t:
            t.cancel()
    jobs = [j for j in jobs if j["id"] not in replaced]
    jid = max((j["id"] for j in jobs), default=0) + 1
    idx0, first_rem = _alloc_ff(now, hh, mm, hh2, mm2, segments)
    if idx0 is not None:
        start_at = now  # 即刻觸發（喺 block 入面）
    else:
        start_at = _next_occurrence(now, hh, mm)
    job = {"id": jid, "type": "alloc", "hh": hh, "mm": mm, "hh2": hh2, "mm2": mm2,
           "daily": daily, "url": "", "seconds": 0, "mode": "",
           "label": "時間分配", "chat_id": chat_id,
           "next": start_at.isoformat(), "shuffle": False, "paused": False,
           "segments": segments, "idx": idx0 or 0, "buf": buf}
    if idx0 is not None and first_rem < segments[idx0]["seconds"]:
        job["_rem"] = first_rem  # 半路加入：第一下計時用淨返嘅秒數（一次性）
    jobs.append(job)
    _save_json(JOBS_PATH, jobs)
    _arm(job)
    return {"next_dt": start_at, **job}, replaced


def _alloc_breakdown(job: dict) -> str:
    """分配排程嘅逐項明細（含開始時間）。job 要帶 next_dt（建立時）或 next。
    半路加入（idx>0 或有 _rem）只會列未嚟緊嘅段。"""
    start = job.get("next_dt") or dt.datetime.fromisoformat(job["next"])
    if not isinstance(start, dt.datetime):
        start = dt.datetime.fromisoformat(start)
    start_idx = job.get("idx", 0)
    t, lines = start, []
    for i, s in enumerate(job.get("segments", [])[start_idx:], 1):
        secs = s["seconds"]
        if i == 1 and job.get("_rem"):
            secs = job["_rem"]  # 半路加入第一下嘅縮短版
        end = t + dt.timedelta(seconds=secs)
        lines.append(f"{i}. {s['text']} — {fmt_duration(secs)}（{t:%H:%M}→{end:%H:%M}）")
        t = end
    return "\n".join(lines)


def _alloc_remaining_end(job: dict, now: dt.datetime) -> dt.datetime:
    """進行中 block 嘅結束時間（由 hh:mm → hh2:mm2 推，跨日自動 +1 天）。"""
    s0 = now.replace(hour=job["hh"], minute=job["mm"], second=0, microsecond=0)
    if s0 > now:
        s0 -= dt.timedelta(days=1)
    e0 = s0.replace(hour=job["hh2"], minute=job["mm2"])
    if e0 <= s0:
        e0 += dt.timedelta(days=1)
    return e0


def _alloc_reflow(job: dict, now: dt.datetime, from_idx: int) -> bool:
    """動態數值核心：將剩餘段按權重重新劈（剩牋_block_end − 而家 − 留空%）。
    提早完成慳到嘅時間跌入到埋嘅段，收工時間照舊唔變。
    剩餘唔夠每段 1 分鐘 → False（交返靜態秒數繼續行）。"""
    segs = job.get("segments", [])
    rem_segs = segs[from_idx:]
    if not rem_segs:
        return False
    R = (_alloc_remaining_end(job, now) - now).total_seconds()
    buf = job.get("buf", 0)
    avail = int(R * (100 - buf) / 100) // 60 * 60
    if avail < 60 * len(rem_segs):
        return False
    W = sum(s.get("w", 1.0) for s in rem_segs)
    used = 0
    for i, s in enumerate(rem_segs):
        if i == len(rem_segs) - 1:
            secs = avail - used
        else:
            secs = int(avail * s.get("w", 1.0) / W) // 60 * 60
            used += secs
        s["seconds"] = secs
    return True


def _alloc_advance(chat_id: int, now: dt.datetime) -> str:
    """「完成」：提早做完而家呢段 → 立刻快進下一階段。
    找緊進行中嘅分配（idx>=1 表示第一下已 fire；next 係呢段尾）。
    舊 system 倒計時冇 intent 可以取消（只可以停緊響嘅），會照響；回覆有提用戶。"""
    jobs = _jobs()
    runs = [j for j in jobs if j.get("type") == "alloc"
            and j.get("idx", 0) >= 1
            and dt.datetime.fromisoformat(j["next"]) > now]
    if not runs:
        return ("❓ 而家冇進行中嘅時間分配。\n"
                "開新 block：`1930至2230 分配 温習、做功課`；send「播程」睇有冇排咗嘅。")
    # 多個就揀最雷嘅嗰段
    job = min(runs, key=lambda j: dt.datetime.fromisoformat(j["next"]))
    segs = job.get("segments", [])
    idx = job.get("idx", 0)                  # 下一段嘅索引（進行中 = idx-1）
    cur = segs[idx - 1] if segs and idx - 1 < len(segs) else {"text": "?"}
    remain = max(0, int((dt.datetime.fromisoformat(job["next"]) - now).total_seconds()))
    saved = fmt_duration(remain) if remain >= 30 else "少於 30 秒"
    t = _TASKS.pop(job["id"], None)
    if t:
        t.cancel()
    if idx < len(segs):                      # 仲有下一段 → 即刻 fire 佢
        reflowed = _alloc_reflow(job, now, idx)   # 慳返嘅時間動態跌入剩餘段
        nxt = segs[idx]
        job["next"] = now.isoformat()
        _save_json(JOBS_PATH, jobs)          # job 已喺 jobs list 內（引用）
        _arm(job)
        head = f"⏩ 提早完成「{cur['text']}」（慳返 {saved}）\n"
        if reflowed:
            end = _alloc_remaining_end(job, now)
            head += (f"→ 剩餘按權重動態重排（照舊 {end:%H:%M} 收工）：\n"
                     f"{_alloc_breakdown(job)} 🚀 馬上開始\n")
        else:
            head += f"→ 即刻開第 {idx + 1}/{len(segs)} 項「{nxt['text']}」🚀\n"
        head += "（時鐘 App 嘅舊倒計時會照響，撳停就得）"
        return head
    # 最後一段都做埋 → 提早收工
    jobs2 = [j for j in jobs if j["id"] != job["id"]]
    if job.get("daily"):
        job["idx"] = 0
        job["next"] = _next_occurrence(now, job["hh"], job["mm"]).isoformat()
        jobs2.append(job)
        _save_json(JOBS_PATH, jobs2)
        _arm(job)
        tail = "（每日分配，聽日自動重開）"
    else:
        _save_json(JOBS_PATH, jobs2)
        tail = "（一次性分配，已刪走）"
    return (f"⏩ 提早完成「{cur['text']}」（慳返 {saved}）\n"
            f"🏁 最後一項都做埋，成個分配提早收工！{tail}")


async def _fire_alloc(job: dict) -> None:
    """分配排程觸發：fire 呢段嘅計時器 → 自動排下一段；
    最後一段做晒就刪走（每日就重設去第二日）。"""
    now = dt.datetime.now()
    segs = job.get("segments", [])
    idx = job.get("idx", 0)
    if not segs or idx >= len(segs):
        _TASKS.pop(job["id"], None)
        _save_json(JOBS_PATH, [j for j in _jobs() if j["id"] != job["id"]])
        return
    seg = segs[idx]
    secs = seg["seconds"]
    if job.get("_rem"):  # 半路加入嘅縮短第一下（一次性）
        secs = int(job["_rem"])
        job["_rem"] = 0
    ok, info = run_intent(timer_intent_cmd(secs, f"{seg['text']}（{idx + 1}/{len(segs)}）"))
    if ok:
        text = (f"⏰ 到點！開始第 {idx + 1}/{len(segs)} 項「{seg['text']}」"
                f"· 計時 {fmt_duration(secs)}")
    else:
        text = f"❌ 開唔到計時器「{seg['text']}」：{str(info)[:120]}" + (
            _BAL_TIP if _is_bal_denied(info) else "")
    await _send_safe(job["chat_id"], text, "分配到點訊息")
    fired_at = dt.datetime.fromisoformat(job["next"])
    keep = True
    if idx + 1 < len(segs):
        job["idx"] = idx + 1
        if _alloc_reflow(job, now, job["idx"]):
            job["next"] = (now + dt.timedelta(
                seconds=segs[job["idx"]]["seconds"])).isoformat()   # 動態吸漂移
        else:
            job["next"] = (fired_at + dt.timedelta(seconds=secs)).isoformat()
    elif job.get("daily"):
        job["idx"] = 0
        job["next"] = _next_occurrence(now, job["hh"], job["mm"]).isoformat()
    else:
        keep = False
    _TASKS.pop(job["id"], None)
    if keep:
        jobs = _jobs()
        for j in jobs:
            if j["id"] == job["id"]:
                j["next"], j["idx"] = job["next"], job["idx"]
                j["_rem"] = job.get("_rem", 0)
        _save_json(JOBS_PATH, jobs)
        _arm(job)
    else:
        _save_json(JOBS_PATH, [j for j in _jobs() if j["id"] != job["id"]])


def _add_job(cmd: PlayerCmd, chat_id: int, now: dt.datetime,
             url: str = "", seconds: int = 0, mode: str = "d", label: str = "") -> tuple:
    """新增排程；同類型同時間嘅舊排程會被取代。回傳 (job, 被取代嘅 id 列表)。"""
    is_timer = cmd.action in ("sched_timer", "sched_timer_daily")
    is_nav = cmd.action in ("sched_nav", "sched_nav_daily")
    jtype = "timer" if is_timer else ("nav" if is_nav else "play")
    jobs = _jobs()
    # 去重：同類型 + 同 hh:mm  collide → 取代舊嘅
    replaced = [j["id"] for j in jobs
                if j.get("type", "play") == jtype and j["hh"] == cmd.hour and j["mm"] == cmd.minute]
    for rid in replaced:
        t = _TASKS.pop(rid, None)
        if t:
            t.cancel()
    jobs = [j for j in jobs if j["id"] not in replaced]

    jid = max((j["id"] for j in jobs), default=0) + 1
    if is_timer:
        default_label = ""
    elif is_nav:
        default_label = "目的地"
    else:
        default_label = _playlists().get("default") or "歌單"
    first = _next_occurrence(now, cmd.hour, cmd.minute)
    job = {"id": jid, "type": jtype, "hh": cmd.hour, "mm": cmd.minute,
           "daily": cmd.action in ("sched_daily", "sched_timer_daily", "sched_nav_daily"),
           "url": url, "seconds": seconds, "mode": mode,
           "label": label or cmd.ref or default_label,
           "chat_id": chat_id, "next": first.isoformat(),
           "shuffle": cmd.shuffle, "paused": False}
    jobs.append(job)
    _save_json(JOBS_PATH, jobs)
    _arm(job)
    return {"next_dt": first, **job}, replaced


def _pause_job(jid: int):
    """暫停排程（保留設定，唔會觸發）。回傳 True/「already」/False。"""
    jobs = _jobs()
    for j in jobs:
        if j["id"] == jid:
            if j.get("paused"):
                return "already"
            j["paused"] = True
            _save_json(JOBS_PATH, jobs)
            t = _TASKS.pop(jid, None)
            if t:
                t.cancel()
            return True
    return False


def _resume_job(jid: int, now: dt.datetime):
    """恢復排程，重新計下一次觸發。回傳下次觸發 datetime 或 None。"""
    jobs = _jobs()
    for j in jobs:
        if j["id"] == jid:
            j["paused"] = False
            nxt = _next_occurrence(now, j["hh"], j["mm"])
            j["next"] = nxt.isoformat()
            _save_json(JOBS_PATH, jobs)
            _arm(j)
            return nxt
    return None


def _edit_job(jid: int, body: str, now: dt.datetime) -> tuple:
    """就地修改排程：hhmm 改時間・每日/一次 改循環・歌單[隨機]/時長 改內容。"""
    jobs = _jobs()
    job = next((j for j in jobs if j["id"] == jid), None)
    if not job:
        return False, f"搵唔到 #{jid}。send「排程」睇編號"
    rest, changes = body.strip(), []
    r = _read_hhmm(rest)
    if r:
        hh, mm, rest = r
        job["hh"], job["mm"] = hh, mm
        changes.append(f"時間→{hh:02d}:{mm:02d}")
    if re.fullmatch(r"(?:每日|每天)", rest, re.IGNORECASE):
        job["daily"] = True
        rest = ""
        changes.append("改做每日")
    elif re.fullmatch(r"一次", rest):
        job["daily"] = False
        rest = ""
        changes.append("改做一次")
    elif rest:
        if job.get("type", "play") == "timer":
            seconds, end = _parse_duration(rest)
            if seconds <= 0:
                return False, f"計時內容睇唔明：{rest}"
            job["seconds"] = seconds
            if rest[end:].strip():
                job["label"] = rest[end:].strip()
            changes.append(f"內容→計時 {fmt_duration(seconds)}")
        elif job.get("type") == "nav":
            dest, mode, shown = _nav_target(rest)
            job["url"] = dest
            job["mode"] = mode
            job["label"] = shown
            changes.append(f"內容→導航去「{shown}」（{_mode_label(mode)}）")
        elif job.get("type") == "alloc":
            return False, "分配內容改唔到局部，send「取消 N」再排過"
        else:
            ref, sh = _strip_shuffle(rest)
            url, info = _resolve_playlist(ref)
            if url is None:
                return False, info
            job["url"] = url
            if ref:
                job["label"] = ref
            job["shuffle"] = sh
            changes.append(f"內容→播「{info or job['label']}」" + ("🔀" if sh else ""))
    if not changes:
        return False, "支援：改 N hhmm｜改 N 每日｜改 N 一次｜改 N 歌單名 [隨機]｜改 N 時長｜改 N 地點名"
    job["next"] = _next_occurrence(now, job["hh"], job["mm"]).isoformat()
    _save_json(JOBS_PATH, jobs)
    t = _TASKS.pop(jid, None)
    if t:
        t.cancel()
    if not job.get("paused"):
        _arm(job)
    return True, "、".join(changes)


def _replaced_note(replaced: list) -> str:
    if not replaced:
        return ""
    return "\n（已自動取代同時間嘅 #" + "、#".join(str(i) for i in replaced) + "）"


def _remove_job(jid: int) -> bool:
    jobs = _jobs()
    remain = [j for j in jobs if j["id"] != jid]
    if len(remain) == len(jobs):
        return False
    _save_json(JOBS_PATH, remain)
    t = _TASKS.pop(jid, None)
    if t:
        t.cancel()
    return True


def _clear_jobs() -> int:
    n = len(_jobs())
    _save_json(JOBS_PATH, [])
    for t in _TASKS.values():
        t.cancel()
    _TASKS.clear()
    return n


async def _restore_jobs(app) -> None:
    """bot 啟動/重開後：每日排程重新計下一次；過期嘅一次排程即刻補播。"""
    global _APP
    _APP = app
    now = dt.datetime.now()
    jobs = _jobs()
    changed = False
    for job in jobs:
        try:
            nxt = dt.datetime.fromisoformat(job["next"])
        except (KeyError, ValueError):
            continue
        if job.get("daily") and nxt <= now:
            job["next"] = _next_occurrence(now, job["hh"], job["mm"]).isoformat()
            if job.get("type") == "alloc":
                job["idx"] = 0  # 分配鏈由頭嚟過
                job["_rem"] = 0
            changed = True
    if changed:
        _save_json(JOBS_PATH, jobs)
    for job in jobs:
        if job.get("paused"):
            continue
        _arm(job)
    if jobs:
        log.info("已恢復 %d 個播放排程", len(jobs))
    # 待辦清單：啟動時更新返條置頂訊息（如果存在過）
    st = _todos()
    if st.get("msg_id") and st.get("chat_id"):
        try:
            await _refresh_todo(st["chat_id"])
        except Exception as e:  # noqa: BLE001
            log.warning("啟動時更新待辦訊息失敗：%s", e)


# ─── WhatsApp 夜更相搬移 ─────────────────────────────────────
# 最短路徑：純 Python scandir + rename，指令 → 執行一步直達，毫秒級回應。
# 「搬相」：將最近夜更時段（預設 23:00–07:00）嘅 WhatsApp 相（包含自己傳出嘅 Sent）
# 搬到 Picture 相簿 WA_Night；「搬相預覽」：齋列唔搬。
_WA_MEDIA_CANDIDATES = (
    "/storage/emulated/0/Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Images",
    "/storage/emulated/0/WhatsApp/Media/WhatsApp Images",
)
_WA_DEST = "/storage/emulated/0/Pictures/WA_Night"
_WA_EXTS = (".jpg", ".jpeg")
_NIGHT_START, _NIGHT_END = 23, 7   # 夜更時段 23:00 → 翌日 07:00


def _wa_dirs(src_root: str | None = None) -> list:
    """WhatsApp 圖片目錄（接收區）＋ Sent/Outgoing（自己傳出嘅一併包埋）。
    src_root 畀測試注入；預設自動偵測新/舊版路徑。搵唔到 → 空 list。"""
    root = None
    if src_root:
        root = src_root if os.path.isdir(src_root) else None
    else:
        for c in _WA_MEDIA_CANDIDATES:
            if os.path.isdir(c):
                root = c
                break
    if root is None:
        return []
    dirs = [root]
    for sub in ("Sent", "Outgoing"):
        p = os.path.join(root, sub)
        if os.path.isdir(p):
            dirs.append(p)
    return dirs


def _wa_night_window(now: dt.datetime) -> tuple:
    """最近嘅夜更時段 (start, end)：[start, end)。
    23:00 後／07:00 前 → 今晚（進行緊，搬到而家為止）；
    其他時間 → 尋晚 23:00 → 今朝 07:00（已完成嘅夜更）。"""
    if now.hour >= _NIGHT_START:
        start = now.replace(hour=_NIGHT_START, minute=0, second=0, microsecond=0)
        end = (start + dt.timedelta(days=1)).replace(hour=_NIGHT_END)
    else:
        end = now.replace(hour=_NIGHT_END, minute=0, second=0, microsecond=0)
        start = (end - dt.timedelta(days=1)).replace(hour=_NIGHT_START)
    return start, end


def _wa_scan(dirs: list, start: dt.datetime, end: dt.datetime) -> list:
    """每個 dir 第一層、jpg/jpeg、mtime 落喺 [start, end) → [(ts, path)]，按時間排序。"""
    s_ep, e_ep = start.timestamp(), end.timestamp()
    hits = []
    for d in dirs:
        try:
            with os.scandir(d) as it:
                for ent in it:
                    try:
                        if not ent.is_file(follow_symlinks=False):
                            continue
                        if not ent.name.lower().endswith(_WA_EXTS):
                            continue
                        ts = ent.stat(follow_symlinks=False).st_mtime
                    except OSError:
                        continue
                    if s_ep <= ts < e_ep:
                        hits.append((ts, ent.path))
        except OSError:
            continue
    hits.sort()
    return hits


def _wa_move(now: dt.datetime, preview: bool = False,
             src_root: str | None = None, dest: str | None = None) -> str:
    """搬相主體：掃 →（預覽）列／真搬，兼防撞名。回傳畀用戶嘅訊息。"""
    dirs = _wa_dirs(src_root)
    if not dirs:
        return ("❌ 搵唔到 WhatsApp Images 資料夾。\n"
                "先喺 Termux 行：termux-setup-storage（撳「允許」儲存權限），再 send「搬相」")
    dest = dest or _WA_DEST
    start, end = _wa_night_window(now)
    hits = _wa_scan(dirs, start, end)
    span = f"{start:%m-%d %H:%M} → {end:%m-%d %H:%M}"
    if not hits:
        return f"✅ 夜更時段（{span}）冇相，唔使搬。"
    sent_n = sum(1 for _, p in hits if "/Sent/" in p or "/Outgoing/" in p)
    lines = [f"🌙 夜更時段 {span}，共 {len(hits)} 張（其中自己傳出 {sent_n} 張）："]
    for ts, path in hits[:8]:
        tag = "↗" if "/Sent/" in path or "/Outgoing/" in path else "↘"
        lines.append(f"  {tag}[{dt.datetime.fromtimestamp(ts):%m-%d %H:%M}] {os.path.basename(path)}")
    if len(hits) > 8:
        lines.append(f"  …（仲有 {len(hits) - 8} 張）")
    if preview:
        lines.append("（預覽：冇郁任何相；send「搬相」先真搬）")
        return "\n".join(lines)
    os.makedirs(dest, exist_ok=True)
    moved = 0
    for ts, path in hits:
        base = os.path.basename(path)
        target = os.path.join(dest, base)
        if os.path.exists(target):                      # 防撞名 → -1 -2…
            stem, ext = os.path.splitext(base)
            i = 1
            while os.path.exists(os.path.join(dest, f"{stem}-{i}{ext}")):
                i += 1
            target = os.path.join(dest, f"{stem}-{i}{ext}")
        try:
            os.replace(path, target)
            moved += 1
        except OSError as e:
            log.warning("搬相失敗 %s：%s", path, e)
    lines.append(f"✅ 搬咗 {moved}/{len(hits)} 張 → {dest}")
    lines.append("（WhatsApp 對話內嗰啲縮圖會變灰；去返相簿 WA_Night 睇原圖）")
    ms = shutil.which("termux-media-scan")              # 通知相簿掃描，開槍就走唔等佢
    if ms:
        try:
            subprocess.Popen([ms, dest], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:  # noqa: BLE001
            pass
    return "\n".join(lines)


def _execute_player(cmd: PlayerCmd, chat_id: int, now: dt.datetime) -> str:
    a = cmd.action
    if a == "wamove":
        return _wa_move(now, preview=(cmd.ref == "preview"))
    if a == "alloc_done":
        return _alloc_advance(chat_id, now)
    if a == "play":
        url, info = _resolve_playlist(cmd.ref)
        if url is None:
            return "❓ " + info
        ok, out = _play(url, cmd.shuffle)
        if ok:
            tag = f"「{info}」" if info else ""
            if out == "NO_AUTOLIST":
                return f"🔶 開咗歌單頁{tag}，但攞唔到首條片做自動播放，喺 app 撳 ▶ 開始"
            how = "🔀 隨機開始播放" if cmd.shuffle else "▶️ 開始播放"
            return f"{how}{tag}" + ("（DRY_RUN）" if DRY_RUN else "")
        return "❌ 開唔到 YouTube（有冇裝 YouTube app？）：" + out[:150]
    if a == "stop":
        ok, how = _stop()
        if not ok:
            return "❌ 停唔到：" + how[:150]
        if how == "home":
            return ("⏸ 已切去主畫面（非 Premium 嘅 YouTube 入背景會自動暫停；"
                    "如果仲響緊，喺 app 手停，或者裝 Termux:API 我幫你用靜音搶焦點）")
        return "⏹ 已停止播放"
    if a in ("sched_once", "sched_daily"):
        url, info = _resolve_playlist(cmd.ref)
        if url is None:
            return "❓ " + info
        job, replaced = _add_job(cmd, chat_id, now, url=url)
        kind = "每日" if a == "sched_daily" else "一次"
        when = f"{day_label(job['next_dt'], now)} {cmd.hour:02d}:{cmd.minute:02d}"
        shuf = " 🔀隨機" if cmd.shuffle else ""
        msg = f"🗓 已排程（{kind}{shuf} #{job['id']}）：{when} 播「{job['label']}」"
        return msg + _replaced_note(replaced)
    if a in ("sched_timer", "sched_timer_daily"):
        job, replaced = _add_job(cmd, chat_id, now, seconds=cmd.seconds)
        kind = "每日" if a == "sched_timer_daily" else "一次"
        when = f"{day_label(job['next_dt'], now)} {cmd.hour:02d}:{cmd.minute:02d}"
        msg = f"🗓 已排程（{kind} #{job['id']}）：{when} {_fmt_job_content(job)}"
        return msg + _replaced_note(replaced)
    if a in ("sched_nav", "sched_nav_daily"):
        dest, mode, shown = _nav_target(cmd.ref)
        job, replaced = _add_job(cmd, chat_id, now, url=dest, mode=mode, label=shown)
        kind = "每日" if a == "sched_nav_daily" else "一次"
        when = f"{day_label(job['next_dt'], now)} {cmd.hour:02d}:{cmd.minute:02d}"
        msg = (f"🗓 已排程（{kind} #{job['id']}）：{when} "
               f"導航去「{job['label']}」（{_mode_label(mode)}）")
        return msg + _replaced_note(replaced)
    if a in ("sched_alloc", "sched_alloc_daily"):
        if not (0 <= cmd.buf <= 90):
            return "❓ 留空要 0-90% 之內"
        daily = a == "sched_alloc_daily"
        s0 = dt.datetime(now.year, now.month, now.day, cmd.hour, cmd.minute)
        e0 = dt.datetime(now.year, now.month, now.day, cmd.hour2, cmd.minute2)
        if e0 <= s0:
            e0 += dt.timedelta(days=1)  # 過夜（例如 2200-0200）
        total = int((e0 - s0).total_seconds())
        segs, err = _alloc_segments(cmd.ref, cmd.buf, total)
        if segs is None:
            return "❓ " + err
        job, replaced = _add_alloc_job(chat_id, now, cmd.hour, cmd.minute,
                                       cmd.hour2, cmd.minute2, daily, segs, cmd.buf)
        kind = "每日" if daily else "一次"
        av = total - sum(s2["seconds"] for s2 in segs)
        when = f"{day_label(job['next_dt'], now)} {cmd.hour:02d}:{cmd.minute:02d}"
        lines = [f"🧩 時間分配（{kind} #{job['id']}）：{when}→{cmd.hour2:02d}:{cmd.minute2:02d}"
                 f"（{fmt_duration(total)}・留空 {cmd.buf}%＝{fmt_duration(av)}隨你用）",
                 _alloc_breakdown(job)]
        return "\n".join(lines) + _replaced_note(replaced)
    if a == "selfcheck":
        nxt = now + dt.timedelta(minutes=2)
        test_cmd = PlayerCmd("sched_timer", hour=nxt.hour, minute=nxt.minute,
                             seconds=90, ref="自檢測試")
        job, _ = _add_job(test_cmd, chat_id, now, seconds=90)
        return ("🩺 自檢已排：兩分鐘後（"
                f"{nxt:%H:%M}）你應該同時見到——\n"
                "① 呢度彈「⏰ 到點」訊息\n"
                "② 時鐘 app 彈出 90 秒計時器\n"
                "❗ 兩樣都冇 → bot 被系統殺咗（send「修復」開保障設定）\n"
                "❗ 有訊息冇計時器/冇導航 → 背景彈窗被擋：\n"
                "　• vivo/Funtouch：要開「後台彈出界面」（設定→應用與權限→權限管理→其他權限）\n"
                "　• 其他機：「喺其他應用上層顯示」要開\n"
                "（試埋熄螢幕等，最似你半夜放工狀態）")
    if a == "protect":
        run_intent(["am", "start", "-a", "android.settings.APPLICATION_DETAILS_SETTINGS",
                    "-d", "package:com.termux"])
        run_intent(["am", "start", "-a", "android.settings.action.MANAGE_OVERLAY_PERMISSION",
                    "-d", "package:com.termux"])
        run_intent(["am", "start", "-a", "android.settings.IGNORE_BATTERY_OPTIMIZATION_SETTINGS"])
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
        return _fmt_jobs(now)
    if a == "cancel":
        if _remove_job(cmd.job_id):
            return f"🗑 已取消 #{cmd.job_id}"
        return f"搵唔到 #{cmd.job_id}。send「排程」睇編號"
    if a == "pause":
        r = _pause_job(cmd.job_id)
        if r is True:
            return f"⏸ 已暫停 #{cmd.job_id}"
        if r == "already":
            return f"#{cmd.job_id} 本身就暫停緊。"
        return f"搵唔到 #{cmd.job_id}。send「排程」睇編號"
    if a == "resume":
        nxt = _resume_job(cmd.job_id, now)
        if nxt is None:
            return f"搵唔到 #{cmd.job_id}。send「排程」睇編號"
        return f"▶️ 已恢復 #{cmd.job_id}（{day_label(nxt, now)} {nxt:%H:%M} 觸發）"
    if a == "edit":
        ok, info = _edit_job(cmd.job_id, cmd.ref, now)
        return f"✏️ #{cmd.job_id}：{info}" if ok else f"❌ {info}"
    if a == "cancel_all":
        return f"🗑 已取消全部 {_clear_jobs()} 個排程"
    if a == "listpl":
        return _fmt_playlists()
    if a == "savepl":
        if not _is_yt_url(cmd.url):
            return "❓ 連結唔似 YouTube（要 youtube.com / youtu.be 開頭）"
        pl = _playlists()
        pl.setdefault("lists", {})[cmd.ref] = cmd.url
        if not pl.get("default"):
            pl["default"] = cmd.ref
        _save_json(PLAYLISTS_PATH, pl)
        warn = "" if "list=" in cmd.url else "\n（提提你：連結冇 list=，似單一影片多過歌單）"
        return f"💾 已儲存歌單「{cmd.ref}」{warn}"
    if a == "delpl":
        pl = _playlists()
        if cmd.ref in pl.get("lists", {}):
            del pl["lists"][cmd.ref]
            if pl.get("default") == cmd.ref:
                pl["default"] = next(iter(pl["lists"]), "")
            _save_json(PLAYLISTS_PATH, pl)
            return f"🗑 已刪歌單「{cmd.ref}」"
        return f"搵唔到歌單「{cmd.ref}」"
    if a == "setdef":
        pl = _playlists()
        if cmd.ref in pl.get("lists", {}):
            pl["default"] = cmd.ref
            _save_json(PLAYLISTS_PATH, pl)
            return f"⭐ 預設歌單 = 「{cmd.ref}」"
        return f"搵唔到歌單「{cmd.ref}」"
    if a == "dests":
        return _fmt_dests()
    if a == "savedest":
        d = _dests()
        d[cmd.ref] = cmd.url
        _save_json(DESTINATIONS_PATH, d)
        return f"📍 已儲存地點「{cmd.ref}」＝「{cmd.url}」"
    if a == "deldest":
        d = _dests()
        if cmd.ref in d:
            del d[cmd.ref]
            _save_json(DESTINATIONS_PATH, d)
            return f"🗑 已刪地點「{cmd.ref}」"
        return f"搵唔到地點「{cmd.ref}」"
    if a == "nav":
        dest, mode, shown = _nav_target(cmd.ref)
        ok, out = _open_nav(dest, mode)
        if ok:
            tag = f"開緊導航去「{shown}」（{_mode_label(mode)}）"
            return f"🧭 {tag}" + ("（DRY_RUN）" if DRY_RUN else "")
        return "❌ 開唔到 Google Maps（有冇裝 Maps app？）：" + out[:150]
    if a == "todo":
        _schedule_todo_refresh(chat_id)
        return _fmt_todos()
    if a == "todo_add":
        n = _todo_add(cmd.ref)
        if not n:
            return "❓ 俾個項目名先，例：待辦 牛奶"
        _schedule_todo_refresh(chat_id)
        return f"📋 已加入 {n} 項待辦"
    if a in ("todo_done", "todo_undone"):
        done = a == "todo_done"
        text = _todo_toggle_idx(cmd.job_id, done)
        if text is None:
            return f"搵唔到第 {cmd.job_id} 項。send「待辦」睇清單"
        _schedule_todo_refresh(chat_id)
        return f"✅ 「{text}」完成，正！" if done else f"☐ 「{text}」標返做未完成"
    if a == "todo_del":
        text = _todo_del_idx(cmd.job_id)
        if text is None:
            return f"搵唔到第 {cmd.job_id} 項。send「待辦」睇清單"
        _schedule_todo_refresh(chat_id)
        return f"🗑 已刪「{text}」"
    if a == "todo_clear_done":
        n, left = _todo_clear_done()
        if not n:
            return "冇已完成項目"
        _schedule_todo_refresh(chat_id)
        return f"🧹 清咗 {n} 項已完成；仲有 {left} 項未完成"
    return "🤔 睇唔明"


# ---------------- Telegram handlers（延後 import，等 parser 可以單獨測試） ----------------

def _execute(p: Parsed, now: dt.datetime) -> str:
    """執行一條已解析指令，回傳結果描述文字。"""
    tag = f"（{p.label}）" if p.label else ""
    tail = "（DRY_RUN 未真正設定）" if DRY_RUN else ""
    if p.kind == "timer":
        if p.seconds > MAX_TIMER_SECONDS:
            return f"⚠️ 超過計時上限 99999 小時（你設咗 {fmt_duration(p.seconds)}），冇設定到"
        ok, out = run_intent(timer_intent_cmd(p.seconds, p.label))
        if ok:
            day = day_label(p.fire_at, now)
            when = f"{p.fire_at:%H:%M}" if day == "今日" else f"{day} {p.fire_at:%H:%M}"
            return f"⏱ 計時器 {fmt_duration(p.seconds)}{tag}，{when} 響{tail}"
        return f"❌ 計時器開唔到（多數係時鐘 App 唔支援 SET_TIMER，裝 Google「時鐘」或設 SKIP_UI=0）：{out[:150]}"
    ok, out = run_intent(alarm_intent_cmd(p.hour, p.minute, p.label))
    if ok:
        return f"⏰ 鬧鐘 {day_label(p.fire_at, now)} {p.hour:02d}:{p.minute:02d}{tag}{tail}"
    return f"❌ 鬧鐘開唔到：{out[:150]}"

async def _ensure_owner(update) -> bool:
    """白名單檢查 + 首次使用自動綁定。回傳 True = 可以繼續。"""
    cid = update.effective_chat.id
    allowed = _allowed_ids()
    if not allowed:
        _bind_owner(cid)
        await update.message.reply_text(
            f"✅ 已自動綁定你做擁有者（chat_id={cid}）\n"
            "由而家起淨係你嘅帳號可以指揮呢隻 bot。\n"
            f"（想加人/換人：改 {CONFIG_PATH} 入面嘅 ALLOWED_CHAT_IDS，唔使重啟）"
        )
        return True
    if cid not in allowed:
        log.warning("未授權存取 chat_id=%s", cid)
        await update.message.reply_text("⛔ 呢隻 bot 已綁定咗其他擁有者。")
        return False
    return True


async def _on_start(update, context):
    if not await _ensure_owner(update):
        return
    await update.message.reply_text("👋 準備就緒！\n" + HELP)


async def _on_message(update, context):
    if not update.message or not update.message.text:
        return
    if not await _ensure_owner(update):
        return

    now = dt.datetime.now()
    items = parse_lines(update.message.text, now)
    if not items:
        return

    results = []
    for ln, p in items:
        if isinstance(p, PlayerCmd):
            results.append(_execute_player(p, update.effective_chat.id, now))
        elif p:
            results.append(_execute(p, now))
        else:
            results.append(f"❓ 睇唔明：{ln}")

    reply = "\n".join(results)
    if len(items) == 1 and results[0].startswith("❓"):
        reply += "\n\n" + HELP  # 單行失敗先彈完整格式說明，批次就逐行標示
    await update.message.reply_text(reply)


def main():
    if not BOT_TOKEN:
        sys.exit(
            "未設定 BOT_TOKEN。\n"
            "最簡單：行 bash setup.sh，佢會問你一次 token 然後全部自動搞掂；\n"
            "或者手動：export BOT_TOKEN=\"你嘅token\" 再 python bot.py"
        )
    from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

    app = Application.builder().token(BOT_TOKEN).post_init(_restore_jobs).build()
    app.add_handler(CommandHandler("start", _on_start))
    app.add_handler(CommandHandler("help", _on_start))
    app.add_handler(CallbackQueryHandler(_on_todo_callback, pattern=r"^todo:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _on_message))
    app.add_error_handler(_on_error)
    log.info("Bot 啟動（長輪詢模式，DRY_RUN=%s，config=%s）", DRY_RUN, CONFIG_PATH)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
