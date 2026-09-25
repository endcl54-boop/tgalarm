# -*- coding: utf-8 -*-
"""大話骰評估台：現役引擎 vs 三種模擬對手（誠實數學／吹水佬／狂徒）。

對手同引擎用同一個 decide API（隱藏資訊對稱：對手只知自己骰＋叫牌史；
攤牌時對家骰隨機补——同真實期望一致）。輸出勝率。
"""
import random
import sys

import liar


def math_act(dice, total, cur, opp=None, jai=False):
    my_n = len(dice)
    n_unk = total - my_n
    if cur:
        p = liar.p_bid_true(liar.my_count_for(dice, cur[1]), n_unk,
                            cur[0], cur[1])
        if p < 0.42:
            return "challenge", None
    cand = liar.legal_raises(cur, total, jai)
    if not cand:
        return "challenge", None
    best = max(cand, key=lambda b: liar.p_bid_true(
        liar.my_count_for(dice, b[1], b[2]), n_unk, b[0], b[1], b[2]))
    return "bid", best


def bluff_act(dice, total, cur, opp=None, jai=False):
    """人類吹水佬：三成機會吹大（期望+1～+2），否則照數學叫。"""
    rng = random
    my_n = len(dice)
    n_unk = total - my_n
    if cur:
        p = liar.p_bid_true(liar.my_count_for(dice, cur[1]), n_unk,
                            cur[0], cur[1])
        if p < 0.35:
            return "challenge", None
    cand = liar.legal_raises(cur, total, jai)
    if not cand:
        return "challenge", None
    if rng.random() < 0.30:
        # 吹：搵個 P≈0.2-0.35 嘅位
        bluffy = [b for b in cand
                  if 0.12 <= liar.p_bid_true(liar.my_count_for(dice, b[1], b[2]),
                                             n_unk, b[0], b[1], b[2]) <= 0.38]
        if bluffy:
            return "bid", rng.choice(bluffy)
    return math_act(dice, total, cur)


def maniac_act(dice, total, cur, opp=None, jai=False):
    """狂徒：永遠加最少，P<0.5 就開。"""
    if cur:
        n_unk = total - len(dice)
        p = liar.p_bid_true(liar.my_count_for(dice, cur[1], cur[2]), n_unk,
                            cur[0], cur[1], cur[2])
        if p < 0.50:
            return "challenge", None
    cand = liar.legal_raises(cur, total, jai)
    if not cand:
        return "challenge", None
    return "bid", cand[0]


OPPONENTS = {"數學佬": math_act, "吹水佬": bluff_act, "狂徒": maniac_act}


def play_game(bot_first: bool, opp_fn, rng) -> bool:
    st = {"you": [rng.randint(1, 6) for _ in range(5)],
          "bot": [rng.randint(1, 6) for _ in range(5)],
          "ny": 5, "nb": 5, "bid": None,
          "u_bids": 0, "u_false": 0.0, "u_calls": 0, "u_folds": 0,
          "u_p_ema": 0.5, "jai": False, "stake": 1,
          "turn": "you" if bot_first else "bot"}
    while st["ny"] and st["nb"]:
        total = st["ny"] + st["nb"]
        if st["turn"] == "you":                      # 對手行 you 側
            act, bid = opp_fn(st["you"], total, st["bid"], None, st.get("jai", False))
            if act == "challenge":
                st["u_calls"] += 1
                q, f, jai = st["bid"]
                cnt = (liar.hand_contribution(st["you"], f, jai)
                       + liar.hand_contribution(st["bot"], f, jai))
                ok = cnt >= q
                if not ok:
                    st["u_false"] = 0.7 * st["u_false"] + 0.3 * 1.0
                else:
                    st["u_false"] = 0.7 * st["u_false"] + 0.3 * 0.0
                st["u_bids"] += 1
                loser = "you" if ok else "bot"
            else:
                st["u_folds"] += 1
                if bid[2]:
                    st["jai"] = True
                import liar as L
                st["u_p_ema"] = 0.7 * st.get("u_p_ema", 0.5) + 0.3 * L.p_bid_true(
                    L.my_count_for(st["bot"], bid[1], bid[2]),
                    st["ny"] + st["nb"] - len(st["bot"]), bid[0], bid[1], bid[2])
                st["bid"] = bid
                loser = None
                st["turn"] = "bot"
        else:
            opp = {"bluff": st["u_false"], "calls": st["u_calls"],
                   "folds": st["u_folds"], "bids": st["u_bids"],
                   "p_ema": st["u_p_ema"]}
            act, bid = liar.decide(st["bot"], total, st["bid"], opp,
                                   st.get("jai", False))
            if act == "challenge":
                q, f, jai = st["bid"]
                cnt = (liar.hand_contribution(st["you"], f, jai)
                       + liar.hand_contribution(st["bot"], f, jai))
                ok = cnt >= q
                loser = "bot" if ok else "you"
            else:
                st["bid"] = bid
                if bid[2]:
                    st["jai"] = True
                loser = None
                st["turn"] = "you"
        if loser:
            if loser == "you":
                st["ny"] -= 1
            else:
                st["nb"] -= 1
            st["bid"] = None
            st["jai"] = False
            st["turn"] = loser
            st["you"] = [rng.randint(1, 6) for _ in range(st["ny"])]
            st["bot"] = [rng.randint(1, 6) for _ in range(st["nb"])]
    return st["ny"] == 0                                # bot 贏＝對手清咗


def main():
    rng = random.Random(20260926)
    print(f"{'對手':<6}{'先手勝率':>10}{'後手勝率':>10}{'總計':>10}")
    for name, fn in OPPONENTS.items():
        w1 = sum(play_game(True, fn, rng) for _ in range(300))
        w2 = sum(play_game(False, fn, rng) for _ in range(300))
        print(f"{name:<6}{w1/300:>9.1%}{w2/300:>9.1%}{(w1+w2)/600:>9.1%}")


if __name__ == "__main__":
    main()
