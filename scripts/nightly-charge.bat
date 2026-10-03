@echo off
cd /d C:\Users\gethi\sources\weathertobattery
claude -p "Run /charge-battery for tomorrow" --allowedTools "Bash,Read,Edit,Write" --permission-mode default
