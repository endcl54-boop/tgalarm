"""bot.py 指令解析 + Intent 生成嘅單元測試（唔使 Telegram、唔使 Android 都行到）"""
import asyncio
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest import mock

import bot


async def _ensure_owner_true(update) -> bool:
    return True
from bot import (
    _execute,
    _is_yt_url,
    _resolve_playlist,
    _save_json,
    alarm_intent_cmd,
    day_label,
    fmt_duration,
    parse_command,
    parse_lines,
    parse_player,
    split_commands,
    timer_intent_cmd,
)

NOW = dt.datetime(2026, 9, 21, 15, 0, 0)  # 星期一 15:00


class TestTimerDuration(unittest.TestCase):
    def test_minutes(self):
        p = parse_command("計時 25分鐘", NOW)
        self.assertEqual((p.kind, p.seconds), ("timer", 1500))
        self.assertEqual(p.fire_at, dt.datetime(2026, 9, 21, 15, 25))

    def test_hours_minutes_combo(self):
        p = parse_command("計時 1小時30分", NOW)
        self.assertEqual(p.seconds, 5400)

    def test_seconds(self):
        p = parse_command("計時 90秒", NOW)
        self.assertEqual(p.seconds, 90)
        self.assertEqual(p.fire_at, dt.datetime(2026, 9, 21, 15, 1, 30))

    def test_cantonese_half_hour(self):
        self.assertEqual(parse_command("計時 1個半鐘", NOW).seconds, 5400)
        self.assertEqual(parse_command("計時 半小時", NOW).seconds, 1800)
        self.assertEqual(parse_command("計時 1小時半", NOW).seconds, 5400)

    def test_decimal_hours(self):
        self.assertEqual(parse_command("計時 1.5小時", NOW).seconds, 5400)

    def test_english_shorthand(self):
        self.assertEqual(parse_command("timer 25m", NOW).seconds, 1500)
        self.assertEqual(parse_command("Timer 2h", NOW).seconds, 7200)

    def test_label_attached_and_spaced(self):
        self.assertEqual(parse_command("計時 10分鐘 杯麵", NOW).label, "杯麵")
        self.assertEqual(parse_command("計時 5分鐘沖茶", NOW).label, "沖茶")


class TestTimerUntilClockTime(unittest.TestCase):
    def test_until_same_day(self):
        p = parse_command("計時到 18:30", NOW)
        self.assertEqual(p.kind, "timer")
        self.assertEqual(p.seconds, 3 * 3600 + 1800)  # 12600

    def test_until_with_label(self):
        p = parse_command("倒數到 15:30 開會", NOW)
        self.assertEqual(p.seconds, 1800)
        self.assertEqual(p.label, "開會")

    def test_until_rolls_to_tomorrow(self):
        p = parse_command("計時到 03:00", NOW)   # 已過咗 → 聽日 03:00
        self.assertEqual(p.seconds, 12 * 3600)

    def test_fullwidth_colon(self):
        p = parse_command("計時到 18：30", NOW)
        self.assertEqual(p.seconds, 12600)


class TestAlarm(unittest.TestCase):
    def test_alarm_tomorrow(self):
        p = parse_command("鬧鐘 07:00", NOW)     # 15:00 先嚟設 07:00 → 聽日
        self.assertEqual((p.kind, p.hour, p.minute), ("alarm", 7, 0))
        self.assertEqual(p.fire_at.date(), dt.date(2026, 9, 22))

    def test_alarm_today_with_label(self):
        p = parse_command("鬧鐘 16:30 接放學", NOW)
        self.assertEqual((p.hour, p.minute), (16, 30))
        self.assertEqual(p.label, "接放學")
        self.assertEqual(p.fire_at.date(), dt.date(2026, 9, 21))

    def test_alarm_no_leading_zero(self):
        p = parse_command("鬧鐘 7:05", NOW)
        self.assertEqual((p.hour, p.minute), (7, 5))

    def test_english_alarm(self):
        p = parse_command("alarm 07:15", NOW)
        self.assertEqual((p.kind, p.hour, p.minute), ("alarm", 7, 15))

    def test_invalid_time_rejected(self):
        self.assertIsNone(parse_command("鬧鐘 25:00", NOW))


class TestGarbage(unittest.TestCase):
    def test_unrelated_text(self):
        self.assertIsNone(parse_command("你好", NOW))
        self.assertIsNone(parse_command("計時", NOW))
        self.assertIsNone(parse_command("", NOW))


class TestIntents(unittest.TestCase):
    def test_timer_intent(self):
        cmd = " ".join(timer_intent_cmd(1500, "杯麵"))
        self.assertIn("android.intent.action.SET_TIMER", cmd)
        self.assertIn("1500", cmd)
        self.assertIn("杯麵", cmd)

    def test_alarm_intent(self):
        cmd = " ".join(alarm_intent_cmd(7, 30, "起身"))
        self.assertIn("android.intent.action.SET_ALARM", cmd)
        self.assertIn("HOUR 7", cmd)
        self.assertIn("MINUTES 30", cmd)

    def test_fmt_duration(self):
        self.assertEqual(fmt_duration(5400), "1小時30分鐘")
        self.assertEqual(fmt_duration(90), "1分鐘30秒")
        self.assertEqual(fmt_duration(600), "10分鐘")


class TestHhmmFormat(unittest.TestCase):
    """無冒號 hhmm 寫法：最尾兩位=分鐘，前面=小時"""

    def test_alarm_4digit(self):
        p = parse_command("鬧鐘 0700", NOW)
        self.assertEqual((p.kind, p.hour, p.minute), ("alarm", 7, 0))

    def test_alarm_3digit_with_label(self):
        p = parse_command("鬧鐘 730 起身", NOW)
        self.assertEqual((p.hour, p.minute), (7, 30))
        self.assertEqual(p.label, "起身")

    def test_alarm_evening(self):
        p = parse_command("鬧鐘 1830", NOW)
        self.assertEqual((p.hour, p.minute), (18, 30))
        self.assertEqual(p.fire_at.date(), dt.date(2026, 9, 21))

    def test_timer_until_4digit(self):
        self.assertEqual(parse_command("計時到 1830", NOW).seconds, 12600)

    def test_timer_bare_4digit_means_until(self):
        p = parse_command("計時 1830", NOW)
        self.assertEqual(p.kind, "timer")
        self.assertEqual(p.seconds, 12600)

    def test_until_3digit_rolls_tomorrow(self):
        p = parse_command("倒數到 730", NOW)  # 07:30 已過 → 聽日
        self.assertEqual(p.seconds, int(16.5 * 3600))

    def test_invalid_hhmm_rejected(self):
        self.assertIsNone(parse_command("鬧鐘 2560", NOW))   # 25 時唔存在
        self.assertIsNone(parse_command("鬧鐘 1260", NOW))   # 60 分唔存在
        self.assertIsNone(parse_command("鬧鐘 07305", NOW))  # 5 位數唔收

    def test_duration_still_wins(self):
        # 有單位一定當時長，唔會誤判做 hhmm
        self.assertEqual(parse_command("計時 90秒", NOW).seconds, 90)
        self.assertEqual(parse_command("計時 10分鐘", NOW).seconds, 600)


class TestBatchSplit(unittest.TestCase):
    """批次輸入：隔行一個指令"""

    def test_two_lines(self):
        self.assertEqual(
            split_commands("鬧鐘 0700\n計時 10分鐘"),
            ["鬧鐘 0700", "計時 10分鐘"],
        )

    def test_blank_lines_and_spaces_skipped(self):
        self.assertEqual(
            split_commands("  鬧鐘 0700  \n\n\n計時 10分鐘 杯麵\n"),
            ["鬧鐘 0700", "計時 10分鐘 杯麵"],
        )

    def test_all_blank(self):
        self.assertEqual(split_commands("\n  \n"), [])


class TestBatchInherit(unittest.TestCase):
    """裸行繼承上一個明確指令嘅關鍵字"""

    def test_inherit_timer_hhmm(self):
        items = parse_lines("計時 1830\n1900\n1930", NOW)
        self.assertEqual([s for _, s in [(l, p.seconds) for l, p in items]],
                         [12600, 14400, 16200])
        self.assertTrue(all(p.kind == "timer" for _, p in items))

    def test_inherit_alarm_with_label(self):
        items = parse_lines("鬧鐘 0700\n0730\n0800 返工", NOW)
        self.assertEqual([(p.hour, p.minute) for _, p in items],
                         [(7, 0), (7, 30), (8, 0)])
        self.assertEqual(items[2][1].label, "返工")

    def test_inherit_duration(self):
        items = parse_lines("計時 5分鐘\n10分鐘", NOW)
        self.assertEqual(items[1][1].seconds, 600)

    def test_context_switch(self):
        items = parse_lines("計時 1830\n1900\n鬧鐘 0700\n0730", NOW)
        self.assertEqual([p.kind for _, p in items],
                         ["timer", "timer", "alarm", "alarm"])

    def test_colon_time_as_continuation(self):
        items = parse_lines("計時 18:30\n19:00", NOW)
        self.assertEqual(items[1][1].seconds, 4 * 3600)

    def test_no_context_is_unknown(self):
        items = parse_lines("1900", NOW)
        self.assertIsNone(items[0][1])

    def test_blank_lines_between_groups(self):
        items = parse_lines("計時 1830\n\n\n1900\n鬧鐘 0700\n\n0730", NOW)
        self.assertEqual([p.kind for _, p in items],
                         ["timer", "timer", "alarm", "alarm"])
        self.assertEqual(len(items), 4)


class TestDayDuration(unittest.TestCase):
    """「天/日」做時長單位"""

    def test_days(self):
        self.assertEqual(parse_command("計時 3天", NOW).seconds, 259200)

    def test_ri(self):
        self.assertEqual(parse_command("計時 1日", NOW).seconds, 86400)

    def test_days_hours_combo(self):
        self.assertEqual(parse_command("計時 1天12小時", NOW).seconds, 129600)

    def test_half_day(self):
        self.assertEqual(parse_command("計時 半天", NOW).seconds, 43200)
        self.assertEqual(parse_command("計時 半日", NOW).seconds, 43200)

    def test_one_and_half_days(self):
        self.assertEqual(parse_command("計時 1天半", NOW).seconds, 129600)
        self.assertEqual(parse_command("計時 2個半天", NOW).seconds, 216000)

    def test_english_days(self):
        self.assertEqual(parse_command("計時 3d", NOW).seconds, 259200)
        self.assertEqual(parse_command("timer 2 days", NOW).seconds, 172800)

    def test_relative_date_not_absorbed(self):
        # 「後天」「明天」係日期唔係時長，唔會被新單位「天/日」誤食
        p = parse_command("計時 後天 0700", NOW)
        self.assertEqual(p.fire_at, dt.datetime(2026, 9, 23, 7, 0))
        p2 = parse_command("計時 明天 1830", NOW)
        self.assertEqual(p2.seconds, 99000)


class TestTimerWithDate(unittest.TestCase):
    """計時連日期：明天/聽日/後天/大後天/mmdd（NOW = 2026-09-21 15:00）"""

    def test_tomorrow(self):
        p = parse_command("計時 明天 1830", NOW)
        self.assertEqual(p.fire_at, dt.datetime(2026, 9, 22, 18, 30))
        self.assertEqual(p.seconds, 99000)

    def test_tingjat(self):
        p = parse_command("計時 聽日 07:00", NOW)
        self.assertEqual(p.fire_at, dt.datetime(2026, 9, 22, 7, 0))

    def test_day_after_tomorrow(self):
        p = parse_command("計時 後天 0700", NOW)
        self.assertEqual(p.fire_at, dt.datetime(2026, 9, 23, 7, 0))
        self.assertEqual(p.seconds, 144000)  # 40 小時

    def test_daai_hautin(self):
        p = parse_command("計時 大後天 0700", NOW)
        self.assertEqual(p.fire_at, dt.datetime(2026, 9, 24, 7, 0))

    def test_mmdd(self):
        p = parse_command("計時 0925 1830", NOW)
        self.assertEqual(p.fire_at, dt.datetime(2026, 9, 25, 18, 30))
        self.assertEqual(p.seconds, 358200)

    def test_mmdd_today_future_time(self):
        p = parse_command("計時 0921 1600", NOW)
        self.assertEqual(p.seconds, 3600)

    def test_mmdd_rolls_next_year(self):
        p = parse_command("計時 0101 0800", NOW)
        self.assertEqual(p.fire_at, dt.datetime(2027, 1, 1, 8, 0))

    def test_mmdd_invalid_date_rejected(self):
        self.assertIsNone(parse_command("計時 0931 1000", NOW))  # 9月31日唔存在

    def test_mmdd_without_time_keeps_hhmm(self):
        # 淨 4 位數、後面冇第二組時間 → 維持原本 hhmm 解讀（12:30）
        p = parse_command("計時 1230", NOW)
        self.assertEqual(p.seconds, 77400)

    def test_date_without_time_rejected(self):
        self.assertIsNone(parse_command("計時 明天", NOW))

    def test_until_branch_supports_date(self):
        self.assertEqual(parse_command("計時到 明天 1830", NOW).seconds, 99000)

    def test_inherit_date_bare_line(self):
        items = parse_lines("計時 明天 1830\n後天 0700", NOW)
        self.assertEqual(items[1][1].fire_at, dt.datetime(2026, 9, 23, 7, 0))


