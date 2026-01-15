import subprocess
import requests
import os
import sys

# --- НАСТРОЙКИ ---
MONITOR_TOKEN = "8250592662:AAGMMdrApsy-dWyXM1T60tcd4ACLA-sqxDE"
CHAT_ID = "-5101296808"

# Словарь: Имя скрипта -> (Название для людей, Имя файла-статуса)
BOTS = {
    "main.py":         ("HR Bot",      "status_hr.txt"),
    "main_analyst.py": ("Analyst Bot", "status_analyst.txt"),
    "main_sales.py":   ("Sales Bot",   "status_sales.txt")
}

def send_tg(text):
    try:
        url = f"https://api.telegram.org/bot{MONITOR_TOKEN.strip()}/sendMessage"
        requests.post(url, json={"chat_id": CHAT_ID.strip(), "text": text, "parse_mode": "HTML"})
    except Exception as e:
        print(f"Ошибка отправки: {e}")

def check_process(script_name):
    try:
        output = subprocess.check_output(["ps", "-ax"]).decode()
        return f"python3 {script_name}" in output
    except:
        return False

def get_status_text(filename):
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                return f.read().strip()
        except:
            return "Ошибка чтения файла"
    else:
        return "⏳ Жду обновления..."

def run_check():
    report = []
    all_alive = True
    
    for script, (name, status_file) in BOTS.items():
        is_alive = check_process(script)
        status_msg = get_status_text(status_file)
        
        if is_alive:
            report.append(f"✅ <b>{name}</b>\n└ <i>{status_msg}</i>")
        else:
            report.append(f"❌ <b>{name}</b>: DOWN ⚠️")
            all_alive = False
            
    msg = "\n\n".join(report)
    
    if all_alive:
        header = "🛡 <b>Системный статус: ОК</b>"
    else:
        header = "🚨 <b>ВНИМАНИЕ! СБОЙ!</b>"
        
    send_tg(f"{header}\n\n{msg}")

if __name__ == "__main__":
    run_check()