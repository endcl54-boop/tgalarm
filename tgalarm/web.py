"""web：網頁域（網頁倉／開頁 intent）。"""
from __future__ import annotations

from . import engine


def web_intent_cmd(url: str) -> list:
    return ["am", "start", "-a", "android.intent.action.VIEW", "-d", url]



def _webs() -> dict:
    return engine._load_json(engine.WEBS_PATH, {})



def _web_target(ref: str) -> tuple:
    """名→已儲 url；http(s) 開頭→直接用。回傳 (url, None) 或 (None, 錯誤訊息)。"""
    r = ref.strip()
    if r.lower().startswith(("http://", "https://")):
        return r, None
    w = engine._webs()
    if r in w:
        return w[r], None
    return None, f"搵唔到網頁「{r}」。send「網頁」睇清單，或者直接俾 https:// 連結"



def _fmt_webs() -> str:
    w = engine._webs()
    if not w:
        return ("🌐 仲未有網頁。send：網頁 新聞 https://news.rthk.hk\n"
                "之後可以：開網頁 新聞・0830 開網頁 新聞・每日 0900 開網頁 新聞・刪網頁 新聞")
    lines = ["🌐 已儲存網頁："]
    for name, u in w.items():
        disp = u if len(u) <= 40 else u[:37] + "…"
        lines.append(f"・{name}：{disp}")
    lines.append("用法：開網頁 名・0830 開網頁 名・每日 0900 開網頁 名・刪網頁 名")
    return "\n".join(lines)