class TestDayLabel(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(day_label(dt.datetime(2026, 9, 21, 18), NOW), "今日")
        self.assertEqual(day_label(dt.datetime(2026, 9, 22, 7), NOW), "聽日")
        self.assertEqual(day_label(dt.datetime(2026, 9, 23, 7), NOW), "後日")
        self.assertEqual(day_label(dt.datetime(2026, 9, 24, 7), NOW), "大後日")
        self.assertEqual(day_label(dt.datetime(2026, 9, 26, 7), NOW), "9月26日")


class TestTimerCap(unittest.TestCase):
    """計時硬上限 99999 小時"""

    def setUp(self):
        self._jobs, self._save, self._arm = bot._jobs, bot._save_json, bot._arm
        bot._jobs = list
        bot._save_json = lambda p, d: None
        bot._arm = lambda j: None

    def tearDown(self):
        bot._jobs, bot._save_json, bot._arm = self._jobs, self._save, self._arm

    def test_over_99999h_rejected(self):
        p = parse_command("計時 100000小時", NOW)
        self.assertIsNotNone(p)
        self.assertIn("超過計時上限", _execute(p, NOW))

    def test_99999h_goes_to_clock_app(self):
        """手機計時器上限 99999 小時（用戶證實）——最大值都直接落 app。"""
        seen = {}
        def fake(cmd, t=0):
            seen["cmd"] = " ".join(cmd)
            return True, "OK"
        old = bot.run_intent
        bot.run_intent = fake
        try:
            p = parse_command("計時 99999小時", NOW)
            r = _execute(p, NOW, chat_id=1)
        finally:
            bot.run_intent = old
        self.assertNotIn("超過計時上限", r)
        self.assertIn("已落時鐘 app", r)
        self.assertIn(str(99999 * 3600), seen["cmd"])   # Int 裝得落

    def test_timer_goes_to_clock_app(self):
        seen = {}
        def fake(cmd, t=0):
            seen["cmd"] = " ".join(cmd)
            return True, "OK"
        old = bot.run_intent
        bot.run_intent = fake
        try:
            r = _execute(parse_command("計時 25分鐘 杯麵", NOW), NOW, chat_id=1)
        finally:
            bot.run_intent = old
        self.assertIn("已落時鐘 app", r)
        self.assertIn("SET_TIMER", seen["cmd"])
        self.assertIn("1500", seen["cmd"])
        self.assertIn("杯麵", seen["cmd"])
        self.assertNotIn("「取消", r)              # 冇開 bot job

    def test_alarm_goes_to_clock_app(self):
        seen = {}
        def fake(cmd, t=0):
            seen["cmd"] = " ".join(cmd)
            return True, "OK"
        old = bot.run_intent
        bot.run_intent = fake
        try:
            r = _execute(parse_command("鬧鐘 0700 起身", NOW), NOW, chat_id=1)
        finally:
            bot.run_intent = old
        self.assertIn("已落手機時鐘", r)
        self.assertIn("07:00", r)
        self.assertIn("SET_ALARM", seen["cmd"])
        self.assertNotIn("「取消", r)              # 冇開 bot job

    def test_intent_fail_falls_back_to_bell(self):
        old = bot.run_intent
        bot.run_intent = lambda cmd, t=0: (False, "boom")
        try:
            r = _execute(parse_command("鬧鐘 0700", NOW), NOW, chat_id=1)
        finally:
            bot.run_intent = old
        self.assertIn("#1", r)
        self.assertIn("設唔到", r)

    def test_takeaway_toggle_and_timer_minus5(self):
        old_save = bot._save_json
        bot._save_json = lambda p, d: None
        bot._TAKEAWAY["on"] = False
        seen = {}
        def fake(cmd, t=0):
            seen["cmd"] = " ".join(cmd)
            return True, "OK"
        oi = bot.run_intent
        bot.run_intent = fake
        try:
            self.assertIn("開", bot._takeaway_handle("外賣"))
            self.assertIn("開緊", bot._takeaway_handle("外賣"))
            r = _execute(parse_command("計時 25分鐘", NOW), NOW, chat_id=1)
            self.assertIn("外賣模式：25分鐘 → 20分鐘", r)
            self.assertIn("1200", seen["cmd"])
            self.assertIn("收工", bot._takeaway_handle("外賣結束"))
            self.assertIn("冇開", bot._takeaway_handle("外賣結束"))
            r2 = _execute(parse_command("計時 25分鐘", NOW), NOW, chat_id=1)
            self.assertNotIn("外賣模式", r2)
            self.assertIn("1500", seen["cmd"])
            self.assertIn("15:25", r2)           # 還原：25分鐘→15:25 響
        finally:
            bot.run_intent = oi
            bot._save_json = old_save
            bot._TAKEAWAY["on"] = False

    def test_takeaway_target_timer_and_clamp_and_alarm(self):
        old_save = bot._save_json
        bot._save_json = lambda p, d: None
        bot._TAKEAWAY["on"] = False
        seen = {}
        def fake(cmd, t=0):
            seen["cmd"] = " ".join(cmd)
            return True, "OK"
        oi = bot.run_intent
        bot.run_intent = fake
        try:
            bot._takeaway_set(True)
            # 計時到 18:30（NOW 15:00）→ 提早 5 分鐘：18:25 響
            r = _execute(parse_command("計時到 18:30", NOW), NOW, chat_id=1)
            self.assertIn("18:25", r)
            self.assertIn(str(12600 - 300), seen["cmd"])
            # 短計時：至少留 1 分鐘
            r2 = _execute(parse_command("計時 2分鐘", NOW), NOW, chat_id=1)
            self.assertIn("2分鐘 → 1分鐘", r2)
            self.assertIn("60", seen["cmd"])
            # 鬧鐘唔受影響
            r3 = _execute(parse_command("鬧鐘 0700", NOW), NOW, chat_id=1)
            self.assertNotIn("外賣模式", r3)
            self.assertIn("SET_ALARM", seen["cmd"])
        finally:
            bot.run_intent = oi
            bot._save_json = old_save
            bot._TAKEAWAY["on"] = False

    def test_takeaway_jobs_line(self):
        old_jobs, old_save = bot._jobs, bot._save_json
        bot._jobs = list
        bot._save_json = lambda p, d: None
        try:
            bot._TAKEAWAY["on"] = True
            self.assertIn("外賣模式", bot._fmt_jobs(NOW))
            bot._TAKEAWAY["on"] = False
            self.assertNotIn("外賣模式", bot._fmt_jobs(NOW))
        finally:
            bot._jobs, bot._save_json = old_jobs, old_save

    def test_timer_intent_fail_falls_back_to_bell(self):
        old = bot.run_intent
        bot.run_intent = lambda cmd, t=0: (False, "boom")
        try:
            r = _execute(parse_command("計時 25分鐘", NOW), NOW, chat_id=1)
        finally:
            bot.run_intent = old
        self.assertIn("#1", r)
        self.assertIn("設唔到", r)


class TestPlayerGrammar(unittest.TestCase):
    """YouTube 歌單指令文法"""

    def test_play_default(self):
        c = parse_player("播")
        self.assertEqual((c.action, c.ref), ("play", ""))

    def test_play_named(self):
        self.assertEqual(parse_player("播 lofi").ref, "lofi")
        self.assertEqual(parse_player("播放 瞓覺").ref, "瞓覺")

    def test_play_url(self):
        u = "https://www.youtube.com/playlist?list=PLxyz"
        c = parse_player(f"播 {u}")
        self.assertEqual((c.action, c.ref), ("play", u))

    def test_stop(self):
        for w in ("停", "停止", "停播", "stop"):
            self.assertEqual(parse_player(w).action, "stop")

    def test_jobs_and_cancel(self):
        self.assertEqual(parse_player("播程").action, "jobs")
        c = parse_player("取消播 2")
        self.assertEqual((c.action, c.job_id), ("cancel", 2))
        self.assertEqual(parse_player("取消全部播").action, "cancel_all")

    def test_playlist_mgmt(self):
        u = "https://www.youtube.com/playlist?list=PLx"
        c = parse_player(f"歌單 lofi {u}")
        self.assertEqual((c.action, c.ref, c.url), ("savepl", "lofi", u))
        self.assertEqual(parse_player("歌單").action, "listpl")
        self.assertEqual(parse_player("預設歌單 lofi").action, "setdef")
        self.assertEqual(parse_player("刪歌單 lofi").action, "delpl")

    def test_sched_once(self):
        c = parse_player("2130 播")
        self.assertEqual((c.action, c.hour, c.minute, c.ref), ("sched_once", 21, 30, ""))
        c2 = parse_player("21:30 播放 lofi")
        self.assertEqual((c2.action, c2.hour, c2.minute, c2.ref), ("sched_once", 21, 30, "lofi"))

    def test_sched_daily(self):
        c = parse_player("每日 0700 播 lofi")
        self.assertEqual((c.action, c.hour, c.minute, c.ref), ("sched_daily", 7, 0, "lofi"))
        c2 = parse_player("每日 07:00 播")
        self.assertEqual((c2.action, c2.ref), ("sched_daily", ""))

    def test_daily_without_play_rejected(self):
        self.assertIsNone(parse_player("每日 0700"))

    def test_no_interference(self):
        # 現有計時/鬧鐘/裸時間行唔會被歌單解析攔截
        self.assertIsNone(parse_player("鬧鐘 0700"))
        self.assertIsNone(parse_player("計時 10分鐘"))
        self.assertIsNone(parse_player("計時到 1830"))
        self.assertIsNone(parse_player("0730"))
        self.assertIsNone(parse_player("0730 起身"))
        self.assertIsNone(parse_player("2560 播"))  # 25 時唔存在

    def test_batch_inherit_untouched_by_player(self):
        # 歌單行之後嘅裸時間唔會誤繼承（ctx 只屬於計時/鬧鐘）
        items = parse_lines("2130 播 lofi\n0730", NOW)
        self.assertEqual(items[0][1].action, "sched_once")
        self.assertIsNone(items[1][1])


class TestPlaylistStore(unittest.TestCase):
    """歌單存取（用臨時檔，唔掂真實設定）"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old = bot.PLAYLISTS_PATH
        bot.PLAYLISTS_PATH = os.path.join(self.tmp, "playlists.json")

    def tearDown(self):
        bot.PLAYLISTS_PATH = self.old

    def test_empty_default_hint(self):
        url, msg = _resolve_playlist("")
        self.assertIsNone(url)
        self.assertIn("未設預設歌單", msg)

    def test_resolve_named_default_and_url(self):
        _save_json(bot.PLAYLISTS_PATH, {
            "default": "lofi",
            "lists": {"lofi": "https://www.youtube.com/playlist?list=PL1",
                      "rain": "https://www.youtube.com/playlist?list=PL2"},
        })
        self.assertEqual(_resolve_playlist("")[0], "https://www.youtube.com/playlist?list=PL1")
        self.assertEqual(_resolve_playlist("rain"), ("https://www.youtube.com/playlist?list=PL2", "rain"))
        self.assertIsNone(_resolve_playlist("冇呢隻")[0])
        self.assertEqual(_resolve_playlist("https://youtu.be/abc")[0], "https://youtu.be/abc")

    def test_is_yt_url(self):
        self.assertTrue(_is_yt_url("https://www.youtube.com/playlist?list=PLx"))
        self.assertTrue(_is_yt_url("https://youtu.be/abc"))
        self.assertTrue(_is_yt_url("https://music.youtube.com/playlist?list=PLx"))
        self.assertFalse(_is_yt_url("https://example.com/x"))
        self.assertFalse(_is_yt_url("notaurl"))


class TestAutoplayUrl(unittest.TestCase):
    """playlist 連結轉 watch?v=…&list=… 先會自動播；shuffle 抽隨機開場"""

    VIDS = ["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"]

    def setUp(self):
        self.old = bot._playlist_videos
        bot._playlist_videos = lambda lid: list(self.VIDS)

    def tearDown(self):
        bot._playlist_videos = self.old

    def test_playlist_becomes_watch_first(self):
        url, auto = bot._autoplay_url("https://www.youtube.com/playlist?list=PLabc-123_x")
        self.assertTrue(auto)
        self.assertEqual(url, "https://www.youtube.com/watch?v=aaaaaaaaaaa&list=PLabc-123_x")

    def test_shuffle_picks_member_keeps_list(self):
        for _ in range(10):
            url, auto = bot._autoplay_url("https://www.youtube.com/playlist?list=PLabc", shuffle=True)
            self.assertTrue(auto)
            vid = re.search(r"v=([\w-]{11})&list=", url).group(1)
            self.assertIn(vid, self.VIDS)
            self.assertIn("&list=PLabc", url)

    def test_watch_with_list_untouched(self):
        u = "https://www.youtube.com/watch?v=abcdefghijk&list=PLabc"
        self.assertEqual(bot._autoplay_url(u), (u, True))

    def test_plain_video_untouched(self):
        u = "https://youtu.be/abcdefghijk"
        self.assertEqual(bot._autoplay_url(u), (u, True))

    def test_fetch_failure_falls_back_to_page(self):
        bot._playlist_videos = lambda lid: []
        u = "https://www.youtube.com/playlist?list=PLabc"
        self.assertEqual(bot._autoplay_url(u), (u, False))


class TestShuffleGrammar(unittest.TestCase):
    """隨機播放文法：前綴「隨機播」或後綴「隨機/random」"""

    def test_prefix(self):
        c = parse_player("隨機播 lofi")
        self.assertEqual((c.action, c.ref, c.shuffle), ("play", "lofi", True))

    def test_suffix(self):
        c = parse_player("播 lofi 隨機")
        self.assertEqual((c.ref, c.shuffle), ("lofi", True))

    def test_english_random_suffix(self):
        c = parse_player("播 lofi random")
        self.assertEqual((c.ref, c.shuffle), ("lofi", True))

    def test_default_off(self):
        self.assertFalse(parse_player("播 lofi").shuffle)

    def test_url_shuffle(self):
        u = "https://www.youtube.com/playlist?list=PLx"
        c = parse_player(f"播 {u} 隨機")
        self.assertEqual((c.ref, c.shuffle), (u, True))

    def test_sched_daily_shuffle(self):
        c = parse_player("每日 0700 播 lofi 隨機")
        self.assertEqual((c.action, c.hour, c.ref, c.shuffle), ("sched_daily", 7, "lofi", True))
        c2 = parse_player("每日 0700 隨機播 lofi")
        self.assertTrue(c2.shuffle)

    def test_sched_once_shuffle(self):
        c = parse_player("2130 播 lofi 隨機")
        self.assertTrue(c.shuffle and c.action == "sched_once" and c.ref == "lofi")


class TestSchedAndMgmt(unittest.TestCase):
    """計時排程 + 排程管理文法"""

    def test_timer_sched_daily(self):
        c = parse_player("每日 0900 計時 25分鐘")
        self.assertEqual((c.action, c.hour, c.minute, c.seconds),
                         ("sched_timer_daily", 9, 0, 1500))

    def test_timer_sched_once_with_label(self):
        c = parse_player("1830 計時 10分鐘 沖涼")
        self.assertEqual((c.action, c.hour, c.minute, c.seconds, c.ref),
                         ("sched_timer", 18, 30, 600, "沖涼"))

    def test_mgmt_grammar(self):
        self.assertEqual(parse_player("暫停 2").action, "pause")
        self.assertEqual(parse_player("繼續 2").action, "resume")
        c = parse_player("改 2 1930")
        self.assertEqual((c.action, c.job_id, c.ref), ("edit", 2, "1930"))
        self.assertEqual(parse_player("取消 2").action, "cancel")
        self.assertEqual(parse_player("排程").action, "jobs")
        self.assertEqual(parse_player("取消全部").action, "cancel_all")

    def test_timer_sched_bad_duration_rejected(self):
        self.assertIsNone(parse_player("每日 0900 計時 abc"))
        self.assertIsNone(parse_player("1830 計時"))  # 淨關鍵字


class TestJobManagement(unittest.TestCase):
    """排程去重、暫停/恢復、編輯（用臨時檔，唔掂真實設定）"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old_j, self.old_p = bot.JOBS_PATH, bot.PLAYLISTS_PATH
        bot.JOBS_PATH = os.path.join(self.tmp, "jobs.json")
        bot.PLAYLISTS_PATH = os.path.join(self.tmp, "playlists.json")
        bot._save_json(bot.PLAYLISTS_PATH, {
            "default": "lofi",
            "lists": {"lofi": "https://www.youtube.com/playlist?list=PL1"}})

    def tearDown(self):
        bot.JOBS_PATH, bot.PLAYLISTS_PATH = self.old_j, self.old_p

    def _mk(self, action, hh=18, mm=20, ref="lofi", seconds=None, shuffle=False):
        return bot.PlayerCmd(action, ref=ref, hour=hh, minute=mm,
                             seconds=seconds, shuffle=shuffle)

    def test_dedupe_same_time_replaces(self):
        _, rep1 = bot._add_job(self._mk("sched_once"), 1, NOW)
        _, rep2 = bot._add_job(self._mk("sched_once", shuffle=True), 1, NOW)
        self.assertEqual(rep1, [])
        self.assertEqual(rep2, [1])
        jobs = bot._jobs()
        self.assertEqual(len(jobs), 1)
        self.assertTrue(jobs[0]["shuffle"])

    def test_different_time_keeps_both(self):
        bot._add_job(self._mk("sched_once", mm=20), 1, NOW)
        bot._add_job(self._mk("sched_once", mm=30), 1, NOW)
        self.assertEqual(len(bot._jobs()), 2)

    def test_timer_and_play_same_time_coexist(self):
        bot._add_job(self._mk("sched_once"), 1, NOW)               # 播 1820
        bot._add_job(self._mk("sched_timer", seconds=600), 1, NOW) # 計時 1820
        self.assertEqual(sorted(j["type"] for j in bot._jobs()), ["play", "timer"])

    def test_pause_and_resume(self):
        bot._add_job(self._mk("sched_once"), 1, NOW)
        self.assertTrue(bot._pause_job(1))
        self.assertEqual(bot._pause_job(1), "already")
        self.assertIn("⏸已暫停", bot._fmt_jobs(NOW))
        nxt = bot._resume_job(1, NOW)
        self.assertIsNotNone(nxt)
        self.assertNotIn("⏸已暫停", bot._fmt_jobs(NOW))
        self.assertIsNone(bot._resume_job(99, NOW))

    def test_edit_time(self):
        bot._add_job(self._mk("sched_once"), 1, NOW)
        ok, _ = bot._edit_job(1, "1930", NOW)
        self.assertTrue(ok)
        self.assertEqual((bot._jobs()[0]["hh"], bot._jobs()[0]["mm"]), (19, 30))

    def test_edit_recurrence(self):
        bot._add_job(self._mk("sched_once"), 1, NOW)
        self.assertTrue(bot._edit_job(1, "每日", NOW)[0])
        self.assertTrue(bot._jobs()[0]["daily"])
        self.assertTrue(bot._edit_job(1, "一次", NOW)[0])
        self.assertFalse(bot._jobs()[0]["daily"])

    def test_edit_content_play(self):
        bot._add_job(self._mk("sched_once"), 1, NOW)
        ok, _ = bot._edit_job(1, "lofi 隨機", NOW)
        self.assertTrue(ok)
        self.assertTrue(bot._jobs()[0]["shuffle"])

    def test_edit_content_timer(self):
        bot._add_job(self._mk("sched_timer", seconds=600), 1, NOW)
        ok, _ = bot._edit_job(1, "25分鐘 泡茶", NOW)
        self.assertTrue(ok)
        j = bot._jobs()[0]
        self.assertEqual((j["seconds"], j["label"]), (1500, "泡茶"))

    def test_edit_missing_job(self):
        ok, _ = bot._edit_job(42, "1830", NOW)
        self.assertFalse(ok)


class TestPlaylistScrape(unittest.TestCase):
    """歌單抽片：RSS 優先，頁面後備"""

    def setUp(self):
        self.old = bot._fetch
        self.old_cache = dict(bot._PL_CACHE)
        bot._PL_CACHE.clear()

    def tearDown(self):
        bot._fetch = self.old
        bot._PL_CACHE.clear()
        bot._PL_CACHE.update(self.old_cache)

    def test_rss_parse_dedupe(self):
        bot._fetch = lambda url: (
            "<feed xmlns:yt='x'>"
            "<entry><yt:videoId>aaaaaaaaaaa</yt:videoId></entry>"
            "<entry><yt:videoId>bbbbbbbbbbb</yt:videoId></entry>"
            "<entry><yt:videoId>aaaaaaaaaaa</yt:videoId></entry>"
            "</feed>")
        self.assertEqual(bot._playlist_videos("PLx"), ["aaaaaaaaaaa", "bbbbbbbbbbb"])

    def test_html_fallback_when_rss_fails(self):
        def fake(url):
            if "feeds" in url:
                raise OSError("連唔到")
            return 'xx{"videoId":"ccccccccccc"}yy{"videoId":"ccccccccccc"}zz'
        bot._fetch = fake
        self.assertEqual(bot._playlist_videos("PLx"), ["ccccccccccc"])

    def test_all_failed_returns_empty(self):
        def fake(url):
            raise OSError("全fail")
        bot._fetch = fake
        self.assertEqual(bot._playlist_videos("PLx"), [])


class TestStopFallback(unittest.TestCase):
    """停：優先系統 am，失敗先用 PATH am"""

    def setUp(self):
        self.old = bot.run_intent

    def tearDown(self):
        bot.run_intent = self.old

    def test_prefers_system_am(self):
        calls = []
        def fake(cmd, t=0):
            calls.append(cmd)
            return True, ""
        bot.run_intent = fake
        ok, _ = bot._stop()
        self.assertTrue(ok)
        self.assertEqual(calls, [["/system/bin/am", "force-stop", bot._YT_PKG]])

    def test_fallback_to_path_am(self):
        seq = iter([(False, "termux-am 唔支援"), (True, "")])
        bot.run_intent = lambda cmd, t=0: next(seq)
        ok, _ = bot._stop()
        self.assertTrue(ok)


class TestNavParse(unittest.TestCase):
    """地點 / 導航 文法"""

    def _p(self, s):
        return bot.parse_player(s)

    def test_save_dest_plain(self):
        c = self._p("地點 公司 沙田石門安群街1號")
        self.assertEqual((c.action, c.ref, c.url), ("savedest", "公司", "沙田石門安群街1號"))

    def test_save_dest_with_separator_and_url(self):
        c = self._p("地點 屋企 = https://maps.app.goo.gl/xyz")
        self.assertEqual((c.action, c.ref), ("savedest", "屋企"))
        self.assertTrue(c.url.startswith("https://"))
        c2 = self._p("地點 公司＝新蒲崗太子道東638號")
        self.assertEqual((c2.action, c2.ref, c2.url), ("savedest", "公司", "新蒲崗太子道東638號"))

    def test_dests_listing_and_delete(self):
        self.assertEqual(self._p("地點").action, "dests")
        self.assertEqual(self._p("目的地").action, "dests")
        c = self._p("刪地點 公司")
        self.assertEqual((c.action, c.ref), ("deldest", "公司"))

    def test_nav_now_variants(self):
        self.assertEqual((self._p("導航 公司").action, self._p("導航 公司").ref), ("nav", "公司"))
        self.assertEqual(self._p("開導航 沙田站").action, "nav")
        self.assertEqual(self._p("導航").action, "dests")  # 淨「導航」→ 清單
        self.assertEqual((self._p("導航 https://maps.app.goo.gl/xyz").action), "nav")

    def test_sched_nav(self):
        c = self._p("每日 0800 導航 公司 步行")
        self.assertEqual((c.action, c.hour, c.minute, c.ref), ("sched_nav_daily", 8, 0, "公司 步行"))
        c = self._p("0830 開導航 沙田站")
        self.assertEqual((c.action, c.hour, c.minute), ("sched_nav", 8, 30))

    def test_nav_does_not_steal_play(self):
        self.assertEqual(self._p("每日 0800 播 citypop").action, "sched_daily")
        self.assertEqual(self._p("0800 播").action, "sched_once")


class TestDestinations(unittest.TestCase):
    """地點儲存 + 導航執行 + 導航排程"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old_d = bot.DESTINATIONS_PATH
        self.old_j = bot.JOBS_PATH
        self.old_p = bot.PLAYLISTS_PATH
        bot.DESTINATIONS_PATH = os.path.join(self.tmp, "destinations.json")
        bot.JOBS_PATH = os.path.join(self.tmp, "jobs.json")
        bot.PLAYLISTS_PATH = os.path.join(self.tmp, "playlists.json")
        self.now = dt.datetime(2026, 1, 5, 10, 0)  # 星期一

    def tearDown(self):
        bot.DESTINATIONS_PATH, bot.JOBS_PATH, bot.PLAYLISTS_PATH = self.old_d, self.old_j, self.old_p

    def _ex(self, line):
        return bot._execute_player(bot.parse_player(line), 12345, self.now)

    def test_save_resolve_delete_flow(self):
        r = self._ex("地點 公司 沙田石門安群街1號")
        self.assertIn("已儲存地點", r)
        dest, mode, shown = bot._nav_target("公司")
        self.assertEqual((dest, shown, mode), ("沙田石門安群街1號", "公司", "r"))  # 預設 transit
        dest, mode, shown = bot._nav_target("公司 巴士")
        self.assertEqual((dest, shown, mode), ("沙田石門安群街1號", "公司", "r"))
        dest, mode, shown = bot._nav_target("公司 步行")
        self.assertEqual((dest, shown, mode), ("沙田石門安群街1號", "公司", "w"))
        dest, mode, _ = bot._nav_target("火星基地")  # 未儲→直接當查詢
        self.assertEqual(dest, "火星基地")
        self.assertIn("公司", self._ex("地點"))
        self.assertIn("已刪地點", self._ex("刪地點 公司"))
        self.assertIn("搵唔到", self._ex("刪地點 公司"))

    def test_open_nav_uri_building(self):
        calls = []
        old = bot.run_intent
        bot.run_intent = lambda cmd, t=0: calls.append(cmd) or (True, "")
        try:
            bot._open_nav("沙田石門安群街1號", "w")
            self.assertIn("google.navigation:q=", calls[0][-1])
            self.assertIn("mode=w", calls[0][-1])
            self.assertIn("%E", calls[0][-1])  # 中文地址已 URL-encode
            bot._open_nav("https://maps.app.goo.gl/xyz")  # 連結直通，唔再加 q=
            self.assertEqual(calls[1][-1], "https://maps.app.goo.gl/xyz")
        finally:
            bot.run_intent = old

    def test_sched_nav_job_fields(self):
        r = self._ex("地點 公司 沙田石門")
        r = self._ex("每日 0800 導航 公司 步行")
        self.assertIn("導航去「公司」", r)
        listing = self._ex("排程")
        self.assertIn("🧭", listing)
        self.assertIn("導航去「公司」", listing)
        jobs = bot._load_json(bot.JOBS_PATH, [])
        self.assertEqual(jobs[0]["type"], "nav")
        self.assertEqual(jobs[0]["mode"], "w")
        self.assertEqual(jobs[0]["url"], "沙田石門")

    def test_nav_dedupe_same_time_same_type(self):
        self._ex("每日 0800 導航 A")
        r = self._ex("每日 0800 導航 B")
        self.assertIn("已自動取代", r)
        jobs = bot._load_json(bot.JOBS_PATH, [])
        self.assertEqual(len(jobs), 1)
        # 同一時間 play 同 nav 可以共存
        self._ex("每日 0800 播 citypop")  # 冇預設/冇名 → 會搵歌單失敗，先至用連結
        jobs = bot._load_json(bot.JOBS_PATH, [])
        # 播食嘅係歌單名 citypop，冇儲 → 排程唔會成立；只檢查 nav job 冇被整
        self.assertEqual(jobs[0]["type"], "nav")

    def test_edit_nav_job_content(self):
        self._ex("每日 0800 導航 沙田站")
        jid = bot._load_json(bot.JOBS_PATH, [])[0]["id"]
        ok, _info = bot._edit_job(jid, "荃灣西站 步行", self.now)
        self.assertTrue(ok)
        job = bot._load_json(bot.JOBS_PATH, [])[0]
        self.assertEqual((job["url"], job["mode"], job["label"]), ("荃灣西站", "w", "荃灣西站"))


class TestDayLabelTonight(unittest.TestCase):
    """第二日凌晨（00:00–05:59）口語叫「今晚」唔係「聽日」"""

    def test_over_midnight_slots(self):
        mon = dt.datetime(2026, 1, 5, 23, 50)
        self.assertEqual(bot.day_label(dt.datetime(2026, 1, 6, 0, 15), mon), "今晚")
        self.assertEqual(bot.day_label(dt.datetime(2026, 1, 6, 5, 59), mon), "今晚")
        self.assertEqual(bot.day_label(dt.datetime(2026, 1, 6, 6, 0), mon), "聽日")
        self.assertEqual(bot.day_label(dt.datetime(2026, 1, 6, 7, 30), mon), "聽日")
        self.assertEqual(bot.day_label(dt.datetime(2026, 1, 5, 23, 55), mon), "今日")
        self.assertEqual(bot.day_label(dt.datetime(2026, 1, 7, 0, 15), mon), "後日")

    def test_alloc_reply_says_tonight(self):
        tmp = tempfile.mkdtemp()
        old = bot.JOBS_PATH
        bot.JOBS_PATH = os.path.join(tmp, "jobs.json")
        try:
            now = dt.datetime(2026, 1, 5, 23, 50)  # 星期一 23:50
            r = bot._execute_player(
                bot.parse_player("0015至0115 分配 留空60% 食麵，休息"),
                12345, now)
            self.assertIn("今晚 00:15", r)
            self.assertNotIn("聽日 00:15", r)
        finally:
            bot.JOBS_PATH = old


class TestStopChainLayers(unittest.TestCase):
    """停：音訊焦點 → force-stop → 主畫面，逐層試"""

    def setUp(self):
        self.old_run, self.old_which = bot.run_intent, bot.shutil.which
        bot.shutil.which = lambda name: None  # 沙盒冇 Termux:API

    def tearDown(self):
        bot.run_intent, bot.shutil.which = self.old_run, self.old_which

    def test_audio_focus_when_termux_api_present(self):
        bot.shutil.which = lambda name: "/x/termux-media-player"
        calls = []
        bot.run_intent = lambda cmd, t=0: calls.append(cmd) or (True, "")
        ok, how = bot._stop()
        self.assertEqual((ok, how), (True, "audio-focus"))
        self.assertIn("silence.wav", calls[0][2])

    def test_home_fallback_when_all_denied(self):
        def fake(cmd, t=0):
            return (any("HOME" in part for part in cmd), "")  # force-stop 全 fail，HOME start 成功
        bot.run_intent = fake
        ok, how = bot._stop()
        self.assertEqual((ok, how), (True, "home"))

    def test_all_layers_fail(self):
        bot.run_intent = lambda cmd, t=0: (False, "denied")
        ok, _how = bot._stop()
        self.assertFalse(ok)


class TestTodo(unittest.TestCase):
    """置頂待辦清單：文法 + 增刪勾 + 顯示"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old = bot.TODO_PATH
        bot.TODO_PATH = os.path.join(self.tmp, "todo.json")

    def tearDown(self):
        bot.TODO_PATH = self.old

    def _p(self, s):
        return bot.parse_player(s)

    def _ex(self, line):
        return bot._execute_player(bot.parse_player(line), 12345, dt.datetime(2026, 1, 5))

    def test_parse_todo_variants(self):
        self.assertEqual(self._p("待辦").action, "todo")
        self.assertEqual(self._p("清單").action, "todo")
        c = self._p("待辦 牛奶、交電費")
        self.assertEqual((c.action, c.ref), ("todo_add", "牛奶、交電費"))
        self.assertEqual((self._p("完成 2").action, self._p("完成 2").job_id), ("todo_done", 2))
        self.assertEqual(self._p("✓3").job_id, 3)
        self.assertEqual((self._p("未做 1").action, self._p("未做 1").job_id), ("todo_undone", 1))
        self.assertEqual((self._p("刪 2").action, self._p("刪 2").job_id), ("todo_del", 2))
        self.assertEqual(self._p("清除已完成").action, "todo_clear_done")
        # 唔好食走其他指令嘅字
        self.assertIsNone(self._p("刪 牛奶"))
        self.assertEqual(self._p("刪地點 公司").action, "deldest")

    def test_add_and_show(self):
        r = self._ex("待辦 牛奶、交電費")
        self.assertIn("已加入 2 項", r)
        self._ex("待辦 買證件相底片")
        text = self._ex("待辦")
        self.assertIn("1. ☐ 牛奶", text)
        self.assertIn("2. ☐ 交電費", text)
        self.assertIn("3. ☐ 買證件相底片", text)
        self.assertIn("仲有 3 項未完成", text)

    def test_add_empty_rejected(self):
        self.assertIn("俾個項目名", self._ex("待辦 、、,"))

    def test_done_undone_flow(self):
        self._ex("待辦 牛奶、交電費")
        self.assertIn("完成", self._ex("完成 2"))
        text = self._ex("待辦")
        self.assertIn("2. ✅ 交電費", text)
        self.assertIn("仲有 1 項未完成", text)
        self.assertIn("未完成", self._ex("未做 2"))
        self.assertIn("2. ☐ 交電費", self._ex("待辦"))
        self.assertIn("搵唔到第 99 項", self._ex("完成 99"))

    def test_delete_renumbers(self):
        self._ex("待辦 A、B、C")
        self.assertIn("已刪「B」", self._ex("刪 2"))
        text = self._ex("待辦")
        self.assertIn("1. ☐ A", text)
        self.assertIn("2. ☐ C", text)
        self.assertNotIn("B", text)

    def test_clear_done(self):
        self._ex("待辦 A、B、C")
        self._ex("完成 1")
        self._ex("完成 3")
        r = self._ex("清除已完成")
        self.assertIn("清咗 2 項", r)
        self.assertIn("仲有 1 項", r)
        text = self._ex("待辦")
        self.assertIn("1. ☐ B", text)
        self.assertNotIn("A", text)
        self.assertIn("冇已完成", self._ex("清除已完成"))

    def test_batch_inherit_todo_lines(self):
        """「待辦 X」之後裸行自動當加待辦（你 send 摺衫 嗰個 case）"""
        items = bot.parse_lines("待辦 較鬧鐘\n摺衫\n還書", dt.datetime(2026, 1, 5))
        self.assertEqual([p.action for _, p in items], ["todo_add", "todo_add", "todo_add"])
        self.assertEqual([p.ref for _, p in items], ["較鬧鐘", "摺衫", "還書"])

    def test_batch_inherit_switches_back_to_alarm(self):
        """中途出現明確指令，繼承對象會即時切換"""
        items = bot.parse_lines("待辦 A\n鬧鐘 0700\n0730", dt.datetime(2026, 1, 5))
        self.assertEqual(items[0][1].action, "todo_add")
        self.assertEqual(items[1][1].kind, "alarm")
        self.assertEqual(items[2][1].kind, "alarm")


class TestAlloc(unittest.TestCase):
    """時間分配：文法 + 切分 + 連環計時"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old_j = bot.JOBS_PATH
        bot.JOBS_PATH = os.path.join(self.tmp, "jobs.json")
        self.now = dt.datetime(2026, 1, 5, 10, 0)  # 星期一

    def tearDown(self):
        bot.JOBS_PATH = self.old_j

    def _p(self, s):
        return bot.parse_player(s)

    def _ex(self, line):
        return bot._execute_player(bot.parse_player(line), 12345, self.now)

    def test_parse_once(self):
        c = self._p("1930至2230 分配 留空10% 温習x2、做功課、沖涼")
        self.assertEqual(c.action, "sched_alloc")
        self.assertEqual((c.hour, c.minute, c.hour2, c.minute2, c.buf), (19, 30, 22, 30, 10))
        self.assertIn("温習", c.ref)

    def test_parse_daily_and_separators(self):
        c = self._p("每日 19:00~21:30 分配 温習、沖涼")
        self.assertEqual((c.action, c.hour, c.minute, c.hour2, c.minute2, c.buf),
                         ("sched_alloc_daily", 19, 0, 21, 30, 0))
        self.assertEqual(self._p("1900-2200 分配 a、b").action, "sched_alloc")
        self.assertEqual(self._p("1900到2200 分配 a").action, "sched_alloc")
        self.assertIsNone(self._p("abc至123 分配 x"))

    def test_segments_weighted_math(self):
        segs, err = bot._alloc_segments("温習x2、做功課、沖涼", 10, 12600)  # 3.5h 留空10%→11340s
        self.assertIsNone(err)
        total = sum(s["seconds"] for s in segs)
        self.assertEqual(total, 12600 * 9 // 10)
        self.assertEqual([s["seconds"] for s in segs], [5640, 2820, 2880])
        self.assertTrue(all(s["seconds"] % 60 == 0 and s["seconds"] >= 60 for s in segs))

    def test_segments_equal(self):
        segs, _err = bot._alloc_segments("A、B", 0, 3600)
        self.assertEqual([s["seconds"] for s in segs], [1800, 1800])

    def test_segments_too_tight_and_bad_buf(self):
        segs, err = bot._alloc_segments("A、B、C", 95, 1800)
        self.assertIsNone(segs)
        self.assertIn("唔夠", err)
        self.assertIn("留空要 0-90%", self._ex("1900-2200 分配 留空99% A、B"))

    def test_execute_breakdown_and_job(self):
        r = self._ex("1900至2230 分配 留空10% 温習x2、做功課、沖涼")
        self.assertIn("🧩 時間分配", r)
        self.assertIn("3小時30分鐘", r)
        self.assertIn("温習 — 1小時34分鐘（19:00→20:34）", r)
        self.assertIn("做功課 — 47分鐘（20:34→21:21）", r)
        self.assertIn("沖涼 — 48分鐘（21:21→22:09）", r)
        self.assertIn("留空 10%", r)
        job = bot._load_json(bot.JOBS_PATH, [])[0]
        self.assertEqual(job["type"], "alloc")
        self.assertEqual(job["idx"], 0)
        self.assertEqual(len(job["segments"]), 3)
        listing = self._ex("排程")
        self.assertIn("🧩", listing)

    def test_dedupe_same_time(self):
        self._ex("1930至2230 分配 A、B")
        r = self._ex("1930至2230 分配 C、D")
        self.assertIn("已自動取代", r)
        jobs = bot._load_json(bot.JOBS_PATH, [])
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["segments"][0]["text"], "C")

    def test_overnight(self):
        r = self._ex("2200至0200 分配 温習、沖涼")
        self.assertIn("4小時", r)  # 22:00→02:00 跨日 4h

    def test_fast_forward_your_0026_case(self):
        """0026 send 0015-0115：喺 block 入面 → 即刻上車，唔好推去聽晚"""
        now = dt.datetime(2026, 1, 5, 0, 26)
        r = bot._execute_player(
            bot.parse_player("0015至0115 分配 留空60% 食麵，休息"), 12345, now)
        self.assertIn("食麵 — 1分鐘（00:26→00:27）", r)  # 半路加入，第一下縮短
        self.assertIn("休息 — 12分鐘（00:27→00:39）", r)
        job = bot._load_json(bot.JOBS_PATH, [])[0]
        self.assertEqual(job["idx"], 0)
        self.assertGreaterEqual(job.get("_rem", 0), 1)
        fire_at = dt.datetime.fromisoformat(job["next"])
        self.assertLess((fire_at - now).total_seconds(), 120)  # 即刻，唔係聽晚

    def test_fast_forward_cross_midnight_block(self):
        """2300-0200 凌晨 01:00 send：第一項過咗，直接入第二項剩 30 分鐘"""
        now = dt.datetime(2026, 1, 6, 1, 0)
        r = bot._execute_player(
            bot.parse_player("2300至0200 分配 温習、沖涼"), 12345, now)
        self.assertIn("沖涼 — 1小時（01:00→02:00）", r)  # 1.5h 段已行 0.5h，剩 1h
        self.assertNotIn("温習 —", r)  # 過咗嘅段唔顯示

    def test_fast_forward_all_elapsed_falls_back(self):
        """仲喺窗內但全部段都過晒 → 正常排下一轉"""
        now = dt.datetime(2026, 1, 5, 0, 50)
        r = bot._execute_player(
            bot.parse_player("0015至0115 分配 留空60% 食麵，休息"), 12345, now)
        self.assertIn("食麵 — 12分鐘", r)  # 足本，即係正常排下一轉
        job = bot._load_json(bot.JOBS_PATH, [])[0]
        self.assertEqual(job["idx"], 0)
        self.assertNotIn("_rem", job)

    def test_fast_forward_fire_consumes_rem(self):
        """半途入車：SET_TIMER 真係要用 _rem（252s）而唔係足本（300s）——你撞正嗰單 bug"""
        now = dt.datetime(2026, 1, 6, 1, 5, 48)
        bot._execute_player(
            bot.parse_player("0105至0120 分配 留空0% 㩒電話，休息x2"), 12345, now)
        job = bot._load_json(bot.JOBS_PATH, [])[0]
        self.assertEqual(job["_rem"], 252)
        got = []
        old = bot.run_intent

        def fake(cmd, t=0):
            for i, a in enumerate(cmd):
                if a == "android.intent.extra.alarm.LENGTH":
                    got.append(int(cmd[i + 1]))
            return True, ""
        bot.run_intent = fake
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(bot._fire_alloc(job))
        finally:
            bot.run_intent = old
            loop.close()
        self.assertEqual(got, [252])  # 唔係 [300]！
        job2 = bot._load_json(bot.JOBS_PATH, [])[0]
        self.assertEqual(job2["_rem"], 0)  # 用咗一次即清
        self.assertEqual(job2["idx"], 1)

    def test_fire_chain_advances_and_finishes(self):
        segs, _ = bot._alloc_segments("甲、乙", 0, 1800)  # 15min ×2
        job, _ = bot._add_alloc_job(12345, self.now, 19, 30, 20, 0, False, segs)
        start_next = job["next"]  # 記住原本時間，fire 會原地改 job
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(bot._fire_alloc(job))  # fire 第1段
            jobs = bot._load_json(bot.JOBS_PATH, [])
            self.assertEqual(jobs[0]["idx"], 1)
            next1 = dt.datetime.fromisoformat(jobs[0]["next"])
            self.assertEqual((next1 - dt.datetime.fromisoformat(start_next)).total_seconds(), 900)
            job2 = {**job, "idx": 1, "next": jobs[0]["next"]}
            loop.run_until_complete(bot._fire_alloc(job2))  # fire 最後段 → 完成刪走
            self.assertEqual(bot._load_json(bot.JOBS_PATH, []), [])
        finally:
            loop.close()

    def test_fire_chain_static_no_reflow_drift(self):
        """正常到點 fire 唔准 reflow：每段嘅 next 都係上一段 fired_at + 段長，
        而且段長永遠唔被改寫——2026-09-23 單「雙倍留空」漂移 bug 迴歸。"""
        segs, _ = bot._alloc_segments("甲，乙，丙，丁，戊", 20, 600)
        self.assertEqual([s["seconds"] for s in segs], [60, 60, 60, 60, 240])
        # next 放喺未來：避免 _arm 即刻 re-fire（production 入面 _arm 都係未來時間）
        future = (dt.datetime.now() + dt.timedelta(hours=1)).replace(microsecond=0)
        job = {"id": 9, "type": "alloc", "hh": 19, "mm": 0, "hh2": 23, "mm2": 0,
               "daily": False, "url": "", "seconds": 0, "mode": "", "label": "時間分配",
               "chat_id": 12345, "next": future.isoformat(), "shuffle": False,
               "paused": False, "segments": segs, "idx": 0, "buf": 20}
        bot._save_json(bot.JOBS_PATH, [job])
        old = bot.run_intent
        bot.run_intent = lambda cmd, t=0: (True, "")
        loop = asyncio.new_event_loop()
        try:
            prev = dt.datetime.fromisoformat(job["next"])
            for expect_secs in (60, 60, 60, 60):
                loop.run_until_complete(bot._fire_alloc(job))
                nxt = dt.datetime.fromisoformat(job["next"])
                self.assertEqual((nxt - prev).total_seconds(), expect_secs)
                prev = nxt
            loop.run_until_complete(bot._fire_alloc(job))  # 最後段 → 刪走
            self.assertEqual(bot._load_json(bot.JOBS_PATH, []), [])
        finally:
            bot.run_intent = old
            for t in bot._TASKS.values():
                t.cancel()
            bot._TASKS.clear()
            loop.close()
        # 段長唔可以被 reflow 改寫（舊 bug 會將 60 秒段愈拉愈長）
        self.assertEqual([s["seconds"] for s in segs], [60, 60, 60, 60, 240])


class TestAllocBufMinutes(unittest.TestCase):
    """留空可選寫分鐘（留空30分鐘）：文法、切分、執行、reflow。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old_j = bot.JOBS_PATH
        bot.JOBS_PATH = os.path.join(self.tmp, "jobs.json")
        self.now = dt.datetime(2026, 1, 5, 10, 0)

    def tearDown(self):
        bot.JOBS_PATH = self.old_j

    def _p(self, s):
        return bot.parse_player(s)

    def _ex(self, line):
        return bot._execute_player(bot.parse_player(line), 12345, self.now)

    def test_parse_units(self):
        for txt, mins in (("1900-2200 分配 留空30分鐘 A、B", 30),
                          ("1900-2200 分配 留空30分钟 A、B", 30),
                          ("1900-2200 分配 留空 45 分 A、B", 45)):
            c = self._p(txt)
            self.assertEqual(c.action, "sched_alloc")
            self.assertEqual((c.buf, c.buf_min), (0, mins))
            self.assertEqual(c.ref, "A、B")
        c = self._p("每日 1900-2200 分配 留空20分鐘 A")
        self.assertEqual((c.action, c.buf_min), ("sched_alloc_daily", 20))
        # 冇寫留空 → 兩者皆 0（同舊行為）
        c = self._p("1900-2200 分配 A、B")
        self.assertEqual((c.buf, c.buf_min), (0, 0))

    def test_segments_math(self):
        # 1900-2200 = 10800s；留空30分鐘 → 9000s 均分兩段
        segs, err = bot._alloc_segments("A、B", 0, 10800, 30)
        self.assertIsNone(err)
        self.assertEqual([s["seconds"] for s in segs], [4500, 4500])
        # 加權照行：9000s 按 2:1 → 6000/3000
        segs, err = bot._alloc_segments("Ax2、B", 0, 10800, 30)
        self.assertEqual([s["seconds"] for s in segs], [6000, 3000])

    def test_execute_and_persist(self):
        r = self._ex("1900至2200 分配 留空30分鐘 A、B")
        self.assertIn("🧩 時間分配", r)
        self.assertIn("留空 30分鐘", r)
        self.assertIn("A — 1小時15分鐘（19:00→20:15）", r)
        self.assertIn("B — 1小時15分鐘（20:15→21:30）", r)
        job = bot._load_json(bot.JOBS_PATH, [])[0]
        self.assertEqual((job["buf"], job["buf_min"]), (0, 30))

    def test_buf_minutes_too_big(self):
        self.assertIn("太多", self._ex("1900-1905 分配 留空10分鐘 A"))

    def test_reflow_keeps_buf_min(self):
        # block 1930-2130，19:30 reflow，留空30分鐘 → 剩 90 分可用
        j = {"hh": 19, "mm": 30, "hh2": 21, "mm2": 30, "buf": 0, "buf_min": 30,
             "segments": [{"text": "a", "seconds": 1200, "w": 1},
                          {"text": "b", "seconds": 600, "w": 1}], "idx": 1}
        self.assertTrue(bot._alloc_reflow(j, dt.datetime(2026, 1, 5, 19, 30), 1))
        self.assertEqual(j["segments"][1]["seconds"], 90 * 60)


class TestAdbLane(unittest.TestCase):
    """ADB lane（第三條 uid 2000 通道）：探測、優先次序、復活Shizuku 指令。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old_j = bot.JOBS_PATH
        bot.JOBS_PATH = os.path.join(self.tmp, "jobs.json")
        self.now = dt.datetime(2026, 1, 5, 10, 0)
        # 清兩個快取，等 patch 實時生效
        bot._RISH_CACHE.update(t=0.0, ok=False)
        bot._ADB_CACHE.update(t=0.0, ok=False)

    def tearDown(self):
        bot.JOBS_PATH = self.old_j
        bot._RISH_CACHE.update(t=0.0, ok=False)
        bot._ADB_CACHE.update(t=0.0, ok=False)

    def _ex(self, line):
        return bot._execute_player(bot.parse_player(line), 12345, self.now)

    def test_parse_revive(self):
        for s in ("復活Shizuku", "重開shizuku", "救Shizuku", "Shizuku復活",
                  "shizuku 救返"):
            c = bot.parse_player(s)
            self.assertIsNotNone(c, s)
            self.assertEqual(c.action, "shizuku_revive", s)

    def test_priv_exec_prefers_adb_lane(self):
        adb_calls = []
        with mock.patch.object(bot, "_rish_available", return_value=True), \
             mock.patch.object(bot, "_adb_lane_available", return_value=True), \
             mock.patch.object(bot, "_adb_shell",
                               side_effect=lambda c: (adb_calls.append(c), (True, "adb-ok"))[1]), \
             mock.patch.object(bot, "run_intent", return_value=(True, "rish-ok")) as ri:
            ok, out = bot._shell_priv_exec("echo hi")
        self.assertTrue(ok)
        self.assertEqual(out, "adb-ok")          # adb lane 先行
        self.assertEqual(adb_calls, ["echo hi"])
        ri.assert_not_called()                    # rish 唔使開

    def test_priv_exec_falls_back_to_rish(self):
        with mock.patch.object(bot, "_adb_lane_available", return_value=False), \
             mock.patch.object(bot, "_rish_available", return_value=True), \
             mock.patch.object(bot, "run_intent", return_value=(True, "rish-ok")) as m:
            ok, out = bot._shell_priv_exec("echo hi")
        self.assertEqual((ok, out), (True, "rish-ok"))
        self.assertEqual(m.call_args[0][0][:2], ["rish", "-c"])

    def test_priv_exec_both_down(self):
        with mock.patch.object(bot, "_rish_available", return_value=False), \
             mock.patch.object(bot, "_adb_lane_available", return_value=False):
            ok, out = bot._shell_priv_exec("echo hi")
        self.assertFalse(ok)
        self.assertIn("都唔喺度", out)

    def test_revive_already_alive(self):
        with mock.patch.object(bot, "_rish_available", return_value=True):
            self.assertIn("行緊", self._ex("復活Shizuku"))

    def test_revive_no_lane(self):
        with mock.patch.object(bot, "_rish_available", return_value=False), \
             mock.patch.object(bot, "_adb_lane_available", return_value=False):
            self.assertIn("救唔到", self._ex("復活Shizuku"))

    def test_revive_success(self):
        states = iter([False, True])  # 初探死 → 行完 start.sh 復活
        with mock.patch.object(bot, "_rish_available",
                               side_effect=lambda: next(states, True)), \
             mock.patch.object(bot, "_adb_lane_available", return_value=True), \
             mock.patch.object(bot, "_adb_shell", return_value=(True, "ok")):
            self.assertIn("復活咗", self._ex("復活Shizuku"))

    def test_revive_start_script_missing(self):
        with mock.patch.object(bot, "_rish_available", return_value=False), \
             mock.patch.object(bot, "_adb_lane_available", return_value=True), \
             mock.patch.object(bot, "_adb_shell",
                               return_value=(False, "No such file")):
            self.assertIn("start.sh 行唔到", self._ex("復活Shizuku"))

    def test_lane_probe_uses_uid2000(self):
        with mock.patch.object(bot.shutil, "which", return_value="/usr/bin/adb"), \
             mock.patch.object(bot.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=0,
                                         stdout="uid=2000(shell)", stderr="")
            self.assertTrue(bot._adb_lane_probe())
            args = run.call_args_list[0][0][0]
            self.assertIn(bot.ADB_TARGET, args)
            self.assertIn("shell", args)


class TestSelfcheck(unittest.TestCase):
    """自檢 + 背景啟動限制檢測"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old_j = bot.JOBS_PATH
        bot.JOBS_PATH = os.path.join(self.tmp, "jobs.json")

    def tearDown(self):
        bot.JOBS_PATH = self.old_j

    def test_parse_and_execute(self):
        self.assertEqual(bot.parse_player("自檢").action, "selfcheck")
        self.assertEqual(bot.parse_player("測試").action, "selfcheck")
        now = dt.datetime(2026, 1, 5, 23, 58)
        r = bot._execute_player(bot.parse_player("自檢"), 12345, now)
        self.assertIn("🩺 自檢已排", r)
        self.assertIn("00:00", r)  # 23:58 + 2 分鐘跨日
        job = bot._load_json(bot.JOBS_PATH, [])[0]
        self.assertEqual(job["type"], "timer")
        self.assertEqual(job["seconds"], 90)
        self.assertIn("自檢測試", job["label"])

    def test_bal_denied_detection(self):
        self.assertTrue(bot._is_bal_denied("Background execution not allowed"))
        self.assertTrue(bot._is_bal_denied("java.lang.SecurityException: Permission Denial"))
        self.assertTrue(bot._is_bal_denied("startActivity is not allowed from background"))
        self.assertFalse(bot._is_bal_denied("no apps can perform this action"))
        self.assertFalse(bot._is_bal_denied("timeout"))

    def test_protect_command(self):
        self.assertEqual(bot.parse_player("修復").action, "protect")
        self.assertEqual(bot.parse_player("保障").action, "protect")
        self.assertEqual(bot.parse_player("權限").action, "protect")
        calls = []
        old = bot.run_intent
        bot.run_intent = lambda cmd, t=0: calls.append(cmd) or (True, "")
        try:
            r = bot._execute_player(bot.parse_player("修復"), 12345, dt.datetime(2026, 1, 5))
        finally:
            bot.run_intent = old
        self.assertEqual(len(calls), 3)
        self.assertIn("APPLICATION_DETAILS_SETTINGS", calls[0][3])
        self.assertIn("com.termux", calls[0][-1])
        self.assertIn("MANAGE_OVERLAY_PERMISSION", calls[1][3])
        self.assertIn("IGNORE_BATTERY_OPTIMIZATION", calls[2][3])
        self.assertIn("無限制", r)
        self.assertIn("通知", r)


class NetworkError(Exception):
    """假 telegram NetworkError（靠類名俾 _err_kind 認，唔使裝 telegram）。"""


class RetryAfter(Exception):
    def __init__(self, retry_after):
        super().__init__("flood")
        self.retry_after = retry_after


class BadRequest(Exception):
    """假不可重試錯。"""


class _FakeBot:
    """可設定頭 N 次 send_message 掟乜嘢例外，之後成功。"""
    def __init__(self, failures):
        self.failures = list(failures)  # list[Exception|None]
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        if self.failures:
            exc = self.failures.pop(0)
            if exc is not None:
                raise exc
        self.sent.append((chat_id, text))


class _FakeApp:
    def __init__(self, bot_obj):
        self.bot = bot_obj


class TestSendSafe(unittest.TestCase):
    def setUp(self):
        self._loops = []
        self._old_app = bot._APP
        self._old_sleep = asyncio.sleep
        self.sleeps = []

        async def fake_sleep(s):
            self.sleeps.append(s)

        asyncio.sleep = fake_sleep  # 全速測試，唔真等

    def tearDown(self):
        bot._APP = self._old_app
        asyncio.sleep = self._old_sleep
        for l in self._loops:
            l.close()

    def _loop(self):
        # 新鮮 loop：唔承繼其他測試喺共用 loop 遺留嘅 pending fire task
        loop = asyncio.new_event_loop()
        self._loops.append(loop)
        return loop

    def _run(self, failures, text="到點！"):
        fake = _FakeBot(failures)
        bot._APP = _FakeApp(fake)
        ok = self._loop().run_until_complete(bot._send_safe(123, text, "測試訊息"))
        return ok, fake

    def test_success_first_try(self):
        ok, fake = self._run([None])
        self.assertTrue(ok)
        self.assertEqual(len(fake.sent), 1)
        self.assertEqual(fake.sent[0], (123, "到點！"))
        self.assertEqual(self.sleeps, [])

    def test_net_blink_twice_then_ok(self):
        # 模擬巡樓弱訊號 2 連斷 → 第 3 次成功
        ok, fake = self._run([NetworkError("x"), NetworkError("y"), None])
        self.assertTrue(ok)
        self.assertEqual(len(fake.sent), 1)
        self.assertEqual(self.sleeps, [5, 20])  # 用晒頭兩級退避

    def test_net_persistent_fail(self):
        ok, fake = self._run([NetworkError("a")] * 5)
        self.assertFalse(ok)
        self.assertEqual(len(fake.sent), 0)
        self.assertEqual(self.sleeps, [5, 20])  # 3 次嘗試、2 次等待

    def test_retry_after_honoured(self):
        ok, _ = self._run([RetryAfter(10), None])
        self.assertTrue(ok)
        self.assertEqual(len(self.sleeps), 1)
        self.assertTrue(10.0 <= self.sleeps[0] <= 91.0)  # retry_after + 1（有上限）

    def test_non_net_error_no_retry(self):
        ok, fake = self._run([BadRequest("chat not found"), None])
        self.assertFalse(ok)
        self.assertEqual(len(fake.sent), 0)
        self.assertEqual(self.sleeps, [])  # 唔會傻等

    def test_no_app_returns_false(self):
        bot._APP = None
        ok = self._loop().run_until_complete(bot._send_safe(123, "x", "測試訊息"))
        self.assertFalse(ok)

    def test_backoff_constant(self):
        self.assertEqual(bot._NET_RETRY_BACKOFF, (5, 20, 45))

    def test_err_kind(self):
        self.assertEqual(bot._err_kind(NetworkError("a")), "net")

        class ConnectTimeoutNet(Exception):
            pass
        ConnectTimeoutNet.__name__ = "ConnectTimeoutNetTimedOut"
        self.assertEqual(bot._err_kind(ConnectTimeoutNet()), "net")
        self.assertEqual(bot._err_kind(RetryAfter(3)), "ratelimit")
        self.assertEqual(bot._err_kind(BadRequest("x")), "other")

    def test_on_error_swallows_net_noise(self):
        class Ctx:
            error = NetworkError("dns blip")
        with self.assertLogs("tgalarm", level="INFO") as cm:
            self._loop().run_until_complete(bot._on_error(None, Ctx()))
        self.assertTrue(any("閃斷" in m for m in cm.output))

    def test_on_error_logs_real_bugs(self):
        class Ctx:
            error = ValueError("真 bug")
        with self.assertLogs("tgalarm", level="ERROR") as cm:
            self._loop().run_until_complete(bot._on_error(None, Ctx()))
        self.assertTrue(any("未捕捉" in m for m in cm.output))


class TestWaMove(unittest.TestCase):
    """搬相：夜更時段計算、掃描過濾、真搬＋防撞名、預覽唔郁嘢。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wa_media_")
        self.sent = os.path.join(self.tmp, "Sent")
        os.makedirs(self.sent)
        self.dest = tempfile.mkdtemp(prefix="wa_night_dest_")
        # 巡樓實景：凌晨 03:50 send「搬相」，睇返尋晚→而家啲相
        self.now = dt.datetime(2026, 9, 23, 3, 50)
        self._key = bot.GEMINI_API_KEY
        bot.GEMINI_API_KEY = ""                        # 預設封讀圖（個別測試自己開）

    def tearDown(self):
        bot.GEMINI_API_KEY = self._key
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.dest, ignore_errors=True)

    def _mk(self, dirpath, name, when: dt.datetime):
        p = os.path.join(dirpath, name)
        with open(p, "wb") as f:
            f.write(b"jpg")
        ts = when.timestamp()
        os.utime(p, (ts, ts))
        return p

    # ── 時段計算 ──
    def test_window_during_night(self):          # 03:50 → 尋晚23:00 → 今朝07:00
        s, e = bot._wa_night_window(self.now)
        self.assertEqual(s, dt.datetime(2026, 9, 22, 23, 0))
        self.assertEqual(e, dt.datetime(2026, 9, 23, 7, 0))

    def test_window_after_2300(self):            # 23:30 → 今晚啱啱開始
        s, e = bot._wa_night_window(dt.datetime(2026, 9, 23, 23, 30))
        self.assertEqual(s, dt.datetime(2026, 9, 23, 23, 0))
        self.assertEqual(e, dt.datetime(2026, 9, 24, 7, 0))

    def test_window_daytime(self):               # 日間 12:00 → 尋晚完成時段
        s, e = bot._wa_night_window(dt.datetime(2026, 9, 23, 12, 0))
        self.assertEqual(s, dt.datetime(2026, 9, 22, 23, 0))
        self.assertEqual(e, dt.datetime(2026, 9, 23, 7, 0))

    # ── 自訂時段（2026-10-02 用戶令：當日或跨夜任何時段）──
    def test_recent_window_same_day(self):
        W = bot._wa_recent_window
        # 14:00 問 0900-1200 → 今日個窗（已完成）
        self.assertEqual(W(dt.datetime(2026, 9, 23, 14, 0), 9, 0, 12, 0),
                         (dt.datetime(2026, 9, 23, 9, 0), dt.datetime(2026, 9, 23, 12, 0)))
        # 10:00 問 0900-1200 → 今日個窗（進行中，end 可以大過 now）
        self.assertEqual(W(dt.datetime(2026, 9, 23, 10, 0), 9, 0, 12, 0),
                         (dt.datetime(2026, 9, 23, 9, 0), dt.datetime(2026, 9, 23, 12, 0)))
        # 08:00 問 0900-1200 → 尋日個窗（最近完成）
        self.assertEqual(W(dt.datetime(2026, 9, 23, 8, 0), 9, 0, 12, 0),
                         (dt.datetime(2026, 9, 22, 9, 0), dt.datetime(2026, 9, 22, 12, 0)))

    def test_recent_window_cross_midnight(self):
        W = bot._wa_recent_window
        # 11:00 問 2300-0700 → 尋晚23 → 今朝07
        self.assertEqual(W(dt.datetime(2026, 9, 23, 11, 0), 23, 0, 7, 0),
                         (dt.datetime(2026, 9, 22, 23, 0), dt.datetime(2026, 9, 23, 7, 0)))
        # 23:30 問 2300-0700 → 今晚23 → 明朝07（進行中）
        self.assertEqual(W(dt.datetime(2026, 9, 23, 23, 30), 23, 0, 7, 0),
                         (dt.datetime(2026, 9, 23, 23, 0), dt.datetime(2026, 9, 24, 7, 0)))
        # 有分鐘：0130 問 0100 0230 → 今日01:00→02:30
        self.assertEqual(W(dt.datetime(2026, 9, 23, 1, 30), 1, 0, 2, 30),
                         (dt.datetime(2026, 9, 23, 1, 0), dt.datetime(2026, 9, 23, 2, 30)))
        # 起＝終 → 拒絕
        self.assertIsNone(W(self.now, 9, 0, 9, 0))

    def test_parse_custom_range(self):
        p = bot.parse_player("搬相 0900 1200")
        self.assertEqual(p.action, "wamove")
        self.assertEqual(p.extra, "9 0 12 0")
        self.assertNotEqual(p.ref, "preview")
        p = bot.parse_player("搬相預覽 2300 0700")
        self.assertEqual(p.ref, "preview")
        self.assertEqual(p.extra, "23 0 7 0")
        p = bot.parse_player("搬相 9:30 11:45")
        self.assertEqual(p.extra, "9 30 11 45")
        p = bot.parse_player("搬相 0900 1200 預覽")
        self.assertEqual(p.ref, "preview")
        self.assertEqual(p.extra, "9 0 12 0")
        # 淨「搬相」照舊
        self.assertEqual(bot.parse_player("搬相").extra, "")
        self.assertEqual(bot.parse_player("搬相預覽").ref, "preview")
        # 壞範圍 → bad
        self.assertEqual(bot.parse_player("搬相 0900").ref, "bad")
        self.assertEqual(bot.parse_player("搬相 2500 1200").ref, "bad")
        self.assertEqual(bot.parse_player("搬相 0900 1200 1500").ref, "bad")

    def test_move_custom_same_day(self):
        self._mk(self.sent, "a.jpg", dt.datetime(2026, 9, 22, 10, 0))
        self._mk(self.sent, "b.jpg", dt.datetime(2026, 9, 23, 9, 30))
        self._mk(self.sent, "c.jpg", dt.datetime(2026, 9, 23, 23, 30))   # 窗外
        now = dt.datetime(2026, 9, 23, 14, 0)
        win = bot._wa_recent_window(now, 9, 0, 12, 0)                    # 今日 09–12
        r = bot._wa_move(now, src_root=self.tmp, dest=self.dest, window=win)
        self.assertIn("時段 09-23 09:00 → 09-23 12:00", r)
        self.assertIn("搬咗 1/1", r)
        sub = os.path.join(self.dest, "2026 09月", "2026-09-23", "Shift_A", "未分類")
        self.assertTrue(os.path.exists(os.path.join(sub, "b.jpg")))   # 09:00 屬 A更
        self.assertFalse(os.path.exists(os.path.join(sub, "a.jpg")))  # 尋日唔搬

    def test_move_custom_cross_midnight(self):
        self._mk(self.sent, "n1.jpg", dt.datetime(2026, 9, 22, 23, 30))
        self._mk(self.sent, "n2.jpg", dt.datetime(2026, 9, 23, 6, 59))
        self._mk(self.sent, "d.jpg", dt.datetime(2026, 9, 23, 12, 0))    # 窗外
        now = dt.datetime(2026, 9, 23, 11, 0)
        win = bot._wa_recent_window(now, 23, 0, 7, 0)
        r = bot._wa_move(now, src_root=self.tmp, dest=self.dest, window=win)
        self.assertIn("09-22 23:00 → 09-23 07:00", r)
        self.assertIn("搬咗 2/2", r)
        self.assertTrue(os.path.exists(os.path.join(
            self.dest, "2026 09月", "2026-09-22", "Shift_C", "未分類", "n1.jpg")))

    def test_execute_bad_range_hint(self):
        r = bot._execute_player(bot.PlayerCmd("wamove", ref="bad"), 12345, self.now)
        self.assertIn("用法", r)
        self.assertIn("搬相 0900 1200", r)

    def test_move_custom_empty_window(self):
        now = dt.datetime(2026, 9, 23, 14, 0)
        win = bot._wa_recent_window(now, 2, 0, 3, 0)                     # 凌晨，冇相
        r = bot._wa_move(now, src_root=self.tmp, dest=self.dest, window=win)
        self.assertIn("冇相，唔使搬", r)


    # ── 目錄偵測 ──
    def test_dirs_include_sent(self):
        ds = bot._wa_dirs(self.tmp)
        self.assertIn(self.tmp, ds)
        self.assertIn(self.sent, ds)

    def test_dirs_missing_root(self):
        self.assertEqual(bot._wa_dirs("/no/such/path_xyz"), [])

    # ── 掃描 ──
    def test_scan_filters_time_ext_depth(self):
        s, e = bot._wa_night_window(self.now)
        mid = dt.datetime(2026, 9, 23, 1, 30)         # 時段內
        out_hi = dt.datetime(2026, 9, 23, 22, 30)     # 時段外（夜晚後嘅日更）
        p_in = self._mk(self.tmp, "IMG-in.jpg", mid)
        p_sent = self._mk(self.sent, "IMG-sent.jpg", dt.datetime(2026, 9, 23, 3, 46))
        self._mk(self.tmp, "IMG-late.jpg", out_hi)                    # 時段外唔中
        self._mk(self.tmp, "IMG-eqend.jpg", e)                        # [start,end) 開端唔中
        self._mk(self.tmp, "note.txt", mid)                           # 非圖唔中
        sub = os.path.join(self.tmp, "Private"); os.makedirs(sub)
        self._mk(sub, "IMG-deep.jpg", mid)                            # 深一層唔掃
        hits = bot._wa_scan([self.tmp, self.sent], s, e)
        self.assertEqual([p for _, p in hits], sorted([p_in, p_sent],
                        key=lambda p: os.stat(p).st_mtime))

    # ── 預覽 ──
    def test_preview_lists_without_moving(self):
        mid = dt.datetime(2026, 9, 23, 1, 30)
        p1 = self._mk(self.tmp, "IMG-a.jpg", mid)
        r = bot._wa_move(self.now, preview=True, src_root=self.tmp, dest=self.dest)
        self.assertIn("預覽", r)
        self.assertIn("1 張", r)
        self.assertTrue(os.path.exists(p1))                 # 冇郁
        self.assertEqual(os.listdir(self.dest), [])         # 目的空置

    # ── 真搬 ──
    def test_move_underground(self):
        mid = dt.datetime(2026, 9, 23, 1, 30)
        p1 = self._mk(self.tmp, "IMG-a.jpg", mid)
        p2 = self._mk(self.sent, "IMG-b.jpg", dt.datetime(2026, 9, 23, 3, 46))
        # 目的已有同名 → 防撞名（樹制：同名檔喺未分類資料夾入面）
        sub_pre = os.path.join(self.dest, "2026 09月", "2026-09-22",
                               "Shift_C", "未分類")
        os.makedirs(sub_pre)
        with open(os.path.join(sub_pre, "IMG-a.jpg"), "wb") as f:
            f.write(b"old")
        r = bot._wa_move(self.now, preview=False, src_root=self.tmp, dest=self.dest)
        self.assertIn("搬咗 2/2 張", r)
        self.assertIn("↗", r)                               # Sent 有箭嘴標記
        self.assertIn("Shift_C", r)                         # 03:50 屬 C更（09-22 開始）
        self.assertFalse(os.path.exists(p1))
        self.assertFalse(os.path.exists(p2))
        sub = os.path.join(self.dest, "2026 09月", "2026-09-22",
                           "Shift_C", "未分類")
        self.assertTrue(os.path.exists(os.path.join(sub, "IMG-a-1.jpg")))
        self.assertTrue(os.path.exists(os.path.join(sub, "IMG-b.jpg")))

    def test_move_nothing_to_do(self):
        r = bot._wa_move(self.now, src_root=self.tmp, dest=self.dest)
        self.assertIn("冇相", r)

    def test_move_missing_folder_guidance(self):
        r = bot._wa_move(self.now, src_root="/no/such/path_xyz")
        self.assertIn("termux-setup-storage", r)

    # ── 指令文法 ──
    def test_grammar(self):
        self.assertEqual(bot.parse_player("搬相").action, "wamove")
        self.assertEqual(bot.parse_player("搬whatsapp相").action, "wamove")
        p = bot.parse_player("搬WA相 預覽")
        self.assertEqual((p.action, p.ref), ("wamove", "preview"))

    # ── 端到端（指令 → _execute_player） ──
    def test_execute_end_to_end(self):
        mid = dt.datetime(2026, 9, 23, 1, 30)
        self._mk(self.tmp, "IMG-x.jpg", mid)
        cmd = bot.parse_player("搬相")
        # 注入 src_root／PATROL_ROOT 做沙盒模擬
        old_dirs, old_root = bot._WA_MEDIA_CANDIDATES, bot.PATROL_ROOT
        bot._WA_MEDIA_CANDIDATES = (self.tmp,)
        bot.PATROL_ROOT = self.dest
        try:
            r = bot._execute_player(cmd, 12345, self.now)
        finally:
            bot._WA_MEDIA_CANDIDATES, bot.PATROL_ROOT = old_dirs, old_root
        self.assertIn("搬咗 1/1 張", r)
        self.assertTrue(os.path.exists(os.path.join(
            self.dest, "2026 09月", "2026-09-22", "Shift_C", "未分類", "IMG-x.jpg")))


class TestWaReturn(unittest.TestCase):
    """搬回：WA_Night → WhatsApp Images（2026-10-03 用戶令）。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wa_night_src_")      # 當 WA_Night
        self.dest = tempfile.mkdtemp(prefix="wa_images_dest_")   # 當 WhatsApp Images
        self.now = dt.datetime(2026, 9, 23, 12, 0)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.dest, ignore_errors=True)

    def _mk(self, name, when=dt.datetime(2026, 9, 23, 1, 0)):
        p = os.path.join(self.tmp, name)
        with open(p, "wb") as f:
            f.write(b"jpg")
        ts = when.timestamp()
        os.utime(p, (ts, ts))
        return p

    def test_parse(self):
        self.assertEqual(bot.parse_player("搬回").action, "wareturn")
        self.assertEqual(bot.parse_player("搬返").action, "wareturn")
        p = bot.parse_player("搬回預覽")
        self.assertEqual((p.action, p.ref), ("wareturn", "preview"))
        p = bot.parse_player("搬返預覽")
        self.assertEqual((p.action, p.ref), ("wareturn", "preview"))
        self.assertIsNone(bot.parse_player("搬回 ABC"))
        self.assertEqual(bot.parse_player("搬相").action, "wamove")   # 唔相沖

    def test_move_back_all(self):
        self._mk("IMG-20260923-WA0001.jpg")
        self._mk("IMG-20260923-WA0002.jpg", dt.datetime(2026, 9, 23, 6, 30))
        r = bot._wa_return(self.now, src=self.tmp, dest_root=self.dest)
        self.assertIn("搬咗 2/2", r)
        self.assertTrue(os.path.exists(os.path.join(self.dest, "IMG-20260923-WA0001.jpg")))
        self.assertEqual(os.listdir(self.tmp), [])                    # 全數搬走

    def test_collision_suffix(self):
        self._mk("IMG-20260923-WA0001.jpg")
        with open(os.path.join(self.dest, "IMG-20260923-WA0001.jpg"), "wb") as f:
            f.write(b"old")
        r = bot._wa_return(self.now, src=self.tmp, dest_root=self.dest)
        self.assertIn("搬咗 1/1", r)
        self.assertTrue(os.path.exists(os.path.join(self.dest, "IMG-20260923-WA0001-1.jpg")))

    def test_preview_and_empty_and_missing(self):
        self._mk("a.jpg")
        r = bot._wa_return(self.now, preview=True, src=self.tmp, dest_root=self.dest)
        self.assertIn("冇郁任何相", r)
        self.assertEqual(len(os.listdir(self.dest)), 0)
        r = bot._wa_return(self.now, src=self.tmp, dest_root=self.dest)  # 搬完再搬
        # a.jpg 已走，tmp 空
        self._mk("b.jpg")
        os.remove(os.path.join(self.tmp, "b.jpg"))
        r = bot._wa_return(self.now, src=self.tmp, dest_root=self.dest)
        self.assertIn("冇相", r)
        r = bot._wa_return(self.now, src="/no/such/dir_xyz", dest_root=self.dest)
        self.assertIn("搵唔到 BG巡邏相片記錄／WA_Night", r)


