#!/usr/bin/env python3
"""engine.py 自動分割器（S3–S13 batch 真拆；2026-10-07）。

輸入：pristine engine.py（/tmp/orig_engine.py）
輸出：tgalarm/{parse,sched,app,exec,jobs,alarms,player,takeaway,guards,
      patrol,nav,android,web,weather,todo,fun}.py ＋ 收縮版 engine.py

機械保證：
- 逐塊 verbatim 切割（連註釋），AST 範圍分析＋token 位置拼接改寫：
  域檔內所有「非本地、非本檔、非 builtin、非 stdlib」名字 → engine.X
  （讀寫删都是）＝延遲綁定，bot shim patch engine.X 對全部域生效
- engine 本體唔改寫（佢就係命名空間本尊），只刪走咗嘅塊＋加底部域
  import＋re-export（bot.X 照讀到）
- `global X` 語句行刪除（賦值已變 engine.X 屬性寫入）
"""
import ast
import builtins
import sys

SRC_PATH = sys.argv[1] if len(sys.argv) > 1 else "/tmp/orig_engine.py"
OUT_DIR = sys.argv[2] if len(sys.argv) > 2 else "tgalarm"

STDLIB_IMPORTS = {  # 名 → import 行
    "asyncio": "import asyncio",
    "dt": "import datetime as dt",
    "fcntl": "import fcntl",
    "json": "import json",
    "logging": "import logging",
    "os": "import os",
    "random": "import random",
    "re": "import re",
    "shlex": "import shlex",
    "shutil": "import shutil",
    "subprocess": "import subprocess",
    "sys": "import sys",
}
BUILTINS = set(dir(builtins))

# ---------------- 分割表（手寫完整映射；缺名 → engine＋警告） ----------------
M = {}
def put(mod, *names):
    for n in names:
        M[n] = mod

put("sched", "_arm", "_wait_wall", "_fire_later", "_hold_wake_lock",
    "_LOCK_FH", "_acquire_singleton")
put("app", "HELP", "_ensure_owner", "_on_start", "_on_message", "main")
put("exec", "_execute_player", "_execute")
put("jobs", "_jobs", "_fmt_job_content", "_fmt_jobs", "_add_simple_job",
    "_add_job", "_pause_job", "_resume_job", "_pause_all", "_resume_all",
    "_edit_job", "_replaced_note", "_remove_job", "_clear_jobs",
    "_restore_jobs", "_next_task_line")
put("alarms", "timer_intent_cmd", "alarm_intent_cmd", "DAILY", "_add_bell",
    "_nag_handle", "_focus_handle", "_countdowns", "_cd_abs",
    "_countdown_days", "_countdown_handle")
put("player", "_YT_CANDIDATES", "_YT_PKG", "_is_yt_url", "_playlists",
    "_resolve_playlist", "_fmt_playlists", "_UA", "_fetch", "_dedupe",
    "_playlist_videos_rss", "_playlist_videos_html", "_PL_CACHE_TTL",
    "_PL_DISK", "_playlist_videos", "_autoplay_url", "_media_vol_max",
    "_set_media_volume", "_play", "_silence_wav", "_stop", "_BAL_TIP",
    "_is_bal_denied")
put("parse", "parse_player")
put("takeaway", "_takeaway_set", "_takeaway_handle")
put("guards", "_battery_chg", "_battery_status_once", "_battery_status",
    "_batt_line", "_battery_handle", "_BT_SYSUI", "_BT_ADAPTER",
    "_parse_bt_connected", "_parse_bt_battery", "_headset_levels",
    "_bthead_line", "_bthead_handle", "_fg_pkg", "_PKG_ALIAS",
    "_pkg_search", "_seal_jobs", "_say_hammer")
put("patrol", "_WA_MEDIA_CANDIDATES", "_WA_DEST", "_WA_EXTS", "_wa_dirs",
    "_wa_night_window", "_wa_recent_window", "_wa_scan", "_patrol_shift",
    "_gemini_classify", "_wa_move", "_wa_return")
put("nav", "_dests", "_NAV_MODES", "_NAV_MODE_LABEL", "_mode_label",
    "_nav_target", "_nav_uri", "_nav_go_script_path", "_nav_write_go_script",
    "_nav_confirm_notify", "_nav_dialog_block", "_nav_run_go",
    "_nav_keyboard", "_nav_keyboard_msg", "_on_nav_callback",
    "_nav_dialog_task", "_open_nav", "_fmt_dests")
