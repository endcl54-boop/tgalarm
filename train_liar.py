# -*- coding: utf-8 -*-
"""大話骰 NN 訓練（沙盒跑，唔使手機）：

1. 教師＝數學引擎（binomial tail 門檻策略）喺隨機狀態出標籤
2. MLP（13→24→6）監督式訓練
3. 自我對弈微調：NN vs 教師打 2000 局，贏嗰啲局 NN 行過嘅位加入訓練
4. 對打評估勝率 → 權重烘焙返入 liar.py（# NN-BEGIN/END 標記之間）

用法：python3 train_liar.py
"""
import math
import random
import secrets
import sys

import numpy as np

import liar

IN, HID, OUT = 13, 24, 6
EPOCHS = 60
LR = 0.05
SEED = 20260926


def features(dice, n_total, cur):
    my_n = len(dice)
    n_unk = n_total - my_n
    cnt = [sum(1 for d in dice if d == f) / 5.0 for f in (1, 2, 3, 4, 5, 6)]
    if cur:
        p = liar.p_bid_true(liar.my_count_for(dice, cur[1]), n_unk,
                            cur[0], cur[1])
    else:
        p = 0.0
    return ([p, (cur[0] / 10.0) if cur else 0.0,
             1.0 if (cur and cur[1] == liar.WILD) else 0.0,
             (cur[1] / 6.0) if cur else 0.0]
            + cnt + [n_total / 10.0, my_n / 5.0, 0.0 if cur else 1.0])


def rand_state(rng):
    my_n = rng.randint(1, 5)
    opp_n = rng.randint(1, 5)
    dice = [rng.randint(1, 6) for _ in range(my_n)]
    n_total = my_n + opp_n
    cur = None
    if rng.random() < 0.55:
        cand = liar.legal_raises(None, n_total)
        cur = rng.choice(cand[:max(2, int(len(cand) * 0.5))])
    return dice, n_total, cur


def teacher_label(dice, n_total, cur, slots, mask, rng):
    """教師：數學門檻＋局面細節。回傳 slot index（-1＝冇得揀）。"""
    legal = [i for i in range(6) if mask[i]]
    if not legal:
        return -1
    my_n = len(dice)
    n_unk = n_total - my_n
    if not cur:
        pmap = {i: liar.p_bid_true(liar.my_count_for(dice, slots[i][1][1],
                                                     slots[i][1][2]),
                                   n_unk, slots[i][1][0], slots[i][1][1],
                                   slots[i][1][2])
                for i in legal if slots[i][0] == "bid"}
        best = max(pmap, key=lambda i: pmap[i])
        # 有強牌叫強牌（跟手），否則最穩
        for i in legal:
            if slots[i][0] == "bid" and tuple(slots[i][1]) == strong_bid(dice, n_total):
                return i if pmap[i] > 0.55 else best
        return best
    p = liar.p_bid_true(liar.my_count_for(dice, cur[1], cur[2]), n_unk,
                        cur[0], cur[1], cur[2])
    if p < 0.42:
        return 0 if mask[0] else max((i for i in legal if slots[i][0] == "bid"),
                                     key=lambda i: liar.p_bid_true(
                                         liar.my_count_for(dice, slots[i][1][1],
                                                           slots[i][1][2]),
                                         n_unk, slots[i][1][0], slots[i][1][1],
                                         slots[i][1][2]))
    # 開人唔著數：叫最穩；12% 機會中庸（少少奸）
    if rng.random() < 0.12:
        for i in legal:
            if i == 3:
                return 3
    for i in legal:
        if i == 1:
            return 1
    return legal[-1]


def strong_bid(dice, n_total):
    best_f = max(range(2, 7), key=lambda f: liar.my_count_for(dice, f))
    c = liar.my_count_for(dice, best_f)
    q = min(max(1, c + (0 if c * 3 >= n_total else 1)), liar.MAX_Q)
    return (q, best_f, False)


def forward_np(X, W1, B1, W2, B2):
    H = np.tanh(X @ W1.T + B1)
    L = H @ W2.T + B2
    L -= L.max(axis=1, keepdims=True)
    E = np.exp(L)
    P = E / E.sum(axis=1, keepdims=True)
    return H, P


def gen_dataset(n, rng):
    X, Y = [], []
    while len(X) < n:
        dice, n_total, cur = rand_state(rng)
        slots, mask = liar.action_slots(dice, n_total, cur)
        y = teacher_label(dice, n_total, cur, slots, mask, rng)
        if y < 0:
            continue
        X.append(features(dice, n_total, cur))
        Y.append(y)
    return np.array(X, dtype=np.float64), np.array(Y)