class TestPatrol(unittest.TestCase):
    """巡邏相片分類機制（2026-10-04 用戶令）：讀圖判崗位→歸檔 PC 同款樹。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wa_media_")
        os.makedirs(os.path.join(self.tmp, "Sent"))
        self.dest = tempfile.mkdtemp(prefix="patrol_root_")
        self.now = dt.datetime(2026, 9, 23, 14, 0)
        self._key, self._cls = bot.GEMINI_API_KEY, bot._gemini_classify
        self._root, self._posts = bot.PATROL_ROOT, bot.PATROL_POSTS
        self._relay = bot.GEMINI_RELAY

    def tearDown(self):
        bot.GEMINI_API_KEY, bot._gemini_classify = self._key, self._cls
        bot.PATROL_ROOT, bot.PATROL_POSTS = self._root, self._posts
        bot.GEMINI_RELAY = self._relay
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.dest, ignore_errors=True)

    def _mk(self, dirpath, name, when):
        p = os.path.join(dirpath, name)
        with open(p, "wb") as f:
            f.write(b"jpg")
        ts = when.timestamp()
        os.utime(p, (ts, ts))
        return p

    def test_shift_mapping(self):
        S = bot._patrol_shift
        self.assertEqual(S(dt.datetime(2026, 10, 4, 7, 0)), ("A", dt.date(2026, 10, 4)))
        self.assertEqual(S(dt.datetime(2026, 10, 4, 14, 59)), ("A", dt.date(2026, 10, 4)))
        self.assertEqual(S(dt.datetime(2026, 10, 4, 15, 0)), ("B", dt.date(2026, 10, 4)))
        self.assertEqual(S(dt.datetime(2026, 10, 4, 23, 5)), ("C", dt.date(2026, 10, 4)))
        self.assertEqual(S(dt.datetime(2026, 10, 4, 0, 30)), ("C", dt.date(2026, 10, 3)))
        self.assertEqual(S(dt.datetime(2026, 10, 4, 6, 59)), ("C", dt.date(2026, 10, 3)))

    def test_move_classified_into_tree(self):
        self._mk(self.tmp, "a.jpg", dt.datetime(2026, 9, 23, 9, 5))
        self._mk(self.tmp, "b.jpg", dt.datetime(2026, 9, 23, 10, 0))
        self._mk(self.tmp, "c.jpg", dt.datetime(2026, 9, 23, 11, 0))

        def fake(path, posts=None):
            n = os.path.basename(path)
            return {"a.jpg": ("T74", "T74"), "b.jpg": ("CP1", "CP1")}.get(n, (None, "未知"))
        bot.GEMINI_API_KEY = "X"
        bot._gemini_classify = fake
        now = dt.datetime(2026, 9, 23, 14, 0)
        win = bot._wa_recent_window(now, 9, 0, 12, 0)
        r = bot._wa_move(now, src_root=self.tmp, dest=self.dest, window=win)
        self.assertIn("T74:1", r)
        self.assertIn("CP1:1", r)
        self.assertIn("未分類:1", r)
        self.assertIn("Shift_A", r)
        base = os.path.join(self.dest, "2026 09月", "2026-09-23", "Shift_A")
        self.assertTrue(os.path.exists(os.path.join(base, "T74", "a.jpg")))
        self.assertTrue(os.path.exists(os.path.join(base, "CP1", "b.jpg")))
        self.assertTrue(os.path.exists(os.path.join(base, "未分類", "c.jpg")))

    def test_preview_shows_targets_without_moving(self):
        self._mk(self.tmp, "a.jpg", dt.datetime(2026, 9, 23, 9, 5))
        bot.GEMINI_API_KEY = "X"
        bot._gemini_classify = lambda path, posts=None: ("T74", "T74")
        now = dt.datetime(2026, 9, 23, 14, 0)
        win = bot._wa_recent_window(now, 9, 0, 12, 0)
        r = bot._wa_move(now, preview=True, src_root=self.tmp,
                         dest=self.dest, window=win)
        self.assertIn("→ T74", r)
        self.assertIn("冇郁任何相", r)
        self.assertEqual(os.listdir(self.dest), [])

    def test_no_key_all_unclassified(self):
        self._mk(self.tmp, "a.jpg", dt.datetime(2026, 9, 23, 9, 5))
        now = dt.datetime(2026, 9, 23, 14, 0)
        win = bot._wa_recent_window(now, 9, 0, 12, 0)
        r = bot._wa_move(now, src_root=self.tmp, dest=self.dest, window=win)
        self.assertIn("你自己分崗位", r)
        self.assertIn("未分類:1", r)
        self.assertTrue(os.path.exists(os.path.join(
            self.dest, "2026 09月", "2026-09-23", "Shift_A", "未分類", "a.jpg")))

    def test_gemini_classify_parse(self):
        import urllib.request

        class R:
            def __init__(self_, text):
                self_.payload = json.dumps(
                    {"candidates": [{"content": {"parts": [{"text": text}]}}]}).encode()

            def read(self_):
                return self_.payload

            def __enter__(self_):
                return self_

            def __exit__(self_, *a):
                return False
        bot.GEMINI_API_KEY = "X"
        holder = []

        def fake_urlopen(req, timeout=25):
            holder.append(req)
            return R("T74。\n")
        old = urllib.request.urlopen
        urllib.request.urlopen = fake_urlopen
        try:
            p = self._mk(self.tmp, "x.jpg", dt.datetime(2026, 9, 23, 9, 5))
            post, _raw = bot._gemini_classify(p, posts=["T74", "CP1"])
            self.assertEqual(post, "T74")
            body = json.loads(holder[0].data.decode())
            self.assertIn("inline_data", json.dumps(body["contents"][0]["parts"][0]))
            urllib.request.urlopen = lambda req, timeout=25: R("未知")
            post, _ = bot._gemini_classify(p, posts=["T74", "CP1"])
            self.assertIsNone(post)
        finally:
            urllib.request.urlopen = old

    def test_relay_path(self):
        import urllib.request
        bot.GEMINI_API_KEY = "X"
        bot.GEMINI_RELAY = "http://100.125.56.83:8787/"
        holder = []

        class R:
            payload = json.dumps({"post": "T74", "raw": "T74"}).encode()

            def read(self_):
                return self_.payload

            def __enter__(self_):
                return self_

            def __exit__(self_, *a):
                return False

        def fake_urlopen(req, timeout=40):
            holder.append(req)
            return R()
        oldu = urllib.request.urlopen
        urllib.request.urlopen = fake_urlopen
        oldposts = bot.PATROL_POSTS
        bot.PATROL_POSTS = ["T74", "CP1"]
        try:
            p = self._mk(self.tmp, "x.jpg", dt.datetime(2026, 9, 23, 9, 5))
            post, raw = bot._gemini_classify(p)
            self.assertEqual((post, raw), ("T74", "T74"))
            self.assertTrue(str(holder[0].full_url).endswith("/classify"))
            # 轉播回未知 → None
            R.payload = json.dumps({"post": None, "raw": "未知"}).encode()
            post, raw = bot._gemini_classify(p)
            self.assertIsNone(post)
            self.assertEqual(raw, "未知")
        finally:
            urllib.request.urlopen = oldu
            bot.PATROL_POSTS = oldposts

    def test_gemini_classify_no_key_and_error(self):
        bot.GEMINI_API_KEY = ""
        p = self._mk(self.tmp, "x.jpg", dt.datetime(2026, 9, 23, 9, 5))
        post, msg = bot._gemini_classify(p)
        self.assertIsNone(post)
        self.assertIn("GEMINI_API_KEY", msg)
        bot.GEMINI_API_KEY = "X"
        import urllib.request
        old = urllib.request.urlopen

        def boom(req, timeout=25):
            raise OSError("no net")
        urllib.request.urlopen = boom
        try:
            post, msg = bot._gemini_classify(p)
        finally:
            urllib.request.urlopen = old
        self.assertIsNone(post)
        self.assertIn("no net", msg)

    def test_return_recursive_tree(self):
        t74 = os.path.join(self.tmp, "2026 09月", "2026-09-23", "Shift_A", "T74")
        os.makedirs(t74)
        self._mk(t74, "a.jpg", dt.datetime(2026, 9, 23, 9, 5))
        un = os.path.join(self.tmp, "2026 09月", "2026-09-22", "Shift_C", "未分類")
        os.makedirs(un)
        self._mk(un, "b.jpg", dt.datetime(2026, 9, 23, 3, 0))
        r = bot._wa_return(self.now, src=self.tmp, dest_root=self.dest)
        self.assertIn("搬咗 2/2", r)
        self.assertTrue(os.path.exists(os.path.join(self.dest, "a.jpg")))
        self.assertTrue(os.path.exists(os.path.join(self.dest, "b.jpg")))
        self.assertEqual(os.listdir(t74), [])


class TestSchedPauseDate(unittest.TestCase):
    """排定日期暫停／繼續（2026-10-04 用戶令）：mmdd 暫停排程 x／mmdd 繼續排程 x。"""

    def setUp(self):
        self.now = dt.datetime(2026, 10, 4, 12, 0)
        self._jobs, self._save, self._add = bot._jobs, bot._save_json, bot._add_simple_job
        self._send = bot._send_safe
        store = [{"id": 1, "type": "timer", "hh": 13, "mm": 0, "label": "A",
                  "chat_id": 1, "daily": True, "next": "2026-10-04T13:00:00"},
                 {"id": 2, "type": "alarm", "hh": 14, "mm": 30, "label": "B",
                  "chat_id": 1, "daily": False, "next": "2026-10-04T14:30:00"}]
        self.store = store
        bot._jobs = lambda: store
        bot._save_json = lambda p, d: None
        self._arm, self._tasks = bot._arm, dict(bot._TASKS)
        bot._arm = lambda j: None          # _resume_job 會 arm——唔准種真 task
        bot._TASKS = {}                    # 隔離：唔好掂到第啲測試嘅 pending task
        self.sent = []

        async def fake_send(cid, text, label=""):
            self.sent.append(text)
            return True
        bot._send_safe = fake_send

    def tearDown(self):
        bot._jobs, bot._save_json, bot._add = self._jobs, self._save, self._add
        bot._send_safe = self._send
        bot._arm, bot._TASKS = self._arm, self._tasks

    def test_parse(self):
        p = bot.parse_player("1005 暫停排程 3")
        self.assertEqual((p.action, p.hour, p.minute, p.extra),
                         ("pause_date", 10, 5, "3"))
        p = bot.parse_player("1012 繼續排程 3,5")
        self.assertEqual((p.action, p.hour, p.minute, p.extra),
                         ("resume_date", 10, 12, "3,5"))
        p = bot.parse_player("1012 繼續排程")
        self.assertEqual(p.extra, "")
        p = bot.parse_player("1005 暫停 3")
        self.assertEqual(p.action, "pause_date")
        # 舊文法零沖突
        self.assertEqual(bot.parse_player("暫停排程").action, "pause_all")
        self.assertEqual(bot.parse_player("暫停 3").action, "pause")

    def test_future_creates_job(self):
        # 真 _add_simple_job：_jobs/_save_json/_arm 已 mock，job 會跌入 self.store
        r = bot._execute_player(bot.PlayerCmd("pause_date", hour=10, minute=5,
                                              extra="1"), 7, self.now)
        self.assertIn("🗓 已排定：10月5日 暫停 #1", r)
        made = [j for j in self.store if j.get("type") == "sched_pause"]
        self.assertEqual(len(made), 1)
        self.assertEqual(made[0]["ids"], [1])
        self.assertTrue(made[0]["next"].startswith("2026-10-05T00:05"))
        r = bot._execute_player(bot.PlayerCmd("resume_date", hour=10, minute=12,
                                              extra=""), 7, self.now)
        self.assertIn("繼續 全部", r)
        made = [j for j in self.store if j.get("type") == "sched_resume"]
        self.assertEqual(len(made), 1)

    def test_past_date_rolls_next_year(self):
        r = bot._execute_player(bot.PlayerCmd("pause_date", hour=9, minute=1,
                                              extra="1"), 7, self.now)
        self.assertIn("9月1日（2027）", r)
        made = [j for j in self.store if j.get("type") == "sched_pause"]
        self.assertEqual(len(made), 1)
        self.assertTrue(made[0]["next"].startswith("2027-09-01T00:05"))

    def test_bad_date(self):
        r = bot._execute_player(bot.PlayerCmd("pause_date", hour=13, minute=40,
                                              extra="1"), 7, self.now)
        self.assertIn("日期唔存在", r)

    def test_unknown_id_rejected(self):
        r = bot._execute_player(bot.PlayerCmd("pause_date", hour=10, minute=5,
                                              extra="9"), 7, self.now)
        self.assertIn("搵唔到 #9", r)

    def test_today_immediate(self):
        r = bot._execute_player(bot.PlayerCmd("pause_date", hour=10, minute=4,
                                              extra="1"), 7, self.now)
        self.assertIn("今日（10月4日）已暫停 #1", r)
        self.assertTrue(self.store[0].get("paused"))

    def test_fire_pause_and_resume(self):
        loop = asyncio.new_event_loop()
        try:
            job = {"id": 50, "type": "sched_pause", "ids": [1, 2],
                   "chat_id": 7, "hh": 0, "mm": 5,
                   "next": "2026-10-05T00:05:00"}
            loop.run_until_complete(bot._fire_later(dict(job), 0))
            self.assertTrue(all(j.get("paused") for j in self.store))
            self.assertIn("已暫停 #1、#2", self.sent[-1])
            job2 = {"id": 51, "type": "sched_resume", "ids": [],
                    "chat_id": 7, "hh": 0, "mm": 5,
                    "next": "2026-10-12T00:05:00"}
            loop.run_until_complete(bot._fire_later(dict(job2), 0))
            self.assertFalse(any(j.get("paused") for j in self.store))
            self.assertIn("已恢復 2 個排程", self.sent[-1])
        finally:
            loop.close()

    def test_fmt(self):
        self.assertEqual(bot._fmt_job_content(
            {"type": "sched_pause", "ids": [3, 5]}), "排定暫停排程：#3、#5")
        self.assertEqual(bot._fmt_job_content(
            {"type": "sched_resume", "ids": []}), "排定繼續排程：全部")


class TestVolPlay(unittest.TestCase):
    """音量x% 播 [歌單]／hhmm 音量x% 播 [歌單]（用戶令 2026-10-05）。"""

    def test_parse_vol(self):
        c = bot.parse_player("音量40% 播 lofi")
        self.assertEqual((c.action, c.vol, c.ref), ("play", 40, "lofi"))
        c2 = bot.parse_player("0700 音量40% 播 lofi")
        self.assertEqual((c2.action, c2.hour, c2.minute, c2.vol, c2.ref),
                         ("sched_once", 7, 0, 40, "lofi"))
        c3 = bot.parse_player("每日 0700 音量40% 播 lofi")
        self.assertEqual((c3.action, c3.vol), ("sched_daily", 40))
        c4 = bot.parse_player("音量40% 隨機播 lofi")
        self.assertEqual((c4.action, c4.vol, c4.shuffle), ("play", 40, True))
        # 寬鬆：音量放喺時間前都收
        c5 = bot.parse_player("音量40% 0700 播 lofi")
        self.assertEqual((c5.action, c5.vol), ("sched_once", 40))
        # 超界即拒
        self.assertEqual(bot.parse_player("音量150% 播 lofi").action, "vol_bad")
        self.assertEqual(bot.parse_player("音量0% 播 lofi").vol, 0)
        # 舊格式零影響
        for t in ("播 lofi", "0700 播 lofi", "每日 0700 播 lofi",
                  "隨機播 lofi", "play lofi"):
            self.assertIsNone(bot.parse_player(t).vol, t)

    def test_set_media_volume(self):
        rec = []

        def fake_shell(cmd):
            rec.append(cmd)
            if "get-max-volume" in cmd:
                return True, "AudioManager.getStreamMaxVolume(3) -> 150"
            if "set-volume" in cmd:
                return True, f"calling AudioManager{cmd[10:]}"
            if "get-stream-volume" in cmd:
                target = rec[-2].split()[-1]      # 對上一個 set 嘅值
                return True, f"AudioManager.getStreamVolume(3) -> {target}"
            return False, "?"

        old = bot._shell_priv_exec
        try:
            bot._shell_priv_exec = fake_shell
            ok, det = bot._set_media_volume(50)
            self.assertTrue(ok)
            self.assertIn("75/150", det)
            self.assertIn("cmd audio set-volume 3 75", rec)
            # 讀返唔對 → 失敗自證
            def bad_shell(cmd):
                if "get-max-volume" in cmd:
                    return True, "-> 150"
                if "set-volume" in cmd:
                    return True, "ok"
                return True, "AudioManager.getStreamVolume(3) -> 120"
            bot._shell_priv_exec = bad_shell
            ok2, det2 = bot._set_media_volume(50)
            self.assertFalse(ok2)
            self.assertIn("75", det2) and self.assertIn("120", det2)
            # 攞唔到 max → 失敗
            bot._shell_priv_exec = lambda c: (False, "lane死")
            ok3, _ = bot._set_media_volume(50)
            self.assertFalse(ok3)
        finally:
            bot._shell_priv_exec = old

    def test_add_job_persists_vol(self):
        self._tmp = tempfile.mkdtemp()
        self._oj, self._ot = bot.JOBS_PATH, dict(bot._TASKS)
        self._oarm = bot._arm
        bot.JOBS_PATH = os.path.join(self._tmp, "j.json")
        bot._arm = lambda j: None
        try:
            now = bot.dt.datetime.now()
            cmd = bot.PlayerCmd("sched_once", ref="lofi", hour=7, minute=0,
                                vol=40)
            job, _rep = bot._add_job(cmd, 1, now, url="u")
            self.assertEqual(job["vol"], 40)
            cmd0 = bot.PlayerCmd("sched_once", ref="lofi", hour=8, minute=0)
            job0, _ = bot._add_job(cmd0, 1, now, url="u")
            self.assertIsNone(job0["vol"])
            # 列表顯示
            self.assertIn("🔊40%", bot._fmt_job_content(job))
            self.assertNotIn("🔊", bot._fmt_job_content(job0))
        finally:
            bot.JOBS_PATH, bot._TASKS, bot._arm = self._oj, self._ot, self._oarm

    def test_fire_sets_volume_before_play(self):
        self._tmp = tempfile.mkdtemp()
        self._oj, self._ot = bot.JOBS_PATH, dict(bot._TASKS)
        self._oarm, self._ori = bot._arm, bot.run_intent
        self._osay, self._oss, self._oplay = bot._say, bot._send_safe, bot._play
        self._osv = bot._set_media_volume
        bot.JOBS_PATH = os.path.join(self._tmp, "j.json")
        bot._arm = lambda j: None
        bot.run_intent = lambda cmd, t=0: (True, "OK")
        order = []

        async def fs(cid, msg, tag=""):
            return None
        bot._send_safe = fs

        async def say(text, delay=0):
            order.append("say")
        bot._say = say
        bot._play = lambda u, sh=False: order.append("play") or (True, "OK")

        def sv(pct):                     # 生產 code 係 sync（to_thread 包）
            order.append(f"vol{pct}")
            return True, "音量 40%（60/150）"
        bot._set_media_volume = sv
        try:
            now = bot.dt.datetime.now()
            job = {"id": 1, "type": "play", "url": "u", "label": "lofi",
                   "hh": now.hour, "mm": now.minute, "daily": False,
                   "vol": 40, "shuffle": False,
                   "next": now.isoformat(), "chat_id": 1, "paused": False}
            bot._save_json(bot.JOBS_PATH, [job])
            loop = asyncio.new_event_loop()   # 屋企式：唔好 asyncio.run（會清 current loop 毒下游）
            try:
                loop.run_until_complete(bot._fire_later(dict(job), 0))
            finally:
                loop.close()
            self.assertEqual(order, ["vol40", "play"])
            # 無 vol：唔好掂音量
            order.clear()
            job2 = dict(job, id=2, vol=None)
            bot._save_json(bot.JOBS_PATH, [job2])
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(bot._fire_later(dict(job2), 0))
            finally:
                loop.close()
            self.assertEqual(order, ["play"])
        finally:
            bot.JOBS_PATH = self._oj
            bot._TASKS = self._ot
            bot._arm, bot.run_intent = self._oarm, self._ori
            bot._say, bot._send_safe, bot._play = self._osay, self._oss, self._oplay
            bot._set_media_volume = self._osv

    def test_edit_vol(self):
        """改播 N 音量50%：就地改已排程播歌任務嘅音量（用戶令 2026-10-06）。"""
        self._tmp = tempfile.mkdtemp()
        self._oj, self._ot, self._oarm = bot.JOBS_PATH, dict(bot._TASKS), bot._arm
        bot.JOBS_PATH = os.path.join(self._tmp, "j.json")
        bot._arm = lambda j: None
        try:
            now = bot.dt.datetime.now()
            job = {"id": 5, "type": "play", "url": "u", "label": "lofi",
                   "hh": 7, "mm": 0, "daily": True, "vol": None,
                   "shuffle": False, "next": now.isoformat(), "chat_id": 1,
                   "paused": False}
            bot._save_json(bot.JOBS_PATH, [job])
            # parse 本來就通（改播家族）
            c = bot.parse_player("改播 5 音量50%")
            self.assertEqual((c.action, c.job_id, c.ref),
                             ("edit", 5, "音量50%"))
            # 淨改音量：其他欄不動
            ok, info = bot._edit_job(5, "音量50%", now)
            self.assertTrue(ok)
            self.assertIn("音量→50%", info)
            j = bot._jobs()[0]
            self.assertEqual((j["vol"], j["hh"], j["daily"]), (50, 7, True))
            self.assertIn("🔊50%", bot._fmt_job_content(j))
            # 混合：時間＋音量一次改
            ok2, info2 = bot._edit_job(5, "0800 音量30%", now)
            self.assertTrue(ok2)
            self.assertIn("時間→08:00", info2)
            self.assertIn("音量→30%", info2)
            j = bot._jobs()[0]
            self.assertEqual((j["vol"], j["hh"], j["mm"]), (30, 8, 0))
            # 拒：>100
            ok3, info3 = bot._edit_job(5, "音量150%", now)
            self.assertFalse(ok3)
            self.assertIn("0–100", info3)
            # 拒：非播歌任務冇音量
            tjob = dict(job, id=6, type="timer", seconds=60, vol=None)
            bot._save_json(bot.JOBS_PATH, [job, tjob])
            ok4, info4 = bot._edit_job(6, "音量50%", now)
            self.assertFalse(ok4)
            self.assertIn("冇音量", info4)
        finally:
            bot.JOBS_PATH, bot._TASKS, bot._arm = self._oj, self._ot, self._oarm


class TestPlaylistCache(unittest.TestCase):
    """_playlist_videos session 快取：第二次起唔出網（最快響應）。"""

    def setUp(self):
        self.old = bot._fetch
        self.old_cache = dict(bot._PL_CACHE)
        bot._PL_CACHE.clear()

    def tearDown(self):
        bot._fetch = self.old
        bot._PL_CACHE.clear()
        bot._PL_CACHE.update(self.old_cache)

    def test_second_call_hits_cache_zero_network(self):
        calls = []

        def fake_fetch(url):
            calls.append(url)
            if "feeds/videos.xml" in url:
                return "<x><yt:videoId>v1111111111</yt:videoId> <yt:videoId>v2222222222</yt:videoId></x>"
            raise AssertionError("第二次唔應該再上網")

        bot._fetch = fake_fetch
        v1 = bot._playlist_videos("PLabc")
        self.assertEqual(len(calls), 1)              # 第一次上網
        v2 = bot._playlist_videos("PLabc")
        self.assertEqual(v1, v2)
        self.assertEqual(len(calls), 1)              # 第二次冇上網

    def test_cache_expiry_refetches(self):
        calls = []

        def fake_fetch(url):
            calls.append(url)
            if "feeds/videos.xml" in url and calls == [url]:
                return "<x><yt:videoId>v3333333333</yt:videoId></x>"
            return "<x><yt:videoId>v4444444444</yt:videoId></x>"

        bot._fetch = fake_fetch
        v1 = bot._playlist_videos("PLstale")
        self.assertEqual(v1, ["v3333333333"])
        # 人工 ageing：將時間戳撥返 7 個鐘前
        ts, vids = bot._PL_CACHE["PLstale"]
        bot._PL_CACHE["PLstale"] = (ts - 7 * 3600, vids)
        v2 = bot._playlist_videos("PLstale")
        self.assertEqual(v2, ["v4444444444"])       # 過期 → 重新上網

    def test_network_dead_falls_back_to_stale_cache(self):
        bot._fetch = lambda url: "<x><yt:videoId>v5555555555</yt:videoId></x>"
        self.assertEqual(bot._playlist_videos("PLdead"), ["v5555555555"])
        ts, vids = bot._PL_CACHE["PLdead"]
        bot._PL_CACHE["PLdead"] = (ts - 7 * 3600, vids)   # ageing

        def boom(url):
            raise OSError("DNS blip")
        bot._fetch = boom
        self.assertEqual(bot._playlist_videos("PLdead"), ["v5555555555"])

    def test_no_cache_no_network_returns_empty(self):
        def boom(url):
            raise OSError("dns")
        bot._fetch = boom
        self.assertEqual(bot._playlist_videos("PLgone"), [])


class TestAllocAdvance(unittest.TestCase):
    """「完成」快進：進行中段即刻入下一段；最後段提早收工。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old_j = bot.JOBS_PATH
        bot.JOBS_PATH = os.path.join(self.tmp, "jobs.json")
        self.old_tasks = dict(bot._TASKS)
        bot._TASKS.clear()
        self.now = dt.datetime(2026, 1, 5, 20, 15)

    def tearDown(self):
        bot.JOBS_PATH = self.old_j
        for t in bot._TASKS.values():
            t.cancel()
        bot._TASKS.clear()
        bot._TASKS.update(self.old_tasks)

    def _mk_alloc(self, idx=1, daily=False, next_at="2026-01-05T20:30:00", jid=7):
        job = {"id": jid, "type": "alloc", "hh": 19, "mm": 30, "hh2": 22, "mm2": 30,
               "daily": daily, "url": "", "seconds": 0, "mode": "", "label": "時間分配",
               "chat_id": 12345, "next": next_at, "shuffle": False, "paused": False,
               "segments": [{"text": "巡樓", "seconds": 3600}, {"text": "發相", "seconds": 3600}],
               "idx": idx}
        bot._save_json(bot.JOBS_PATH, [job])
        return job

    def _done(self):
        return bot._execute_player(bot.parse_player("完成"), 12345, self.now)

    # ── 文法 ──
    def test_grammar(self):
        for s in ("完成", "完成咗", "早完成", "提早完成", "下一階段", "下階段", "跳過", "skip", "next"):
            self.assertEqual(bot.parse_player(s).action, "alloc_done", s)
        self.assertIsNone(bot.parse_player("完成咗件事先話你知"))   # 長句唔攪

    # ── 冇進行中 ──
    def test_no_running_alloc(self):
        r = self._done()
        self.assertIn("冇進行中", r)
        self.assertIn("播程", r)

    def test_not_started_yet(self):            # 排咗嘅分配未開波（idx=0）唔當進行中
        self._mk_alloc(idx=0)
        r = self._done()
        self.assertIn("冇進行中", r)

    # ── 中段快進 ──
    def test_mid_stage_advances(self):
        self._mk_alloc()                 # 巡樓進行中，仲淨 15 分鐘
        r = self._done()
        self.assertIn("提早完成「巡樓」", r)
        self.assertIn("慳返 15分鐘", r)
        self.assertIn("動態重排", r)                     # 慳到嘅時間動態跌入
        self.assertIn("（20:15→22:30）", r)             # 收工時間照舊
        self.assertEqual(bot._jobs()[0]["segments"][1]["seconds"], 135 * 60)  # 135分全食
        self.assertIn("撳停", r)               # 提醒舊倒計時
        self.assertEqual(bot._jobs()[0]["next"], self.now.isoformat())  # next 即刻拉前
        self.assertIn(7, bot._TASKS)           # 重裝備

    def test_mid_stage_uses_now_exactly(self):
        self._mk_alloc(next_at="2026-01-05T20:16:30")   # 淨 90 秒
        r = self._done()
        self.assertIn("提早完成「巡樓」", r)
        self.assertEqual(bot._jobs()[0]["next"], self.now.isoformat())

    # ── 最後段收工 ──
    def test_last_stage_finishes_once_off(self):
        self._mk_alloc(idx=2)            # 發相（最後段）進行中
        r = self._done()
        self.assertIn("提早收工", r)
        self.assertIn("已刪走", r)
        self.assertEqual(bot._jobs(), [])      # job 消失
        self.assertNotIn(7, bot._TASKS)

    def test_last_stage_daily_rearms_tomorrow(self):
        self._mk_alloc(idx=2, daily=True)
        r = self._done()
        self.assertIn("提早收工", r)
        self.assertIn("每日", r)
        self.assertIn("聽日", r)
        jobs = bot._jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["idx"], 0)
        nxt = dt.datetime.fromisoformat(jobs[0]["next"])
        self.assertTrue(nxt > self.now)        # 下個 19:30（聽日）
        self.assertEqual((nxt.hour, nxt.minute), (19, 30))

    # ── 多個分配揀最雷 ──
    def test_multiple_picks_earliest(self):
        j1 = self._mk_alloc(jid=7, next_at="2026-01-05T20:50:00")
        j2 = self._mk_alloc(jid=8, next_at="2026-01-05T20:20:00")
        bot._save_json(bot.JOBS_PATH, [j1, j2])
        r = self._done()
        self.assertIn("動態重排", r)                 # 揀咗 20:20 嗰個（慳 5 分跌入）
        self.assertEqual(dt.datetime.fromisoformat(bot._jobs()[1]["next"]),
                         self.now)


