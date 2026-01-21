import telebot
from telebot import types
import subprocess
import os
import time
import threading
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Загрузка env
load_dotenv()

MONITOR_TOKEN = os.getenv("MONITOR_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

# Лимит размера лога (5 МБ)
MAX_LOG_SIZE_BYTES = 5 * 1024 * 1024 

# Проверка токена
if not MONITOR_TOKEN:
    print("❌ ОШИБКА: MONITOR_TOKEN не найден в .env!")
    sys.exit(1)

bot = telebot.TeleBot(MONITOR_TOKEN)

# --- НАСТРОЙКИ ---
BOTS = {
    "main.py":           ("HR Bot",        "status_hr.txt",        "log_hr.txt"),
    "main_analyst.py":   ("Analyst Bot",   "status_analyst.txt",   "log_analyst.txt"),
    "main_sales.py":     ("Sales Bot",     "status_sales.txt",     "log_sales.txt"),
    "main_recruiter.py": ("Recruiter Bot", "status_recruiter.txt", "log_recruiter.txt")
}

# --- ЛОГИКА ---
def check_process(script_name):
    """Проверяет, запущен ли процесс с указанным именем скрипта"""
    try:
        output = subprocess.check_output(["ps", "-ax"]).decode()
        return script_name in output
    except:
        return False

def get_status_text(filename):
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                return f.read().strip()
        except:
            return "Ошибка чтения"
    return "⏳ Нет данных"

def get_last_error_log(logfile):
    if not os.path.exists(logfile):
        return "⚠️ Лог-файл не найден"
    try:
        with open(logfile, "r", encoding="utf-8", errors='ignore') as f:
            lines = f.readlines()
            last_lines = lines[-8:] if len(lines) > 8 else lines
            return "".join(last_lines).strip()
    except Exception as e:
        return f"Ошибка: {e}"

def cleanup_logs():
    for script, (name, status_file, log_file) in BOTS.items():
        if os.path.exists(log_file):
            try:
                size = os.path.getsize(log_file)
                if size > MAX_LOG_SIZE_BYTES:
                    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()
                        last_lines = lines[-200:]
                    with open(log_file, "w", encoding="utf-8") as f:
                        f.write(f"--- LOG CLEANED BY MONITOR (Was > 5MB) ---\n")
                        f.writelines(last_lines)
                    print(f"🧹 Лог {log_file} был очищен.")
            except Exception as e:
                print(f"Ошибка очистки лога {log_file}: {e}")

def get_moscow_time():
    return (datetime.utcnow() + timedelta(hours=3)).strftime("%H:%M:%S")

def generate_report():
    report = []
    all_alive = True
    
    for script, (name, status_file, log_file) in BOTS.items():
        is_alive = check_process(script)
        if is_alive:
            status_msg = get_status_text(status_file)
            report.append(f"✅ <b>{name}</b>\n└ <i>{status_msg}</i>")
        else:
            error_msg = get_last_error_log(log_file).replace("<", "&lt;").replace(">", "&gt;")
            report.append(f"❌ <b>{name}</b>: DOWN 💀\n<pre>{error_msg}</pre>")
            all_alive = False
            
    msk_time = get_moscow_time()
    header = f"🛡 <b>Система в норме</b> (МСК: {msk_time})" if all_alive else f"🚨 <b>СБОЙ!</b> (МСК: {msk_time})"
    return f"{header}\n\n" + "\n\n".join(report)

# --- ИНТЕРФЕЙС ---
def get_keyboard():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔄 Обновить статус", callback_data="refresh"))
    return markup

@bot.message_handler(commands=['start', 'status'])
def send_status(message):
    try:
        bot.send_message(message.chat.id, generate_report(), reply_markup=get_keyboard(), parse_mode="HTML")
    except Exception as e:
        print(f"❌ Ошибка отправки: {e}")

@bot.callback_query_handler(func=lambda call: call.data == "refresh")
def refresh_callback(call):
    try:
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, 
                              text=generate_report(), reply_markup=get_keyboard(), parse_mode="HTML")
        bot.answer_callback_query(call.id, "Обновлено!")
    except: pass

def background_checker():
    while True:
        time.sleep(1800)
        cleanup_logs()
        try:
            text = generate_report()
            if "❌" in text and ADMIN_CHAT_ID:
                bot.send_message(ADMIN_CHAT_ID, f"🚨 <b>АВТО-ТРЕВОГА!</b>\n\n{text}", parse_mode="HTML")
        except: pass

if __name__ == "__main__":
    threading.Thread(target=background_checker, daemon=True).start()
    print("🤖 Monitor Bot запускается...")
    
    # Auto-restart loop
    while True:
        try:
            bot.infinity_polling(timeout=10, long_polling_timeout=5)
        except Exception as e:
            print(f"⚠️ Polling упал: {e}. Рестарт через 5 сек...")
            time.sleep(5)