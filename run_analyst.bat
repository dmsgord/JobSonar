@echo off
chcp 65001 > nul
title JobSonar [ANALYST] v4.8
color 0B
cls
echo =================================
echo   JOBSONAR ANALYST BOT v4.8
echo =================================
python main_analyst.py
echo.
echo CRASHED OR STOPPED. Restart in 10s...
timeout /t 10 > nul
goto :eof