def train():
    rng = random.Random(SEED)
    npr = np.random.default_rng(SEED)
    print("① 生成教師數據…")
    X, Y = gen_dataset(60000, rng)
    Yk = np.eye(OUT)[Y]
    W1 = npr.normal(0, 0.3, (HID, IN))
    B1 = np.zeros(HID)
    W2 = npr.normal(0, 0.3, (OUT, HID))
    B2 = np.zeros(OUT)
    print("② 監督訓練…")
    for ep in range(EPOCHS):
        H, P = forward_np(X, W1, B1, W2, B2)
        G = (P - Yk) / len(X)
        gW2 = G.T @ H
        gB2 = G.sum(0)
        GH = G @ W2 * (1 - H**2)
        gW1 = GH.T @ X
        gB1 = GH.sum(0)
        W2 -= LR * gW2; B2 -= LR * gB2
        W1 -= LR * gW1; B1 -= LR * gB1
        if ep % 10 == 0 or ep == EPOCHS - 1:
            acc = (P.argmax(1) == Y).mean()
            print(f"   ep{ep:3d} acc={acc:.3f}")
    # ③ 自我對弈微調：NN vs 教師，贏局嘅狀態加落數據再練一轉
    print("③ 自我對弈微調…")

    def nn_act(dice, n_total, cur):
        slots, mask = liar.action_slots(dice, n_total, cur)
        H, P = forward_np(np.array([features(dice, n_total, cur)]),
                          W1, B1, W2, B2)
        pr = P[0]
        best, bi = -1, -1
        for i in range(6):
            if mask[i] and pr[i] > best:
                best, bi = pr[i], i
        return slots[bi], bi

    def teach_act(dice, n_total, cur):
        slots, mask = liar.action_slots(dice, n_total, cur)
        i = teacher_label(dice, n_total, cur, slots, mask, rng)
        return slots[i], i

    def play_game(first, Xw, Yw):
        st = {"you": [rng.randint(1, 6) for _ in range(5)],
              "bot": [rng.randint(1, 6) for _ in range(5)],
              "ny": 5, "nb": 5, "bid": None, "turn": "you"}
        trace = []
        while st["ny"] and st["nb"] and len(trace) < 200:
            total = st["ny"] + st["nb"]
            who = st["turn"]
            actfn = nn_act if (who == "you") == (first == "nn") else teach_act
            (kind, bid), slot = actfn(st["you"], total, st["bid"])
            if (who == "you") == (first == "nn"):
                trace.append((features(st["you"], total, st["bid"]), slot))
            if kind == "challenge":
                # 揭盅（approx）：對家骰隨機补
                opp = [rng.randint(1, 6) for _ in
                       range(st["nb"] if who == "you" else st["ny"])]
                mine = st["you"] if who == "you" else st["bot"]
                q, f, jai_b = st["bid"]
                cnt = sum(1 for d in list(mine) + opp
                          if d == f or (not jai_b and f != 1 and d == 1))
                ok = cnt >= q
                bidder = "bot" if who == "you" else "you"
                if ok:
                    loser = "bot" if bidder == "you" else "you"
                else:
                    loser = "you" if bidder == "you" else "bot"
                if loser == "you":
                    st["ny"] -= 1
                else:
                    st["nb"] -= 1
                st["bid"] = None
                st["jai"] = False
                st["turn"] = loser
                st["you"] = [rng.randint(1, 6) for _ in range(st["ny"])]
                st["bot"] = [rng.randint(1, 6) for _ in range(st["nb"])]
            else:
                st["bid"] = bid
                if bid[2]:
                    st["jai"] = True
                st["turn"] = "bot" if who == "you" else "you"
        nn_win = (st["nb"] == 0) if first == "nn" else (st["ny"] == 0)
        if nn_win:
            Xw.extend(t[0] for t in trace)
            Yw.extend(t[1] for t in trace)
        return nn_win

    Xw, Yw = [], []
    wins = 0
    N = 2000
    for g in range(N):
        first = "nn" if g % 2 == 0 else "teach"
        wins += play_game(first, Xw, Yw)
    print(f"   NN vs 教師：{wins}/{N} = {wins/N:.1%}"
          f"（先手優勢對半，~50% 即同級）")
    if Xw:
        Xf = np.array(Xw, dtype=np.float64)
        Yf = np.eye(OUT)[np.array(Yw)]
        for ep in range(8):
            H, P = forward_np(Xf, W1, B1, W2, B2)
            G = (P - Yf) / len(Xf)
            H2 = H
            gW2 = G.T @ H2; gB2 = G.sum(0)
            GH = G @ W2 * (1 - H2**2)
            gW1 = GH.T @ Xf; gB1 = GH.sum(0)
            W2 -= LR * gW2; B2 -= LR * gB2
            W1 -= LR * gW1; B1 -= LR * gB1
        print(f"   微調用咗 {len(Xw)} 個贏局狀態")

    # ④ 烘焙
    def fmt(a):
        return "(" + ",\n ".join("(" + ", ".join(f"{v:.5f}" for v in row) + ")"
                                 for row in a) + ")"

    block = (f"W1 = {fmt(W1)}\nB1 = ({', '.join(f'{v:.5f}' for v in B1)})\n"
             f"W2 = {fmt(W2)}\nB2 = ({', '.join(f'{v:.5f}' for v in B2)})")
    src = open("liar.py").read()
    i = src.find("# NN-BEGIN")
    i = src.find("\n", i) + 1
    j = src.find("# NN-END")
    assert i > 10 and j > i
    open("liar.py", "w").write(src[:i] + block + "\n" + src[j:])
    print("④ 權重已烘焙入 liar.py")
    # 驗推理
    import importlib
    importlib.reload(liar)
    dice, n_total, cur = [2, 2, 5, 1, 6], 10, (3, 4)
    t0 = time.time()
    for _ in range(200):
        liar.decide(dice, n_total, cur)
    print(f"⑤ 推理速度：{(time.time()-t0)/200*1000:.2f} ms/決策")


if __name__ == "__main__":
    import time
    train()
