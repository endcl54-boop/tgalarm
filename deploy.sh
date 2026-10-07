#!/usr/bin/env bash
# tgalarm 一鍵部署 v2（2026-10-07 用戶令：根治時間黑洞——5 題拍板）
# v2：①全部 remote call 包 timeout（掛極 25s）②restart/probe 改叫電話側
#     腳本（ssh 淨係叫腳本，唔帶 sleep/背景邏輯——掛住等慣犯絕跡）
# 用法：./deploy.sh   （pack→md5→scp→restart→probe；probe 失敗自動修復×3）
set -u
cd "$(dirname "$0")" || exit 1
PYZ=bot.pyz
SSH="timeout 25 ssh -o ConnectTimeout=10 -i $HOME/.ssh/tv_verify phone"
SCP="timeout 40 scp -q -o ConnectTimeout=10 -i $HOME/.ssh/tv_verify"
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
R=$(timeout 25 ssh -o ConnectTimeout=10 -i "$HOME/.ssh/tv_verify" phone 'md5sum ~/telegram-alarm-bot/bot.pyz 2>/dev/null' | cut -d' ' -f1)
[ "$L" = "$R" ] || fail "md5 唔齊：本地 $L vs 電話 $R"

echo "▸ 4/6 restart（電話側 restart_bot.sh——一句即返）"
$SSH 'bash ~/telegram-alarm-bot/restart_bot.sh' >/dev/null 2>&1

echo "▸ 5/6 標準 probe（status_bot.sh：PID＋getUpdates 200）"
for i in 1 2 3; do
  sleep 6
  OUT=$($SSH 'bash ~/telegram-alarm-bot/status_bot.sh' 2>/dev/null)
  PID=$(echo "$OUT" | head -1)
  LOG=$(echo "$OUT" | tail -1)
  if [ -n "$PID" ] && echo "$LOG" | grep -q "getUpdates.*200"; then
    echo "▸ 6/6 ✅ 部署完成：md5=$L PID=$PID"
    echo "$LOG"
    exit 0
  fi
  echo "  ⚠️ probe 圈 $i 唔過（PID=$PID）——自動修復：restart_bot.sh 重起"
  $SSH 'bash ~/telegram-alarm-bot/restart_bot.sh' >/dev/null 2>&1
done
fail "3 圈 probe 都唔過——要人手睇 bot.log"
