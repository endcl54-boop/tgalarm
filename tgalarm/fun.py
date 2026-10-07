"""fun：趣味域（骰仔／密碼／打氣／匯率／時間／AI Mode／大話骰）。"""
from __future__ import annotations

from . import engine

        # TG 摳制確認一開始就在度（keyboard）：彈窗過時/開唔到免再叫，log 已錄。


def _serpapi_key() -> str:
    """SerpAPI key：環境變數或設定檔（改咗即時生效，唔使重啟）。"""
    return (engine.os.environ.get("SERPAPI_KEY", "")
            or engine._read_config_file().get("SERPAPI_KEY", "")).strip()



def _ai_mode_answer(question: str, timeout: int = 90) -> tuple:
    """問 Google AI Mode（經 SerpAPI），回傳 (ok, 回覆文字)。
    零依賴（urllib）。end-point：search.json?engine=google_ai_mode。"""
    import urllib.parse
    import urllib.request
    key = engine._serpapi_key()
    if not key:
        return False, ("❌ 未設定 SERPAPI_KEY。\n"
                       "搞法：喺 ~/.tgalarm/config 加一行 SERPAPI_KEY=你嘅key"
                       "（唔使重啟）")
    params = urllib.parse.urlencode(
        {"engine": "google_ai_mode", "q": question, "api_key": key})
    url = f"https://serpapi.com/search.json?{params}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            data = engine.json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return False, f"❌ 搜尋失敗：{e}"
    err = data.get("error")
    if isinstance(err, str) and err:
        return False, f"❌ SerpAPI：{err}"
    body = "\n\n".join(
        (b.get("snippet") or "").strip()
        for b in (data.get("text_blocks") or [])
        if (b.get("snippet") or "").strip())
    if not body:
        return False, "❓ Google AI Mode 對呢條問題冇答案。"
    refs = data.get("references") or []
    ref_lines = []
    for rf in refs[:5]:
        title = (rf.get("title") or rf.get("source") or "").strip()
        link = (rf.get("link") or "").strip()
        if title and link:
            ref_lines.append(f"• {title}\n  {link}")
    if ref_lines:
        body += "\n\n📚 來源：\n" + "\n".join(ref_lines)
    if len(body) > 4000:
        body = body[:3990] + "\n…（太長，截咗）"
    return True, body

_LIAR_DICE_RE = engine.re.compile(r"^\s*我?\s*((?:[1-6]\s+){4}[1-6])\s*$")



def _liar_handle(chat_id: int, t: str):
    """大話骰指令分發。回傳回覆文字；None=唔關佢事（跌返其他指令）。"""
    if engine._liar is None:
        return None
    st = engine._LIAR_GAMES.get(chat_id)
    if t == "戰績":
        car = {}
        if engine._liar.CAREER_PATH:
            car = engine._load_json(engine._liar.CAREER_PATH, {"you": 0, "bot": 0}) or {}
        out = f"📜 生涯戰績：你 {car.get('you', 0)}：{car.get('bot', 0)} 我"
        if st:
            out += f"\n今場：你 {st['you_wins']}：{st['bot_wins']} 我"
        return out
    if t.startswith(("開 ", "去 ")):
        return None                     # 開網頁／導航——唔關大話骰事
    if t in ("大話", "大話骰", "玩大話", "開枱"):
        if st and not st["over"]:
            return "開咗枱喇——繼續！開=攤牌，大話結束=收工。"
        starter = engine.random.choice(("you", "bot"))
        engine._LIAR_GAMES[chat_id] = engine._liar.new_game(starter=starter)
        g = engine._LIAR_GAMES[chat_id]
        head = ("🎲 開枱！我搖好咗 5 粒（你知我唔知）。你搖啦——")
        if starter == "bot":
            return head + "\n" + engine._liar.bot_speak_bid(g)
        return head + "你先叫（起手 3個起、齋 2個起；叫1即齋）。例：3個4／2個1齋"
    if st is None:
        if engine._liar.parse_bid(t) or t in ("開", "開！", "開!", "劈", "劈！",
                                       "大話結束", "收工", "唔玩"):
            return "未開枱——打「大話」開枱先（之後叫 3個4／2個1齋 咁款）。"
        return None
    if t in ("大話結束", "收工", "唔玩"):
        engine._LIAR_GAMES.pop(chat_id, None)
        car = {}
        if engine._liar.CAREER_PATH:
            car = engine._load_json(engine._liar.CAREER_PATH, {"you": 0, "bot": 0}) or {}
        return (f"收工。今場戰績 你 {st['you_wins']}：{st['bot_wins']} 我 🤝"
                f"\n📜 生涯戰績：你 {car.get('you', 0)}：{car.get('bot', 0)} 我")
    if st["over"]:
        engine._LIAR_GAMES.pop(chat_id, None)
        return None
    if st["await_dice"]:
        if engine._LIAR_DICE_RE.match(t):
            rep, _done = engine._liar.user_dice_declare(st, t)
            return rep
        return ("等緊你報骰（例：我 2 3 5 5 6）。"
                "唔想玩就「大話結束」。")
    bid = engine._liar.parse_bid(t)
    if bid:
        return engine._liar.user_bid(st, *bid)
    if t in ("開", "開！", "開!", "大話!", "大話！"):
        return engine._liar.user_challenge(st)
    if t in ("劈", "劈！"):
        return engine._liar.user_challenge(st, stake=2)
    if st["turn"] == "you" and st["bid"] and not engine.re.match(
            r"^天氣|排程|幫助|help|時間 |匯率|問 |ai |", t):
        return ("睇唔明——叫牌（例：3個4）、"
                "開！（攤牌）、或大話結束。")
    return None



