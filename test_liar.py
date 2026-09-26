# -*- coding: utf-8 -*-
"""大話骰引擎測試：數學對 brute force、合法性、NN 推理、速度、全流程。"""
import asyncio
import random
import time
import unittest

import bot
import liar


class TestLiarMath(unittest.TestCase):
    """Binomial tail 對暴力枚舉。"""

    @staticmethod
    def _brute_tail(n, q, p, iters=40000):
        rng = random.Random(7)
        hits = 0
        for _ in range(iters):
            c = sum(1 for _ in range(n) if rng.random() < p)
            if c >= q:
                hits += 1
        return hits / iters

    def test_tail_matches_bruteforce(self):
        for (n, q) in [(5, 2), (5, 3), (6, 4), (8, 5)]:
            exact = liar._binom_tail(n, q, 1 / 3)
            brute = self._brute_tail(n, q, 1 / 3)
            self.assertAlmostEqual(exact, brute, delta=0.02,
                                   msg=f"n={n} q={q}")

    def test_p_bid_true_bounds_and_wild(self):
        self.assertEqual(liar.p_bid_true(0, 0, 1, 4), 0.0)
        self.assertEqual(liar.p_bid_true(3, 0, 3, 4), 1.0)   # 自己手已夠
        # 1 百搭：P(face) 用 1/3；P(1) 用 1/6
        self.assertAlmostEqual(liar.p_bid_true(0, 6, 2, 4),
                               liar.p_bid_true(0, 6, 2, 5))
        self.assertGreater(liar.p_bid_true(0, 6, 2, 4),
                           liar.p_bid_true(0, 6, 2, 1))

    def test_my_count_wilds_straight_quint(self):
        self.assertEqual(liar.my_count_for([1, 1, 4, 4, 6], 4), 4)
        self.assertEqual(liar.my_count_for([1, 2, 3], 1), 1)  # 淨計1
        self.assertEqual(liar.my_count_for([1, 4, 4], 4, True), 2)  # 齋
        self.assertEqual(liar.hand_contribution([1, 2, 3, 4, 5], 4), 0)  # 蛇
        self.assertEqual(liar.hand_contribution([2, 3, 4, 5, 6], 1), 0)
        self.assertEqual(liar.hand_contribution([3, 3, 3, 3, 3], 3), 6)  # 圍骰
        self.assertEqual(liar.hand_contribution([3, 3, 3, 3, 3], 5), 0)


class TestLiarBids(unittest.TestCase):
    """叫牌全序＋解析。"""

    def test_rank_order(self):
        self.assertLess(liar.bid_rank(3, 4), liar.bid_rank(3, 5))
        self.assertLess(liar.bid_rank(3, 6), liar.bid_rank(3, 1))   # 1 最大
        self.assertLess(liar.bid_rank(3, 1), liar.bid_rank(4, 2))
        self.assertLess(liar.bid_rank(2, 1), liar.bid_rank(3, 2))
        # 齋版插喺非齋同面同非齋下一面中間
        self.assertLess(liar.bid_rank(3, 4, False), liar.bid_rank(3, 4, True))
        self.assertLess(liar.bid_rank(3, 4, True), liar.bid_rank(3, 5, False))
        self.assertLess(liar.bid_rank(3, 6, True), liar.bid_rank(3, 1, True))

    def test_parse_bid(self):
        self.assertEqual(liar.parse_bid("3個4"), (3, 4, False))
        self.assertEqual(liar.parse_bid(" 12個6！"), (12, 6, False))
        self.assertEqual(liar.parse_bid("3個4齋"), (3, 4, True))
        self.assertEqual(liar.parse_bid("3個4 齋"), (3, 4, True))
        self.assertEqual(liar.parse_bid("3個1齋"), (3, 1, True))  # 叫1即齋
        self.assertEqual(liar.parse_bid("3個1"), (3, 1, True))  # 自動 normalize
        self.assertIsNone(liar.parse_bid("30個4"))
        self.assertIsNone(liar.parse_bid("3個7"))
        self.assertIsNone(liar.parse_bid("34"))

    def test_legal_raises_chain(self):
        seq = [(2, 4, False), (2, 5, False), (2, 6, False), (2, 1, False),
               (3, 2, False), (3, 4, True), (4, 6, True), (4, 1, True)]
        for a, b in zip(seq, seq[1:]):
            self.assertLess(liar.bid_rank(*a), liar.bid_rank(*b),
                            f"{a} 應細過 {b}")
        # 齋 mode：產出全部齋
        c = liar.legal_raises((3, 4, True), 10, jai_mode=True)
        self.assertTrue(all(b[2] for b in c))


