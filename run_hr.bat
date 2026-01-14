@echo off
chcp 65001 > nul
title JobSonar [HR] v4.8
color 0F
cls
echo =================================
echo   JOBSONAR HR BOT v4.8
echo =================================
python main.py
echo.
echo CRASHED OR STOPPED. Restart in 10s...
timeout /t 10 > nul
goto :eof