put("android", "_RISH_CACHE", "_RISH_TTL", "_rish_probe", "_rish_available",
    "ADB_TARGET", "_ADB_CACHE", "_ADB_TTL", "_adb_shell", "_adb_lane_probe",
    "_adb_lane_available", "_shell_priv_exec")
put("web", "_webs", "_web_target", "_fmt_webs", "web_intent_cmd")
put("weather", "_HKO_CURRENT_URL", "_HKO_FND_URL", "_HKO_UA", "_HKO_KEYS",
    "_hko_fetch", "_hko_flat", "_hko_section", "_HKO_STATIONS", "_HOME",
    "_HOME_NEAR", "_GPS_CACHE", "_gps_fix", "_nearest_station",
    "_hko_district_line", "_hko_current", "_hko_fnd", "_weather_report")
put("fun", "_serpapi_key", "_ai_mode_answer", "_LIAR_DICE_RE",
    "_liar_handle", "_FX_URL", "_FX_ALIAS", "_fx_code", "_fx_parse",
    "_fx_reply", "_TIME_ZONES", "_time_reply", "_PEP", "_pick_reply",
    "_dice_reply", "_password_reply")
put("todo", "_todos", "_todo_add", "_todo_toggle_idx", "_todo_del_idx",
    "_todo_clear_done", "_todo_speech", "_fmt_todos", "_todo_keyboard",
    "_schedule_todo_refresh", "_refresh_todo", "_on_todo_callback",
    "_alloc_buf", "_alloc_segments", "_alloc_ff", "_add_alloc_job",
    "_alloc_breakdown", "_alloc_remaining_end", "_alloc_reflow",
    "_alloc_advance", "_fire_alloc")
# finance 兩條 shim 由 engine 直接 re-export tgalarm.finance（S1 已存在）
FINANCE_REEXPORT = {"_findef_route": "_finance_mod.route",
                    "_findef_api": "_finance_mod.api",
                    "_finance_mod": "finance as _finance_mod"}

DOCSTRINGS = {
    "sched": "sched：排程引擎（_arm／_fire_later／牆鐘等待／單例鎖／wake lock）。\n共享狀態全部經 engine.X 延遲綁定（測試 patch engine.X 對呢度生效）。",
    "app": "app：Telegram 入口層（_on_message／_on_start／main／HELP）。\n組合根：識所有域（經 engine re-export）；共享名經 engine.X 延遲綁定。",
    "exec": "exec：指令執行器（_execute_player／_execute——PlayerCmd／dict 指令分派到各域）。",
    "jobs": "jobs：排程倉 CRUD＋列表／暫停／恢復／編輯／下一任務行。",
    "alarms": "alarms：鬧鐘／計時／連環／倒數／專注／碎念域。",
    "player": "player：播歌域（歌單倉／live／自動播／音量／停播候選鏈）。",
    "takeaway": "takeaway：外賣模式域（即開／即收／每日排程版）。",
    "guards": "guards：守護域（電量守／耳機守／封印防線）。",
    "patrol": "patrol：搬相域（夜更相搬移／搬回／Gemini 分類）。",
    "nav": "nav：導航域（地點倉／Maps URI／彈窗確認／導航任務）。",
    "android": "android：Android 執行 lane（adb→rish 特權通道／探活快取）。",
    "web": "web：網頁域（網頁倉／開頁 intent）。",
    "weather": "weather：天氣域（HKO RSS＋九日／GPS 定位佐敦）。",
    "fun": "fun：趣味域（骰仔／密碼／打氣／匯率／時間／AI Mode／大話骰）。",
    "parse": "parse：文法解析域（parse_lines／parse_command／parse_player／日期時間解析器）。",
    "todo": "todo：待辦＋時間分配域（todo 倉／alloc 分段快進）。",
}

# ---------------- 讀原檔＋切塊 ----------------
src = open(SRC_PATH, encoding="utf-8").read()
lines = src.splitlines(keepends=True)
tree = ast.parse(src)

