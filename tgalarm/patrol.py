"""patrol：搬相域（夜更相搬移／搬回／Gemini 分類）。"""
from __future__ import annotations

from . import engine

# ─── WhatsApp 夜更相搬移 ─────────────────────────────────────
# 最短路徑：純 Python scandir + rename，指令 → 執行一步直達，毫秒級回應。
# 「搬相」：將最近夜更時段（預設 23:00–07:00）嘅 WhatsApp 相（包含自己傳出嘅 Sent）
# 搬到 Picture 相簿 WA_Night；「搬相預覽」：齋列唔搬。
_WA_MEDIA_CANDIDATES = (
    "/storage/emulated/0/Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Images",
    "/storage/emulated/0/WhatsApp/Media/WhatsApp Images",
)

_WA_DEST = "/storage/emulated/0/Pictures/WA_Night"

_WA_EXTS = (".jpg", ".jpeg")



def _wa_dirs(src_root: str | None = None) -> list:
    """WhatsApp 圖片目錄（接收區）＋ Sent/Outgoing（自己傳出嘅一併包埋）。
    src_root 畀測試注入；預設自動偵測新/舊版路徑。搵唔到 → 空 list。"""
    root = None
    if src_root:
        root = src_root if engine.os.path.isdir(src_root) else None
    else:
        for c in engine._WA_MEDIA_CANDIDATES:
            if engine.os.path.isdir(c):
                root = c
                break
    if root is None:
        return []
    dirs = [root]
    for sub in ("Sent", "Outgoing"):
        p = engine.os.path.join(root, sub)
        if engine.os.path.isdir(p):
            dirs.append(p)
    return dirs



def _wa_night_window(now: engine.dt.datetime) -> tuple:
    """最近嘅夜更時段 (start, end)：[start, end)。
    23:00 後／07:00 前 → 今晚（進行緊，搬到而家為止）；
    其他時間 → 尋晚 23:00 → 今朝 07:00（已完成嘅夜更）。"""
    if now.hour >= engine._NIGHT_START:
        start = now.replace(hour=engine._NIGHT_START, minute=0, second=0, microsecond=0)
        end = (start + engine.dt.timedelta(days=1)).replace(hour=engine._NIGHT_END)
    else:
        end = now.replace(hour=engine._NIGHT_END, minute=0, second=0, microsecond=0)
        start = (end - engine.dt.timedelta(days=1)).replace(hour=engine._NIGHT_START)
    return start, end



def _wa_recent_window(now: engine.dt.datetime, sh: int, sm: int, eh: int, em: int):
    """自訂時段：最近一次出現嘅 (start→end) 窗（[start, end)）。

    當日窗（起<終，如 0900→1200）：今日未到終點就用尋日嗰個；
    跨夜窗（起>終，如 2300→0700）：過咗起點就當今晚進行中。
    起＝終 → None（語意不明，拒絕）。"""
    if (sh, sm) == (eh, em):
        return None
    if (sh, sm) < (eh, em):                     # 當日窗
        start = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
        end = now.replace(hour=eh, minute=em, second=0, microsecond=0)
        if now < start:                         # 今日未開始 → 尋日嗰個窗
            start -= engine.dt.timedelta(days=1)
            end -= engine.dt.timedelta(days=1)
        return start, end                       # 已完成或進行中都用今日
    start = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
    if now < start:                             # 未到今日起點 → 尋晚嗰個
        start -= engine.dt.timedelta(days=1)
    end = (start + engine.dt.timedelta(days=1)).replace(hour=eh, minute=em)
    return start, end



