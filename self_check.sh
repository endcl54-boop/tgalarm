#!/usr/bin/env bash
# tgalarm 開場自檢（2026-10-07 用戶令：每輪第一 call；沙盒重置即刻知＋自動救）
# 掃：git HEAD vs origin／core/／ruff／bot.pyz／ssh 可達。異常自動照 runbook 救。
cd "$(dirname "$0")" || exit 1
ISSUES=""

# 1) git：HEAD 對齊 origin/main（remote 抹咗自動重建）
TOKEN=$(cat "$HOME/.gh_token" 2>/dev/null)
if ! git remote get-url origin >/dev/null 2>&1; then
  git remote add origin "https://x-access-token:${TOKEN}@github.com/endcl54-boop/tgalarm.git" 2>/dev/null
fi
git fetch origin -q 2>/dev/null
HEAD=$(git rev-parse --short HEAD 2>/dev/null)
ORI=$(git rev-parse --short origin/main 2>/dev/null)
if [ -n "$ORI" ] && [ "$HEAD" != "$ORI" ]; then
  echo "⚠️ HEAD=$HEAD ≠ origin/main=$ORI（沙盒重置老返）——git reset --soft origin/main 重排"
  ISSUES="$ISSUES head"
fi

# 2) core/（被食慣犯）——自動 git 救
if [ ! -f tgalarm/core/__init__.py ]; then
  git checkout -q origin/main -- tgalarm/core/__init__.py 2>/dev/null \
    && echo "🛠 core/ 被食→git 救返" || { echo "❌ core/ 救唔返"; ISSUES="$ISSUES core"; }
fi

# 3) ruff（逢重置失蹤）——自動補
command -v ruff >/dev/null 2>&1 || { pip install -q ruff >/dev/null 2>&1 && echo "🛠 ruff 重裝"; }

# 4) bot.pyz（pack 產物，無都唔算病）
[ -f bot.pyz ] || echo "ℹ️ bot.pyz 冇（deploy.sh 會 pack）"

# 5) ssh 可達（ts_up 先救一輪）
chmod +x "$HOME/ts_up.sh" 2>/dev/null; "$HOME/ts_up.sh" >/dev/null 2>&1
chmod 600 "$HOME/.ssh/tv_verify" 2>/dev/null
if ssh -o ConnectTimeout=10 -i "$HOME/.ssh/tv_verify" phone 'true' 2>/dev/null; then
  SS="✓"
else
  SS="✗"; ISSUES="$ISSUES ssh"
fi

if [ -z "$ISSUES" ]; then
  echo "SELF_CHECK 全綠（HEAD=$HEAD ssh=$SS）"
else
  echo "SELF_CHECK 異常項:$ISSUES——見上方修復記錄"
fi