# 塊＝(起行, 止行(0-based excl), 定義名集合, 類型)
blocks = []
for node in tree.body:
    names = set()
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                         ast.ClassDef)):
        names.add(node.name)
    elif isinstance(node, ast.Assign):
        for t in node.targets:
            if isinstance(t, ast.Name):
                names.add(t.id)
    kind = "def"
    # 裝飾器行（@dataclass 等）喺 node.lineno 之前——唔包就會切走
    dec_start = node.lineno - 1
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        dec_start = min([d.lineno for d in node.decorator_list]
                        + [node.lineno]) - 1
    src_txt = "".join(lines[dec_start:node.end_lineno])
    if isinstance(node, ast.If):
        kind = "if"
        body_src = src_txt
        if "import liar" in body_src:
            names.add("_liar")
        elif '__name__' in body_src and "main()" in body_src:
            names.add("__main_guard__")
    elif isinstance(node, ast.Try):
        kind = "try"
        if "import liar" in src_txt:
            names.add("_liar")
    elif isinstance(node, ast.Expr):
        kind = "docstring"
    blocks.append((dec_start, node.end_lineno, names, kind))

# 前置註釋行（# 或空白）歸跟隨塊
def with_comments(start):
    s = start
    while s > 0 and (lines[s - 1].strip() == ""
                     or lines[s - 1].lstrip().startswith("#")):
        s -= 1
    return s

assigned = {}
unknown = []
for (s, e, names, kind) in blocks:
    if kind == "docstring":
        assigned.setdefault("engine", []).append((s, e))
        continue
    mod = None
    for n in names:
        if n == "__main_guard__":
            mod = "app"
            break
        if n in FINANCE_REEXPORT:
            mod = "finance"
            break
        if n in M:
            mod = M[n]
            break
    if mod is None:
        mod = "engine"
        unknown.extend(names or [f"lines{s+1}-{e}"])
    s2 = with_comments(s)
    assigned.setdefault(mod, []).append((s2, e))

if unknown:
    print("⚠️ 無映射符號（入 engine）：", sorted(set(unknown)))
_all_names = set()
for _b in blocks:
    _all_names |= _b[2]
missing = [n for n in M if n not in _all_names]
if missing:
    print("⚠️ 映射表有但原檔冇：", missing)

# ---------------- AST 範圍分析＋token 改寫 ----------------
class Scope:
    def __init__(self, parent=None):
        self.locals = set()
        self.parent = parent
    def has(self, n):
        s = self
        while s:
            if n in s.locals:
                return True
            s = s.parent
        return False

def bound_names(nodes, file_globals):
    """函數 body 入面「喺呢個 scope 綁定」嘅名（唔入巢狀函數/comprehension）。
    file_global 名唔算 local（佢哋變 engine.X 屬性讀寫）。"""
    out = set()

    def walk(n):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                          ast.ClassDef)):
            out.add(n.name)
            return
        if isinstance(n, (ast.Lambda, ast.ListComp, ast.SetComp,
                          ast.DictComp, ast.GeneratorExp)):
            return
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store,
                                                          ast.Del)):
            if n.id not in file_globals:
                out.add(n.id)
            return
        if isinstance(n, ast.Global):
            return
        if isinstance(n, ast.ExceptHandler) and n.name:
            out.add(n.name)
        if isinstance(n, ast.withitem) and n.optional_vars:
            for t in ast.walk(n.optional_vars):
                if isinstance(t, ast.Name):
                    out.add(t.id)
        if isinstance(n, ast.Import):
            for al in n.names:
                out.add((al.asname or al.name).split(".")[0])
        if isinstance(n, ast.ImportFrom):
            for al in n.names:
                out.add(al.asname or al.name)
        for ch in ast.iter_child_nodes(n):
            walk(ch)

    for n in nodes:
        walk(n)
    return out


