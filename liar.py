# -*- coding: utf-8 -*-
"""大話骰（Dudo／Perudo，港式完整版）1v1 引擎。

規則（2026-09-26 用戶提供完整版＋計分制）：
  · 1 百搭（唔叫齋時）；叫「齋」之後成個 round 1 唔再百搭
  · 起手規則（2026-09-26 用戶追加）：唔齋 3 個起、齋 2 個起；
    1 只做百搭——永遠唔叫得「X個1」
  · 叫牌全序：數量優先；同數量入面 2<3<4<5<6<1；齋版大過非齋同叫
  · 蛇（1-5 或 2-6 順子）：嗰手 5 粒當 0 顆
  · 圍骰（5 粒全同）：該面多算 1 顆（當 6 顆）
  · 劈＝挑戰但輸贏雙倍分；bot 對自己叫有信心會「反劈」（再雙倍）
  · 計分制：輸家唔減骰，記分（開=1／劈=2／反劈=4），輸家先叫，永續玩
  · 攤牌結算：齋／蛇／圍骰全部生效

決策三層（快——純本地、零網絡、NN 推理 <0.5ms）：
  1. 數學層：Binomial tail 精確 P(叫牌屬實)；極端值直接否決 NN
  2. NN 層：13→24→6 MLP（自我對弈訓練，權重烘焙），純 Python 推理
  3. 對手建模：出價質素 EMA → 緊逼（鏡像）／攻擊閘切換
"""
import math
import re
import secrets

WILD = 1
MAX_Q = 15
CH_VETO_LO = 0.12
CH_GATE_BASE = 0.45
CH_GATE_MAX = 0.70
OPEN_MIN_Q = 3                        # 起手：唔齋 3 個起
OPEN_MIN_JAI = 2                      # 起手：齋叫 2 個起

# ---------------- 數學層 ----------------

def _binom_tail(n: int, q: int, p: float) -> float:
    if q <= 0:
        return 1.0
    if q > n:
        return 0.0
    pmf = (1.0 - p) ** n
    acc = pmf
    for k in range(1, q):
        pmf *= (n - k + 1) / k * (p / (1.0 - p))
        acc += pmf
    return max(0.0, min(1.0, 1.0 - acc))


def hand_contribution(dice, face: int, jai: bool = False) -> int:
    """一手骰對某面嘅貢獻（蛇=0；圍骰=面+1；1 百搭除非齋）。"""
    if len(dice) == 5 and sorted(dice) in ([1, 2, 3, 4, 5], [2, 3, 4, 5, 6]):
        return 0                          # 蛇：0 顆
    if face == WILD:
        c = sum(1 for d in dice if d == 1)
    else:
        c = sum(1 for d in dice if d == face or (not jai and d == 1))
    if len(dice) == 5 and len(set(dice)) == 1 and dice[0] == face:
        c += 1                            # 圍骰：當 6 顆
    return c


def my_count_for(dice, face: int, jai: bool = False) -> int:
    return hand_contribution(dice, face, jai)


def p_bid_true(my_count: int, n_unknown: int, q: int, face: int,
               jai: bool = False) -> float:
    p_face = 1.0 / 6.0 if face == WILD else 2.0 / 6.0
    return _binom_tail(n_unknown, q - my_count, p_face)


# ---------------- 叫牌排序／解析 ----------------

def bid_rank(q: int, face: int, jai: bool = False) -> int:
    """全序：數量 → 面（2<…<6<1）→ 齋版大過非齋。"""
    return q * 100 + (6 if face == WILD else face - 1) * 10 + (1 if jai else 0)


def bid_text(q: int, face: int, jai: bool = False) -> str:
    return f"{q}個{face}{'齋' if jai else ''}"


_BID_RE = re.compile(r"^\s*(\d{1,2})\s*個\s*([1-6])\s*(齋|斋)?\s*!?[。.!！]?\s*$")


def parse_bid(text: str):
    """回傳 (q, face, jai)；唔合法回 None。叫「1齋」冇意義→回 (q,1,False)。"""
    m = _BID_RE.match(text)
    if not m:
        return None
    q, f = int(m.group(1)), int(m.group(2))
    jai = bool(m.group(3))
    if not 1 <= q <= MAX_Q:
        return None
    if f == WILD:
        jai = False
    return q, f, jai