class TestLiarEngine(unittest.TestCase):
    """動作槽遮罩＋decide 合法性 fuzz＋速度。"""

    def test_masks(self):
        slots, mask = liar.action_slots([2, 2, 5, 1, 6], 10, None)
        self.assertEqual(mask[0], 0)                       # 開局冇得開
        self.assertGreaterEqual(sum(mask), 3)              # 有得叫
        # 必開：對家叫晒成牆
        slots2, mask2 = liar.action_slots([2, 3, 5, 1, 6], 10, (10, 6))
        self.assertEqual(sum(mask2), 1)
        self.assertEqual(mask2[0], 1)
        # 咁真唔准開：我手已經自己夠
        slots3, mask3 = liar.action_slots([4, 4, 4, 1, 1], 10, (4, 4))
        self.assertEqual(mask3[0], 0)                      # 5+? 至少4→P高
        self.assertGreaterEqual(sum(mask3), 1)

    def test_decide_always_legal_fuzz(self):
        rng = random.Random(42)
        for _ in range(500):
            my_n = rng.randint(1, 5)
            dice = [rng.randint(1, 6) for _ in range(my_n)]
            opp = rng.randint(1, 5)
            total = my_n + opp
            cur = None
            if rng.random() < 0.6:
                cand = liar.legal_raises(None, total)
                cur = rng.choice(cand)
            act, bid = liar.decide(dice, total, cur)
            if act == "challenge":
                self.assertIsNotNone(cur)
            else:
                self.assertEqual(len(bid), 3)
                q, f, jai = bid
                self.assertTrue(1 <= q <= liar.MAX_Q and 1 <= f <= 6)
                if cur:
                    self.assertGreater(liar.bid_rank(q, f, jai),
                                       liar.bid_rank(*cur))

    def test_decide_speed(self):
        dice = [2, 2, 5, 1, 6]
        t0 = time.time()
        for _ in range(200):
            liar.decide(dice, 10, (3, 4))
        dt = time.time() - t0
        self.assertLess(dt, 2.0, f"200 次用了 {dt:.2f}s（要求 <2s）")

    def test_policy_sums_to_one(self):
        p = liar.nn_policy([0.0] * 13)
        self.assertAlmostEqual(sum(p), 1.0, places=6)


