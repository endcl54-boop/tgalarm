#!/data/data/com.termux/files/usr/bin/bash
# restart_bot.sh（2026-10-07 用戶令：ssh 淨係叫腳本，唔帶 sleep/背景邏輯）
# 叫法：ssh phone 'bash ~/telegram-alarm-bot/restart_bot.sh'——一句即返
pgrep -f "[b]ot\.py" >/dev/null && pkill -f "[b]ot\.py"
sleep 1
cd "$HOME/telegram-alarm-bot" || exit 1
setsid nohup python3 bot.py >> bot.log 2>&1 < /dev/null &
echo "STARTED"
