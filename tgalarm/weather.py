"""weather：天氣域（HKO RSS＋九日／GPS 定位佐敦）。"""
from __future__ import annotations

from . import engine

# ---- 天氣：天文台官方 RSS（用戶令 2026-10-06 改用 data.gov.hk 資源）----
_HKO_CURRENT_URL = "https://rss.weather.gov.hk/rss/CurrentWeather_uc.xml"  # 資源 61b364e0

_HKO_FND_URL = "https://rss.weather.gov.hk/rss/SeveralDaysWeatherForecast_uc.xml"

_HKO_UA = {"User-Agent": "tgalarm/1.0"}

_HKO_KEYS = ("天氣概況", "本港地區天氣預測", "展望")



def _hko_fetch(url: str):
    import urllib.request
    with urllib.request.urlopen(
            urllib.request.Request(url, headers=engine._HKO_UA), timeout=30) as r:
        return r.read().decode("utf-8", "replace")



def _hko_flat(url: str):
    """RSS → (title, 內文flat)。flat＝剝 HTML tag＋去晒空白嘅一條字串。"""
    import html as _html
    import xml.etree.ElementTree as ET
    root = ET.fromstring(engine._hko_fetch(url))
    item = root.find("./channel/item")
    title = (item.findtext("title") or "").strip()
    desc = item.findtext("description") or ""
    text = engine.re.sub(r"<[^>]+>", " ", _html.unescape(desc))
    return title, engine.re.sub(r"\s+", "", text)



def _hko_section(flat: str, keys, stop_pat: str) -> list:
    """概況／預測／展望段落（有先有）：回 [(key, 文字)]。"""
    out = []
    for key in keys:
        m = engine.re.search(engine.re.escape(key) + r"[：:]?(.{8,400}?)"
                      r"(?=" + stop_pat + r"|$)", flat)
        if m:
            out.append((key, m.group(1)))
    return out



# 天文台各區監測站約數座標（揀最近站用，唔做導航級用途）
_HKO_STATIONS = {
    "天文台": (22.302, 114.172), "京士柏": (22.318, 114.179),
    "深水埗": (22.336, 114.155), "九龍城": (22.329, 114.188),
    "黃大仙": (22.336, 114.196), "觀塘": (22.310, 114.226),
    "啟德跑道公園": (22.304, 114.211), "將軍澳": (22.318, 114.264),
    "西貢": (22.382, 114.270), "沙田": (22.377, 114.188),
    "大埔": (22.448, 114.165), "大美督": (22.470, 114.221),
    "打鼓嶺": (22.527, 114.147), "流浮山": (22.468, 113.996),
    "元朗公園": (22.445, 114.022), "石崗": (22.433, 114.078),
    "荃灣可觀": (22.374, 114.113), "荃灣城門谷": (22.369, 114.148),
    "屯門": (22.410, 113.977), "青衣": (22.359, 114.106),
    "長洲": (22.203, 114.027), "赤鱲角": (22.301, 113.915),
    "香港公園": (22.277, 114.160), "跑馬地": (22.266, 114.185),
    "筲箕灣": (22.279, 114.229), "赤柱": (22.220, 114.213),
    "黃竹坑": (22.245, 114.160)}

_HOME = "佐敦"                     # 屋企（用戶 2026-10-06：我屋企係佐敦）

_HOME_NEAR = ("京士柏", "天文台", "深水埗", "九龍城")

_GPS_CACHE = [0.0, None]           # [時間戳, (lat, lng)｜None]



def _gps_fix():
    """而家位置：termux-location → dumpsys last fix。都唔得回 None
    （cache 10 分鐘，避免次次 query 等十幾秒）。"""
    import time
    if time.time() - engine._GPS_CACHE[0] < 600:
        return engine._GPS_CACHE[1]
    import subprocess
    loc = None
    try:
        p = subprocess.run(
            ["termux-location", "-p", "network", "-r", "once"],
            capture_output=True, text=True, timeout=14)
        d = engine.json.loads(p.stdout or "{}")
        if d.get("latitude") is not None:
            loc = (float(d["latitude"]), float(d["longitude"]))
    except Exception:
        pass
    if loc is None:
        ok, out = engine._shell_priv_exec("dumpsys location")
        mm = engine.re.search(r"last location=Location\[[a-z]+\s+([\-0-9.]+),([\-0-9.]+)",
                       out or "")
        if ok and mm:
            loc = (float(mm.group(1)), float(mm.group(2)))
    engine._GPS_CACHE[0], engine._GPS_CACHE[1] = time.time(), loc
    return loc



def _nearest_station(lat: float, lng: float) -> str:
    best, bd = "天文台", 9e9
    for n, (a, b) in engine._HKO_STATIONS.items():
        d = (lat - a) ** 2 + (lng - b) ** 2
        if d < bd:
            best, bd = n, d
    return best