def _wa_scan(dirs: list, start: engine.dt.datetime, end: engine.dt.datetime) -> list:
    """每個 dir 第一層、jpg/jpeg、mtime 落喺 [start, end) → [(ts, path)]，按時間排序。"""
    s_ep, e_ep = start.timestamp(), end.timestamp()
    hits = []
    for d in dirs:
        try:
            with engine.os.scandir(d) as it:
                for ent in it:
                    try:
                        if not ent.is_file(follow_symlinks=False):
                            continue
                        if not ent.name.lower().endswith(engine._WA_EXTS):
                            continue
                        ts = ent.stat(follow_symlinks=False).st_mtime
                    except OSError:
                        continue
                    if s_ep <= ts < e_ep:
                        hits.append((ts, ent.path))
        except OSError:
            continue
    hits.sort()
    return hits



def _patrol_shift(ts: engine.dt.datetime) -> tuple:
    """巡更更次（2026-10-04 用戶制，照 PC 樹 Shift_A/B/C）：
    07:00–15:00=A・15:00–23:00=B・23:00–07:00=C（跨夜）。
    回傳 (字母, 更次開始日 date)——C更 過午夜，開始日算前一晚。"""
    if 7 <= ts.hour < 15:
        return "A", ts.date()
    if 15 <= ts.hour < 23:
        return "B", ts.date()
    if ts.hour >= 23:
        return "C", ts.date()
    return "C", (ts - engine.dt.timedelta(days=1)).date()



