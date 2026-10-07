"""player：播歌域（歌單倉／live／自動播／音量／停播候選鏈）。"""
from __future__ import annotations

from . import engine

# YouTube 類 app 候選（2026-10-06 個案：部機冇官方 YT，用緊 Morphe fork）：
# 逐個試 am start，邊個裝咗用邊個；_YT_PKG 留首選名做相容
_YT_CANDIDATES = ("com.google.android.youtube",
                  "app.morphe.android.youtube",
                  "app.morphe.android.apps.youtube.music")

_YT_PKG = _YT_CANDIDATES[0]



def _is_yt_url(s: str) -> bool:
    return bool(engine.re.match(r"https?://(www\.|m\.|music\.)?(youtube\.com|youtu\.be)/", s, engine.re.IGNORECASE))




def _playlists() -> dict:
    return engine._load_json(engine.PLAYLISTS_PATH, {"default": "", "lists": {}})



def _resolve_playlist(ref: str) -> tuple:
    """ref=「」→預設；名→連結；連結→直接用。回傳 (url, 顯示名) 或 (None, 錯誤訊息)。"""
    pl = engine._playlists()
    if not ref:
        name = pl.get("default", "")
        if not name:
            return None, "未設預設歌單。先 send：歌單 名稱 YouTube連結"
        ref = name
    if ref in pl.get("lists", {}):
        return pl["lists"][ref], ref
    if engine._is_yt_url(ref):
        return ref, ""
    return None, f"搵唔到歌單「{ref}」。send「歌單」睇現有歌單"



_UA = ("Mozilla/5.0 (Linux; Android 10) "
       "AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36")



def _fetch(url: str) -> str:
    """下載頁面文字（上限 2MB）。4 秒硬頂——畀面反應夠快，塞網即走後備。"""
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": engine._UA})
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
        xml = engine._fetch(f"https://www.youtube.com/feeds/videos.xml?playlist_id={list_id}")
        return engine._dedupe(engine.re.findall(r"<yt:videoId>([\w-]{11})", xml))
    except Exception as e:
        engine.log.warning("RSS 攞歌單失敗：%s", e)
        return []



def _playlist_videos_html(list_id: str) -> list:
    """後備：爬 playlist 頁面，兩套正則。"""
    try:
        html = engine._fetch(f"https://www.youtube.com/playlist?list={list_id}")
        ids = engine.re.findall(r'"videoId"\s*:\s*"([\w-]{11})"', html)
        if not ids:
            ids = engine.re.findall(r"watch\?v=([\w-]{11})", html)
        return engine._dedupe(ids)
    except Exception as e:
        engine.log.warning("爬歌單頁失敗：%s", e)
        return []

_PL_CACHE_TTL = 6 * 3600        # 6 小時內重播 = 零網絡直達 am start



_PL_DISK = engine.os.path.expanduser("~/.tgalarm/playlist_ids.json")



def _playlist_videos(list_id: str) -> list:
    """由 YouTube playlist 抽出全部 videoId（去重、保持順序；唔使 API key）。
    優先 6 小時 session 快取（上次成功嘅就算過期都攞嚟做後備），
    miss 先行官方 RSS，再失敗爬頁面。最快響應：第二次起唔出網。
    2026-10-06 加持久快取（playlist_ids.json）：Google 對非瀏覽器 client
    派殼頁（innertube/piped 全堵，真機實證），server 端抓取唔再穩陣——
    種過一次（沙盒代抓）就永久有開場 id，fetch 得到就自動 refresh。"""
    hit = engine._PL_CACHE.get(list_id)
    if hit and engine.dt.datetime.now().timestamp() - hit[0] < engine._PL_CACHE_TTL:
        return hit[1]
    if not hit and engine.os.path.exists(engine._PL_DISK):
        d = engine._load_json(engine._PL_DISK, {})
        if d.get(list_id):
            engine._PL_CACHE[list_id] = (0.0, list(d[list_id]))   # ts=0＝非新鮮，淨做後備
            hit = engine._PL_CACHE[list_id]
    vids = engine._playlist_videos_rss(list_id) or engine._playlist_videos_html(list_id)
    if vids:
        engine._PL_CACHE[list_id] = (engine.dt.datetime.now().timestamp(), vids)
        try:
            engine._save_json(engine._PL_DISK,
                       {k: v for k, (_t, v) in engine._PL_CACHE.items() if v})
        except OSError:
            pass
        return vids
    return hit[1] if hit else []   # 網絡死檔：拎到舊快取總好過開返歌單頁



def _autoplay_url(url: str, shuffle: bool = False) -> tuple:
    """回傳 (用嚟開嘅 url, 係咪自動播格式)。
    YouTube app 開 playlist 頁只會停喺頁面；要 watch?v=<片>&list=<單> 先會自動播。
    shuffle=True 隨機抽一條做開場（之後跟歌單順序播）。"""
    m = engine.re.search(r"[?&]list=([\w-]+)", url)
    if m and "watch?v=" not in url:
        vids = engine._playlist_videos(m.group(1))
        if vids:
            vid = engine.random.choice(vids) if shuffle else vids[0]
            return f"https://www.youtube.com/watch?v={vid}&list={m.group(1)}", True
        return url, False
    # watch／youtu.be／live（直播電台，2026-10-06 用戶轉用）：app 直開即播
    return url, ("watch?v=" in url or "youtu.be/" in url
                 or bool(engine.re.search(r"/live/([\w-]{11})", url)))



