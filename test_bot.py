# -*- coding: utf-8 -*-
"""bot.py 指令解析 + Intent 生成嘅單元測試（唔使 Telegram、唔使 Android 都行到）"""
import asyncio
import datetime as dt
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import bot
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

    def test_over_99999h_rejected(self):
        p = parse_command("計時 100000小時", NOW)
        self.assertIsNotNone(p)
        self.assertIn("超過計時上限", _execute(p, NOW))

    def test_exactly_99999h_allowed(self):
        p = parse_command("計時 99999小時", NOW)
        self.assertEqual(p.seconds, 99999 * 3600)
        self.assertNotIn("超過計時上限", _execute(p, NOW))  # 去到 intent 步驟（沙盒冇 am，但唔係上限擋）


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
        def fake(cmd):
            calls.append(cmd)
            return True, ""
        bot.run_intent = fake
        ok, _ = bot._stop()
        self.assertTrue(ok)
        self.assertEqual(calls, [["/system/bin/am", "force-stop", bot._YT_PKG]])

    def test_fallback_to_path_am(self):
        seq = iter([(False, "termux-am 唔支援"), (True, "")])
        bot.run_intent = lambda cmd: next(seq)
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
        bot.run_intent = lambda cmd: calls.append(cmd) or (True, "")
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
        ok, info = bot._edit_job(jid, "荃灣西站 步行", self.now)
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
        bot.run_intent = lambda cmd: calls.append(cmd) or (True, "")
        ok, how = bot._stop()
        self.assertEqual((ok, how), (True, "audio-focus"))
        self.assertIn("silence.wav", calls[0][2])

    def test_home_fallback_when_all_denied(self):
        def fake(cmd):
            return (any("HOME" in part for part in cmd), "")  # force-stop 全 fail，HOME start 成功
        bot.run_intent = fake
        ok, how = bot._stop()
        self.assertEqual((ok, how), (True, "home"))

    def test_all_layers_fail(self):
        bot.run_intent = lambda cmd: (False, "denied")
        ok, how = bot._stop()
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
        segs, err = bot._alloc_segments("A、B", 0, 3600)
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

        def fake(cmd):
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
        bot.run_intent = lambda cmd: (True, "")
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
        bot.run_intent = lambda cmd: calls.append(cmd) or (True, "")
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

    def tearDown(self):
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
        # 目的已有同名 → 防撞名
        with open(os.path.join(self.dest, "IMG-a.jpg"), "wb") as f:
            f.write(b"old")
        r = bot._wa_move(self.now, preview=False, src_root=self.tmp, dest=self.dest)
        self.assertIn("搬咗 2/2 張", r)
        self.assertIn("↗", r)                               # Sent 有箭嘴標記
        self.assertFalse(os.path.exists(p1))
        self.assertFalse(os.path.exists(p2))
        self.assertTrue(os.path.exists(os.path.join(self.dest, "IMG-a-1.jpg")))
        self.assertTrue(os.path.exists(os.path.join(self.dest, "IMG-b.jpg")))

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
        # 注入 src_root／dest 做沙盒模擬
        old_dirs, old_dest = bot._WA_MEDIA_CANDIDATES, bot._WA_DEST
        bot._WA_MEDIA_CANDIDATES = (self.tmp,)
        bot._WA_DEST = self.dest
        try:
            r = bot._execute_player(cmd, 12345, self.now)
        finally:
            bot._WA_MEDIA_CANDIDATES, bot._WA_DEST = old_dirs, old_dest
        self.assertIn("搬咗 1/1 張", r)
        self.assertTrue(os.path.exists(os.path.join(self.dest, "IMG-x.jpg")))


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
        job = self._mk_alloc()                 # 巡樓進行中，仲淨 15 分鐘
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
        job = self._mk_alloc(idx=2)            # 發相（最後段）進行中
        r = self._done()
        self.assertIn("提早收工", r)
        self.assertIn("已刪走", r)
        self.assertEqual(bot._jobs(), [])      # job 消失
        self.assertNotIn(7, bot._TASKS)

    def test_last_stage_daily_rearms_tomorrow(self):
        job = self._mk_alloc(idx=2, daily=True)
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

        def run(cmd):
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
        calls, run = self._stub([False, False, False])
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
        bot.run_intent = lambda cmd: calls.append(cmd) or (True, "ok")
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
        def run(cmd):
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
        bot.run_intent = lambda cmd: calls.append(cmd) or (True, "")
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
        bot._jobs = lambda: []
        bot._save_json = lambda *a, **k: None
        bot.run_intent = lambda cmd: (True, "")
        bot._RISH_CACHE.update({"t": 1e18, "ok": True})  # 舊 cache 話 ok，都要重探
        # 新流程：通知彈窗先；呢度強制行後備直開路，驗證重探＋警告仍然喺度
        bot._nav_confirm_notify = lambda job: (False, "冇 termux-notification")
        bot._shell_priv_exec = lambda s: (True, "")
        bot._adb_lane_available = lambda: False
        self._fire()
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
        bot._jobs = lambda: []
        bot._save_json = lambda *a, **k: None
        calls = []
        bot.run_intent = lambda cmd: calls.append(cmd) or (True, "ok")
        bot._RISH_CACHE.update({"t": 0.0, "ok": False})
        bot._nav_confirm_notify = lambda job: (False, "冇")
        self._fire()
        self.assertEqual(calls[0][0], "rish")           # probe ok → WAKEUP 都行 rish
        self.assertNotIn("可能彈唔出", sent[0])

    def test_notify_ok_means_no_direct_open(self):
        """彈窗通知成功 → 唔直接開 app，等用戶撳確定。"""
        bot.shutil.which = lambda _: "/x/rish"
        sent = []
        async def fake_send(cid, text, label=""):
            sent.append(text)
            return True
        bot._send_safe = fake_send
        bot._jobs = lambda: []
        bot._save_json = lambda *a, **k: None
        calls = []
        bot.run_intent = lambda cmd: calls.append(cmd) or (True, "ok")
        bot._shell_priv_exec = lambda s: calls.append(["wake", s]) or (True, "")
        bot._nav_confirm_notify = lambda job: (True, "ok")
        self._fire()
        self.assertIn("撳【確定開地圖】先會開", sent[0])
        # 淨係得 WAKEUP，冇直接 am start 開地圖
        self.assertEqual(len(calls), 1)
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
        ok, out = bot._nav_confirm_notify(self._job())
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
        self.assertIn("撳【確定開地圖】先會開", r)
        self.assertEqual(opened, [])          # 未撳掣 → 唔直接開

    def test_notify_fail_direct_open(self):
        bot._nav_confirm_notify = lambda job: (False, "冇 termux-notification")
        bot._open_nav = lambda d, m: (True, "")
        r = self._ex("導航 屋企")
        self.assertIn("開緊導航去", r)
        self.assertIn("直接開", r)