def collect_prefix_positions(chunk_src, file_globals, needed_imports):
    """回 (要加 engine. 前綴嘅 (lineno,col) 集, 要刪嘅行號集)。"""
    tree = ast.parse(chunk_src)
    positions = set()
    global_lines = set()

    def visit(node, scope):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            s = Scope(scope)
            a = node.args
            for arg in (list(getattr(a, "posonlyargs", [])) + list(a.args)
                        + list(a.kwonlyargs)):
                s.locals.add(arg.arg)
            if a.vararg:
                s.locals.add(a.vararg.arg)
            if a.kwarg:
                s.locals.add(a.kwarg.arg)
            s.locals |= bound_names(node.body, file_globals)
            for d in node.decorator_list:
                visit(d, scope)
            for default in list(a.defaults) + [d for d in a.kw_defaults if d]:
                visit(default, scope)
            if node.returns:
                visit(node.returns, scope)
            for arg in (list(getattr(a, "posonlyargs", [])) + list(a.args)
                        + list(a.kwonlyargs)):
                if arg.annotation:
                    visit(arg.annotation, scope)
            for stmt in node.body:
                visit(stmt, s)
            return
        if isinstance(node, ast.Lambda):
            s = Scope(scope)
            a = node.args
            for arg in (list(getattr(a, "posonlyargs", [])) + list(a.args)
                        + list(a.kwonlyargs)):
                s.locals.add(arg.arg)
            if a.vararg:
                s.locals.add(a.vararg.arg)
            if a.kwarg:
                s.locals.add(a.kwarg.arg)
            for default in list(a.defaults) + [d for d in a.kw_defaults if d]:
                visit(default, scope)
            visit(node.body, s)
            return
        if isinstance(node, ast.Global):
            global_lines.add(node.lineno)
            return
        if isinstance(node, ast.Name):
            at_root = scope.parent is None        # module 層（import 期）
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                # ★先判 file_global（scope.has 會被下面 add 污染）
                is_fg = (not scope.has(node.id) and node.id in file_globals
                         and not node.id.startswith("__"))
                scope.locals.add(node.id)
                # 函數內 Store 自己檔全域名 → engine.X（patch 語義一致）；
                # module 層 Store 保持本地（init 順序＝原語義）
                if is_fg and not at_root:
                    positions.add((node.lineno, node.col_offset))
                return
            # Load：本地／builtin／stdlib／dunder 豁免；函數內連同檔名都
            # 行 engine.X（單一命名空間，bot patch engine.X 對本域生效）；
            # module 層同檔名保持本地（未 re-export、init 順序＝原語義）
            if scope.has(node.id):
                return
            if (node.id in BUILTINS
                    or (node.id.startswith("__")
                        and node.id.endswith("__"))):
                return
            if at_root and node.id in file_globals:
                return
            positions.add((node.lineno, node.col_offset))
            return
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp,
                             ast.GeneratorExp)):
            s = Scope(scope)
            for gen in node.generators:
                for tn in ast.walk(gen.target):
                    if isinstance(tn, ast.Name):
                        s.locals.add(tn.id)
                visit(gen.iter, scope)
                for cond in gen.ifs:
                    visit(cond, s)
            if isinstance(node, ast.DictComp):
                visit(node.key, s)
                visit(node.value, s)
            else:
                visit(node.elt, s)
            return
        if isinstance(node, ast.ExceptHandler) and node.name:
            scope.locals.add(node.name)
        if isinstance(node, ast.withitem) and node.optional_vars:
            for tn in ast.walk(node.optional_vars):
                if isinstance(tn, ast.Name):
                    scope.locals.add(tn.id)
        for ch in ast.iter_child_nodes(node):
            visit(ch, scope)

    visit(tree, Scope())
    return positions, global_lines

def rewrite_chunk(chunk_src, file_globals):
    """回 (改寫後源碼, 用到嘅 stdlib 名集)。"""
    # 先估 stdlib 用量（unprefixed 候選）
    tree = ast.parse(chunk_src)
    used = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and n.id in STDLIB_IMPORTS:
            used.add(n.id)
    positions, global_lines = collect_prefix_positions(
        chunk_src, file_globals, used)
    lines_c = chunk_src.splitlines(keepends=True)
    for ln in global_lines:
        lines_c[ln - 1] = "\n"          # 刪 global 語句（留換行防錯位）
    # 逐行由大 col 到細插入 engine. 前綴（AST 位置精準、註釋全保）
    pos_by_line = {}
    for (ln, col) in positions:
        pos_by_line.setdefault(ln, set()).add(col)
    for ln, cols in pos_by_line.items():
        line = lines_c[ln - 1]
        # AST col=UTF-8 byte 位；中文行要轉返 char 位先 splice
        def _to_char(bc, _ln=line):
            return len(_ln.encode("utf-8")[:bc].decode("utf-8",
                                                      errors="ignore"))
        for cc in sorted((_to_char(c) for c in cols), reverse=True):
            line = line[:cc] + "engine." + line[cc:]
        lines_c[ln - 1] = line
    new_src = "".join(lines_c)
    try:
        tree2 = ast.parse(new_src)      # 驗證語法
    except SyntaxError:
        import tempfile
        p = tempfile.mktemp(prefix="bad_chunk_", dir="/tmp")
        open(p, "w", encoding="utf-8").write(
            "=====原=====>\n" + chunk_src + "\n=====改=====>\n" + new_src)
        print("❌ 改寫失敗，樣本：", p)
        raise
    used2 = set()
    for n in ast.walk(tree2):
        if isinstance(n, ast.Name) and n.id in STDLIB_IMPORTS:
            used2.add(n.id)
    return new_src, used2