class TestLiarGame(unittest.TestCase):
    """狀態機全流程。"""

    def test_score_mode_20_rounds_no_elimination(self):
        rng = random.Random(99)
        st = liar.new_game(starter="bot")
        liar.bot_speak_bid(st)                       # bot 先開
        for _ in range(20):
            self.assertFalse(st["over"])
            self.assertEqual(st["you_n"] + st["bot_n"], 10)   # 永遠 10 粒
            if st["await_dice"]:
                ud = "我 " + " ".join(str(rng.randint(1, 6)) for _ in range(5))
                rep, _ = liar.user_dice_declare(st, ud)
                self.assertIsNotNone(rep)
                continue
            act, bid = liar.decide([rng.randint(1, 6) for _ in range(st["you_n"])],
                                   st["you_n"] + st["bot_n"], st["bid"])
            if act == "challenge":
                r = liar.user_challenge(st)
                self.assertIn("打你手骰", r)
            else:
                r = liar.user_bid(st, *bid)
                self.assertIsNotNone(r)
        self.assertEqual(st["you_n"] + st["bot_n"], 10)       # 冇人減過骰
        self.assertGreater(st["you_wins"] + st["bot_wins"], 0) # 有計分

    def test_wrong_turn_and_low_raise_rejected(self):
        st = liar.new_game(starter="you")
        st["bot"] = [4, 4, 1, 2, 6]                   # 釘骰：bot 會叫唔會亂開
        r = liar.user_bid(st, 3, 5)
        self.assertIn("我叫", r)                       # bot 回應咗
        r = liar.user_challenge(st)
        self.assertIn("打你手骰", r)                   # bot 叫完→到你，開得
        rep, _ = liar.user_dice_declare(st, "我 1 1 1 1 1")
        self.assertIn("攤牌", rep)

    def test_reveal_counts_and_loser(self):
        st = liar.new_game(starter="you")
        st["bot"] = [4, 4, 1, 2, 6]                   # 釘住 bot 骰
        liar.user_bid(st, 3, 5)                       # 可能 bot 加注或開
        if st["await_dice"]:                          # bot 開咗你
            rep, _ = liar.user_dice_declare(st, "我 5 5 5 5 5")
            self.assertIn("攤牌", rep)
        else:
            # bot 加咗注 → 你開佢
            rep = liar.user_challenge(st)
            self.assertIn("打你手骰", rep)
            rep, _ = liar.user_dice_declare(st, "我 5 5 5 5 5")
            self.assertIn("攤牌", rep)
        # 計分制：冇人扣骰，有勝場
        self.assertEqual(st["you_n"] + st["bot_n"], 10)
        self.assertGreater(st["you_wins"] + st["bot_wins"], 0)

    def test_declare_parse_fail(self):
        st = liar.new_game(starter="you")
        liar.user_bid(st, 3, 3)
        if st["await_dice"]:
            rep, _ = liar.user_dice_declare(st, "我 1 2 3")   # 唔夠 5 粒
            self.assertIsNone(rep)


class TestOppModel(unittest.TestCase):
    """對手建模：出價質素 EMA → 預設緊逼（鏡像），證實亂叫先放寬。"""

    def test_new_game_has_opp_fields(self):
        st = liar.new_game(starter="you")
        for k in ("u_p_ema", "u_bids", "u_false", "u_calls", "u_folds"):
            self.assertIn(k, st)

    def test_user_bid_updates_p_ema(self):
        st = liar.new_game(starter="you")
        st["bot"] = [2, 2, 2, 5, 6]
        before = st["u_p_ema"]
        liar.user_bid(st, 3, 2)          # 高質叫（我手三條2，P 好高）
        self.assertGreater(st["u_p_ema"], before)
        st2 = liar.new_game(starter="you")
        st2["bot"] = [2, 2, 2, 5, 6]
        liar.user_bid(st2, 9, 3)         # 爛叫（P 低）
        self.assertLess(st2["u_p_ema"], 0.45)

    def test_tight_never_bids_below_floor(self):
        rng = random.Random(11)
        checked = 0
        for _ in range(150):
            my_n = rng.randint(2, 5)
            dice = [rng.randint(1, 6) for _ in range(my_n)]
            opp_n = rng.randint(1, 5)
            total = my_n + opp_n
            cand = liar.legal_raises(None, total)
            best_p = max(liar.p_bid_true(liar.my_count_for(dice, b[1]),
                                         total - my_n, b[0], b[1])
                         for b in cand)
            if best_p < 0.43:
                continue                  # 淨低質位可揀（被迫）→唔適用
            act, bid = liar.decide(dice, total, None,
                                   {"bids": 5, "p_ema": 0.6,
                                    "bluff": 0.1, "calls": 0, "folds": 9})
            if act == "bid":
                p = liar.p_bid_true(liar.my_count_for(dice, bid[1]),
                                    total - my_n, bid[0], bid[1])
                self.assertGreaterEqual(p, 0.40, f"dice={dice} bid={bid}")
                checked += 1
        self.assertGreater(checked, 30)

    def test_gate_uses_opp_quality(self):
        """對手出價質素 EMA 直接驅動挑戰閘：爛叫佬放、正經人鏡像 0.42。"""
        dice, total = [2, 3, 5, 1, 6], 10
        seen = {}
        orig = liar.action_slots

        def spy(*a, **k):
            seen["hi"] = a[4] if len(a) > 4 else k.get("gate_hi")
            return orig(*a, **k)
        liar.action_slots = spy
        try:
            liar.decide(dice, total, None,
                        {"bids": 5, "p_ema": 0.3, "bluff": 0.8,
                         "calls": 0, "folds": 9})
            self.assertGreaterEqual(seen["hi"], 0.60)   # 爛叫佬→閘放寬
            liar.decide(dice, total, None,
                        {"bids": 5, "p_ema": 0.6, "bluff": 0.1,
                         "calls": 0, "folds": 9})
            self.assertEqual(seen["hi"], 0.42)          # 正經→鏡像
        finally:
            liar.action_slots = orig