class TestNavUnlockWatch(unittest.TestCase):
    """鎖屏到點：解鎖後自動重發通知令頭條重新彈出。"""

    def setUp(self):
        self._shell = bot._adb_shell
        self._notify = bot._nav_confirm_notify
        self._unlocked = bot._screen_unlocked
        self._watch = bot._nav_unlock_watch
        self._run = bot.subprocess.run
        self._sleep = asyncio.sleep

        async def fast_sleep(_):
            pass
        asyncio.sleep = fast_sleep

    def tearDown(self):
        bot._adb_shell = self._shell
        bot._nav_confirm_notify = self._notify
        bot._screen_unlocked = self._unlocked
        bot._nav_unlock_watch = self._watch
        bot.subprocess.run = self._run
        asyncio.sleep = self._sleep

    def _job(self):
        return {"id": 3, "type": "nav", "url": "X", "mode": "r",
                "label": "屋企", "chat_id": 1}

    def test_screen_unlocked_true(self):
        bot._adb_shell = lambda c: (True, "isKeyguardShowing=false\n  mWakefulness=Awake")
        self.assertTrue(bot._screen_unlocked())

    def test_screen_locked(self):
        bot._adb_shell = lambda c: (True, "isKeyguardShowing=true\n  mWakefulness=Awake")
        self.assertFalse(bot._screen_unlocked())

    def test_screen_off(self):
        bot._adb_shell = lambda c: (True, "isKeyguardShowing=false\n  mWakefulness=Asleep")
        self.assertFalse(bot._screen_unlocked())

    def test_adb_dead_means_locked(self):
        bot._adb_shell = lambda c: (False, "")
        self.assertFalse(bot._screen_unlocked())

    def test_watch_reposts_after_unlock(self):
        states = iter([False, False, True])
        bot._screen_unlocked = lambda: next(states, True)
        removed, posted = [], []
        bot.subprocess.run = lambda cmd, **kw: removed.append(cmd[0])
        bot._nav_confirm_notify = lambda job: posted.append(job["id"]) or (True, "ok")
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(bot._nav_unlock_watch(self._job()))
        finally:
            loop.close()
        self.assertEqual(removed, ["termux-notification-remove"])
        self.assertEqual(posted, [3])                 # 解鎖後重發一次

    def test_fire_starts_watch_when_locked(self):
        watched = []
        bot._nav_confirm_notify = lambda job: (True, "ok")
        bot._screen_unlocked = lambda: False
        async def fake_watch(job):
            watched.append(job["id"])
        bot._nav_unlock_watch = fake_watch
        bot._shell_priv_exec = lambda s: (True, "")
        bot.run_intent = lambda cmd: (True, "")
        sent = []
        async def fake_send(cid, text, label=""):
            sent.append(text)
            return True
        old_send, old_jobs, old_save, old_dry = (bot._send_safe, bot._jobs,
                                                 bot._save_json, bot.DRY_RUN)
        bot._send_safe, bot._jobs, bot._save_json, bot.DRY_RUN = fake_send, lambda: [], (lambda *a, **k: None), False
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
        self.assertEqual(watched, [42])


if __name__ == "__main__":
    unittest.main(verbosity=2)
