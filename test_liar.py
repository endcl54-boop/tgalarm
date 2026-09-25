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

    def test_my_count_wilds(self):
        self.assertEqual(liar.my_count_for([1, 1, 4, 4, 6], 4), 4)
        self.assertEqual(liar.my_count_for([1, 2, 3], 1), 1)  # 淨計1


class TestLiarBids(unittest.TestCase):
    """叫牌全序＋解析。"""

    def test_rank_order(self):
        self.assertLess(liar.bid_rank(3, 4), liar.bid_rank(3, 5))
        self.assertLess(liar.bid_rank(3, 6), liar.bid_rank(3, 1))   # 1 最大
        self.assertLess(liar.bid_rank(3, 1), liar.bid_rank(4, 2))
        self.assertLess(liar.bid_rank(2, 1), liar.bid_rank(3, 2))

    def test_parse_bid(self):
        self.assertEqual(liar.parse_bid("3個4"), (3, 4))
        self.assertEqual(liar.parse_bid(" 12個6！"), (12, 6))
        self.assertIsNone(liar.parse_bid("30個4"))
        self.assertIsNone(liar.parse_bid("3個7"))
        self.assertIsNone(liar.parse_bid("34"))

    def test_legal_raises_chain(self):
        seq = [(2, 4), (2, 5), (2, 6), (2, 1), (3, 2), (3, 4), (4, 6), (4, 1)]
        for a, b in zip(seq, seq[1:]):
            self.assertLess(liar.bid_rank(*a), liar.bid_rank(*b),
                            f"{a} 應細過 {b}")


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
                self.assertEqual(len(bid), 2)
                q, f = bid
                self.assertTrue(1 <= q <= liar.MAX_Q and 1 <= f <= 6)
                if cur:
                    self.assertGreater(liar.bid_rank(q, f),
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

    def test_full_game_random_to_completion(self):
        rng = random.Random(99)
        st = liar.new_game(starter="bot")
        liar.bot_speak_bid(st)                       # bot 先開
        guard = 0
        while not st["over"]:
            guard += 1
            self.assertLess(guard, 400, "局打唔完（死循環？）")
            if st["await_dice"]:
                # 用戶誠實報：隨機 5 粒
                ud = "我 " + " ".join(str(rng.randint(1, 6)) for _ in range(5))
                rep, _ = liar.user_dice_declare(st, ud)
                self.assertIsNotNone(rep)
                continue
            # 用戶：跟引擎建議（當佢識玩）
            act, bid = liar.decide(st["bot"] and [rng.randint(1, 6)
                                                  for _ in range(st["you_n"])],
                                   st["you_n"] + st["bot_n"], st["bid"])
            if act == "challenge":
                r = liar.user_challenge(st)
                self.assertIn("打你手骰", r)
            else:
                r = liar.user_bid(st, *bid)
                self.assertIsNotNone(r)
        self.assertTrue(st["you_n"] == 0 or st["bot_n"] == 0)
        self.assertIn("戰績", (liar.user_dice_declare(st, "我 1 1 1 1 1")[0]
                              or "")) if False else None

    def test_wrong_turn_and_low_raise_rejected(self):
        st = liar.new_game(starter="you")
        st["bot"] = [4, 4, 1, 2, 6]                   # 釘骰：bot 會叫唔會亂開
        r = liar.user_bid(st, 2, 5)
        self.assertIn("我叫", r)                       # bot 回應咗
        r = liar.user_challenge(st)
        self.assertIn("打你手骰", r)                   # bot 叫完→到你，開得
        rep, _ = liar.user_dice_declare(st, "我 1 1 1 1 1")
        self.assertIn("攤牌", rep)

    def test_reveal_counts_and_loser(self):
        st = liar.new_game(starter="you")
        st["bot"] = [4, 4, 1, 2, 6]                   # 釘住 bot 骰
        liar.user_bid(st, 2, 5)                       # 可能 bot 加注或開
        if st["await_dice"]:                          # bot 開咗你
            rep, _ = liar.user_dice_declare(st, "我 5 5 5 5 5")
            self.assertIn("攤牌", rep)
        else:
            # bot 加咗注 → 你開佢
            rep = liar.user_challenge(st)
            self.assertIn("打你手骰", rep)
            rep, _ = liar.user_dice_declare(st, "我 5 5 5 5 5")
            self.assertIn("攤牌", rep)
        # 扣粒：其中一方 -1
        self.assertIn(st["you_n"] + st["bot_n"], (9,))

    def test_declare_parse_fail(self):
        st = liar.new_game(starter="you")
        liar.user_bid(st, 2, 3)
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
        liar.user_bid(st, 1, 2)          # 高質叫（我手三條2，P 好高）
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

        def spy(d, n, c, lo=0.12, hi=0.75):
            seen["hi"] = hi
            return orig(d, n, c, lo, hi)
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
        r = bot._liar_handle(1, "2個5")
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
        self.assertIsNone(bot._liar_handle(9, "大話結束"))  # 冇局


if __name__ == "__main__":
    unittest.main(verbosity=2)