# ---------------- 產生各模組 ----------------
import os

os.makedirs(OUT_DIR, exist_ok=True)
module_files = {}

ORDER = ["sched", "app", "exec", "jobs", "parse", "alarms", "player",
         "takeaway", "guards", "patrol", "nav", "android", "web",
         "weather", "todo", "fun"]
reexport_map = {}   # module -> [names]

for mod in ORDER:
    chunks = assigned.get(mod, [])
    if not chunks:
        continue
    file_globals = {n for n, m in M.items() if m == mod}
    body_parts = []
    used_all = set()
    for (s, e) in chunks:
        piece = "".join(lines[s:e])
        new_piece, used = rewrite_chunk(piece, file_globals)
        body_parts.append(new_piece)
        used_all |= used
    header = [f'"""{DOCSTRINGS[mod]}"""', "from __future__ import annotations",
              "from . import engine", "", ""]
    module_files[mod] = "\n".join(header) + "\n".join(body_parts)
    reexport_map[mod] = sorted(n for n, m in M.items() if m == mod)

# ---------------- 產生新 engine.py ----------------
eng_chunks = assigned.get("engine", [])
# 頂層 import 行全部過濾——header 統一出「命名空間契約塊」（杜絕 F811 重複）
_import_lines = set()
for _n in tree.body:
    if isinstance(_n, (ast.Import, ast.ImportFrom)):
        _import_lines.update(range(_n.lineno, _n.end_lineno + 1))
eng_body = "".join(
    lines[i] for (s0, e0) in eng_chunks for i in range(s0, e0)
    if (i + 1) not in _import_lines)
eng_tree = ast.parse("".join(lines[eng_chunks[0][0]:eng_chunks[-1][1]])
                     if eng_chunks else "pass")
eng_used = set()
for n in ast.walk(eng_tree):
    if isinstance(n, ast.Name) and n.id in STDLIB_IMPORTS:
        eng_used.add(n.id)

rel = []
for mod in sorted([m for m in ORDER if m in module_files] + ["finance"]):
    rel.append(f"from . import {mod} as _{mod}_mod")
rel.append("_findef_route = _finance_mod.route")
rel.append("_findef_api = _finance_mod.api")
rel.append("")
for mod in ORDER:
    for n in reexport_map.get(mod, []):
        rel.append(f"{n} = _{mod}_mod.{n}")


new_engine = ('# ruff: noqa: F401  —— 呢塊 import 係命名空間契約：'
              '域檔經 engine.X 引用，engine 自己未必用到\n'
              '"""tgalarm 引擎中樞（S13 batch 拆分後）：狀態／設定／路徑／'
              'jobs 倉／TG 發送／語音／共用格式化。域模組（同目錄 *.py）'
              '全部經 engine.X 延遲綁定存取呢度——bot shim patch engine.X '
              '對全模組生效。各域本體見同目錄檔案。"""\n'
              "from __future__ import annotations\n\n"
              + "import asyncio\nimport datetime as dt\nimport fcntl\n"
              + "import json\nimport logging\nimport os\nimport random\n"
              + "import re\nimport shlex\nimport shutil\n"
              + "import subprocess\nimport sys\n"
              + "from dataclasses import dataclass\n"
              + "\n" + eng_body + "\n\n"
              + "# ---- 域模組（verbatim 拆出；呢度 re-export 保持 bot.X 相容）----\n"
              + "\n".join(rel) + "\n")

with open(os.path.join(OUT_DIR, "engine.py"), "w", encoding="utf-8") as f:
    f.write(new_engine)
for mod, content in module_files.items():
    with open(os.path.join(OUT_DIR, f"{mod}.py"), "w", encoding="utf-8") as f:
        f.write(content)

print(f"✅ 拆完：engine（{len(new_engine.splitlines())} 行）＋ "
      f"{len(module_files)} 個域檔")
for mod in ORDER:
    if mod in module_files:
        n = len(module_files[mod].splitlines())
        flag = "⚠️>800" if n > 800 else "✓"
        print(f"  {mod:9s} {n:5d} 行 {flag}（{len(reexport_map.get(mod, []))} 符號）")