def legal_raises(cur, n_total: int, jai_mode: bool = False):
    """cur=None 或 (q,face,jai)。jai_mode（已有人叫齋）→全部產齋叫。
    起手底線：唔齋 OPEN_MIN_Q 個起、齋 OPEN_MIN_JAI 個起；
    1 只做百搭——面 1 永遠唔產（用戶起手規則 2026-09-26）。"""
    r0 = bid_rank(*cur) if cur else -1
    out = []
    for q in range(1, min(MAX_Q, n_total + 2) + 1):
        for f in (2, 3, 4, 5, 6):
            for jai in ((True,) if jai_mode else (False, True)):
                if cur:
                    if bid_rank(q, f, jai) > r0:
                        out.append((q, f, jai))
                elif q >= (OPEN_MIN_JAI if jai else OPEN_MIN_Q):
                    out.append((q, f, jai))
    return out


# ---------------- 動作槽 ----------------
# slot 0=開 1=最穩 2=最平 3=中庸 4=大話 5=強叫（跟自己手）

def action_slots(dice, n_total: int, cur, gate_lo: float = CH_VETO_LO,
                 gate_hi: float = 0.75, jai_mode: bool = False):
    if cur and len(cur) == 2:
        cur = (cur[0], cur[1], False)      # 容忍舊式 2 元組
    my_n = len(dice)
    n_unk = n_total - my_n
    slots = [("challenge", None)] * 6
    mask = [0, 1, 1, 1, 1, 1]

    def p_of(b):
        return p_bid_true(my_count_for(dice, b[1], b[2]),
                          n_unk, b[0], b[1], b[2])

    if cur:
        p_cur = p_of(cur)
        mask[0] = 1
        if p_cur < gate_lo:
            return slots, [1, 0, 0, 0, 0, 0]
        if p_cur > gate_hi:
            mask[0] = 0
    cand = legal_raises(cur, n_total, jai_mode)
    if not cand:
        return slots, [0] * 6
    ps = [(b, p_of(b)) for b in cand]
    slots[1] = ("bid", max(ps, key=lambda x: x[1])[0])
    slots[2] = ("bid", cand[0])
    slots[3] = ("bid", min(ps, key=lambda x: abs(x[1] - 0.50))[0])
    slots[4] = ("bid", min(ps, key=lambda x: abs(x[1] - 0.28))[0])
    best_f = max(range(2, 7), key=lambda f: my_count_for(dice, f, jai_mode))
    strong = [b for b in cand
              if b[1] == best_f
              and b[0] <= my_count_for(dice, best_f, jai_mode) + 1]
    if strong:
        slots[5] = ("bid", strong[0])
    seen = set()
    for i in range(1, 6):
        b = slots[i][1]
        if b is None:
            mask[i] = 0
        elif mask[i]:
            if b in seen:
                mask[i] = 0
            else:
                seen.add(b)
    return slots, mask