# ---- 隨問隨答小工具：匯率／世界時間／隨機／密碼／打氣 ----
_FX_URL = "https://open.er-api.com/v6/latest/{base}"

_FX_ALIAS = {
    "USD": ("美金", "美元", "美紙", "us dollar"), "HKD": ("港紙", "港幣", "港銀"),
    "JPY": ("日圓", "日元"), "CNY": ("人民幣", "人仔", "人民幣"), "EUR": ("歐羅", "欧元"),
    "GBP": ("英鎊", "英磅"), "TWD": ("台幣", "台币", "新台幣"), "KRW": ("韓圜", "韓元"),
    "SGD": ("新加坡幣", "坡紙"), "AUD": ("澳元", "澳洲紙"), "CAD": ("加幣", "加拿大紙"),
    "THB": ("泰銖"), "VND": ("越南盾"), "PHP": ("披索"), "MYR": ("馬幣"),
}



def _fx_code(tok: str) -> str:
    t = tok.strip().lower()
    if t in ("hkd", "港紙", "港幣", "港銀"):
        return "HKD"
    for code, names in engine._FX_ALIAS.items():
        if t in (n.lower() for n in names):
            return code
    return t.upper() if engine.re.fullmatch(r"[a-z]{3}", t) else ""



def _fx_parse(arg: str):
    m = engine.re.match(r"^(\d+(?:\.\d+)?)\s*(.+)$", arg.strip())
    if not m:
        return None
    return float(m.group(1)), engine._fx_code(m.group(2))



def _fx_reply(arg: str) -> str:
    """匯率：免 key API（open.er-api.com）。arg 空＝主要貨幣表；否則 金額 幣種。"""
    import urllib.request
    try:
        with urllib.request.urlopen(
                engine._FX_URL.format(base="USD"), timeout=20) as r:
            rates = engine.json.loads(r.read().decode())["rates"]
        hkd = rates["HKD"]
    except Exception as e:
        return f"❌ 匯率攞唔到：{e}"
    if not arg.strip():
        rows = [f"1 {c} = {hkd / rates[c]:.4f} 港紙"
                for c in ("USD", "EUR", "GBP", "JPY", "CNY", "TWD", "KRW", "SGD")
                if c in rates]
        return "💱 今日匯率（兌港紙）：\n" + "\n".join(rows)
    got = engine._fx_parse(arg)
    if not got or not got[1]:
        return "❓ 用法：匯率 100 美金（或 usd／jpy／歐羅…）"
    amt, code = got
    if code not in rates:
        return f"❓ 唔識「{code}」呢個幣種"
    if code == "HKD":
        return f"💱 {amt:g} 港紙 = {amt / hkd:.4f} 美金（參考）"
    v_hkd = amt / rates[code] * hkd
    return (f"💱 {amt:g} {engine._FX_ALIAS.get(code, (code,))[0]} = "
            f"{v_hkd:,.2f} 港紙（1 {code} = {hkd / rates[code]:.4f} HKD）")