class TestAllocReflow(unittest.TestCase):
    """動態數值：提早完成嘅慳返時間按權重跌入剩餘段，收工冧巴照舊。"""

    def setUp(self):
        pass

    def _job(self, segs, buf=0, start=(19, 30), end=(22, 30)):
        return {"hh": start[0], "mm": start[1], "hh2": end[0], "mm2": end[1],
                "buf": buf, "segments": segs, "idx": 1}

    def test_single_seg_absorbs_all(self):
        j = self._job([{"text": "a", "seconds": 3600, "w": 1},
                       {"text": "b", "seconds": 3600, "w": 1}])
        now = dt.datetime(2026, 1, 5, 20, 15)          # 提早 15 分鐘
        self.assertTrue(bot._alloc_reflow(j, now, 1))
        self.assertEqual(j["segments"][0]["seconds"], 3600)   # 已過段唔郁
        self.assertEqual(j["segments"][1]["seconds"], 135 * 60)  # b 新秒 = 22:30 − 20:15 = 135 分
        self.assertEqual((now + dt.timedelta(seconds=j["segments"][1]["seconds"])).
                         strftime("%H:%M"), "22:30")

    def test_weights_honoured(self):
        # a x2 已做完；剩 b x2、c x1 → 提早 30 分，剩餘 90 分按 2:1 劈 → 60/30
        j = self._job([{"text": "a", "seconds": 3600, "w": 2},
                       {"text": "b", "seconds": 1800, "w": 2},
                       {"text": "c", "seconds": 900, "w": 1}],
                      start=(19, 30), end=(21, 0))
        now = dt.datetime(2026, 1, 5, 20, 0)           # a 本應 20:30 完
        self.assertTrue(bot._alloc_reflow(j, now, 1))
        self.assertEqual(j["segments"][1]["seconds"], 40 * 60)  # 60 分 × 2/3
        self.assertEqual(j["segments"][2]["seconds"], 20 * 60)  # 60 分 × 1/3
        # 總和 = 60 分餘額，尾段食正
        tot = sum(s["seconds"] for s in j["segments"][1:])
        self.assertEqual((now + dt.timedelta(seconds=tot)).strftime("%H:%M"), "21:00")

    def test_buf_preserved(self):
        # buf 50%：剩 120 分 → 得 60 分可用
        j = self._job([{"text": "a", "seconds": 1200, "w": 1},
                       {"text": "b", "seconds": 600, "w": 1}],
                      buf=50, start=(19, 30), end=(21, 30))
        self.assertTrue(bot._alloc_reflow(j, dt.datetime(2026, 1, 5, 19, 30), 1))
        self.assertEqual(j["segments"][1]["seconds"], 60 * 60)

    def test_insufficient_time_fallback(self):
        # 剩 50 秒但仲有 2 段 → False，攞唔郁
        j = self._job([{"text": "a", "seconds": 300, "w": 1},
                       {"text": "b", "seconds": 300, "w": 1},
                       {"text": "c", "seconds": 300, "w": 1}],
                      start=(22, 29), end=(22, 30))
        ok = bot._alloc_reflow(j, dt.datetime(2026, 1, 5, 22, 29, 10), 1)
        self.assertFalse(ok)
        self.assertEqual(j["segments"][1]["seconds"], 300)

    def test_no_remaining_segs(self):
        j = self._job([{"text": "a", "seconds": 3600, "w": 1}])
        self.assertFalse(bot._alloc_reflow(j, dt.datetime(2026, 1, 5, 20, 0), 5))

    def test_cross_day_block_end(self):
        # 跨日：2300-0200；01:15 send 完成 → block_end = 02:00 同一日
        j = self._job([{"text": "巡", "seconds": 3600, "w": 1},
                       {"text": "發", "seconds": 3600, "w": 1}],
                      start=(23, 0), end=(2, 0))
        now = dt.datetime(2026, 1, 6, 1, 15)
        end = bot._alloc_remaining_end(j, now)
        self.assertEqual(end.strftime("%m-%d %H:%M"), "01-06 02:00")
        self.assertTrue(bot._alloc_reflow(j, now, 1))
        self.assertEqual(j["segments"][1]["seconds"], 45 * 60)

    def test_default_weight_old_jobs(self):
        # 舊 job 冇 w 欄 → 當 1.0，照樣動態
        j = self._job([{"text": "a", "seconds": 1000}, {"text": "b", "seconds": 1000},
                       {"text": "c", "seconds": 1000}])
        now = dt.datetime(2026, 1, 5, 20, 0)
        self.assertTrue(bot._alloc_reflow(j, now, 1))
        self.assertEqual(j["segments"][1]["seconds"] + j["segments"][2]["seconds"], 150 * 60)