# ---------------- 神經網絡（權重烘焙） ----------------
# NN-BEGIN（train_liar.py 會重建呢段）
W1 = ((0.28852, 0.20695, -0.35249, -0.31013, 0.52730, 0.18882, -0.37634, 0.04783, 0.05023, 0.56525, -0.05554, 0.07129, -0.03048),
 (-0.14137, 0.06008, -0.24563, -0.20077, -0.13272, 0.23239, -0.34894, -0.11289, 0.34124, 0.34817, 0.24195, 0.13996, 0.00310),
 (-0.27646, 0.22260, 0.01185, -0.38791, 0.04023, -0.14837, -0.05546, 0.43538, -0.10320, 0.25232, 0.31625, -0.06072, 0.05970),
 (-0.50972, 0.31041, -0.17287, -0.83685, -0.25683, 0.63302, -0.09721, 0.09159, 0.28022, 0.08520, -0.60597, -0.09644, 0.03841),
 (0.13318, -0.07705, -0.04462, -0.04370, 0.27681, -0.22146, 0.34649, -0.19923, 0.28957, -0.68717, -0.02182, -0.03989, 0.41557),
 (0.04070, -0.20712, 0.22631, -0.36726, -0.26718, 0.08799, 0.41345, 0.12899, -0.02092, -1.00203, -0.65561, -0.32686, -0.11068),
 (0.10388, 0.66456, 0.15964, 0.12923, 0.12530, -0.12033, -0.01075, -0.39568, 0.36777, -0.18733, 0.26782, -0.15181, 0.11864),
 (0.11964, 0.04268, -0.08861, 0.11488, 0.01033, -0.53318, -0.46052, 0.55530, -0.54993, 0.35344, 0.15237, 0.27780, 0.00145),
 (-0.12237, -0.03282, 0.46626, 0.36246, 0.15443, 0.28911, 0.09974, 0.65639, -0.56542, 0.13302, -0.20360, -0.42346, -0.60496),
 (0.20660, 0.08983, -0.28283, -0.05533, 0.29398, -0.38402, -0.44944, 0.12382, 0.19820, -0.18313, -0.46940, 0.08149, 0.16735),
 (-0.40624, 0.07291, -0.15777, -0.21924, -0.14343, -0.15066, -0.21464, -0.04714, 0.60193, 0.33070, -0.00870, 0.06453, -0.07639),
 (0.20826, 0.15379, 0.12723, 0.21938, -0.28642, 0.26160, -0.03944, -0.28911, 0.47939, -0.41479, 0.42360, 0.06249, 0.43882),
 (-0.02445, 0.19685, -0.00600, 0.38406, 0.12712, -0.02767, 0.16376, -0.04096, 0.09391, -0.17741, 0.33846, -0.24156, -0.32228),
 (0.21131, 0.51300, 0.04840, 0.43595, -0.01439, -0.16500, 0.45299, -0.42884, -0.48933, 0.18102, 0.29866, 0.17045, 0.29071),
 (-0.40507, -0.05341, -0.04263, 0.25029, 0.24011, -0.29382, 0.79432, -0.02952, -0.29904, 0.15353, 0.22487, 0.20183, 0.15307),
 (-0.04482, 0.40045, 0.10662, -0.07800, -0.44377, -0.02394, -0.00483, 0.25880, 0.01274, 0.41858, 0.03624, 0.35523, -0.21272),
 (-0.12495, 0.35171, -0.16112, -0.21075, 0.35131, 0.34973, -0.57956, 0.06200, 0.45724, 0.10299, 0.38135, -0.19396, 0.38758),
 (0.42114, 0.13570, 0.05263, 0.20575, -0.09272, 0.09226, -0.15127, 0.17430, -0.15283, 0.37925, -0.11638, 0.45316, -0.22072),
 (-0.22762, 0.21386, -0.27180, -0.41814, 0.11241, -0.01837, 0.28998, -0.07193, 0.28809, -0.26845, -0.36155, -0.29141, -0.18894),
 (0.38511, -0.11937, 0.64396, 0.52945, 0.11152, 0.41428, -0.50396, 0.38632, -0.47244, -0.40626, 0.41152, 0.18092, -0.32450),
 (-0.57013, -0.40875, 0.10815, 0.21723, -0.22126, -0.13888, -0.03017, -0.29986, 0.10775, -0.00768, 0.25248, 0.73719, -0.28920),
 (-0.29179, -0.80726, 0.08121, -0.21771, 0.29691, -0.16259, 0.01778, 0.23123, -0.14177, -0.10665, -0.06971, -0.02590, 0.07897),
 (0.56467, -0.53709, 0.34396, -0.06719, -0.45273, -0.07410, 0.10418, 0.14155, -0.31779, -0.05694, -0.06488, -0.31275, 0.45028),
 (-0.20355, -0.03115, -0.10177, 0.32984, 0.09348, -0.64821, 0.31019, 0.50634, -0.28493, -0.26579, -0.02792, 0.44767, -0.28729))
