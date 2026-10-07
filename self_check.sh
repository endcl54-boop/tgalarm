#!/usr/bin/env bash
# tgalarm 開場自檢 v2（2026-10-07 用戶令：偵測到即救，唔止報告）
# 掃＋救：git HEAD vs origin（老返→soft-reset 重排）／identity（抹→補）／
#         core/（食→git 救）／ruff（失蹤→補）／bot.pyz 存在／ssh 可達
cd "$(dirname "$0")" || exit 1
ISSUES=""

# 0) ssh key 權限（逢重置被抹）
chmod 600 "$HOME/.ssh/tv_verify" 2>/dev/null

# 1) git remote／identity（逢重置被抹）
TOKEN=$(cat "$HOME/.gh_token" 2>/dev/null)
git remote get-url origin >/dev/null 2>&1 || \
  git remote add origin "https://x-access-token:${TOKEN}@github.com/endcl54-boop/tgalarm.git" 2>/dev/null
[ "$(git config user.name)" = "agent" ] || git config user.name agent
[ "$(git config user.email)" = "agent@local" ] || git config user.email agent@local

# 2) HEAD vs origin（老返→soft-reset 重排：working tree 唔郁，安全）
git fetch origin -q 2>/dev/null
HEAD=$(git rev-parse --short HEAD 2>/dev/null)
ORI=$(git rev-parse --short origin/main 2>/dev/null)
if [ -n "$ORI" ] && [ "$HEAD" != "$ORI" ]; then
  git reset -q --soft origin/main && echo "🛠 HEAD 老返 $HEAD→soft-reset origin/main（$ORI）"
  HEAD=$ORI
  ISSUES="$ISSUES head"
fi

# 2b) ★soft-reset 後 core 必救（實錄：core 被食＋add -A＝刪除推上 main 兩連）
#     贖回鏈：origin/main→ef70643（最後有 core 嘅 commit）
if [ ! -f tgalarm/core/__init__.py ]; then
  git checkout -q origin/main -- tgalarm/core/__init__.py 2>/dev/null || \
    git checkout -q ef70643 -- tgalarm/core/__init__.py 2>/dev/null
  [ -f tgalarm/core/__init__.py ] && echo "🛠 core/ 贖返（origin→ef70643 後備）" \
    || { echo "❌ core/ 兩層都救唔返——add -A 前必須人手處理"; ISSUES="$ISSUES core"; }
fi

# 3) core/（慣犯）——git 救
if [ ! -f tgalarm/core/__init__.py ]; then
  git checkout -q origin/main -- tgalarm/core/__init__.py 2>/dev/null \
    && echo "🛠 core/ 被食→git 救返" || { echo "❌ core/ 救唔返"; ISSUES="$ISSUES core"; }
fi

# 4) ruff（逢重置失蹤）
command -v ruff >/dev/null 2>&1 || { pip install -q ruff >/dev/null 2>&1 && echo "🛠 ruff 重裝"; }

# 5) bot.pyz（pack 產物，冇唔算病）
[ -f bot.pyz ] || echo "ℹ️ bot.pyz 冇（deploy.sh 會 pack）"

# 6) ssh 可達（隧道先救一輪）
chmod +x "$HOME/ts_up.sh" 2>/dev/null; "$HOME/ts_up.sh" >/dev/null 2>&1
chmod 600 "$HOME/.ssh/tv_verify" 2>/dev/null
if timeout 15 ssh -o ConnectTimeout=10 -i "$HOME/.ssh/tv_verify" phone 'true' 2>/dev/null; then
  SS="✓"
else
  SS="✗"; ISSUES="$ISSUES ssh"
fi

if [ -z "$ISSUES" ]; then
  echo "SELF_CHECK 全綠（HEAD=$HEAD ssh=$SS）"
else
  echo "SELF_CHECK 處理完:$ISSUES（見上方修復記錄；head=已 soft-reset 待 commit）"
fi