class TestLiarGlue(unittest.TestCase):
    """bot.py 接線：開枱／叫牌／開／報骰／收工。"""

    def setUp(self):
        self._decide = liar.decide
        bot._LIAR_GAMES.clear()

    def tearDown(self):
        liar.decide = self._decide
        bot._LIAR_GAMES.clear()

    def test_start_bid_challenge_finish(self):
        r = bot._liar_handle(1, "大話")
        self.assertIn("開枱", r)
        r = bot._liar_handle(1, "3個5")
        self.assertTrue(r)                            # bot 回應（叫/開）
        if bot._LIAR_GAMES[1]["await_dice"]:
            r = bot._liar_handle(1, "我 1 2 3 4 5")
            self.assertIn("攤牌", r)
        else:
            r = bot._liar_handle(1, "開")
            self.assertIn("打你手骰", r)
            r = bot._liar_handle(1, "我 1 2 3 4 5")
            self.assertIn("攤牌", r)
        r = bot._liar_handle(1, "大話結束")
        self.assertIn("戰績", r)
        self.assertNotIn(1, bot._LIAR_GAMES)

    def test_duplicate_start_hint(self):
        bot._liar_handle(2, "大話")
        r = bot._liar_handle(2, "大話")
        self.assertIn("開咗枱", r)

    def test_not_liar_text_returns_none(self):
        bot._liar_handle(3, "大話")
        self.assertIsNone(bot._liar_handle(3, "天氣"))
        self.assertIn("未開枱", bot._liar_handle(9, "大話結束"))  # 冇局都提示
        self.assertIn("未開枱", bot._liar_handle(9, "2個1齋"))    # 叫牌都提示
        self.assertIsNone(bot._liar_handle(9, "天氣"))            # 唔關事→靜


class TestJaiPai(unittest.TestCase):
    """齋叫＋劈／反劈＋結算新規則。"""

    def setUp(self):
        bot._LIAR_GAMES.clear()

    def tearDown(self):
        bot._LIAR_GAMES.clear()

    def test_jai_persists_and_message(self):
        st = liar.new_game(starter="you")
        st["bot"] = [4, 4, 1, 2, 6]
        r = liar.user_bid(st, 2, 4, jai=True)
        self.assertIn("齋叫生效", r)
        self.assertTrue(st["jai"])
        # 之後 bot 叫都係齋
        if st["bid"]:
            self.assertTrue(st["bid"][2])

    def test_pai_double_stake_and_counter(self):
        st = liar.new_game(starter="you")
        st["bot"] = [5, 5, 1, 3, 3]     # 對 3個5 有底氣（3≥3）→ 反劈
        st["bid"], st["bidder"], st["turn"] = (3, 5, False), "bot", "you"
        r = liar.user_challenge(st, stake=2)
        self.assertIn("劈", r)
        self.assertIn("反劈", r)
        self.assertEqual(st["stake"], 4)    # 反劈 → 4
        rep, _ = liar.user_dice_declare(st, "我 2 2 2 2 2")
        self.assertIn("注 4 分", rep)
        self.assertEqual(st["bot_wins"], 4)  # bot 贏 4 分

    def test_pai_no_counter_when_weak(self):
        st = liar.new_game(starter="you")
        st["bot"] = [2, 2, 5, 5, 3]     # 對 4 完全冇貢獻，冇底氣
        st["bid"], st["bidder"], st["turn"] = (2, 4, False), "bot", "you"
        r = liar.user_challenge(st, stake=2)
        self.assertEqual(st["stake"], 2)    # 唔敢反劈
        rep, _ = liar.user_dice_declare(st, "我 5 5 5 5 5")
        self.assertIn("注 2 分", rep)
        self.assertEqual(st["you_wins"], 2)