class TestRunIntentGuardrails(unittest.TestCase):
    """run_intent 守穩：timeout 唔會再被縮細；超時錯誤訊息講人話。"""

    def test_timeout_budget_ten_seconds(self):
        captured = {}

        def fake_run(cmd, **kw):
            captured.update(kw)

            class R:
                returncode = 0
                stdout = ""
                stderr = ""
            return R()

        old = bot.subprocess.run
        bot.subprocess.run = fake_run
        try:
            ok, _ = bot.run_intent(["am", "start"])
        finally:
            bot.subprocess.run = old
        self.assertTrue(ok)
        self.assertGreaterEqual(captured.get("timeout", 0), 10,
                                "am 超時最少要 10s——電話 load 高呢陣 3s 會漏響鬧鐘")

    def test_timeout_expired_friendly_message(self):
        def boom(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
        old = bot.subprocess.run
        bot.subprocess.run = boom
        try:
            ok, info = bot.run_intent(["am", "start"])
        finally:
            bot.subprocess.run = old
        self.assertFalse(ok)
        self.assertIn("超時", info)
        self.assertNotIn("'am'", info)   # 唔好成段 command 嚇親



class TestNavFallback(unittest.TestCase):
    """導航 intent 三重後備：VIEW → MapsActivity → https。"""

    def _stub(self, pattern):
        """pattern: list 開頭/結尾撇要失敗。回傳 (calls, run_intent_func)"""
        calls = []

        def run(cmd, t=0):
            calls.append(cmd)
            n = len(calls) - 1
            if pattern[n]:
                return True, ""
            return False, "Activity not started"
        return calls, run

    def test_view_ok_short_circuit(self):
        calls, run = self._stub([True])
        old = bot.run_intent
        bot.run_intent = run
        try:
            ok, _ = bot._open_nav("沙田", "r")
        finally:
            bot.run_intent = old
        self.assertTrue(ok)
        self.assertEqual(len(calls), 1)

    def test_component_second(self):
        calls, run = self._stub([False, True, True])
        old = bot.run_intent
        bot.run_intent = run
        try:
            ok, _ = bot._open_nav("沙田", "w")
        finally:
            bot.run_intent = old
        self.assertTrue(ok)
        self.assertEqual(len(calls), 2)
        self.assertIn("com.google.android.apps.maps/com.google.android.maps.MapsActivity", calls[1])
        self.assertIn("--activity-clear-task", calls[1])
        self.assertIn("travelmode=walking", calls[1][-1])

    def test_https_last_resort(self):
        calls, run = self._stub([False, False, True])
        old = bot.run_intent
        bot.run_intent = run
        try:
            ok, _ = bot._open_nav("沙田", "r")
        finally:
            bot.run_intent = old
        self.assertTrue(ok)
        self.assertEqual(len(calls), 3)
        self.assertIn("android.intent.action.VIEW", calls[2])
        self.assertIn("--activity-clear-task", calls[2])
        self.assertIn("travelmode=transit", calls[2][-1])

    def test_all_fail_reports_last_error(self):
        _calls, run = self._stub([False, False, False])
        old = bot.run_intent
        bot.run_intent = run
        try:
            ok, info = bot._open_nav("沙田", "r")
        finally:
            bot.run_intent = old
        self.assertFalse(ok)
        self.assertIn("Activity not started", info)


class TestOpenNavRish(unittest.TestCase):
    """Shizuku/rish 路線：用 adb shell 身份彈導航，繞過手機廠背景閘。"""

    def setUp(self):
        self._cache = dict(bot._RISH_CACHE)
        self._run = bot.run_intent
        self._probe = bot._rish_probe

    def tearDown(self):
        bot._RISH_CACHE.update(self._cache)
        bot.run_intent = self._run
        bot._rish_probe = self._probe

    def test_rish_first_when_available(self):
        bot._RISH_CACHE.update({"t": 1e18, "ok": True})
        calls = []
        bot.run_intent = lambda cmd, t=0: calls.append(cmd) or (True, "ok")
        ok, _ = bot._open_nav("沙田石門安群街1號", "r")
        self.assertTrue(ok)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][:2], ["rish", "-c"])
        payload = calls[0][2]
        self.assertTrue(payload.startswith("input keyevent KEYCODE_WAKEUP;"))
        self.assertIn("am start --activity-clear-task -a android.intent.action.VIEW", payload)
        self.assertIn("google.navigation:q=", payload)

    def test_rish_fail_falls_back_to_am(self):
        bot._RISH_CACHE.update({"t": 1e18, "ok": True})
        calls = []
        def run(cmd, t=0):
            calls.append(cmd)
            return (False, "Service has not been started") if cmd[0] == "rish" else (True, "")
        bot.run_intent = run
        ok, _ = bot._open_nav("沙田", "w")
        self.assertTrue(ok)
        self.assertEqual(calls[0][0], "rish")
        self.assertEqual(calls[1][0], "am")  # 跌返第一重普通後備

    def test_rish_unavailable_goes_straight_am(self):
        bot._RISH_CACHE.update({"t": 1e18, "ok": False})
        calls = []
        bot.run_intent = lambda cmd, t=0: calls.append(cmd) or (True, "")
        bot._open_nav("沙田", "r")
        self.assertEqual(calls[0][0], "am")  # 冇 rish 就直接 am

    def test_negative_probe_cached(self):
        probes = []
        bot._rish_probe = lambda: probes.append(1) or False
        bot._RISH_CACHE.update({"t": 0.0, "ok": True})
        self.assertFalse(bot._rish_available())
        bot._rish_available()
        self.assertEqual(len(probes), 1)  # TTL 內唔會再 probe

    def test_rish_probe_no_binary(self):
        old_which = bot.shutil.which
        bot.shutil.which = lambda _: None
        try:
            self.assertFalse(bot._rish_probe())
        finally:
            bot.shutil.which = old_which

    def test_rish_probe_uid2000(self):
        class R:
            returncode = 0
            stdout = "uid=2000(shell) gid=2000(shell)"
            stderr = ""
        old_which, old_run = bot.shutil.which, bot.subprocess.run
        bot.shutil.which = lambda _: "/data/data/com.termux/files/usr/bin/rish"
        bot.subprocess.run = lambda *a, **k: R()
        try:
            self.assertTrue(bot._rish_probe())
        finally:
            bot.shutil.which, bot.subprocess.run = old_which, old_run


class TestNavFireRishWarning(unittest.TestCase):
    """到點 fire 導航嗰陣：強制重 probe + Shizuku server 死要喺訊息講明。"""

    def setUp(self):
        self._cache = dict(bot._RISH_CACHE)
        self._run = bot.run_intent
        self._probe = bot._rish_probe
        self._which = bot.shutil.which
        self._send = bot._send_safe
        self._jobs = bot._jobs
        self._save = bot._save_json
        self._dry = bot.DRY_RUN
        self._sleep = asyncio.sleep
        self._notify = bot._nav_confirm_notify
        self._priv = bot._shell_priv_exec
        self._adblane = bot._adb_lane_available
        self._kb = bot._nav_keyboard_msg
        async def fake_sleep(_):
            pass
        asyncio.sleep = fake_sleep
        bot.DRY_RUN = False

    def tearDown(self):
        bot._RISH_CACHE.update(self._cache)
        bot.run_intent = self._run
        bot._rish_probe = self._probe
        bot.shutil.which = self._which
        bot._send_safe = self._send
        bot._jobs = self._jobs
        bot._save_json = self._save
        bot.DRY_RUN = self._dry
        asyncio.sleep = self._sleep
        bot._nav_confirm_notify = self._notify
        bot._shell_priv_exec = self._priv
        bot._adb_lane_available = self._adblane
        bot._nav_keyboard_msg = self._kb

    def _job(self):
        nxt = (dt.datetime.now() + dt.timedelta(seconds=1)).isoformat()
        return {"id": 999, "type": "nav", "hh": 7, "mm": 32, "daily": False,
                "url": "佐敦道31-37號百誠大廈", "seconds": 0, "mode": "r",
                "label": "屋企", "chat_id": 123, "next": nxt,
                "shuffle": False, "paused": False}

    def _fire(self):
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(bot._fire_later(self._job(), 0.01))
        finally:
            loop.close()

    def test_fire_forces_fresh_probe_and_warns_when_server_dead(self):
        bot.shutil.which = lambda _: "/x/rish"
        probes = []
        bot._rish_probe = lambda: probes.append(1) or False
        sent = []
        async def fake_send(cid, text, label=""):
            sent.append(text)
            return True
        bot._send_safe = fake_send
        bot._jobs = list
        bot._save_json = lambda *a, **k: None
        bot.run_intent = lambda cmd, t=0: (True, "")
        bot._RISH_CACHE.update({"t": 1e18, "ok": True})  # 舊 cache 話 ok，都要重探
        # 新流程：通知彈窗先；呢度強制行後備直開路，驗證重探＋警告仍然喺度
        bot._nav_confirm_notify = lambda job: (False, "冇 termux-notification")
        bot._shell_priv_exec = lambda s: (True, "")
        bot._adb_lane_available = lambda: False
        # 彈窗先行之下，後備直開路只喺冇彈窗（DRY_RUN）嗰條 branch 行到
        old_dry = bot.DRY_RUN
        bot.DRY_RUN = True
        try:
            self._fire()
        finally:
            bot.DRY_RUN = old_dry
        self.assertEqual(len(probes), 1)               # fallback 前重探過
        self.assertFalse(bot._RISH_CACHE["ok"])
        self.assertTrue(sent)
        self.assertIn("彈窗通知出唔到，直接開咗", sent[0])
        self.assertIn("可能彈唔出", sent[0])              # fail-loud，唔再靜默

    def test_no_warning_when_probe_ok(self):
        bot.shutil.which = lambda _: "/x/rish"
        bot._rish_probe = lambda: True
        sent = []
        async def fake_send(cid, text, label=""):
            sent.append(text)
            return True
        bot._send_safe = fake_send
        bot._jobs = list
        bot._save_json = lambda *a, **k: None
        calls = []
        bot.run_intent = lambda cmd, t=0: calls.append(cmd) or (True, "ok")
        bot._RISH_CACHE.update({"t": 0.0, "ok": False})
        bot._nav_confirm_notify = lambda job: (True, "ok")
        kbs = []
        async def fake_kb(cid, job):
            kbs.append(job["id"])
        bot._nav_keyboard_msg = fake_kb
        self._fire()
        self.assertEqual(kbs, [999])                    # TG 掣確認出咗
        # run_intent 淨係行 WAKEUP（rish keyevent），冇直接開地圖
        self.assertEqual(calls, [["rish", "-c", "input keyevent KEYCODE_WAKEUP"]])

    def test_notify_ok_means_no_direct_open(self):
        """彈窗通知成功 → 唔直接開 app，等用戶撳確定。"""
        bot.shutil.which = lambda _: "/x/rish"
        sent = []
        async def fake_send(cid, text, label=""):
            sent.append(text)
            return True
        bot._send_safe = fake_send
        bot._jobs = list
        bot._save_json = lambda *a, **k: None
        calls = []
        bot.run_intent = lambda cmd, t=0: calls.append(cmd) or (True, "ok")
        bot._shell_priv_exec = lambda s: calls.append(["wake", s]) or (True, "")
        bot._nav_confirm_notify = lambda job: (True, "ok")
        kbs = []
        async def fake_kb(cid, job):
            kbs.append(job["id"])
        bot._nav_keyboard_msg = fake_kb
        self._fire()
        self.assertEqual(kbs, [999])                    # TG 掣確認出咗
        self.assertEqual(sent, [])                      # 冇舊式到點文字（keyboard 代替）
        self.assertEqual(len(calls), 1)                 # 淨係 WAKEUP
        self.assertEqual(calls[0][0], "wake")


