#!/data/data/com.termux/files/usr/bin/bash
# status_bot.sh（2026-10-07 用戶令：一句返 PID＋log 尾行）
cd "$HOME/telegram-alarm-bot" || exit 1
pgrep -f "[b]ot\.py" | tail -1
tail -1 bot.log