def _gemini_classify(img_path: str, posts: list | None = None) -> tuple:
    """Gemini 讀圖判崗位（2026-10-04 用戶令：bot 讀圖分類）。
    回傳 (代號 或 None, 原始回覆或錯誤)。判唔出／出錯→None。"""
    import base64
    import urllib.parse
    import urllib.request
    if not engine.GEMINI_API_KEY:
        return None, "未設定 GEMINI_API_KEY"
    posts = posts or engine.PATROL_POSTS
    try:
        with open(img_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
    except OSError as e:
        return None, f"讀唔到檔：{e}"
    if engine.GEMINI_RELAY:                                    # 電話（HK）經沙盒轉播
        body = engine.json.dumps({"b64": b64}).encode()
        err = ""
        for _ in range(2):
            try:
                req = urllib.request.Request(
                    engine.GEMINI_RELAY.rstrip("/") + "/classify", data=body,
                    headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=40) as r:
                    d = engine.json.loads(r.read().decode("utf-8", "replace"))
                p = d.get("post")
                return (p if p in posts else None), str(d.get("raw") or "")
            except Exception as e:
                err = str(e)
        return None, err
    prompt = ("香港屋苑保安巡邏相，判斷屬於邊個崗位。只可以回覆以下其中一個代號："
              + "、".join(posts)
              + "。根據相中大廈座數牌／樓層牌／位置特徵判斷；判斷唔到就只回覆：未知。")
    body = engine.json.dumps({"contents": [{"parts": [
        {"inline_data": {"mime_type": "image/jpeg", "data": b64}},
        {"text": prompt}]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 200,
                             "thinkingConfig": {"thinkingBudget": 0}}}).encode()
    # 2026-10-04 實證：新開 key 食唔到 2.0-flash／2.5-flash／2.5-pro（「no longer
    # available to new users」）；2.5 家族淨 2.5-flash-lite 通（models list 實證）
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           "gemini-2.5-flash-lite:generateContent?key=" + urllib.parse.quote(engine.GEMINI_API_KEY))
    err = ""
    for _ in range(2):                                  # 出錯重試一次
        try:
            req = urllib.request.Request(
                url, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=25) as r:
                data = engine.json.loads(r.read().decode("utf-8", "replace"))
            parts = ((data.get("candidates") or [{}])[0].get("content")
                     or {}).get("parts") or [{}]
            txt = (parts[0].get("text") or "").strip()
            tok = engine.re.sub(r"[^A-Za-z0-9]", "", txt.splitlines()[0] if txt else "")
            for p in posts:
                if tok and tok.lower() == engine.re.sub(r"[^A-Za-z0-9]", "", p).lower():
                    return p, txt
            return None, txt or "空回覆"
        except Exception as e:
            err = str(e)
    return None, err



def _wa_move(now: engine.dt.datetime, preview: bool = False,
             src_root: str | None = None, dest: str | None = None,
             window: tuple | None = None) -> str:
    """搬相主體：掃 → 讀圖分類 → 歸檔入巡邏相片記錄樹（2026-10-04 用戶令）。

    樹：root/YYYY M月/YYYY-MM-DD/Shift_X/崗位｜未分類；
    更次照 PC 樹：A 07–15・B 15–23・C 23–07（跟更次開始日）。
    window=None＝最近夜更時段；dest＝測試用 root 覆寫。"""
    dirs = engine._wa_dirs(src_root)
    if not dirs:
        return ("❌ 搵唔到 WhatsApp Images 資料夾。\n"
                "先喺 Termux 行：termux-setup-storage（撳「允許」儲存權限），再 send「搬相」")
    root = dest or engine.PATROL_ROOT
    custom = window is not None
    head = "時段" if custom else "夜更時段"
    icon = "📁" if custom else "🌙"
    start, end = window if custom else engine._wa_night_window(now)
    hits = engine._wa_scan(dirs, start, end)
    span = f"{start:%m-%d %H:%M} → {end:%m-%d %H:%M}"
    if not hits:
        return f"✅ {head}（{span}）冇相，唔使搬。"
    if engine.GEMINI_API_KEY:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=3) as ex:
            labels = list(ex.map(lambda h: engine._gemini_classify(h[1])[0], hits))
    else:
        labels = [None] * len(hits)
    letter, sdate = engine._patrol_shift(start)
    base = engine.os.path.join(root, f"{sdate:%Y} {sdate:%m}月",
                        f"{sdate:%Y-%m-%d}", f"Shift_{letter}")
    sent_n = sum(1 for _, p in hits if "/Sent/" in p or "/Outgoing/" in p)
    tally = {}
    for lab in labels:
        k = lab or "未分類"
        tally[k] = tally.get(k, 0) + 1
    lines = [f"{icon} {head} {span}，共 {len(hits)} 張"
             f"（其中自己傳出 {sent_n} 張）——讀圖分類："
             + "　".join(f"{k}:{v}" for k, v in tally.items())]
    for (ts, path), lab in list(zip(hits, labels))[:8]:
        tag = "↗" if "/Sent/" in path or "/Outgoing/" in path else "↘"
        lines.append(f"  {tag}[{engine.dt.datetime.fromtimestamp(ts):%m-%d %H:%M}] "
                     f"{engine.os.path.basename(path)} → {lab or '未分類'}")
    if len(hits) > 8:
        lines.append(f"  …（仲有 {len(hits) - 8} 張）")
    if not engine.GEMINI_API_KEY:
        lines.append("📁 全部入 未分類——你自己分崗位（電話檔案管理員或 PC 拖入 T74 等資料夾）")
    if preview:
        lines.append("（預覽：冇郁任何相；send「搬相」先真搬）")
        return "\n".join(lines)
    moved = 0
    touched = set()
    for (ts, path), lab in zip(hits, labels):
        d = engine.os.path.join(base, lab or "未分類")
        try:
            engine.os.makedirs(d, exist_ok=True)
            base_fn = engine.os.path.basename(path)
            target = engine.os.path.join(d, base_fn)
            if engine.os.path.exists(target):                  # 防撞名 → -1 -2…
                stem, ext = engine.os.path.splitext(base_fn)
                i = 1
                while engine.os.path.exists(engine.os.path.join(d, f"{stem}-{i}{ext}")):
                    i += 1
                target = engine.os.path.join(d, f"{stem}-{i}{ext}")
            engine.os.replace(path, target)
            moved += 1
            touched.add(d)
        except OSError as e:
            engine.log.warning("搬相失敗 %s：%s", path, e)
    for p in engine._PATROL_POSTS:
        try:
            engine.os.makedirs(engine.os.path.join(base, p), exist_ok=True)
        except OSError as e:
            engine.log.warning("開崗位資料夾失敗 %s：%s", p, e)
    lines.append(f"✅ 搬咗 {moved}/{len(hits)} 張 → {base}")
    lines.append("📂 崗位資料夾開定：" + "、".join(engine._PATROL_POSTS)
                 + "——USB 過 PC 直接拖入去")
    lines.append("（USB 過電腦：成個 BG巡邏相片記錄 資料夾抄過去直接合併同名樹）")
    ms = engine.shutil.which("termux-media-scan")
    for d in touched:
        if ms:
            try:
                engine.subprocess.Popen([ms, d], stdin=engine.subprocess.DEVNULL,
                                 stdout=engine.subprocess.DEVNULL, stderr=engine.subprocess.DEVNULL)
            except Exception:
                pass
    return "\n".join(lines)