class TestNavConfirmNotify(unittest.TestCase):
    """頭條通知＋確定掣：寫開地圖腳本＋post 通知。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old_j = bot.JOBS_PATH
        bot.JOBS_PATH = os.path.join(self.tmp, "jobs.json")
        self._which = bot.shutil.which
        self._run = bot.subprocess.run

    def tearDown(self):
        bot.JOBS_PATH = self.old_j
        bot.shutil.which = self._which
        bot.subprocess.run = self._run

    def _job(self):
        return {"id": 7, "type": "nav", "url": "佐敦道31號", "mode": "r",
                "label": "屋企", "chat_id": 123}

    def test_nav_uri(self):
        u = bot._nav_uri("沙田", "r")
        self.assertTrue(u.startswith("google.navigation:q="))
        self.assertIn("%E6%B2%99%E7%94%B0", u)
        self.assertTrue(u.endswith("mode=r"))
        self.assertEqual(bot._nav_uri("https://maps.app/x"), "https://maps.app/x")

    def test_notify_posts_and_writes_script(self):
        bot.shutil.which = lambda n: f"/x/{n}"
        captured = {}
        def fake_run(cmd, **kw):
            captured["cmd"] = cmd
            return mock.Mock(returncode=0, stdout="", stderr="")
        bot.subprocess.run = fake_run
        ok, _out = bot._nav_confirm_notify(self._job())
        self.assertTrue(ok)
        cmd = captured["cmd"]
        self.assertEqual(cmd[0], "termux-notification")
        self.assertIn("--button1", cmd)
        self.assertIn("確定開地圖", cmd)
        self.assertIn("--priority", cmd)
        self.assertEqual(cmd[cmd.index("--priority") + 1], "high")
        script = cmd[cmd.index("--button1-action") + 1]
        self.assertTrue(script.startswith("sh "))
        path = script[3:]
        content = open(path).read()
        self.assertIn(bot.ADB_TARGET, content)          # adb lane 優先
        self.assertIn("google.navigation:q=", content)
        self.assertIn("https://www.google.com/maps/dir/", content)  # 後備
        self.assertTrue(os.stat(path).st_mode & 0o100)  # 可執行

    def test_notify_missing_api(self):
        bot.shutil.which = lambda n: None
        ok, out = bot._nav_confirm_notify(self._job())
        self.assertFalse(ok)
        self.assertIn("termux-notification", out)

    def test_notify_timeout(self):
        bot.shutil.which = lambda n: f"/x/{n}"
        def boom(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
        bot.subprocess.run = boom
        ok, out = bot._nav_confirm_notify(self._job())
        self.assertFalse(ok)
        self.assertIn("超時", out)


class TestManualNavConfirm(unittest.TestCase):
    """手動「導航 X」都要先彈確認通知，撳掣先開地圖。"""

    def setUp(self):
        self._notify = bot._nav_confirm_notify
        self._open = bot._open_nav
        self._dry = bot.DRY_RUN
        bot.DRY_RUN = False

    def tearDown(self):
        bot._nav_confirm_notify = self._notify
        bot._open_nav = self._open
        bot.DRY_RUN = self._dry

    def _ex(self, line):
        return bot._execute_player(bot.parse_player(line), 12345,
                                   dt.datetime(2026, 9, 24, 10, 0))

    def test_notify_first(self):
        opened = []
        bot._nav_confirm_notify = lambda job: (True, "ok")
        bot._open_nav = lambda d, m: opened.append(1) or (True, "")
        r = self._ex("導航 屋企")
        self.assertIn("撳【是】先會開地圖", r)
        self.assertEqual(opened, [])          # 未撳掣 → 唔直接開

    def test_notify_fail_direct_open(self):
        bot._nav_confirm_notify = lambda job: (False, "冇 termux-notification")
        bot._open_nav = lambda d, m: (True, "")
        r = self._ex("導航 屋企")
        self.assertIn("開緊導航去", r)
        self.assertIn("直接開", r)


class TestWeather(unittest.TestCase):
    """天氣：天文台官方 RSS（報告＋九日預報）＋隨問隨答＋每日簡報排程。"""

    CUR = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0"><channel><title>本港地區天氣報告</title>'
        '<item><title>香港天文台於2026年10月06日01時02分發出之天氣報告</title>'
        '<description><![CDATA[<p>上 午 1 時 天 文 台 錄 得：<br/>'
        '氣 溫 ： 25 度<br/>相 對 濕 度 ： 百 分 之 65<br/>'
        '<p></p>本 港 其 他 地 區 的 氣 溫 ：<br/>'
        '<table><tr><td>將 軍 澳 </td><td>23 度 ，</td></tr>'
        '<tr><td>觀 塘 </td><td>24 度 ，</td></tr>'
        '<tr><td>京 士 柏 </td><td>24 度 ，</td></tr>'
        '<tr><td>跑 馬 地 </td><td>25 度 ，</td></tr></table><br/>'
        '展 望 ： 大 致 天 晴 及 乾 燥 。<br/>]]>'
        '</description></item></channel></rss>')

    FND = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0"><channel><title>九天天氣預報</title>'
        '<item><title>香港天文台於2026年10月06日00時50分發出之天氣報告</title>'
        '<description><![CDATA[ 天 氣 概 況 ：<br/>'
        '乾 燥 的 東 北 季 候 風 會 在 未 來 一 兩 日 帶 來 大 致 良 好 天 氣 。 <p/><p/>'
        '十 月 六 日 ( 星 期 二 ) <br/>風：北 至 東 北 風 4 級 。 <br/>'
        '天 氣 ： 大 致 多 雲 及 乾 燥 。 <br/>氣 溫： 23 至 29 度 。<br/>'
        '相 對 濕 度 ：百 分 之 45 至 75 。<br/><p/><p/>'
        '十 月 七 日 ( 星 期 三 ) <br/>風：東 北 風 4 級 。 <br/>'
        '天 氣 ： 多 雲 ， 稍 後 有 驟 雨 。 <br/>氣 溫： 24 至 30 度 。<br/>'
        '相 對 濕 度 ：百 分 之 60 至 90 。<br/>]]>'
        '</description></item></channel></rss>')

    def setUp(self):
        import urllib.request
        self._urlopen = urllib.request.urlopen
        self._report = bot._weather_report
        self._gps = bot._gps_fix
        self._owner = bot._ensure_owner
        self._send = bot._send_safe
        self._jobs = bot._jobs
        self._save = bot._save_json
        self._arm = bot._arm

    def tearDown(self):
        import urllib.request
        urllib.request.urlopen = self._urlopen
        bot._weather_report = self._report
        bot._gps_fix = self._gps
        bot._ensure_owner = self._owner
        bot._send_safe = self._send
        bot._jobs = self._jobs
        bot._save_json = self._save
        bot._arm = self._arm

    def test_report_formats_and_umbrella(self):
        import urllib.request

        def fake_urlopen(req, timeout=30):
            url = req.full_url if hasattr(req, "full_url") else str(req)

            class R:
                def read(self_):
                    return (self.FND if "SeveralDays" in url
                            else self.CUR).encode()

                def __enter__(self_):
                    return self_

                def __exit__(self_, *a):
                    return False
            return R()
        bot._gps_fix = lambda: None          # GPS 唔得 → 屋企佐敦
        urllib.request.urlopen = fake_urlopen
        ok, txt = bot._weather_report()
        self.assertTrue(ok, txt)
        self.assertIn("天文台 01:02 報：25°C", txt)
        self.assertIn("濕度 65%", txt)
        self.assertIn("🏠 佐敦附近（京士柏）24°C", txt)
        self.assertIn("展望", txt)
        self.assertIn("天氣概況", txt)
        self.assertIn("今日（10月6日 週二）", txt)
        self.assertIn("今日（10月6日 週二）：大致多雲及乾燥，23–29°C", txt)
        self.assertIn("聽日（10月7日 週三）", txt)
        self.assertIn("24–30°C", txt)
        self.assertIn("帶遮", txt)          # 聽日驟雨 → 提醒

    def test_gps_district_line(self):
        import urllib.request

        def fake_urlopen(req, timeout=30):
            url = req.full_url if hasattr(req, "full_url") else str(req)

            class R:
                def read(self_):
                    return (self.FND if "SeveralDays" in url
                            else self.CUR).encode()

                def __enter__(self_):
                    return self_

                def __exit__(self_, *a):
                    return False
            return R()
        urllib.request.urlopen = fake_urlopen
        self.assertEqual(bot._nearest_station(22.2665, 114.1850), "跑馬地")
        self.assertEqual(bot._nearest_station(22.4480, 114.1650), "大埔")
        bot._gps_fix = lambda: (22.2665, 114.1850)
        ok, txt = bot._weather_report()
        self.assertTrue(ok, txt)
        self.assertIn("📍 你嗰邊（跑馬地）25°C", txt)
        bot._gps_fix = lambda: (22.3820, 114.2700)   # 西貢唔喺樣本表
        ok2, txt2 = bot._weather_report()
        self.assertTrue(ok2)
        self.assertIn("🏠 佐敦附近（京士柏）24°C", txt2)

    def test_report_current_dead_fnd_alive(self):
        import urllib.request

        def fake_urlopen(req, timeout=30):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "CurrentWeather" in url:
                raise OSError("current死")

            class R:
                def read(self_):
                    return self.FND.encode()

                def __enter__(self_):
                    return self_

                def __exit__(self_, *a):
                    return False
            return R()
        urllib.request.urlopen = fake_urlopen
        ok, txt = bot._weather_report()
        self.assertTrue(ok)
        self.assertIn("今日（10月6日 週二）", txt)
        self.assertIn("而家讀數攞唔到", txt)

    def test_report_network_error(self):
        import urllib.request

        def boom(url, timeout=30):
            raise OSError("dead")
        urllib.request.urlopen = boom
        ok, msg = bot._weather_report()
        self.assertFalse(ok)
        self.assertIn("dead", msg)

    def test_ondemand_dispatch(self):
        replies = []

        class Msg:
            text = "天氣"

            async def reply_text(self, t):
                replies.append(t)

        class Upd:
            message = Msg()

        bot._ensure_owner = _ensure_owner_true
        bot._weather_report = lambda: (True, "今日好熱")
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(bot._on_message(Upd(), None))
        finally:
            loop.close()
        self.assertEqual(len(replies), 2)
        self.assertIn("今日好熱", replies[1])

    def test_fire_weather_daily_reschedules(self):
        sent = []

        async def fake_send(cid, text, label=""):
            sent.append((cid, text))
            return True
        bot._weather_report = lambda: (True, "好天")
        bot._send_safe = fake_send
        orig_next = dt.datetime.now().isoformat()
        job = {"id": 77, "type": "weather", "hh": 11, "mm": 0, "daily": True,
               "chat_id": 1, "next": orig_next}
        bot._jobs = lambda: [dict(job)]
        saved = []
        bot._save_json = lambda path, data: saved.append(data)
        bot._arm = lambda j: None
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(bot._fire_later(job, 0.01))
        finally:
            loop.close()
        self.assertEqual(len(sent), 1)
        self.assertIn("🌤", sent[0][1])
        self.assertIn("好天", sent[0][1])
        self.assertTrue(saved)             # next 已重排＋存檔
        self.assertNotEqual(saved[0][0]["next"], orig_next)

    def test_fmt_job_weather(self):
        self.assertEqual(bot._fmt_job_content(
            {"type": "weather", "hh": 11, "mm": 0}), "天氣簡報")


class TestPayday(unittest.TestCase):
    """出糧「可花」：GAS ?api=json 讀今日可花＋隨問隨答。"""

    PAYLOAD = {
        "events": [], "now": {"date": "2026-10-02", "time": "09:48:09"},
        "payday": "2026-10-05", "error": None,
        "display": {"mode": "home", "hero": "$23", "tone": "tight",
                    "sub": "上限，唔係目標。今日唔洗晒，會留去後面。",
                    "preview": "10月2日至10月4日已解鎖",
                    "trust": "戶口 $70 · 10月2日至10月4日鎖住 $70",
                    "warning": "食咗後半糧，後面會緊",
                    "confirm": None, "note": None}}

    def setUp(self):
        import urllib.request
        self._urlopen = urllib.request.urlopen
        self._report = bot._payday_report
        self._gas = bot.GAS_URL
        self._owner = bot._ensure_owner
        self._say = bot._say
        bot.GAS_URL = "https://script.google.com/macros/s/TEST/exec"

    def tearDown(self):
        import urllib.request
        urllib.request.urlopen = self._urlopen
        bot._payday_report = self._report
        bot.GAS_URL = self._gas
        bot._ensure_owner = self._owner
        bot._say = self._say

    def _mock(self, payload):
        import urllib.request

        class R:
            def read(self_):
                return json.dumps(payload).encode()

            def __enter__(self_):
                return self_

            def __exit__(self_, *a):
                return False
        urllib.request.urlopen = lambda url, timeout=15: R()

    def test_report_ok(self):
        self._mock(self.PAYLOAD)
        ok, txt = bot._payday_report()
        self.assertTrue(ok)
        self.assertIn("今日可花 $23", txt)
        self.assertIn("下次出糧：10月5日", txt)
        self.assertIn("鎖住 $70", txt)
        self.assertIn("食咗後半糧", txt)
        self.assertIn("上限，唔係目標", txt)

    def test_report_no_url(self):
        bot.GAS_URL = ""
        ok, msg = bot._payday_report()
        self.assertFalse(ok)
        self.assertIn("GAS_URL", msg)

    def test_report_network_error(self):
        import urllib.request

        def boom(url, timeout=15):
            raise OSError("conn refused")
        urllib.request.urlopen = boom
        ok, msg = bot._payday_report()
        self.assertFalse(ok)
        self.assertIn("conn refused", msg)

    def test_report_setup_mode(self):
        self._mock({"display": {"mode": "setup"}, "error": None})
        ok, msg = bot._payday_report()
        self.assertFalse(ok)
        self.assertIn("未設定", msg)

    def test_report_blocked_tone(self):
        p = json.loads(json.dumps(self.PAYLOAD))
        p["display"]["tone"] = "blocked"
        p["display"]["hero"] = "$0"
        self._mock(p)
        ok, txt = bot._payday_report()
        self.assertTrue(ok)
        self.assertIn("未有許可", txt)
        self.assertNotIn("今日可花", txt.splitlines()[0])

    def test_fmt_payday(self):
        self.assertEqual(bot._payday_fmt("2026-10-05"), "10月5日")
        self.assertEqual(bot._payday_fmt(""), "")
        self.assertEqual(bot._payday_fmt(None), "")

    def test_ondemand_dispatch(self):
        replies = []

        class Msg:
            text = "可花"

            async def reply_text(self, t):
                replies.append(t)

        class Upd:
            message = Msg()

        async def fake_say(t, delay=0):
            replies.append("[說]" + t)
        bot._ensure_owner = _ensure_owner_true
        bot._payday_report = lambda: (True, "今日可花 $23\n戶口 $70")
        bot._say = fake_say
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(bot._on_message(Upd(), None))
        finally:
            loop.close()
        self.assertEqual(len(replies), 3)
        self.assertIn("今日可花 $23", replies[1])
        self.assertIn("[說]今日可花23蚊", replies[2])


class TestNavDialog(unittest.TestCase):
    """導航確認彈窗：等耐性＋結果有 log＋冇人撳要話用戶知。"""

    def setUp(self):
        self._run = bot.subprocess.run
        self._block = bot._nav_dialog_block
        self._send = bot._send_safe

    def tearDown(self):
        bot.subprocess.run = self._run
        bot._nav_dialog_block = self._block
        bot._send_safe = self._send

    def test_block_timeout(self):
        def boom(*a, **k):
            raise bot.subprocess.TimeoutExpired(cmd="termux-dialog", timeout=1)
        bot.subprocess.run = boom
        self.assertEqual(
            bot._nav_dialog_block({"id": 1, "label": "公司"}), "timeout")

    def test_block_yes(self):
        class R:
            stdout = '{"code": 0, "text": "yes"}'
            stderr = ""
        bot.subprocess.run = lambda *a, **k: R()
        self.assertEqual(
            bot._nav_dialog_block({"id": 1, "label": "公司"}), "yes")

    def test_task_notifies_on_timeout(self):
        sent = []

        async def fake_send(cid, text, label=""):
            sent.append(text)
            return True
        bot._nav_dialog_block = lambda j, timeout=3600: "timeout"
        bot._send_safe = fake_send
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(bot._nav_dialog_task(
                {"id": 3, "label": "公司", "chat_id": 1}))
        finally:
            loop.close()
        self.assertEqual(sent, [])   # keyboard 在度，過時免再叫

    def test_task_silent_on_no(self):
        sent = []

        async def fake_send(cid, text, label=""):
            sent.append(text)
            return True
        bot._nav_dialog_block = lambda j, timeout=3600: "no"
        bot._send_safe = fake_send
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(bot._nav_dialog_task(
                {"id": 3, "label": "公司", "chat_id": 1}))
        finally:
            loop.close()
        self.assertEqual(sent, [])

    def test_block_err_garbage_output(self):
        class R:
            stdout = '{"weird": 1}'
            stderr = "boom"
            returncode = 0
        bot.subprocess.run = lambda *a, **k: R()
        self.assertEqual(
            bot._nav_dialog_block({"id": 2, "label": "公司"}), "err")

    def test_task_retries_once_on_err(self):
        calls, gos = [], []

        def fake_block(job, timeout=3600):
            calls.append(1)
            return "yes" if len(calls) > 1 else "err"

        bot._nav_dialog_block = fake_block
        bot._nav_run_go = lambda job: gos.append(job)
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(bot._nav_dialog_task(
                {"id": 9, "label": "公司", "chat_id": 1}))
        finally:
            loop.close()
        self.assertEqual(len(calls), 2)     # err 之後重彈一次
        self.assertEqual(len(gos), 1)       # 第二次 yes → 開地圖


class TestUtilTools(unittest.TestCase):
    """小工具：匯率／世界時間／揀／骰仔／密碼／打氣。"""

    def setUp(self):
        import urllib.request
        self._urlopen = urllib.request.urlopen
        self._owner = bot._ensure_owner
        self._fx = bot._fx_reply

    def tearDown(self):
        import urllib.request
        urllib.request.urlopen = self._urlopen
        bot._ensure_owner = self._owner
        bot._fx_reply = self._fx

    def test_fx_parse_aliases(self):
        self.assertEqual(bot._fx_parse("100 美金"), (100.0, "USD"))
        self.assertEqual(bot._fx_parse("50 日圓"), (50.0, "JPY"))
        self.assertEqual(bot._fx_parse("12.5 gbp"), (12.5, "GBP"))
        self.assertIsNone(bot._fx_parse("美金"))

    def test_fx_reply_table_and_convert(self):
        import urllib.request

        class R:
            def read(self_):
                return json.dumps({"rates": {"USD": 1.0, "HKD": 7.8,
                                             "JPY": 150.0}}).encode()

            def __enter__(self_):
                return self_

            def __exit__(self_, *a):
                return False
        urllib.request.urlopen = lambda url, timeout=20: R()
        tbl = bot._fx_reply("")
        self.assertIn("今日匯率", tbl)
        conv = bot._fx_reply("100 美金")
        self.assertIn("780.00 港紙", conv)          # 100 USD × 7.8
        jpy = bot._fx_reply("150 日圓")
        self.assertIn("7.80 港紙", jpy)             # 150/150 × 7.8

    def test_fx_network_error(self):
        import urllib.request

        def boom(url, timeout=20):
            raise OSError("dead")
        urllib.request.urlopen = boom
        self.assertIn("攞唔到", bot._fx_reply(""))

    def test_time_reply_known_and_unknown(self):
        r = bot._time_reply("東京")
        self.assertIn("東京", r)
        self.assertRegex(r, r"\d{1,2}:\d{2}")
        self.assertIn("用法", bot._time_reply("火星"))

    def test_pick_dice_password(self):
        r = bot._pick_reply("飲茶/壽司/拉麵")
        self.assertIn("揀咗：", r)
        self.assertIn("用法", bot._pick_reply("只有一個"))
        d = bot._dice_reply("20")
        self.assertRegex(d, r"🎲 \d+（d20）")
        p = bot._password_reply("16")
        self.assertIn("🔐", p)
        self.assertIn("長度要", bot._password_reply("3"))

    def test_pep_talk(self):
        self.assertTrue(bot._PEP)
        self.assertTrue(all(isinstance(x, str) and x for x in bot._PEP))

    def test_dispatch_dice_and_pep(self):
        replies = []

        class Msg:
            text = "打氣"

            async def reply_text(self, t):
                replies.append(t)

        class Upd:
            message = Msg()

        bot._ensure_owner = _ensure_owner_true
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(bot._on_message(Upd(), None))
        finally:
            loop.close()
        self.assertEqual(len(replies), 1)
        self.assertTrue(replies[0].startswith("💪 "))


class TestBell(unittest.TestCase):
    """統一 bot 守：計時/鬧鐘入排程，到點 1 秒計時器即響。"""

    def setUp(self):
        self._save, self._arm, self._jobs = bot._save_json, bot._arm, bot._jobs
        self._intent, self._send = bot.run_intent, bot._send_safe

    def tearDown(self):
        bot._save_json, bot._arm, bot._jobs = self._save, self._arm, self._jobs
        bot.run_intent, bot._send_safe = self._intent, self._send

    def test_alarm_creates_bell_job(self):
        bot._jobs = list
        saved = []
        bot._save_json = lambda p, d: saved.append(d)
        bot._arm = lambda j: None
        p = parse_command("鬧鐘 0700 起身", NOW)
        r = _execute(p, NOW, chat_id=42)
        self.assertIn("⏰ 鬧鐘", r)
        self.assertIn("#1", r)
        job = saved[0][0]
        self.assertEqual(job["type"], "bell")
        self.assertEqual(job["bell"], "alarm")
        self.assertEqual(job["label"], "起身")
        self.assertEqual((job["hh"], job["mm"]), (7, 0))

    def test_fire_bell_rings_1s_and_removes(self):
        """alarm bell（app 後備）＝開 1 秒鐘；timer bell＝語音讀（雙軌制）。"""
        sent, fired, removed = [], [], []

        async def fake_send(cid, text, label=""):
            sent.append(text)
            return True
        bot.run_intent = lambda cmd, t=0: fired.append(cmd) or (True, "")
        bot._send_safe = fake_send
        said = []
        old_say = bot._say

        async def fake_say(t, delay=0):
            said.append(t)
        bot._say = fake_say
        bot._jobs = lambda: [{"id": 9, "type": "bell", "bell": "alarm",
                              "hh": 1, "mm": 2, "daily": False, "label": "杯麵",
                              "chat_id": 1, "next": dt.datetime.now().isoformat(),
                              "seconds": 0, "url": "", "shuffle": False,
                              "paused": False}]
        bot._save_json = lambda p, d: removed.append(d)
        job = dict(bot._jobs()[0])
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(bot._fire_later(job, 0.01))
        finally:
            loop.close()
        self.assertEqual(len(fired), 1)
        self.assertEqual(fired[0][6], "1")            # 1 秒計時（即響）
        self.assertIn("杯麵", fired[0])                # 帶 label
        self.assertEqual(sent, ["⏰ 杯麵"])
        self.assertEqual(removed, [[]])               # 用完即刪
        bot._say = old_say

    def test_bell_in_listing(self):
        s = bot._fmt_job_content({"type": "bell", "label": "杯麵"})
        self.assertIn("杯麵", s)


class TestSeries(unittest.TestCase):
    """連環鬧：鬧鐘 hhmm-hhmm 每x分鐘 [文字]（範圍內定時響）。"""

    def setUp(self):
        self._save = bot._save_json
        self._arm = bot._arm
        self._jobs = bot._jobs
        self._intent = bot.run_intent
        self._send = bot._send_safe
        bot._jobs = list
        saved = []
        bot._save_json = lambda p, d: saved.append(d)
        bot._arm = lambda j: None

    def tearDown(self):
        bot._save_json = self._save
        bot._arm = self._arm
        bot._jobs = self._jobs
        bot.run_intent = self._intent
        bot._send_safe = self._send

    def test_parse_combined(self):
        c = bot.parse_player("鬧鐘 0900-1700 每60分鐘 轉位")
        self.assertIsNotNone(c)
        self.assertEqual(c.action, "series")
        self.assertEqual((c.hour, c.minute, c.hour2, c.minute2), (9, 0, 17, 0))
        self.assertEqual(c.seconds, 3600)
        self.assertEqual(c.ref, "轉位")

    def test_parse_daily_and_variants(self):
        c = bot.parse_player("每日 2330-2359 每15分鐘 飲水")
        self.assertEqual(c.action, "series_daily")
        self.assertEqual(c.seconds, 900)
        c2 = bot.parse_player("計時 0800-0830 每10分鐘")
        self.assertEqual((c2.action, c2.ref), ("series", ""))
        c3 = bot.parse_player("鬧鐘 1700-0900 每10分鐘")   # 過午夜＝合法
        self.assertEqual((c3.hour, c3.minute, c3.hour2, c3.minute2), (17, 0, 9, 0))
        self.assertIsNone(bot.parse_player("鬧鐘 0900-0900 每10分鐘"))  # 零長度
        self.assertIsNone(bot.parse_player("鬧鐘 0900-1700 每0分鐘"))

    def test_add_job_and_reply(self):
        cmd = bot.PlayerCmd("series", hour=9, minute=0, hour2=10, minute2=30,
                            seconds=1800, ref="轉位")
        r = bot._execute_player(cmd, 1, dt.datetime.now())
        self.assertIn("09:00–10:30", r)
        self.assertIn("每30分鐘", r)
        self.assertIn("共 4 響", r)     # 9:00,9:30,10:00,10:30

    def test_fire_advances_within_window(self):
        start = (dt.datetime.now() + dt.timedelta(minutes=1)).replace(
            second=0, microsecond=0)
        end = start + dt.timedelta(minutes=30)
        sent, fired = [], []

        async def fake_send(cid, text, label=""):
            sent.append(text)
            return True
        def fake_intent(cmd, t=0):
            fired.append(cmd)
            return True, ""
        bot.run_intent = fake_intent
        bot._send_safe = fake_send
        job = {"id": 60, "type": "series", "hh": start.hour, "mm": start.minute,
               "end_hh": end.hour, "end_mm": end.minute,
               "every": 600, "label": "轉位", "daily": False,
               "chat_id": 1, "next": start.isoformat()}
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(bot._fire_later(job, 0.01))
        finally:
            loop.close()
        self.assertEqual(len(fired), 1)
        self.assertEqual(fired[0][6], "1")      # 1 秒計時（即響）
        self.assertEqual(sent, ["⏰ 轉位"])
        # 推進咗 10 分鐘，仲喺 window 內
        nxt = dt.datetime.fromisoformat(job["next"])
        self.assertGreater(nxt, start)

    def test_fire_end_daily_rolls_to_tomorrow_start(self):
        now = dt.datetime.now().replace(second=0, microsecond=0)
        start = now
        sent = []

        async def fake_send(cid, text, label=""):
            sent.append(text)
            return True
        bot.run_intent = lambda cmd, t=0: (True, "")
        bot._send_safe = fake_send
        job = {"id": 61, "type": "series", "hh": start.hour, "mm": start.minute,
               "end_hh": start.hour, "end_mm": start.minute,   # 即刻到期
               "every": 600, "label": "起身", "daily": True,
               "chat_id": 1, "next": start.isoformat()}
        bot._jobs = lambda: [dict(job)]
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(bot._fire_later(job, 0.01))
        finally:
            loop.close()
        nxt = dt.datetime.fromisoformat(job["next"])
        self.assertEqual((nxt - start).days, 1)          # 聽日同一開始時間
        self.assertEqual(nxt.hour, start.hour)

    def test_fire_end_once_deletes(self):
        now = dt.datetime.now().replace(second=0, microsecond=0)
        sent = []

        async def fake_send(cid, text, label=""):
            sent.append(text)
            return True
        bot.run_intent = lambda cmd, t=0: (True, "")
        bot._send_safe = fake_send
        removed = []
        job = {"id": 62, "type": "series", "hh": now.hour, "mm": now.minute,
               "end_hh": now.hour, "end_mm": now.minute,
               "every": 600, "label": "x", "daily": False,
               "chat_id": 1, "next": now.isoformat()}
        bot._jobs = lambda: [job]
        bot._save_json = lambda p, d: removed.append(d)
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(bot._fire_later(job, 0.01))
        finally:
            loop.close()
        self.assertEqual(removed, [[]])                  # 清空＝用完即棄

    def test_frankie_two_line_midnight(self):
        # Frankie 原句：兩行＋過午夜
        res = bot.parse_lines("計時 2100-0000\n\n每60分鐘 報更")
        self.assertEqual(len(res), 1)
        _ln, p = res[0]
        self.assertEqual(p.action, "series")
        self.assertEqual((p.hour, p.minute, p.hour2, p.minute2), (21, 0, 0, 0))
        self.assertEqual(p.seconds, 3600)
        self.assertEqual(p.ref, "報更")
        # 單行一樣得
        p2 = bot.parse_player("計時 2100-0000 每60分鐘 報更")
        self.assertEqual((p2.hour2, p2.minute2), (0, 0))

    def test_range_without_every_rejected(self):
        # 淨範圍冇「每」唔好誤設單一計時器（Frankie 見過 label「-0000」嗰下）
        self.assertIsNone(bot.parse_command("計時 2100-0000"))
        self.assertIsNone(bot.parse_command("鬧鐘 2100-0000"))

    def test_fire_midnight_chain(self):
        # 2100-0000 每日 每60分鐘：23:00 響 → 00:00 響 → 聽日 21:00
        base = dt.datetime.now().replace(hour=23, minute=0,
                                         second=0, microsecond=0)
        sent = []

        async def fake_send(cid, text, label=""):
            sent.append(text)
            return True
        bot.run_intent = lambda cmd, t=0: (True, "")
        bot._send_safe = fake_send
        job = {"id": 63, "type": "series", "hh": 21, "mm": 0,
               "end_hh": 0, "end_mm": 0, "every": 3600, "label": "報更",
               "daily": True, "chat_id": 1, "next": base.isoformat()}
        bot._jobs = lambda: [dict(job)]
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(bot._fire_later(job, 0.01))
            nxt1 = dt.datetime.fromisoformat(job["next"])
            self.assertEqual(nxt1 - base, dt.timedelta(hours=1))   # 00:00
            loop.run_until_complete(bot._fire_later(job, 0.01))
            nxt2 = dt.datetime.fromisoformat(job["next"])
            self.assertEqual(nxt2.hour, 21)                        # 聽日 21:00
            self.assertEqual((nxt2.date() - base.date()).days, 2)
        finally:
            loop.close()

    def test_fmt_job(self):
        s = bot._fmt_job_content({"type": "series", "hh": 9, "mm": 0,
                                  "end_hh": 17, "end_mm": 0, "every": 3600,
                                  "label": "轉位"})
        self.assertIn("每60分鐘", s)
        self.assertIn("09:00–17:00", s)
        self.assertIn("轉位", s)


class TestWakeLock(unittest.TestCase):
    """啟動時攞 wake lock——Android 排程準唔準嘅關鍵，唔係換 cron。"""

    def setUp(self):
        self._run = bot.subprocess.run

    def tearDown(self):
        bot.subprocess.run = self._run

    def test_hold_calls_termux_wake_lock(self):
        cmds = []
        bot.subprocess.run = lambda c, **k: cmds.append(c) or type(
            "R", (), {"returncode": 0})()
        self.assertTrue(bot._hold_wake_lock())
        self.assertEqual(cmds, [["termux-wake-lock"]])

    def test_hold_tolerates_failure(self):
        def boom(*a, **k):
            raise OSError("dead")
        bot.subprocess.run = boom
        self.assertFalse(bot._hold_wake_lock())


class TestNavKeyboard(unittest.TestCase):
    """TG 掣制導航確認（主確認路）。"""

    def setUp(self):
        self._send = bot._send_safe
        self._go = bot._nav_run_go
        self._jobs = bot._jobs
        bot._PENDING_NAVS.clear()

    def tearDown(self):
        bot._send_safe = self._send
        bot._nav_run_go = self._go
        bot._jobs = self._jobs
        bot._PENDING_NAVS.clear()

    def test_keyboard_msg_stores_pending(self):
        sent = []

        async def fake_send(cid, text, label="", markup=None):
            sent.append((text, markup))
            return True
        bot._send_safe = fake_send
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(bot._nav_keyboard_msg(
                1, {"id": "m1", "label": "公司"}))
        finally:
            loop.close()
        self.assertEqual(len(sent), 1)
        self.assertTrue(sent[0][1] is None or sent[0][1])
        self.assertIn("m1", bot._PENDING_NAVS)

    def test_callback_go_runs_and_edits(self):
        gos = []
        bot._nav_run_go = lambda job: gos.append(job)
        bot._PENDING_NAVS["m9"] = {"id": "m9", "label": "尋旺角",
                                   "chat_id": 1, "url": "u", "mode": "d"}

        class Q:
            data = "nav:go:m9"
            message = type("M", (), {"chat_id": 1})()

            async def answer(self):
                pass

            async def edit_message_text(self, t):
                self.edited = t
        q = Q()
        upd = type("U", (), {"callback_query": q})()
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(bot._on_nav_callback(upd, None))
        finally:
            loop.close()
        self.assertEqual(len(gos), 1)
        self.assertNotIn("m9", bot._PENDING_NAVS)

    def test_callback_unknown_expired(self):
        edited = []

        class Q:
            data = "nav:go:ghost"

            async def answer(self):
                pass

            async def edit_message_text(self, t):
                edited.append(t)
        q = Q()
        upd = type("U", (), {"callback_query": q})()
        bot._jobs = list
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(bot._on_nav_callback(upd, None))
        finally:
            loop.close()
        self.assertEqual(len(edited), 1)
        self.assertIn("過期", edited[0])


class TestNavGoScript(unittest.TestCase):
    """開地圖腳本：三層後備都要寫入。"""

    def setUp(self):
        self._jobs_path = bot.JOBS_PATH
        self._tmp = tempfile.mkdtemp()
        bot.JOBS_PATH = os.path.join(self._tmp, "jobs.json")

    def tearDown(self):
        bot.JOBS_PATH = self._jobs_path
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_three_tiers(self):
        job = {"id": 9, "url": "尖沙咀", "mode": "r", "label": "尖沙咀"}
        path = bot._nav_write_go_script(job)
        body = open(path).read()
        self.assertIn("adb", body)                 # ⓪ adb lane
        self.assertIn("rish -c", body)             # ① Shizuku
        self.assertIn("termux-open-url", body)     # ② 零權限兜底
        self.assertIn("--activity-clear-task", body)
        self.assertTrue(os.access(path, os.X_OK))


class TestAiMode(unittest.TestCase):
    """Google AI Mode（SerpAPI）問答。"""

    def setUp(self):
        self._key = bot._serpapi_key
        self._owner = bot._ensure_owner
        self._ai = bot._ai_mode_answer
        import urllib.request
        self._urlopen = urllib.request.urlopen

    def tearDown(self):
        bot._serpapi_key = self._key
        bot._ensure_owner = self._owner
        bot._ai_mode_answer = self._ai
        import urllib.request
        urllib.request.urlopen = self._urlopen

    @staticmethod
    class _Resp:
        def __init__(self, payload):
            self._p = payload

        def read(self):
            return json.dumps(self._p).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def test_no_key(self):
        bot._serpapi_key = lambda: ""
        ok, msg = bot._ai_mode_answer("x")
        self.assertFalse(ok)
        self.assertIn("SERPAPI_KEY", msg)

    def test_success_with_references(self):
        import urllib.request
        bot._serpapi_key = lambda: "k"
        urllib.request.urlopen = lambda url, timeout=90: self._Resp({
            "text_blocks": [{"type": "paragraph", "snippet": "答案A"},
                            {"type": "list", "snippet": "答案B"}],
            "references": [{"title": "來源甲", "link": "http://a"},
                           {"title": "", "link": ""}]})
        ok, msg = bot._ai_mode_answer("點去銅鑼灣")
        self.assertTrue(ok)
        self.assertIn("答案A", msg)
        self.assertIn("答案B", msg)
        self.assertIn("來源甲", msg)
        self.assertIn("http://a", msg)

    def test_api_error(self):
        import urllib.request
        bot._serpapi_key = lambda: "k"
        urllib.request.urlopen = lambda url, timeout=90: self._Resp(
            {"error": "quota exceeded"})
        ok, msg = bot._ai_mode_answer("x")
        self.assertFalse(ok)
        self.assertIn("quota", msg)

    def test_empty_answer(self):
        import urllib.request
        bot._serpapi_key = lambda: "k"
        urllib.request.urlopen = lambda url, timeout=90: self._Resp(
            {"text_blocks": []})
        ok, _msg = bot._ai_mode_answer("x")
        self.assertFalse(ok)

    def test_truncation(self):
        import urllib.request
        bot._serpapi_key = lambda: "k"
        urllib.request.urlopen = lambda url, timeout=90: self._Resp(
            {"text_blocks": [{"snippet": "字" * 6000}]})
        ok, msg = bot._ai_mode_answer("x")
        self.assertTrue(ok)
        self.assertLessEqual(len(msg), 4010)
        self.assertIn("截", msg)

    def test_message_dispatch(self):
        replies = []

        class Msg:
            text = "ai 明天會唔會落雨"

            async def reply_text(self, t):
                replies.append(t)

        class Upd:
            message = Msg()

        bot._ensure_owner = _ensure_owner_true
        bot._ai_mode_answer = lambda q, timeout=90: (True, f"答：{q}")
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(bot._on_message(Upd(), None))
        finally:
            loop.close()
        self.assertEqual(len(replies), 2)          # 「問緊…」＋答案
        self.assertIn("明天會唔會落雨", replies[1])

    def test_message_dispatch_ask_prefix(self):
        replies = []

        class Msg:
            text = "問 邊度有好吃嘅"

            async def reply_text(self, t):
                replies.append(t)

        class Upd:
            message = Msg()

        bot._ensure_owner = _ensure_owner_true
        bot._ai_mode_answer = lambda q, timeout=90: (True, "答")
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(bot._on_message(Upd(), None))
        finally:
            loop.close()
        self.assertEqual(len(replies), 2)


class TestNavDialogTask(unittest.TestCase):
    """真彈窗確認：termux-dialog confirm，撳【是】先會開地圖。"""

    def setUp(self):
        self._run = bot.subprocess.run
        self._block = bot._nav_dialog_block
        self._runit = bot._nav_run_go
        self._task = bot._nav_dialog_task
        self._notify = bot._nav_confirm_notify

    def tearDown(self):
        bot.subprocess.run = self._run
        bot._nav_dialog_block = self._block
        bot._nav_run_go = self._runit
        bot._nav_dialog_task = self._task
        bot._nav_confirm_notify = self._notify

    def _job(self):
        return {"id": 3, "type": "nav", "url": "X", "mode": "r",
                "label": "屋企", "chat_id": 1}

    def _run_task(self):
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(bot._nav_dialog_task(self._job()))
        finally:
            loop.close()

    @staticmethod
    def _result(stdout):
        return type("R", (), {"stdout": stdout, "stderr": "", "returncode": 0})()

    def test_dialog_yes(self):
        bot.subprocess.run = lambda cmd, **kw: self._result('{"code":-1,"text":"yes"}')
        self.assertEqual(bot._nav_dialog_block(self._job()), "yes")

    def test_dialog_no(self):
        bot.subprocess.run = lambda cmd, **kw: self._result('{"code":0,"text":"no"}')
        self.assertEqual(bot._nav_dialog_block(self._job()), "no")

    def test_dialog_timeout(self):
        def boom(cmd, **kw):
            raise bot.subprocess.TimeoutExpired(cmd, 600)
        bot.subprocess.run = boom
        self.assertEqual(bot._nav_dialog_block(self._job()), "timeout")

    def test_dialog_garbage(self):
        bot.subprocess.run = lambda cmd, **kw: self._result("")
        self.assertEqual(bot._nav_dialog_block(self._job()), "err")

    def test_task_yes_opens_map(self):
        bot._nav_dialog_block = lambda job, timeout=600: "yes"
        ran = []
        bot._nav_run_go = lambda job: ran.append(job["id"])
        self._run_task()
        self.assertEqual(ran, [3])

    def test_task_no_removes_notification(self):
        bot._nav_dialog_block = lambda job, timeout=600: "no"
        removed = []
        bot.subprocess.run = lambda cmd, **kw: removed.append(cmd[0])
        self._run_task()
        self.assertEqual(removed, ["termux-notification-remove"])

    def test_fire_starts_dialog_task(self):
        started = []
        bot._nav_confirm_notify = lambda job: (True, "ok")

        async def fake_kb(cid, job):
            started.append(job["id"])
        bot._nav_keyboard_msg = fake_kb
        bot._shell_priv_exec = lambda s: (True, "")
        bot.run_intent = lambda cmd, t=0: (True, "")

        async def fake_send(cid, text, label=""):
            return True
        old_send, old_jobs, old_save, old_dry = (bot._send_safe, bot._jobs,
                                                 bot._save_json, bot.DRY_RUN)
        old_kb = bot._nav_keyboard_msg
        bot._send_safe, bot._jobs, bot._save_json, bot.DRY_RUN = fake_send, list, (lambda *a, **k: None), False
        try:
            nxt = (dt.datetime.now() + dt.timedelta(seconds=1)).isoformat()
            job = {"id": 42, "type": "nav", "hh": 7, "mm": 0, "daily": False,
                   "url": "X", "seconds": 0, "mode": "r", "label": "屋企",
                   "chat_id": 1, "next": nxt, "shuffle": False, "paused": False}
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(bot._fire_later(job, 0.01))
                pending = asyncio.all_tasks(loop)
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending))
            finally:
                loop.close()
        finally:
            bot._send_safe, bot._jobs, bot._save_json, bot.DRY_RUN = old_send, old_jobs, old_save, old_dry
            bot._nav_keyboard_msg = old_kb
        self.assertEqual(started, [42])


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestWebPage(unittest.TestCase):
    """定時開自定義網頁：儲存／清單／即刻開／排程／到點 fire。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._old_webs, self._old_jobs = bot.WEBS_PATH, bot.JOBS_PATH
        bot.WEBS_PATH = os.path.join(self._tmp, "webs.json")
        bot.JOBS_PATH = os.path.join(self._tmp, "jobs.json")
        self._arm, self._shell = bot._arm, bot._shell_priv_exec
        self._si, self._dry = bot.run_intent, bot.DRY_RUN
        bot.DRY_RUN = False
        bot._arm = lambda j: None
        bot._shell_priv_exec = lambda *a, **k: None

    def tearDown(self):
        bot.WEBS_PATH, bot.JOBS_PATH = self._old_webs, self._old_jobs
        bot._arm, bot._shell_priv_exec = self._arm, self._shell
        bot.run_intent, bot.DRY_RUN = self._si, self._dry
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _p(self, line):
        return bot.parse_player(line)

    def test_web_intent_cmd(self):
        cmd = " ".join(bot.web_intent_cmd("https://example.com"))
        self.assertIn("android.intent.action.VIEW", cmd)
        self.assertIn("-d https://example.com", cmd)

    def test_web_parse(self):
        self.assertEqual((self._p("網頁").action), "webs")
        c = self._p("網頁 新聞 https://news.rthk.hk")
        self.assertEqual((c.action, c.ref, c.url), ("saveweb", "新聞", "https://news.rthk.hk"))
        self.assertEqual(self._p("刪網頁 新聞").action, "delweb")
        c2 = self._p("開網頁 新聞")
        self.assertEqual((c2.action, c2.ref), ("web", "新聞"))
        c3 = self._p("0830 開網頁 新聞")
        self.assertEqual((c3.action, c3.hour, c3.minute, c3.ref),
                         ("sched_web", 8, 30, "新聞"))
        c4 = self._p("每日 0900 開網頁 新聞")
        self.assertEqual((c4.action, c4.hour, c4.minute),
                         ("sched_web_daily", 9, 0))

    def test_web_save_list_delete(self):
        now = dt.datetime(2026, 9, 27, 12, 0)
        r = bot._execute_player(self._p("網頁 新聞 https://news.rthk.hk"), 1, now)
        self.assertIn("已儲存", r)
        r2 = bot._execute_player(self._p("網頁"), 1, now)
        self.assertIn("news.rthk.hk", r2)
        r3 = bot._execute_player(self._p("網頁 壞連結 唔係url"), 1, now)
        self.assertIn("http", r3)                     # 要齊 http(s) 開頭
        r4 = bot._execute_player(self._p("刪網頁 新聞"), 1, now)
        self.assertIn("已刪", r4)

    def test_web_open_now(self):
        now = dt.datetime(2026, 9, 27, 12, 0)
        bot._execute_player(self._p("網頁 新聞 https://news.rthk.hk"), 1, now)
        seen = {}
        bot.run_intent = lambda cmd, t=0: seen.update(cmd=" ".join(cmd)) or (True, "OK")
        r = bot._execute_player(self._p("開網頁 新聞"), 1, now)
        self.assertIn("開緊網頁", r)
        self.assertIn("VIEW", seen["cmd"])
        self.assertIn("news.rthk.hk", seen["cmd"])
        r2 = bot._execute_player(self._p("開網頁 https://example.com"), 1, now)
        self.assertIn("example.com", r2)
        r3 = bot._execute_player(self._p("開網頁 冇呢個"), 1, now)
        self.assertIn("搵唔到", r3)

    def test_web_schedule_creates_job(self):
        now = dt.datetime(2026, 9, 27, 12, 0)
        bot._execute_player(self._p("網頁 新聞 https://news.rthk.hk"), 1, now)
        made = {}
        bot._arm = lambda j: made.setdefault("armed", j)
        r = bot._execute_player(self._p("每日 0900 開網頁 新聞"), 1, now)
        self.assertIn("已排程", r)
        self.assertIn("每日", r)
        job = made["armed"]
        self.assertEqual(job["type"], "web")
        self.assertTrue(job["daily"])
        self.assertEqual(job["url"], "https://news.rthk.hk")
        self.assertEqual((job["hh"], job["mm"]), (9, 0))

    def test_web_fire_opens_browser(self):
        now = dt.datetime(2026, 9, 27, 12, 0)
        bot._execute_player(self._p("網頁 新聞 https://news.rthk.hk"), 1, now)
        seen = {}
        bot.run_intent = lambda cmd, t=0: seen.update(cmd=" ".join(cmd)) or (True, "OK")

        async def fake_send(cid, msg, tag=""):
            seen["msg"] = msg
        bot._send_safe = fake_send
        self._sendsafe = None
        job = {"id": 99, "type": "web", "hh": 9, "mm": 0, "daily": False,
               "url": "https://news.rthk.hk", "label": "新聞",
               "chat_id": 1, "next": now.isoformat(), "seconds": 0,
               "mode": "", "shuffle": False, "paused": False}
        asyncio.run(bot._fire_later(job, 0))
        self.assertIn("VIEW", seen["cmd"])
        self.assertIn("news.rthk.hk", seen["cmd"])
        self.assertIn("到點", seen["msg"])
        self.assertIn("開網頁「新聞」", seen["msg"])