B1 = (0.01777, 0.13802, 0.09157, -0.10709, -0.03312, -0.19687, 0.02160, 0.07531, -0.04213, 0.07017, 0.03785, 0.08932, 0.09404, 0.00678, -0.08679, 0.09019, -0.00361, 0.11640, -0.10365, 0.10583, -0.01004, 0.06762, -0.15379, 0.03421)
W2 = ((0.18468, 0.19521, -0.19364, -0.54498, -0.25145, -0.75410, -0.21114, 0.67692, 0.23781, 0.07675, 0.31523, 0.05373, 0.17092, -0.05248, 0.00650, 0.22891, -0.28794, 0.37807, -0.47700, -0.06752, 0.43842, 0.03596, -0.43419, 0.53926),
 (-0.12574, 0.13609, 0.06404, 0.03283, 0.11341, 0.46230, -0.17272, -0.13620, 0.61217, -0.12093, 0.25990, 0.24864, 0.34259, 0.08490, 0.06739, 0.30282, 0.20679, -0.40580, 0.01260, -0.59071, -0.08158, -0.15247, 0.14414, 0.61375),
 (0.17972, -0.08958, -0.39952, 0.20637, -0.10099, -0.17837, 0.32083, 0.69272, -0.06895, 0.13529, -0.12557, -0.47291, -0.30675, 0.10669, -0.05898, -0.71821, -0.03602, -0.34484, 0.09262, -0.19417, -0.06288, -0.22663, 0.41272, -0.26731),
 (0.23299, -0.41276, -0.53750, 0.13438, -0.13437, 0.41292, -0.45504, 0.21903, -0.00671, 0.04507, -0.33469, 0.17522, -0.19215, 0.27565, 0.20656, 0.09525, -0.19988, 0.07370, -0.11659, -0.79005, -0.14282, -0.31885, -0.14996, -0.30666),
 (-0.17054, 0.00948, 0.06082, -0.12858, 0.25036, 0.23339, -0.26236, -0.08256, 0.07264, 0.23859, 0.09747, 0.17988, -0.37491, -0.30717, 0.05527, -0.15915, -0.35465, -0.04185, 0.20474, -0.14937, -0.28008, 0.26379, 0.47098, 0.34104),
 (-0.14910, 0.40613, 0.38186, -0.27869, 0.02719, -0.43961, 0.17834, -0.12284, -0.11595, 0.35270, -0.20627, 0.87182, 0.32830, 0.48460, -0.35137, 0.22413, 0.16984, -0.19514, -0.21870, 0.39920, -0.68492, 0.04823, -0.27073, -0.18277))
B2 = (0.18299, -0.09702, -0.09083, -0.09925, -0.05773, 0.16183)
# NN-END


def nn_policy(x):
    h = [math.tanh(sum(w * xi for w, xi in zip(wrow, x)) + b)
         for wrow, b in zip(W1, B1)]
    logits = [sum(w * hi for w, hi in zip(wrow, h)) + b
              for wrow, b in zip(W2, B2)]
    m = max(logits)
    es = [math.exp(z - m) for z in logits]
    s = sum(es)
    return [e / s for e in es]


