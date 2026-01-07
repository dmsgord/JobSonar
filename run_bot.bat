@echo off
title JobSonar HR Bot
:: 🔥 ЧИНИМ РУССКИЙ ЯЗЫК В КОНСОЛИ
chcp 65001 >nul

cd /d "%~dp0"
echo 🚀 Запускаю бота...

if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
) else (
    echo ❌ Ошибка: папка venv не найдена!
    pause
    exit
)

:: Если вдруг базы нет - создаем
if not exist whitelist.py (
    echo ⚠️ Файл whitelist.py не найден. Генерирую...
    python filter_100.py
)

python main.py
pause