def _wa_return(now: engine.dt.datetime, preview: bool = False,
               src: str | None = None, dest_root: str | None = None) -> str:
    """搬回：WA_Night 相簿 → WhatsApp Images 主目錄（2026-10-03 用戶令）。

    全數搬回（唔分時段——搬出去嘅嘢要就得全部）；防撞名 -1 -2；預覽唔郁。"""
    roots = []
    for r in ((src,) if src else (engine.PATROL_ROOT, engine._WA_DEST)):
        if r and engine.os.path.isdir(r) and r not in roots:
            roots.append(r)
    if not roots:
        return "❌ 搵唔到 BG巡邏相片記錄／WA_Night 相簿（未搬過相？）。"
    root = dest_root
    if not root:
        for c in engine._WA_MEDIA_CANDIDATES:
            if engine.os.path.isdir(c):
                root = c
                break
    if not root:
        return ("❌ 搵唔到 WhatsApp Images 資料夾。\n"
                "先喺 Termux 行：termux-setup-storage（撳「允許」儲存權限），再 send「搬回」")
    hits, seen = [], set()
    for r in roots:                                     # 遞歸行勻分類樹（2026-10-04）
        for dirpath, _dn, fns in engine.os.walk(r):
            for fn in fns:
                if not fn.lower().endswith(engine._WA_EXTS):
                    continue
                p = engine.os.path.join(dirpath, fn)
                if p in seen:
                    continue
                try:
                    ts = engine.os.stat(p).st_mtime
                except OSError:
                    continue
                seen.add(p)
                hits.append((ts, p))
    hits.sort()
    if not hits:
        return "✅ 冇相，唔使搬。"
    lines = [f"↩️ 共 {len(hits)} 張，搬返 {engine.os.path.basename(root.rstrip('/')) or root}："]
    for ts, path in hits[:8]:
        lines.append(f"  [{engine.dt.datetime.fromtimestamp(ts):%m-%d %H:%M}] {engine.os.path.basename(path)}")
    if len(hits) > 8:
        lines.append(f"  …（仲有 {len(hits) - 8} 張）")
    if preview:
        lines.append("（預覽：冇郁任何相；send「搬回」先真搬）")
        return "\n".join(lines)
    moved = 0
    for ts, path in hits:
        base = engine.os.path.basename(path)
        target = engine.os.path.join(root, base)
        if engine.os.path.exists(target):                      # 防撞名 → -1 -2…
            stem, ext = engine.os.path.splitext(base)
            i = 1
            while engine.os.path.exists(engine.os.path.join(root, f"{stem}-{i}{ext}")):
                i += 1
            target = engine.os.path.join(root, f"{stem}-{i}{ext}")
        try:
            engine.os.replace(path, target)
            moved += 1
        except OSError as e:
            engine.log.warning("搬回失敗 %s：%s", path, e)
    lines.append(f"✅ 搬咗 {moved}/{len(hits)} 張 → {root}")
    ms = engine.shutil.which("termux-media-scan")
    if ms:
        for d in [root] + roots:
            try:
                engine.subprocess.Popen([ms, d], stdin=engine.subprocess.DEVNULL,
                                 stdout=engine.subprocess.DEVNULL, stderr=engine.subprocess.DEVNULL)
            except Exception:
                pass
    return "\n".join(lines)