def decide(dice, n_total: int, cur, opp=None, jai_mode: bool = False):
    """回傳 ('challenge', None) 或 ('bid', (q, face, jai))。"""
    my_n = len(dice)
    n_unk = n_total - my_n
    bluff = float((opp or {}).get("bluff", 0.0))
    u_bids = int((opp or {}).get("bids", 0))
    calls = float((opp or {}).get("calls", 0.0))
    folds = float((opp or {}).get("folds", 0.0))
    if cur and len(cur) == 2:
        cur = (cur[0], cur[1], False)
    if u_bids >= 2:
        gate_hi = min(0.30 + 0.45 * bluff, CH_GATE_MAX)
    else:
        gate_hi = 0.35
    u_p_ema = float((opp or {}).get("p_ema", 0.5))
    tight = not (u_bids >= 3 and u_p_ema < 0.45)
    if tight:
        gate_hi = 0.42

    def _p(b):
        return p_bid_true(my_count_for(dice, b[1], b[2]),
                          n_unk, b[0], b[1], b[2])

    slots, mask = action_slots(dice, n_total, cur, CH_VETO_LO, gate_hi,
                               jai_mode)
    if tight:
        for i in (2, 3, 4, 5):
            mask[i] = 0
        if not any(mask[i] for i in range(1, 6)):
            cand = legal_raises(cur, n_total, jai_mode)
            if cand:
                best = max(cand, key=lambda b: _p(b))
                slots[1] = ("bid", best)
                mask = [mask[0], 1, 0, 0, 0, 0]
    floor = 0.42
    if not tight:
        floor = 0.30
    if floor > 0.30:
        for i in range(1, 6):
            if mask[i] and slots[i][1] is not None and _p(slots[i][1]) < floor:
                mask[i] = 0
        if not any(mask[i] for i in range(1, 6)):
            cand = legal_raises(cur, n_total, jai_mode)
            if cand:
                best = max(cand, key=lambda b: _p(b))
                slots[1] = ("bid", best)
                mask = [mask[0], 1, 0, 0, 0, 0]
    if sum(mask) == 0:
        if cur:
            return "challenge", None
        return "bid", legal_raises(None, n_total, jai_mode)[0]
    if not W1:
        if cur:
            p = p_bid_true(my_count_for(dice, cur[1], cur[2]),
                           n_unk, cur[0], cur[1], cur[2])
            return (("challenge", None) if p < 0.40
                    else ("bid", slots[1][1]))
        return "bid", slots[1][1]
    cnt = [sum(1 for d in dice if d == f) / 5.0 for f in (1, 2, 3, 4, 5, 6)]
    p_cur = (_p(cur) if cur else 0.0)
    x = ([p_cur, (cur[0] / 10.0) if cur else 0.0,
          1.0 if (cur and cur[1] == WILD) else 0.0,
          (cur[1] / 6.0) if cur else 0.0]
         + cnt + [n_total / 10.0, my_n / 5.0, 0.0 if cur else 1.0])
    probs = nn_policy(x)
    best, bi = -1.0, -1
    for i in range(6):
        if mask[i] and probs[i] > best:
            best, bi = probs[i], i
    return slots[bi]


# ---------------- 遊戲狀態機（1v1，計分制） ----------------

def roll(n: int):
    return [secrets.randbelow(6) + 1 for _ in range(n)]


def new_game(n_start: int = 5, starter: str = "you"):
    st = {"bot": roll(n_start), "you_n": n_start, "bot_n": n_start,
          "bid": None, "bidder": None, "turn": starter,
          "over": False, "await_dice": False, "you_wins": 0, "bot_wins": 0,
          "round": 1, "u_bids": 0, "u_false": 0.0, "u_calls": 0,
          "u_folds": 0, "u_p_ema": 0.5, "jai": False, "stake": 1}
    return st


def bot_speak_bid(st) -> str:
    total = st["you_n"] + st["bot_n"]
    opp = {"bluff": st.get("u_false", 0.0), "calls": st.get("u_calls", 0),
           "folds": st.get("u_folds", 0), "bids": st.get("u_bids", 0),
           "p_ema": st.get("u_p_ema", 0.5)}
    act, bid = decide(st["bot"], total, st["bid"], opp, st.get("jai", False))
    if act == "challenge":
        st["stake"] = st.get("stake", 1)
        st["await_dice"] = True
        return ("🕵️ 我開你！打你手骰過嚟（例：我 2 3 5 5 6）"
                "——靠你自覺報真數 😏")
    st["bid"], st["bidder"], st["turn"] = bid, "bot", "you"
    tag = "（齋）" if st.get("jai") else ""
    return f"🎯 我叫：{bid_text(*bid)}{tag}"


def user_bid(st, q: int, f: int, jai: bool = False):
    if st["over"] or st["await_dice"]:
        return None
    if st["turn"] != "you":
        return "而家未到你叫——我啱啱先叫咗，你開得或者加。"
    if f == WILD:
        return "「1」只做百搭，唔叫得 1 ⚠️ 叫 2–6 啦（例：3個4）。"
    if st["bid"] is None and q < (OPEN_MIN_JAI if jai else OPEN_MIN_Q):
        return (f"起手規則：唔齋 {OPEN_MIN_Q} 個起、"
                f"齋叫 {OPEN_MIN_JAI} 個起 ⚠️（例：3個4／2個5齋）")
    if f == WILD and jai:
        jai = False
    if st.get("jai"):
        jai = True                            # 齋一開，round 全齋
    n_total = st["you_n"] + st["bot_n"]
    if st["bid"] and bid_rank(q, f, jai) <= bid_rank(*st["bid"]):
        return (f"要叫大過「{bid_text(*st['bid'])}」先得"
                f"（1 百搭；齋版大過非齋；同數量入面 1 最大）。")
    st["bid"], st["bidder"], st["turn"] = (q, f, jai), "you", "bot"
    if jai and not st.get("jai"):
        st["jai"] = True
        st["u_folds"] = st.get("u_folds", 0) + 1
        _p = p_bid_true(my_count_for(st["bot"], f, True),
                        st["you_n"] + st["bot_n"] - len(st["bot"]), q, f, True)
        st["u_p_ema"] = 0.7 * st.get("u_p_ema", 0.5) + 0.3 * _p
        return bot_speak_bid(st) + "\n☠️ 齋叫生效——呢個 round 1 唔再百搭。"
    st["u_folds"] = st.get("u_folds", 0) + 1
    _p = p_bid_true(my_count_for(st["bot"], f, jai),
                    st["you_n"] + st["bot_n"] - len(st["bot"]), q, f, jai)
    st["u_p_ema"] = 0.7 * st.get("u_p_ema", 0.5) + 0.3 * _p
    return bot_speak_bid(st)


