#!/usr/bin/env bash
# tgalarm 一鍵部署（2026-10-07 用戶令：根治「md5sum: bot.pyz: No such file」）
# ★根治點：呢個錯全部係 compound 指令行錯 cwd——本腳本鎖死 repo cwd。
# 用法：./deploy.sh   （pack→md5→scp→重啟→probe；probe 失敗自動修復×3）
set -u
cd "$(dirname "$0")" || exit 1
PYZ=bot.pyz
SSH="ssh -o ConnectTimeout=15 -i $HOME/.ssh/tv_verify phone"
SCP="scp -q -o ConnectTimeout=15 -i $HOME/.ssh/tv_verify"
fail() { echo "❌ $1"; exit 1; }

echo "▸ 1/6 pack"
python3 pack.py >/dev/null 2>&1 || fail "pack.py 爆"
[ -f "$PYZ" ] || fail "bot.pyz 冇產生"
L=$(md5sum "$PYZ" | cut -d' ' -f1)

echo "▸ 2/6 ssh tunnel"
chmod +x "$HOME/ts_up.sh" 2>/dev/null
"$HOME/ts_up.sh" >/dev/null 2>&1
chmod 600 "$HOME/.ssh/tv_verify"

echo "▸ 3/6 scp＋md5 對齊"
$SCP "$PYZ" phone:~/telegram-alarm-bot/ || fail "scp"
R=$($SSH 'md5sum ~/telegram-alarm-bot/bot.pyz 2>/dev/null' | cut -d' ' -f1)
[ "$L" = "$R" ] || fail "md5 唔齊：本地 $L vs 電話 $R"

echo "▸ 4/6 restart"
$SSH 'pkill -f "[b]ot\.py"; true' >/dev/null 2>&1
$SSH 'cd ~/telegram-alarm-bot && nohup python3 bot.py >> bot.log 2>&1 < /dev/null & sleep 5; exit 0' 2>/dev/null
sleep 5

echo "▸ 5/6 標準 probe（PID＋getUpdates 200）"
for i in 1 2 3; do
  PID=$($SSH 'pgrep -f "[b]ot\.py" | tail -1' 2>/dev/null)
  LOG=$($SSH 'tail -1 ~/telegram-alarm-bot/bot.log' 2>/dev/null)
  if [ -n "$PID" ] && echo "$LOG" | grep -q "getUpdates.*200"; then
    echo "▸ 6/6 ✅ 部署完成：md5=$L PID=$PID"
    echo "$LOG"
    exit 0
  fi
  echo "  ⚠️ probe 圈 $i 唔過（PID=$PID）——自動修復：劏咗重起"
  $SSH 'pkill -f "[b]ot\.py"; true' >/dev/null 2>&1
  $SSH 'cd ~/telegram-alarm-bot && nohup python3 bot.py >> bot.log 2>&1 < /dev/null & sleep 6; exit 0' 2>/dev/null
  sleep 4
done
fail "3 圈 probe 都唔過——要人手睇 bot.log"