_TIME_ZONES = {"東京": "Asia/Tokyo", "首爾": "Asia/Seoul", "上海": "Asia/Shanghai",
               "北京": "Asia/Shanghai", "台北": "Asia/Taipei", "新加坡": "Asia/Singapore",
               "曼谷": "Asia/Bangkok", "悉尼": "Australia/Sydney", "雪梨": "Australia/Sydney",
               "紐約": "America/New_York", "洛杉磯": "America/Los_Angeles",
               "溫哥華": "America/Vancouver", "倫敦": "Europe/London",
               "巴黎": "Europe/Paris", "法蘭克福": "Europe/Berlin",
               "蘇黎世": "Europe/Zurich", "杜拜": "Asia/Dubai"}



def _time_reply(arg: str) -> str:
    from zoneinfo import ZoneInfo
    z = engine._TIME_ZONES.get(arg.strip())
    if not z:
        return ("❓ 用法：時間 東京／紐約／倫敦／巴黎／悉尼／首爾／新加坡／"
                "曼谷／杜拜／溫哥華…")
    try:
        n = engine.dt.datetime.now(ZoneInfo(z))
    except Exception:
        return "⚠️ 呢部機未裝時區資料（tzdata）——叫 bot 幫手整"
    return f"🌍 {arg.strip()}而家 {n:%H:%M}（{n:%m月%d日 %a}）"



_PEP = [
    "今日唔知點，聽日繼續嚟過。你已經好叻。",
    "慢慢嚟，比較快。搞掂一步係一步。",
    "你冇停過手，已經贏咗尐日日躺平嘅人。",
    "難搞嘅嘢留返個精神好嘅自己。而家飲啖水先。",
    "做到七成已經好犀利——剩嗰三成聽日話咁快。",
    "你而家嘅努力，聽日嘅你會多謝你。",
    "係咁㗎啦，好開心咁樣啦！行落去就得。",
    "唔使同人比，同尐日嘅你比已經進咗步。",
    "放輕鬆，你行到呢度已經唔容易。",
    "搞定佢，然後獎勵自己好嘢食。",
    "世界唔會記得你有幾攰，但你個身體會——早啲抖。",
    "今日係你餘生第一日，隨便你點玩。",
    "問題大過你？拆開佢，逐件整。",
    "你已經捱過好多個「搞唔掂」嘅日子，今次都得。",
    "加油，頂住！你係全場最得嗰個。",
]



def _pick_reply(rest: str) -> str:
    opts = [o.strip() for o in engine.re.split(r"[/、,，]|定|定係", rest) if o.strip()]
    if len(opts) < 2:
        return "❓ 用法：揀 飲茶/壽司/拉麵（用／隔開兩個以上）"
    import secrets
    return f"🎯 揀咗：{secrets.choice(opts)}"



def _dice_reply(rest: str) -> str:
    import secrets
    m = engine.re.fullmatch(r"\s*(\d{1,3})?", rest.strip())
    faces = int(m.group(1)) if (m and m.group(1)) else 6
    if not 2 <= faces <= 1000:
        return "❓ 骰面要 2–1000"
    return f"🎲 {secrets.randbelow(faces) + 1}（d{faces}）"



def _password_reply(rest: str) -> str:
    import secrets
    import string
    m = engine.re.fullmatch(r"\s*(\d{1,3})?", rest.strip())
    n = int(m.group(1)) if (m and m.group(1)) else 16
    if not 8 <= n <= 64:
        return "❓ 長度要 8–64"
    pools = [string.ascii_lowercase, string.ascii_uppercase,
             string.digits, "!@#$%^&*-_=+"]
    allc = "".join(pools)
    chars = [secrets.choice(p) for p in pools]
    chars += [secrets.choice(allc) for _ in range(n - len(chars))]
    secrets.SystemRandom().shuffle(chars)
    return f"🔐 `{''.join(chars)}`\n（已確保大小寫＋數字＋符號；-copy 去用啦）"