def user_challenge(st, stake: int = 1):
    """開（stake=1）／劈（stake=2）。"""
    if st["over"] or st["await_dice"]:
        return None
    if not st["bid"]:
        return "都未有人叫，開乜？你先叫啦（例：3個4）。"
    if st["turn"] != "you":
        return "要到我先可以開。而家我等緊你叫牌。"
    st["stake"] = stake
    extra = ""
    if stake >= 2:
        q, f, jai = st["bid"]
        if hand_contribution(st["bot"], f, jai) >= q:
            st["stake"] = 4
            extra = "\n💪 反劈！注碼加到 4 分。"
    st["u_calls"] = st.get("u_calls", 0) + 1
    st["await_dice"] = True
    return (f"🗡 劈！輸贏 {st['stake']} 分——"
            "打你手骰過嚟（例：我 2 3 5 5 6）——靠你自覺報真數 😏" + extra)


_DICE_RE = re.compile(r"^\s*我?\s*((?:[1-6]\s+){4}[1-6])\s*$")


def user_dice_declare(st, text: str):
    """用戶報骰（攤牌）。回傳 (回覆文字, 完局?)——計分制下完局永遠 False。"""
    m = _DICE_RE.match(text)
    if not m or not st["await_dice"]:
        return None, False
    ud = [int(c) for c in m.group(1).split()]
    bd = st["bot"]
    q, f, jai = st["bid"]
    cnt = (hand_contribution(ud, f, jai) + hand_contribution(bd, f, jai))
    ok = cnt >= q
    bidder = st["bidder"]
    if ok:
        loser = "bot" if bidder == "you" else "you"
    else:
        loser = "you" if bidder == "you" else "bot"
    stake = st.get("stake", 1)
    if loser == "you":
        st["bot_wins"] += stake
    else:
        st["you_wins"] += stake
    if bidder == "you":
        st["u_bids"] += 1
        st["u_false"] = 0.7 * st.get("u_false", 0.0) + 0.3 * (0.0 if ok else 1.0)
    verdict = ("✅ 夠數！" if ok else "❌ 唔夠！")
    who = "你" if loser == "you" else "我"
    detail = (f"{'淨計' if jai or f == WILD else '加埋'}「{f}」共 {cnt} 粒"
              f"（叫 {bid_text(q, f, jai)}{'，注 ' + str(stake) + ' 分' if stake > 1 else ''}）")
    lines = [f"🎬 攤牌！你：{' '.join(map(str, ud))}　我：{' '.join(map(str, bd))}",
             f"{detail} → {verdict}{who}輸。戰績 你{st['you_wins']}：{st['bot_wins']}我"]
    st["await_dice"] = False
    st["bid"], st["bidder"] = None, None
    st["jai"] = False
    st["stake"] = 1
    st["bot"] = roll(st["bot_n"])
    st["round"] += 1
    st["turn"] = loser
    lines.append(f"—— 第 {st['round']} 回合（分 你{st['you_wins']}：{st['bot_wins']}我）——")
    if loser == "bot":
        lines.append(bot_speak_bid(st))
    else:
        lines.append("你先叫（起手 3個起、齋 2個起；例：3個4）。")
    return "\n".join(lines), False