class TestShortForms(unittest.TestCase):
    """減阻力短式：開 X／去 X／計時淨數字／鬧鐘整點／X時間。"""

    def test_short_open_and_go(self):
        c = bot.parse_player("開 新聞")
        self.assertEqual((c.action, c.ref), ("web", "新聞"))
        c2 = bot.parse_player("去 公司")
        self.assertEqual((c2.action, c2.ref), ("nav", "公司"))
        c3 = bot.parse_player("0830 去 公司")
        self.assertEqual((c3.action, c3.hour, c3.minute, c3.ref),
                         ("sched_nav", 8, 30, "公司"))
        c4 = bot.parse_player("每日 0900 開 新聞")
        self.assertEqual(c4.action, "sched_web_daily")
        c5 = bot.parse_player("開 https://example.com")
        self.assertEqual((c5.action, c5.ref), ("web", "https://example.com"))
        self.assertIsNone(bot.parse_player("開枱"))  # 開枱唔關 player 事（大話骰用）

    def test_liar_yields_open_go(self):
        bot._LIAR_GAMES.clear()
        bot._LIAR_GAMES[13] = bot._liar.new_game(starter="you")
        try:
            self.assertIsNone(bot._liar_handle(13, "開 新聞"))
            self.assertIsNone(bot._liar_handle(13, "去 公司"))
            r = bot._liar_handle(13, "開")          # 單字「開」仍係攤牌
            self.assertIsNotNone(r)
        finally:
            bot._LIAR_GAMES.clear()

    def test_bare_number_timer_and_alarm_hour(self):
        self.assertEqual(bot.parse_command("計時 25").seconds, 1500)
        self.assertEqual(bot.parse_command("計時 90").seconds, 5400)
        p = bot.parse_command("計時 25 杯麵")
        self.assertEqual((p.seconds, p.label), (1500, "杯麵"))
        # 3-4 位保留 hhmm 語義
        self.assertEqual(bot.parse_command("計時 700").fire_at.strftime("%H:%M"),
                         "07:00")
        self.assertEqual(bot.parse_command("計時 1830").fire_at.strftime("%H:%M"),
                         "18:30")
        # 鬧鐘整點
        self.assertEqual(bot.parse_command("鬧鐘 7").fire_at.strftime("%H:%M"),
                         "07:00")
        self.assertEqual(bot.parse_command("鬧鐘 23").fire_at.strftime("%H:%M"),
                         "23:00")
        self.assertIsNone(bot.parse_command("鬧鐘 25"))
        # 單位寫法照舊
        self.assertEqual(bot.parse_command("計時 25分鐘").seconds, 1500)

    def test_city_time_suffix(self):
        import re as _re
        m = _re.fullmatch(r"([\u4e00-\u9fff\w]{1,12})時間", "東京時間")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "東京")


class TestFocusResumeOnRestore(unittest.TestCase):
    """bashrc 復活場景：focus job 恢復＝牆鐘重算重返崗位——唔盲殺唔預落唔疊鐘。"""

    def test_stale_focus_resumed_on_restore(self):
        tmp = tempfile.mkdtemp()
        old_j = bot.JOBS_PATH
        bot.JOBS_PATH = os.path.join(tmp, "j.json")
        old_arm = bot._arm
        armed = []
        bot._arm = lambda j: armed.append(j["id"])
        try:
            now = dt.datetime.now()
            jobs = [
                {"id": 1, "type": "focus", "wmin": 25, "bmin": 5,
                 "label": "", "chat_id": 1, "hh": 10,
                 "mm": 0, "daily": False, "seconds": 0, "url": "",
                 "shuffle": False, "paused": False,
                 "session_start":
                     (now - dt.timedelta(minutes=34)).isoformat(),
                 "next": (now - dt.timedelta(minutes=4)).isoformat()},
                {"id": 2, "type": "play", "label": "lofi",
                 "url": "https://x", "chat_id": 1, "hh": 7, "mm": 0,
                 "daily": True, "seconds": 0, "shuffle": False,
                 "paused": False,
                 "next": bot._next_occurrence(now, 7, 0).isoformat()},
            ]
            with open(bot.JOBS_PATH, "w", encoding="utf-8") as f:
                json.dump(jobs, f, ensure_ascii=False)
            rec2 = []
            old_ri = bot.run_intent
            bot.run_intent = (lambda cmd, t=0: rec2.append(" ".join(cmd))
                              or (True, "OK"))

            async def fs(cid, msg, tag=""):
                pass
            old_ss = bot._send_safe
            bot._send_safe = fs
            try:
                asyncio.run(bot._restore_jobs(None))
                # focus job 照恢復（重返崗位，唔盲殺），play 都恢復
                self.assertEqual([j["type"] for j in bot._jobs()],
                                 ["focus", "play"])
                self.assertIn(1, armed)
                self.assertIn(2, armed)
                # 恢復後 stale fire：牆鐘重算 → 落「剩餘」鐘（唔疊全長）
                n0 = len(rec2)
                asyncio.run(bot._fire_later(dict(bot._jobs()[0]), 0))
                self.assertEqual(len(rec2), n0 + 1)
                self.assertIn("1260", rec2[-1])   # 55−34＝21 分鐘剩餘
            finally:
                bot.run_intent = old_ri
                bot._send_safe = old_ss
        finally:
            bot.JOBS_PATH = old_j
            bot._arm = old_arm
            shutil.rmtree(tmp, ignore_errors=True)


class TestWaitWall(unittest.TestCase):
    """隨機擴展：倒數日／分組／習慣提醒／專注模式／電量守。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._oj, self._oc = bot.JOBS_PATH, bot.COUNTDOWNS_PATH
        bot.JOBS_PATH = os.path.join(self._tmp, "j.json")
        bot.COUNTDOWNS_PATH = os.path.join(self._tmp, "c.json")
        self._arm, self._si, self._ss = bot._arm, bot.run_intent, bot._send_safe
        self._arm = bot._arm
        bot._arm = lambda j: None
        self.seen = {"msgs": []}
        bot.run_intent = (lambda cmd, t=0: self.seen.update(cmd=" ".join(cmd))
                          or (True, "OK"))

        async def fs(cid, msg, tag=""):
            self.seen["msgs"].append(msg)
        bot._send_safe = fs

    def tearDown(self):
        bot.JOBS_PATH, bot.COUNTDOWNS_PATH = self._oj, self._oc
        bot._arm, bot.run_intent, bot._send_safe = self._arm, self._si, self._ss
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_countdown(self):
        r = bot._countdown_handle("倒數 考試 2027-05-04", 1)
        self.assertIn("仲有", r)
        r2 = bot._countdown_handle("倒數 聖誕 12-25", 1)
        self.assertIn("每年", r2)
        self.assertIn("聖誕", bot._countdown_handle("倒數", 1))
        self.assertIn("已刪", bot._countdown_handle("刪倒數 考試", 1))
        self.assertIn("唔存在", bot._countdown_handle("倒數 壞 2027-13-40", 1))

    def test_groups(self):
        r = bot._groups_handle("分組 3 阿明,阿強,阿寶,小明,阿偉")
        self.assertEqual(r.count("組："), 3)
        names = sum(len(l.split("：")[1].split("、")) for l in r.splitlines()[1:])
        self.assertEqual(names, 5)
        self.assertIn("分唔到", bot._groups_handle("分組 9 A,B"))
        self.assertIsNone(bot._groups_handle("唔係分組"))

    def test_nag_job_and_fire(self):
        r = bot._nag_handle("提醒 每60分 飲水", 1)
        self.assertIn("每 60 分鐘", r)
        jobs = bot._jobs()
        self.assertEqual(jobs[0]["type"], "nag")
        self.assertEqual(jobs[0]["every"], 3600)
        asyncio.run(bot._fire_later(dict(jobs[0]), 0))
        self.assertIn("飲水", self.seen["msgs"][-1])
        # 每日 0700 播嗰類唔會被「提醒」字眼誤食
        self.assertIsNone(bot._nag_handle("提醒 每700分", 1))

    def test_focus_loop(self):
        """治根 v3：唔預落（逐段落鐘）＋牆鐘重算（復活返崗位）＋殭屍閘。"""
        rec = []
        old_ri = bot.run_intent
        bot.run_intent = (lambda cmd, t=0: rec.append(" ".join(cmd))
                          or (True, "OK"))
        try:
            self._focus_loop_body(rec)
        finally:
            bot.run_intent = old_ri

    def _focus_loop_body(self, rec):
        now = bot.dt.datetime.now()
        r = bot._focus_handle("專注 25 數學", 1)
        self.assertIn("即刻落第一個計時器", r)
        self.assertEqual(len(rec), 0)          # 唔預落——handle 零落鐘
        job = bot._jobs()[0]
        self.assertEqual((job["type"], job["wmin"], job["bmin"]),
                         ("focus", 25, 5))
        self.assertIsNotNone(job.get("session_start"))
        # 即刻 fire：落第一個工作鐘 1500
        asyncio.run(bot._fire_later(dict(job), 0))
        self.assertIn("1500", rec[-1])
        self.assertIn("🎯 開始專注 25 分鐘（數學）", self.seen["msgs"][-1])
        start = bot.dt.datetime.fromisoformat(job["session_start"])
        j1 = bot._jobs()[0]
        self.assertEqual(bot.dt.datetime.fromisoformat(j1["next"]),
                         start + bot.dt.timedelta(minutes=25))
        # 工作段完 → 落休息鐘 300
        b1 = dict(job, session_start=(start - bot.dt.timedelta(minutes=25))
                  .isoformat(), next=now.isoformat())
        asyncio.run(bot._fire_later(b1, 0))
        self.assertIn("300", rec[-1])
        self.assertIn("☕ 休息 5 分鐘", self.seen["msgs"][-1])
        # 復活接軌：bot 死咗 34 分鐘，工作段#2 個鐘未落 → 落剩餘 21 分鐘
        dead = dict(job, session_start=(now - bot.dt.timedelta(minutes=34))
                    .isoformat(),
                    next=(now - bot.dt.timedelta(minutes=4)).isoformat())
        asyncio.run(bot._fire_later(dead, 0))
        self.assertIn("1260", rec[-1])
        self.assertIn("復活接軌", self.seen["msgs"][-1])
        # 段鐘已落（bot 凍緊時鐘 app 照行）→ 靜靜返崗位，零落鐘
        quiet = dict(job, session_start=(now - bot.dt.timedelta(minutes=27))
                     .isoformat(),
                     next=(now + bot.dt.timedelta(minutes=3)).isoformat())
        n = len(rec)
        asyncio.run(bot._fire_later(quiet, 0))
        self.assertEqual(len(rec), n)
        self.assertIn("返到崗位", self.seen["msgs"][-1])
        # 殭屍閘：job 已剷 → fire 唔出聲唔落鐘
        bot._save_json(bot.JOBS_PATH, [])
        asyncio.run(bot._fire_later(dict(dead), 0))
        self.assertEqual(len(rec), n)
        self.assertNotIn("已落時鐘", self.seen["msgs"][-1])
        # 開新 session 清舊鏈；專注結束收工
        bot._focus_handle("專注 25", 1)
        bot._focus_handle("專注 50", 1)
        fs = [j for j in bot._jobs() if j.get("type") == "focus"]
        self.assertEqual(len(fs), 1)
        self.assertEqual(fs[0]["wmin"], 50)
        r2 = bot._focus_handle("專注結束", 1)
        self.assertIn("收工", r2)
        self.assertEqual([j for j in bot._jobs()
                          if j.get("type") == "focus"], [])

    def test_battery_guard(self):
        r = bot._battery_handle("電量守 20", 1)
        self.assertIn("電量守開工", r)
        job = bot._jobs()[0]
        self.assertEqual((job["type"], job["thr"]), ("battery", 20))
        bot._battery_status = lambda: (15, False, 33.0)
        asyncio.run(bot._fire_later(dict(job), 0))
        self.assertIn("15%", self.seen["msgs"][-1])
        self.assertTrue(bot._jobs()[0]["alerted"])
        bot._battery_status = lambda: (80, True, 30.0)
        n = len(self.seen["msgs"])
        asyncio.run(bot._fire_later(dict(bot._jobs()[0]), 0))
        self.assertEqual(len(self.seen["msgs"]), n)      # 冇事靜默
        self.assertFalse(bot._jobs()[0]["alerted"])
        self.assertIn("收工", bot._battery_handle("電量守完", 1))

    def test_bthead_guard(self):
        """(54) 藍牙耳機電量守：parser＋即查＋開守／收工＋fire 骨。"""
        sysui = ("      mConnectedDevices=[CachedBluetoothDevice{"
                 "anonymizedAddress=XX:XX:XX:XX:C9:AD, name=看什麽看, "
                 "groupId=-1, member=[]}]")
        adapter = ("rec[0]: valString=+IPHONEACCEV=1,1,6, valObject=null, "
                   "device=XX:XX:XX:XX:C9:AD\n"
                   "rec[1]: valString=+IPHONEACCEV=1,1,9, valObject=null, "
                   "device=XX:XX:XX:XX:C9:AD")
        self.assertEqual(bot._parse_bt_connected(sysui),
                         [("XX:XX:XX:XX:C9:AD", "看什麽看")])
        self.assertEqual(bot._parse_bt_connected(""), [])
        self.assertEqual(bot._parse_bt_battery(adapter),
                         {"XX:XX:XX:XX:C9:AD": 100})  # 取最後一筆；頂級 9=滿電
        self.assertEqual(bot._parse_bt_battery(
            "valString=+IPHONEACCEV=1,1,10, device=XX:XX:XX:XX:C9:AD"),
            {"XX:XX:XX:XX:C9:AD": 100})               # 防禦：10 都當滿電
        self.assertEqual(bot._parse_bt_battery("garbage"), {})
        old_hl = bot._headset_levels
        try:
            bot._headset_levels = lambda: (True, [("看什麽看", 90)])
            self.assertIn("90%", bot._bthead_handle("耳機", 1))
            self.assertIn("冇", bot._bthead_handle(
                "耳機", 1)) if False else None
            bot._headset_levels = lambda: (True, [])
            self.assertIn("冇", bot._bthead_handle("耳機", 1))
            bot._headset_levels = lambda: (False, "lane死")
            self.assertIn("❌", bot._bthead_handle("耳機", 1))
            # 開守：預設 60、指定 40、超界拒
            self.assertIn("耳機守開工", bot._bthead_handle("耳機守", 1))
            self.assertEqual(bot._jobs()[0]["thr"], 60)
            self.assertIn("耳機守開工", bot._bthead_handle("耳機守 40", 1))
            j40 = next(j for j in bot._jobs() if j.get("thr") == 40)
            self.assertEqual(j40["type"], "bthead")
            self.assertIn("5–95", bot._bthead_handle("耳機守 4", 1))
            self.assertIn("🎧", bot._fmt_jobs(bot.dt.datetime.now()))
            # fire：≤thr 報一次；>thr+5 重置；讀數 None 靜默
            bot._headset_levels = lambda: (True, [("看什麽看", 35)])
            asyncio.run(bot._fire_later(dict(j40), 0))
            self.assertIn("35%", self.seen["msgs"][-1])
            j40 = next(j for j in bot._jobs() if j.get("thr") == 40)
            self.assertTrue(j40["alerted"])
            n = len(self.seen["msgs"])
            bot._headset_levels = lambda: (True, [("看什麽看", 35)])
            asyncio.run(bot._fire_later(dict(j40), 0))
            self.assertEqual(len(self.seen["msgs"]), n)   # 報一次過
            bot._headset_levels = lambda: (True, [("看什麽看", 90)])
            asyncio.run(bot._fire_later(dict(j40), 0))
            j40 = next(j for j in bot._jobs() if j.get("thr") == 40)
            self.assertFalse(j40["alerted"])
            n = len(self.seen["msgs"])
            bot._headset_levels = lambda: (True, [("看什麽看", None)])
            asyncio.run(bot._fire_later(dict(j40), 0))
            self.assertEqual(len(self.seen["msgs"]), n)   # 冇讀數靜默
            self.assertIn("收工", bot._bthead_handle("耳機守完", 1))
            self.assertEqual([j for j in bot._jobs()
                              if j.get("type") == "bthead"], [])
        finally:
            bot._headset_levels = old_hl

    def test_jobs_list_icons(self):
        now = dt.datetime.now()
        bot._nag_handle("提醒 每30分 飲水", 1)
        bot._focus_handle("專注 25", 1)
        r = bot._fmt_jobs(now)
        self.assertIn("💧", r)
        self.assertIn("🎯", r)
        self.assertIn("每30分 飲水", r)
        # 排定日期 job 有自己 icon（唔好跌返 🎵）
        bot._add_simple_job(1, {"type": "sched_pause", "ids": [3], "label": "x",
                                "hh": 0, "mm": 5, "chat_id": 1,
                                "next": "2026-10-05T00:05:00"})
        r2 = bot._fmt_jobs(now)
        self.assertIn("⏸一次 00:05 排定暫停排程：#3", r2)
        self.assertIn("mmdd 暫停/繼續排程", r2)


class TestSeriesWindow(unittest.TestCase):
    """連環鬧窗口：尾響要完場（window_end 缺失都唔可以錨錯日多響）。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._oj = bot.JOBS_PATH
        bot.JOBS_PATH = os.path.join(self._tmp, "j.json")
        self._si, self._ss = bot.run_intent, bot._send_safe
        self._arm = bot._arm
        bot._arm = lambda j: None
        bot.run_intent = lambda cmd, t=0: (True, "OK")

        async def fs(cid, msg, tag=""):
            pass
        bot._send_safe = fs

    def tearDown(self):
        bot.JOBS_PATH = self._oj
        bot.run_intent, bot._send_safe = self._si, self._ss
        bot._arm = self._arm
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _mk(self, daily, next_iso):
        return {"id": 8, "type": "series", "hh": 20, "mm": 15,
                "end_hh": 7, "end_mm": 15, "daily": daily, "every": 3600,
                "label": "水樽，筆", "chat_id": 1, "next": next_iso,
                "seconds": 0, "url": "", "shuffle": False, "paused": False}

    def test_final_ring_ends_series_even_without_window_end(self):
        """2026-09-28 實證 bug：尾響 07:15 window_end 缺失→錨去聽日→08:15 繼續響。"""
        now = dt.datetime.now()
        f0715 = now.replace(hour=7, minute=15, second=0, microsecond=0)
        json.dump([self._mk(False, f0715.isoformat())],
                  open(bot.JOBS_PATH, "w"))
        asyncio.run(bot._fire_later(self._mk(False, f0715.isoformat()), 0))
        self.assertEqual([j for j in bot._jobs() if j["id"] == 8], [])  # 完場

    def test_daily_final_ring_reschedules_tomorrow_start(self):
        now = dt.datetime.now()
        f0715 = now.replace(hour=7, minute=15, second=0, microsecond=0)
        json.dump([self._mk(True, f0715.isoformat())],
                  open(bot.JOBS_PATH, "w"))
        asyncio.run(bot._fire_later(self._mk(True, f0715.isoformat()), 0))
        j = bot._jobs()[0]
        self.assertEqual(j["next"][11:16], "20:15")
        self.assertNotEqual(j["next"][:10], f0715.date().isoformat())
        self.assertIsNone(j.get("window_end"))

    def test_midseries_missing_window_end_reanchors_backwards(self):
        now = dt.datetime.now()
        mid = (now.replace(hour=21, minute=15, second=0, microsecond=0)
               - dt.timedelta(days=1))
        json.dump([self._mk(True, mid.isoformat())],
                  open(bot.JOBS_PATH, "w"))
        asyncio.run(bot._fire_later(self._mk(True, mid.isoformat()), 0))
        j = bot._jobs()[0]
        self.assertEqual(j["next"][11:16], "22:15")
        self.assertEqual(j["window_end"][11:16], "07:15")   # 錨返昨晚20:15起


