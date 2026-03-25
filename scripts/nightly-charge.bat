@echo off
cd /d C:\Users\gethi\source\weatherToBattery
claude -p "Run /charge-battery for tomorrow" --allowedTools "Bash,Read,Edit,Write" --permission-mode default