def _hko_district_line(seg: str) -> str | None:
    """地區行：GPS 得→你嗰邊（最近站）；唔得→屋企（佐敦附近）。"""
    try:
        loc = engine._gps_fix()
    except Exception:
        loc = None
    if loc:
        st = engine._nearest_station(*loc)
        m = engine.re.search(engine.re.escape(st) + r"(\d{1,2})度", seg)
        if m:
            return f"📍 你嗰邊（{st}）{int(m.group(1))}°C"
    for st in engine._HOME_NEAR:
        m = engine.re.search(engine.re.escape(st) + r"(\d{1,2})度", seg)
        if m:
            return f"🏠 {engine._HOME}附近（{st}）{int(m.group(1))}°C"
    return None



def _hko_current() -> list:
    """本港地區天氣報告 → 行陣（而家／地區行／概況展望）。"""
    title, flat = engine._hko_flat(engine._HKO_CURRENT_URL)
    tm = engine.re.search(r"於(\d{4})年(\d{1,2})月(\d{1,2})日(\d{1,2})時(\d{1,2})分", title)
    when = f"{int(tm.group(4)):02d}:{int(tm.group(5)):02d}" if tm else "??:??"
    lines = []
    temp = engine.re.search(r"錄得[：:]?氣溫[：:]?(\d{1,2})度", flat) or \
        engine.re.search(r"氣溫[：:]?(\d{1,2})度", flat)
    hum = engine.re.search(r"相對濕度[：:]?百分之(\d{1,3})", flat)
    if temp:
        lines.append(f"天文台 {when} 報：{int(temp.group(1))}°C"
                     + (f"、濕度 {int(hum.group(1))}%" if hum else ""))
    seg = flat.split("本港其他地區的氣溫", 1)[-1]
    dline = engine._hko_district_line(seg)
    if dline:
        lines.append(dline)
    lines += [f"{k}：{v}" for k, v in
              engine._hko_section(flat, engine._HKO_KEYS,
                           "天氣概況|本港地區天氣預測|展望|本港其他地區的氣溫")]
    return lines



def _hko_fnd() -> list:
    """九天天氣預報 → 今日／聽日兩行＋帶遮提示。
    注意：HKO RSS 月份日期係中文數字（「十月六日」）。"""
    _title, flat = engine._hko_flat(engine._HKO_FND_URL)
    gen = engine._hko_section(flat, ("天氣概況",),
                       r"[一二三四五六七八九十]{1,3}月[一二三四五六七八九十初]{1,3}日")
    pat = (r"([一二三四五六七八九十]{1,3})月([一二三四五六七八九十初]{1,3})日"
           r"\(星期([一二三四五六日])\)"
           r".*?天氣[：:]?(.*?)氣溫[：:]?(\d{1,2})至(\d{1,2})度")
    days = []
    for m in engine.re.finditer(pat, flat):
        mo, day = engine._cn_num(m.group(1)), engine._cn_num(m.group(2))
        if mo and day:
            mo, day = int(mo), int(day)
            wx = m.group(4).rstrip("。")
            days.append({"label": f"{mo}月{day}日 週{m.group(3)}",
                         "wx": wx, "lo": int(m.group(5)),
                         "hi": int(m.group(6))})
    lines = [f"{k}：{v}" for k, v in gen]
    for i, d in enumerate(days[:2]):
        tag = "今日" if i == 0 else "聽日"
        lines.append(f"{tag}（{d['label']}）：{d['wx']}，"
                     f"{d['lo']}–{d['hi']}°C")
    rainy = [d["label"] for d in days[:2] if "雨" in d["wx"]]
    if rainy:
        lines.append(f"☂ {'、'.join(rainy)} 有雨——記得帶遮！")
    return lines



def _weather_report() -> tuple:
    """天文台官方 RSS（本港地區天氣報告＋九日預報）。回傳 (ok, 文字)。
    兩源一死一生都照出活的嗰邊；齊死先算失敗。"""
    errs = []
    cur = fnd = None
    try:
        cur = engine._hko_current()
    except Exception as e:
        errs.append(f"報告：{str(e)[:80]}")
    try:
        fnd = engine._hko_fnd()
    except Exception as e:
        errs.append(f"預報：{str(e)[:80]}")
    if cur is None and fnd is None:
        return False, "；".join(errs) or "天文台 RSS 讀唔到"
    lines = list(cur or [])
    if fnd:
        lines += fnd
    if cur is None:
        lines.append(f"⚠️ 而家讀數攞唔到（{errs[0][:60]}）")
    return True, "\n".join(lines)