class TestOpeningRules(unittest.TestCase):
    """起手規則（2026-09-26 用戶追加）：唔齋 3 個起、齋 2 個起、1 淨做百搭。"""

    def test_opening_floor_user_side(self):
        st = liar.new_game(starter="you")
        r = liar.user_bid(st, 2, 5)
        self.assertIn("起手", r)
        self.assertIsNone(st["bid"])                  # 冇落叫
        r = liar.user_bid(st, 1, 4)
        self.assertIn("起手", r)
        r = liar.user_bid(st, 2, 4, jai=True)         # 齋 2 個起＝合法
        self.assertIn("齋叫生效", r)
        self.assertTrue(st["jai"])
        if st["bid"]:
            self.assertTrue(st["bid"][2])             # bot 跟住都係齋

    def test_ones_always_jai(self):
        """用戶更正：1齋接受——「X個1」一律當齋；起手 1個1 屬齋（照齋 2 個起）。"""
        self.assertEqual(liar.parse_bid("3個1"), (3, 1, True))
        self.assertEqual(liar.parse_bid("3個1齋"), (3, 1, True))
        for cur in (None, (3, 4, False)):
            for jm in (False, True):
                c = liar.legal_raises(cur, 10, jai_mode=jm)
                self.assertTrue(c)
                self.assertTrue(all(b[2] for b in c if b[1] == 1),
                                f"面1非齋: cur={cur} jm={jm}")
        st = liar.new_game(starter="you")
        r = liar.user_bid(st, 1, 1)
        self.assertIn("起手", r)                      # 1個1 屬齋 → 唔夠 2 個起
        self.assertIsNone(st["bid"])
        st2 = liar.new_game(starter="you")
        st2["bot"] = [1, 1, 4, 4, 6]                  # 釘骰：bot 有底氣會叫唔會開
        r2 = liar.user_bid(st2, 2, 1, jai=True)
        self.assertIn("我叫", r2)                      # 2個1齋 起手＝合法
        self.assertTrue(st2["jai"])                   # 叫1即齋 mode 開咗
        self.assertTrue(st2["bid"][2])                # bot 跟住都係齋
        self.assertGreater(liar.bid_rank(*st2["bid"]),
                           liar.bid_rank(2, 1, True))

    def test_bot_opening_respects_floors(self):
        rng = random.Random(7)
        for _ in range(200):
            dice = [rng.randint(1, 6) for _ in range(5)]
            act, bid = liar.decide(dice, 10, None)
            self.assertEqual(act, "bid")
            q, f, jai = bid
            if f == 1:
                self.assertTrue(jai)                  # 面1一定齋
            self.assertGreaterEqual(q, liar.OPEN_MIN_JAI if jai
                                    else liar.OPEN_MIN_Q)

    def test_glue_rejects_low_opening(self):
        bot._LIAR_GAMES.clear()
        bot._LIAR_GAMES[11] = liar.new_game(starter="you")
        r = bot._liar_handle(11, "2個5")
        self.assertIn("起手", r)
        self.assertIsNone(bot._LIAR_GAMES[11]["bid"])
        r = bot._liar_handle(11, "3個5")
        self.assertTrue(r)
        bot._LIAR_GAMES.clear()

    def test_glue_accepts_ones_jai(self):
        bot._LIAR_GAMES.clear()
        bot._LIAR_GAMES[12] = liar.new_game(starter="you")
        bot._LIAR_GAMES[12]["bot"] = [1, 1, 4, 4, 6]
        r = bot._liar_handle(12, "1個1")
        self.assertIn("起手", r)                      # 1個1 唔夠齋底
        r = bot._liar_handle(12, "2個1齋")
        self.assertTrue(r)                            # 2個1齋 起手＝合法
        g = bot._LIAR_GAMES[12]
        self.assertTrue(g["jai"])                     # 叫1即齋 mode 開咗
        self.assertTrue(g["bid"][2])                  # bot 跟住都係齋
        self.assertGreater(liar.bid_rank(*g["bid"]),
                           liar.bid_rank(2, 1, True))
        bot._LIAR_GAMES.clear()


if __name__ == "__main__":
    unittest.main(verbosity=2)