def _media_vol_max() -> int | None:
    """部機 STREAM_MUSIC（3）最大格數；vivo 實測 150（唔係一般 15）。"""
    ok, out = engine._shell_priv_exec("cmd audio get-max-volume 3")
    m = engine.re.search(r"->\s*(\d+)", out or "")
    return int(m.group(1)) if ok and m else None



def _set_media_volume(pct: int) -> tuple:
    """開播前設媒體音量。pct=最大聲嘅百分比（0–100，用戶 2026-10-05 揀定）。
    通道：cmd audio set-volume（自證：設完讀返核對）。回 (成功, 詳情)；
    失敗唔攔播放（響鬧大過天）。"""
    mx = engine._media_vol_max()
    if not mx:
        return False, "攞唔到最大音量（特權通道死咗？）"
    idx = max(0, min(mx, round(mx * pct / 100)))
    ok1, _o = engine._shell_priv_exec(f"cmd audio set-volume 3 {idx}")
    ok2, out2 = engine._shell_priv_exec("cmd audio get-stream-volume 3")
    m = engine.re.search(r"->\s*(\d+)", out2 or "")
    cur = int(m.group(1)) if ok2 and m else None
    if ok1 and cur == idx:
        return True, f"音量 {pct}%（{idx}/{mx}）"
    return False, f"音量設唔到（目標 {idx}，讀返 {cur}）"



def _is_yt_url(u: str) -> bool:
    """YouTube link 判定（2026-10-07 用戶令：網播網頁係 YT 都要劏）。"""
    u = (u or "").lower()
    return any(k in u for k in ("youtube.com/", "youtu.be/",
                                "music.youtube.com"))


def _stop_yt_before_web(u: str) -> None:
    """網播開網頁前：YT link 經 VIEW 會撥去 YT app（唔係瀏覽器），
    要同播歌一樣先 force-stop，唔係帶返舊 task 舊片。"""
    if not _is_yt_url(u) or engine.DRY_RUN:
        return
    for pkg in engine._YT_CANDIDATES:
        engine._shell_priv_exec(f"am force-stop {pkg}")


def _play(url: str, shuffle: bool = False) -> tuple:
    """優先直開 YouTube app（穩陣快），失敗先交畀系統揀 app。
    播前先 force-stop（用戶 2026-10-07 指定）：app 行緊嗰陣 am start 淨係帶前
    舊 task，新 URL 送唔入去（Morphe YT 實錄）；劏乾淨冷啟動先穩。
    回傳 (成功與否, 訊息)；成功但只開到歌單頁（唔自動播）時訊息 = "NO_AUTOLIST"。"""
    target, auto = engine._autoplay_url(url, shuffle)
    ok = out = False
    for pkg in engine._YT_CANDIDATES:
        # 播前劏乾淨：force-stop→冷啟動（封印同款特權 lane；失敗唔攔播放）
        engine._shell_priv_exec(f"am force-stop {pkg}")
        ok, out = engine.run_intent(["am", "start", "-a", "android.intent.action.VIEW",
                              "-d", target, pkg])
        if ok:
            break
    if not ok:
        ok, out = engine.run_intent(["am", "start", "-a", "android.intent.action.VIEW", "-d", target])
    if ok and not auto:
        out = "NO_AUTOLIST"
    return ok, out



def _silence_wav() -> str:
    """整定一段 0.3 秒無聲 WAV（俾 Termux:API 搶音訊焦點用）。"""
    path = engine.os.path.expanduser("~/.tgalarm/silence.wav")
    if not engine.os.path.exists(path):
        import wave
        engine.os.makedirs(engine.os.path.dirname(path), exist_ok=True)
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
    if engine.shutil.which("termux-media-player"):
        ok, _ = engine.run_intent(["termux-media-player", "play", engine._silence_wav()])
        if ok:
            engine.run_intent(["termux-media-player", "stop"])
            return True, "audio-focus"
    ok = out = False
    for am0 in ("/system/bin/am", "am"):
        for pkg in engine._YT_CANDIDATES:
            ok, out = engine.run_intent([am0, "force-stop", pkg])
            if ok:
                break
        if ok:
            break
    if ok:
        return True, "force-stop"
    ok, out = engine.run_intent(["am", "start", "-a", "android.intent.action.MAIN",
                          "-c", "android.intent.category.HOME"])
    if ok:
        return True, "home"
    return False, out



def _fmt_playlists() -> str:
    pl = engine._playlists()
    if not pl.get("lists"):
        return "🎵 仲未有歌單。send：歌單 名稱 YouTube連結"
    lines = ["🎵 歌單："]
    for name in pl["lists"]:
        star = "（預設）" if name == pl.get("default") else ""
        lines.append(f"・{name}{star}")
    return "\n".join(lines)



_BAL_TIP = ("\n💡 背景啟動被擋：vivo/Funtouch 要開「後台彈出界面」（設定→應用與權限→"
            "權限管理→其他權限→Termux；或 i管家→應用管理→權限管理），兼開「鎖屏顯示」；"
            "其他機開「喺其他應用上層顯示」。詳細路徑 send「修復」")



def _is_bal_denied(info) -> bool:
    """am start 失敗訊息係咪似「背景唔俾彈 activity」類。"""
    txt = str(info).lower()
    return "securityexception" in txt or "background" in txt or "not allowed" in txt