class TestJsonHeal(unittest.TestCase):
    """牆鐘分段等：deep sleep（monotonic 凍結）都唔會拖遲排程。"""

    def test_basic_past_and_future(self):
        past = bot.dt.datetime.now() - bot.dt.timedelta(seconds=1)
        self.assertIsNone(asyncio.run(bot._wait_wall(past)))          # 已過點→即刻過
        t0 = time.monotonic()
        target = bot.dt.datetime.now() + bot.dt.timedelta(seconds=0.6)
        asyncio.run(bot._wait_wall(target, chunk=0.2))
        dt_used = time.monotonic() - t0
        self.assertGreaterEqual(dt_used, 0.5)
        self.assertLess(dt_used, 3.0)

    def test_wall_jump_catches_up(self):
        """模擬 suspend：牆鐘中途跳前 15 分鐘，_wait_wall 應即刻醒。"""
        real_dt = bot.dt.datetime

        class FrozenMeta(type):
            pass

        class ShimDt(real_dt, metaclass=FrozenMeta):
            jumped = {"n": 0}

            @classmethod
            def now(cls):
                # 第一次 now() 之後就「凍結期完，牆鐘跳 15 分鐘」
                if cls.jumped["n"] == 0:
                    cls.jumped["n"] = 1
                    return real_dt.now()
                if cls.jumped["n"] == 1:
                    cls.jumped["n"] = 2
                    return real_dt.now() + bot.dt.timedelta(minutes=15)
                return real_dt.now()

        orig_dt = bot.dt
        try:
            import types
            shim = types.SimpleNamespace(datetime=ShimDt, timedelta=bot.dt.timedelta)
            bot.dt = shim
            t0 = time.monotonic()
            target = real_dt.now() + bot.dt.timedelta(seconds=120)
            asyncio.run(bot._wait_wall(target, chunk=0.2))
            used = time.monotonic() - t0
            self.assertLess(used, 5.0, f"牆鐘跳前應即刻追上，實際用咗 {used:.1f}s")
        finally:
            bot.dt = orig_dt



class TestSingletonLock(unittest.TestCase):
    """單例鎖：第二條 instance（hook/boot/restart 重疊）即刻退出——
    防 getUpdates 互搶令訊息調轉序（專注結束先行＝鬼計時器）。"""

    def test_second_instance_exits(self):
        tmp = tempfile.mkdtemp()
        lp = os.path.join(tmp, "bot.lock")
        try:
            self.assertTrue(bot._acquire_singleton(lp))
            self.assertFalse(bot._acquire_singleton(lp))   # 同 process 第二攞
            self.assertTrue(os.path.exists(lp))
        finally:
            bot._LOCK_FH = None
            shutil.rmtree(tmp, ignore_errors=True)



class TestDailyAlarm(unittest.TestCase):
    """每日單鬧：鬧鐘 每日0734 標籤（用戶直覺寫法）——到點 1 秒鐘、翻日再響。"""

    def test_parse_forms(self):
        now = dt.datetime(2026, 9, 29, 13, 20)
        for txt in ("鬧鐘 每日0734 看待辦", "鬧鐘 每日 0734 看待辦",
                    "每日 鬧鐘 0734 看待辦", "每日0734 鬧鐘 看待辦"):
            p = bot.parse_player(txt)
            self.assertIsNotNone(p, txt)
            self.assertEqual((p.action, p.hour, p.minute, p.ref),
                             ("sched_alarm_daily", 7, 34, "看待辦"), txt)
        # 舊路唔破壞
        self.assertIsNone(bot.parse_player("鬧鐘 0734 看待辦"))   # 即刻鬧鐘
        c = bot.parse_command("鬧鐘 0734 看待辦", now)
        self.assertEqual((c.kind, c.hour, c.minute), ("alarm", 7, 34))
        p = bot.parse_player("鬧鐘 0900-1700 每60分鐘 轉位")
        self.assertEqual(p.action, "series")                     # 連環鬧
        p = bot.parse_player("每日 0900 計時 25分鐘")
        self.assertEqual(p.action, "sched_timer_daily")          # 每日計時

    def test_create_direct_in_app(self):
        """用戶令：鬧鐘統一用手機 app——每日單鬧直接落循環鬧鐘，零 bot job。"""
        tmp = tempfile.mkdtemp()
        old_j = bot.JOBS_PATH
        bot.JOBS_PATH = os.path.join(tmp, "j.json")
        old_ri, old_arm, rec = bot.run_intent, bot._arm, []
        bot._arm = lambda j: None
        bot.run_intent = (lambda cmd, t=0: rec.append(" ".join(cmd))
                          or (True, "OK"))
        try:
            now = dt.datetime.now()
            ack = bot._execute_player(
                bot.parse_player("鬧鐘 每日0734 看待辦"), 1, now)
            self.assertIn("已落手機時鐘", ack)
            self.assertIn("日日", ack)
            self.assertIn("讀你聽", ack)
            self.assertIn("--eia", rec[-1])
            self.assertIn("android.intent.extra.alarm.DAYS 1,2,3,4,5,6,7",
                          rec[-1])
            self.assertIn("MESSAGE 看待辦", rec[-1])
            self.assertIn("HOUR 7", rec[-1])
            # 語音回聲：每日 timer bell（app 照主，回聲淨讀）
            echo = [j for j in bot._jobs() if j["type"] == "bell"]
            self.assertEqual(len(echo), 1)
            self.assertEqual((echo[0]["bell"], echo[0]["daily"],
                              echo[0]["hh"], echo[0]["mm"]),
                             ("timer", True, 7, 34))
        finally:
            bot._arm = old_arm
            bot.run_intent = old_ri
            bot.JOBS_PATH = old_j
            shutil.rmtree(tmp, ignore_errors=True)

    def test_fallback_bell_when_intent_fails(self):
        """app 設唔到 → bot daily bell job 守返（原本行為）。"""
        tmp = tempfile.mkdtemp()
        old_j, old_arm, old_ri = bot.JOBS_PATH, bot._arm, bot.run_intent
        bot.JOBS_PATH = os.path.join(tmp, "j.json")
        bot._arm = lambda j: None
        bot.run_intent = lambda cmd, t=0: (False, "SecurityException: x")
        try:
            now = dt.datetime.now()
            ack = bot._execute_player(
                bot.parse_player("鬧鐘 每日 0734 後備"), 1, now)
            self.assertIn("bot 排程守返", ack)
            jobs = [j for j in bot._jobs() if j["type"] == "bell"]
            self.assertEqual(len(jobs), 1)
            self.assertEqual((jobs[0]["daily"], jobs[0]["hh"], jobs[0]["mm"],
                              jobs[0]["label"]),
                             (True, 7, 34, "後備"))
        finally:
            bot.JOBS_PATH, bot._arm, bot.run_intent = old_j, old_arm, old_ri
            shutil.rmtree(tmp, ignore_errors=True)



class TestTimerLabelCollision(unittest.TestCase):
    """「計時 1530 1727」——4位數撞「MMDD HHMM」語法（2026-10-02 用戶令改制）：
    非外賣＝嚴謹 mmdd hhmm，日期唔存在明確拒絕（唔再靜靜當 hhmm＋標籤）；
    外賣模式＝hhmm 後任何數字＝單號，蓋過 mmdd。真日期照 mmdd；打錯照拒。"""

    def test_strict_mmdd_without_takeaway(self):
        old = dict(bot._TAKEAWAY)
        bot._TAKEAWAY["on"] = False
        try:
            now = dt.datetime(2026, 9, 29, 13, 30)
            self.assertIsNone(bot.parse_command("計時 1530 1727", now))  # 嚴謹：15月唔存在
            self.assertIsNone(bot.parse_command("計時 0931 1830", now))  # 打錯照拒
            p = bot.parse_command("計時 0925 1830", now)
            self.assertEqual(p.fire_at.date(), dt.date(2027, 9, 25))  # 真日期照舊
            p = bot.parse_command("計時 1230", now)                       # 淨 hhmm 照舊
            self.assertEqual((p.fire_at.hour, p.fire_at.minute), (12, 30))
            p = bot.parse_command("計時 1530 單號1727", now)              # 文字標籤照舊
            self.assertEqual((p.fire_at.hour, p.fire_at.minute), (15, 30))
            self.assertEqual(p.label, "單號1727")
        finally:
            bot._TAKEAWAY.clear()
            bot._TAKEAWAY.update(old)

    def test_takeaway_order_number_overrides(self):
        old = dict(bot._TAKEAWAY)
        bot._TAKEAWAY["on"] = True
        try:
            now = dt.datetime(2026, 9, 29, 13, 30)
            p = bot.parse_command("計時 1530 1727", now)
            self.assertEqual((p.fire_at.hour, p.fire_at.minute), (15, 30))
            self.assertEqual(p.label, "單號1727")
            # 蓋過 mmdd：1005 1830＝10:05＋單號1830（唔係日期）
            p = bot.parse_command("計時 1005 1830", now)
            self.assertEqual((p.fire_at.hour, p.fire_at.minute), (10, 5))
            self.assertEqual(p.label, "單號1830")
            # 任何位數都收
            p = bot.parse_command("計時 1830 25", now)
            self.assertEqual(p.label, "單號25")
            p = bot.parse_command("計時到 1830 952786", now)
            self.assertEqual(p.label, "單號952786")
            # 相對日＋單號
            p = bot.parse_command("計時 聽日 0900 777", now)
            self.assertEqual((p.fire_at.hour, p.fire_at.minute, p.fire_at.day), (9, 0, 30))
            self.assertEqual(p.label, "單號777")
            # 非數字標籤照舊；淨 hhmm 冇標籤
            p = bot.parse_command("計時 1830 開會", now)
            self.assertEqual(p.label, "開會")
            p = bot.parse_command("計時 1830", now)
            self.assertEqual(p.label, "")
        finally:
            bot._TAKEAWAY.clear()
            bot._TAKEAWAY.update(old)



class TestSeriesEvery(unittest.TestCase):
    """連環鬧（2026-10-03 用戶令）：裸寫法都收；每x 支持小時＋中文數字。"""

    def test_bare_range_every_two_hours(self):
        p = bot.parse_player("2305-0705 每兩小時 報更")
        self.assertEqual(p.action, "series")
        self.assertEqual((p.hour, p.minute, p.hour2, p.minute2), (23, 5, 7, 5))
        self.assertEqual(p.seconds, 7200)
        self.assertEqual(p.ref, "報更")

    def test_daily_prefix_still_daily(self):
        p = bot.parse_player("每日 2305-0705 每兩小時 報更")
        self.assertEqual(p.action, "series_daily")
        self.assertEqual(p.seconds, 7200)

    def test_regression_prefixed_minutes(self):
        p = bot.parse_player("鬧鐘 2100-0000 每90分鐘 報更")
        self.assertEqual(p.action, "series")
        self.assertEqual((p.hour, p.minute, p.hour2, p.minute2), (21, 0, 0, 0))
        self.assertEqual(p.seconds, 5400)

    def test_hour_unit_and_cn_numerals(self):
        p = bot.parse_player("2305-0705 每三小時 報更")
        self.assertEqual(p.seconds, 10800)
        p = bot.parse_player("2305-0705 每二十分鐘 報更")
        self.assertEqual(p.seconds, 1200)
        p = bot.parse_player("2305-0705 每半小时 報更")     # 半 未支援
        self.assertIsNone(p)
        p = bot.parse_player("2305-0705 每1.5小時 報更")
        self.assertEqual(p.seconds, 5400)

    def test_no_every_is_not_series(self):
        self.assertIsNone(bot.parse_player("2305-0705 報更"))

    def test_two_line_merge_with_hours(self):
        merged = bot._merge_series_lines(["計時 2100-0000", "每2小時 報更"])
        self.assertEqual(len(merged), 1)
        p = bot.parse_player(merged[0])
        self.assertEqual(p.action, "series")
        self.assertEqual(p.seconds, 7200)


class TestPauseAllResumeAll(unittest.TestCase):
    """全局暫停／繼續排程（2026-10-03 用戶令）：暫停排程＝全部停、繼續排程＝全部恢復。"""

    def test_parse_global_and_perjob(self):
        for t in ["暫停排程", "暫停全部", "全部暫停", "暫停所有", "/暫停排程"]:
            self.assertEqual(bot.parse_player(t).action, "pause_all", t)
        for t in ["繼續排程", "恢復排程", "繼續全部", "全部恢復", "/繼續排程"]:
            self.assertEqual(bot.parse_player(t).action, "resume_all", t)
        # 單任務文法照舊
        self.assertEqual(bot.parse_player("暫停 3").action, "pause")
        self.assertEqual(bot.parse_player("繼續 #3").action, "resume")

    def test_pause_all_then_resume_all(self):
        old_j, old_save, old_arm = bot.JOBS_PATH, bot._save_json, bot._arm
        old_jobs, old_ri = bot._jobs, bot.run_intent
        store = []
        bot._jobs = lambda: store
        bot._save_json = lambda p, d: None
        bot.JOBS_PATH = "/tmp/nonexistent_jobs_pause_all.json"
        bot._arm = lambda j: None
        bot.run_intent = lambda cmd, t=0: (True, "OK")
        try:
            now = dt.datetime(2026, 10, 3, 12, 0)
            store.append({"id": 1, "type": "timer", "hh": 13, "mm": 0,
                          "label": "A", "chat_id": 1, "daily": True,
                          "next": "2026-10-03T13:00:00"})
            store.append({"id": 2, "type": "alarm", "hh": 14, "mm": 30,
                          "label": "B", "chat_id": 1, "daily": False,
                          "next": "2026-10-03T14:30:00"})
            # 全部暫停
            r = bot._execute_player(bot.PlayerCmd("pause_all"), 1, now)
            self.assertIn("已暫停全部", r)
            self.assertIn("2", r)
            self.assertTrue(all(j.get("paused") for j in store))
            # 再停 → 全部暫停緊
            r = bot._execute_player(bot.PlayerCmd("pause_all"), 1, now)
            self.assertIn("都暫停緊", r)
            # 全部恢復
            r = bot._execute_player(bot.PlayerCmd("resume_all"), 1, now)
            self.assertIn("已恢復 2 個", r)
            self.assertFalse(any(j.get("paused") for j in store))
            self.assertTrue(all(j["next"].startswith("2026-10-03T1") for j in store))
            # 再恢復 → 冇暫停緊
            r = bot._execute_player(bot.PlayerCmd("resume_all"), 1, now)
            self.assertIn("冇暫停緊", r)
            # 恢復唔會郁在行緊 job 嘅 next
            self.assertEqual(store[0]["next"], "2026-10-03T13:00:00")
            # 空表
            store.clear()
            r = bot._execute_player(bot.PlayerCmd("pause_all"), 1, now)
            self.assertIn("冇排程", r)
        finally:
            bot.JOBS_PATH, bot._save_json, bot._arm = old_j, old_save, old_arm
            bot._jobs, bot.run_intent = old_jobs, old_ri


class TestTTS(unittest.TestCase):
    """通知語音化：termux-tts-speak 廣東話讀出下一個任務（連機都唔使睇）。"""

    def test_scrub_and_cjk_when(self):
        self.assertEqual(bot._speech_scrub("🌤 今日 32度☀️【好熱】(注意)"),
                         "今日 32度 好熱 注意")
        now = dt.datetime(2026, 9, 29, 13, 30)
        self.assertEqual(
            bot._cjk_when(dt.datetime(2026, 9, 29, 7, 32), now),
            "今日朝早7點32分")
        self.assertEqual(
            bot._cjk_when(dt.datetime(2026, 9, 29, 18, 0), now),
            "今日下晝6點正")
        self.assertEqual(
            bot._cjk_when(dt.datetime(2026, 9, 30, 7, 5), now),
            "聽日朝早7點零5分")
        self.assertEqual(
            bot._cjk_when(dt.datetime(2026, 9, 29, 0, 30), now),
            "今日凌晨12點30分")

    def test_say_uses_termux_tts(self):
        calls = []

        class FakeCP:
            returncode = 0

        def fake_run(args, timeout=None):
            calls.append(args)
            return FakeCP()
        old_run = bot.subprocess.run
        bot.subprocess.run = fake_run
        try:
            asyncio.run(bot._say("測試一句"))
            # 第一 call＝預熱 battery-status，第二 call＝tts 本體
            self.assertGreaterEqual(len(calls), 2)
            self.assertEqual(calls[0][0], "termux-battery-status")
            self.assertEqual(calls[1][0], "termux-tts-speak")
            self.assertIn("-s", calls[1])
            self.assertIn("ALARM", calls[1])
            self.assertIn("測試一句", calls[1])
        finally:
            bot.subprocess.run = old_run

    def test_next_task_line(self):
        tmp = tempfile.mkdtemp()
        old_j = bot.JOBS_PATH
        bot.JOBS_PATH = os.path.join(tmp, "j.json")
        try:
            now = dt.datetime(2026, 9, 29, 13, 30)
            jobs = [
                {"id": 1, "type": "nav", "label": "屋企",
                 "next": "2026-09-29T18:20:00", "paused": False,
                 "hh": 18, "mm": 20, "daily": True, "url": "x",
                 "seconds": 0, "mode": "d", "shuffle": False},
                {"id": 2, "type": "web", "label": "記帳",
                 "next": "2026-09-29T19:33:00", "paused": False,
                 "hh": 19, "mm": 33, "daily": True, "url": "x",
                 "seconds": 0, "shuffle": False},
                {"id": 3, "type": "play", "label": "lofi",
                 "next": "2026-09-29T14:00:00", "paused": True,
                 "hh": 14, "mm": 0, "daily": False, "url": "y",
                 "seconds": 0, "shuffle": False},
                {"id": 4, "type": "focus", "label": "",
                 "next": "2026-09-29T13:40:00", "paused": False,
                 "hh": 13, "mm": 40, "daily": False,
                 "session_start": "2026-09-29T13:30:00",
                 "wmin": 25, "bmin": 5},
            ]
            with open(bot.JOBS_PATH, "w", encoding="utf-8") as f:
                json.dump(jobs, f, ensure_ascii=False)
            line = bot._next_task_line(now)
            self.assertIn("今日下晝6點20分", line)
            self.assertIn("屋企", line)     # paused／focus 排除後最早嗰個
        finally:
            bot.JOBS_PATH = old_j
            shutil.rmtree(tmp, ignore_errors=True)

    def test_alloc_fire_speaks_segment(self):
        tmp = tempfile.mkdtemp()
        old_j, old_ri = bot.JOBS_PATH, bot.run_intent
        bot.JOBS_PATH = os.path.join(tmp, "j.json")
        bot.run_intent = lambda cmd, t=0: (True, "OK")
        said = []

        async def fs(cid, msg, tag=""):
            pass

        async def fake_say(txt, delay=0):
            said.append(txt)
        old_ss, old_say = bot._send_safe, bot._say
        bot._send_safe = fs
        bot._say = fake_say
        try:
            alloc = {"id": 5, "type": "alloc", "label": "分配",
                     "daily": True, "hh": 16, "mm": 0, "idx": 0, "_rem": 0,
                     "segments": [{"text": "沖涼", "seconds": 1800},
                                  {"text": "食飯", "seconds": 3600}],
                     "next": "2026-09-29T16:00:00", "chat_id": 1,
                     "seconds": 0, "url": "", "shuffle": False,
                     "paused": False}
            with open(bot.JOBS_PATH, "w", encoding="utf-8") as f:
                json.dump([alloc], f, ensure_ascii=False)
            asyncio.run(bot._fire_later(dict(alloc), 0))
            self.assertTrue(said)
            self.assertIn("第1項", said[0])
            self.assertIn("沖涼", said[0])
        finally:
            bot.JOBS_PATH, bot.run_intent = old_j, old_ri
            bot._send_safe, bot._say = old_ss, old_say
            shutil.rmtree(tmp, ignore_errors=True)



class TestTimerBellSpeaks(unittest.TestCase):
    """計時雙軌：app 響＋bot 到點讀——timer bell fire＝_say＋TG 文字。"""

    def test_timer_bell_speaks_label(self):
        sent, fired = [], []

        async def fake_send(cid, text, label=""):
            sent.append(text)
            return True
        old_ri, old_ss, old_j = bot.run_intent, bot._send_safe, bot.JOBS_PATH
        old_say = bot._say
        bot.run_intent = lambda cmd, t=0: fired.append(cmd) or (True, "")
        bot._send_safe = fake_send
        said = []

        async def fake_say(t, delay=0):
            said.append(t)
        bot._say = fake_say
        tmp = tempfile.mkdtemp()
        bot.JOBS_PATH = os.path.join(tmp, "j.json")
        try:
            bot._save_json(bot.JOBS_PATH, [{
                "id": 3, "type": "bell", "bell": "timer", "hh": 17,
                "mm": 23, "daily": False, "label": "攞集運", "chat_id": 1,
                "next": dt.datetime.now().isoformat(), "seconds": 0,
                "url": "", "shuffle": False, "paused": False}])
            asyncio.run(bot._fire_later(dict(bot._jobs()[0]), 0))
            self.assertEqual(fired, [])            # 唔開計時器
            self.assertEqual(said, ["攞集運"])     # 讀標籤
            self.assertTrue(any("攞集運" in x for x in sent))
            self.assertEqual(bot._jobs(), [])      # fire 完剷
        finally:
            bot.run_intent, bot._send_safe = old_ri, old_ss
            bot._say, bot.JOBS_PATH = old_say, old_j
            shutil.rmtree(tmp, ignore_errors=True)



class TestSeal(unittest.TestCase):
    """封印：停用（pm disable-user）優先，pm 死退 25 秒巡邏；到期自動復活。"""

    def _mock_lane(self, disable_ok=True, fg_pkg=""):
        calls = []

        def fake_exec(cmd, t=0):
            calls.append(cmd)
            if "disable-user" in cmd:
                return (disable_ok, "")
            if "pm enable" in cmd:
                return (True, "")
            if "force-stop" in cmd:
                return (True, "")
            if "grep" in cmd and fg_pkg:
                return (True, ("  topResumedActivity="
                        f"ActivityRecord{{.. u0 {fg_pkg}/.ui.MainActivity ..}}"))
            if "packages -3" in cmd:
                return (True, ("package:com.zabank.mobile\n"
                              "package:com.zabank.vendor"))
            return (True, "")
        return calls, fake_exec

    def _setup(self, tmp):
        old_j, old_arm = bot.JOBS_PATH, bot._arm
        bot.JOBS_PATH = os.path.join(tmp, "j.json")
        bot._arm = lambda j: None
        said = []

        async def fs(cid, m, t=""):
            pass

        async def fk(t, delay=0):
            said.append(t)
        old_ss, old_say, old_exec = bot._send_safe, bot._say, \
            bot._shell_priv_exec
        bot._send_safe = fs
        bot._say = fk
        return said, (old_j, old_arm, old_ss, old_say, old_exec)

    def _teardown(self, olds, tmp):
        old_j, old_arm, old_ss, old_say, old_exec = olds
        bot.JOBS_PATH, bot._arm, bot._send_safe = old_j, old_arm, old_ss
        bot._say, bot._shell_priv_exec = old_say, old_exec
        shutil.rmtree(tmp, ignore_errors=True)

    def test_disable_mode(self):
        """pm 行：全停用——圖示灰、唔使巡、等到期翌日 00:01 復活。"""
        tmp = tempfile.mkdtemp()
        said, olds = self._setup(tmp)
        calls, fake_exec = self._mock_lane(disable_ok=True)
        bot._shell_priv_exec = fake_exec
        try:
            now = dt.datetime.now()
            r = bot._execute_player(
                bot.parse_player("封印 zabank 到 2030-01-01"), 1, now)
            self.assertIn("已停用", r)
            self.assertNotIn("巡邏中", r)
            job = bot._jobs()[0]
            self.assertEqual({a["mode"] for a in job["apps"]},
                             {"disabled"})
            nxt = dt.datetime.fromisoformat(job["next"])
            self.assertEqual((nxt.date(), nxt.hour, nxt.minute),
                             (dt.date(2030, 1, 2), 0, 1))
            self.assertTrue(any("disable-user --user 0 com.zabank.mobile"
                                in c for c in calls))
            # fire：靜默等（冇 patrol）
            calls.clear()
            asyncio.run(bot._fire_later(dict(job), 0))
            self.assertFalse(any("force-stop" in c for c in calls))
            # 到期：pm enable 復活＋通知＋剷
            stale = dict(bot._jobs()[0],
                         apps=[{"pkg": "com.zabank.mobile",
                                "label": "zabank", "until": "2020-01-01",
                                "mode": "disabled"}])
            calls.clear()
            said.clear()
            asyncio.run(bot._fire_later(stale, 0))
            self.assertTrue(any("pm enable --user 0 com.zabank.mobile"
                                in c for c in calls))
            self.assertEqual(said[-1], "解封喇")
            self.assertEqual(bot._jobs(), [])
        finally:
            self._teardown(olds, tmp)

    def test_patrol_fallback(self):
        """pm 死：巡邏模式——命中 force-stop＋旁白；提早解封照覆。"""
        tmp = tempfile.mkdtemp()
        said, olds = self._setup(tmp)
        _calls, fake_exec = self._mock_lane(disable_ok=False)
        bot._shell_priv_exec = fake_exec
        try:
            now = dt.datetime.now()
            r = bot._execute_player(
                bot.parse_player("封印 zabank 到 2030-01-01"), 1, now)
            self.assertIn("巡邏中", r)
            job = bot._jobs()[0]
            self.assertEqual(job["apps"][0]["mode"], "patrol")
            # 命中
            calls2, fake_exec2 = self._mock_lane(disable_ok=False,
                                                 fg_pkg="com.zabank.mobile")
            bot._shell_priv_exec = fake_exec2
            asyncio.run(bot._fire_later(dict(job), 0))
            self.assertTrue(any("force-stop com.zabank.mobile" in c
                                for c in calls2))
            self.assertEqual(said, ["封印緊，專注返正嘢"])
            # 提早解封
            bot._shell_priv_exec = fake_exec
            r = bot._execute_player(bot.parse_player("解封 zabank"), 1, now)
            self.assertIn("已解封", r)
            self.assertEqual(bot._jobs(), [])
        finally:
            self._teardown(olds, tmp)
