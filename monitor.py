import telebot
from telebot import types
import subprocess
import os
import time
import threading
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Загрузка env
load_dotenv()

MONITOR_TOKEN = os.getenv("MONITOR_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

bot = telebot.TeleBot(MONITOR_TOKEN)

# --- НАСТРОЙКИ ---
# Формат: "script.py": ("Имя", "Файл статуса", "Файл логов")
BOTS = {
    "main.py":         ("HR Bot",      "status_hr.txt",      "log_hr.txt"),
    "main_analyst.py": ("Analyst Bot", "status_analyst.txt", "log_analyst.txt"),
    "main_sales.py":   ("Sales Bot",   "status_sales.txt",   "log_sales.txt")
}

# --- ЛОГИКА ---
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
            return "Ошибка чтения"
    return "⏳ Нет данных"

def get_last_error_log(logfile):
    """Читает последние 10 строк лога, если бот упал"""
    if not os.path.exists(logfile):
        return "⚠️ Лог-файл не найден"
    
    try:
        # Читаем последние строки
        with open(logfile, "r", encoding="utf-8", errors='ignore') as f:
            lines = f.readlines()
            # Берем последние 8 строк и склеиваем
            last_lines = lines[-8:] if len(lines) > 8 else lines
            return "".join(last_lines).strip()
    except Exception as e:
        return f"Ошибка чтения лога: {e}"

def get_moscow_time():
    return (datetime.utcnow() + timedelta(hours=3)).strftime("%H:%M:%S")

def generate_report():
    report = []
    all_alive = True
    
    for script, (name, status_file, log_file) in BOTS.items():
        is_alive = check_process(script)
        
        if is_alive:
            # Если жив — показываем статус из txt
            status_msg = get_status_text(status_file)
            report.append(f"✅ <b>{name}</b>\n└ <i>{status_msg}</i>")
        else:
            # Если мертв — читаем ЛОГ ОШИБОК
            error_msg = get_last_error_log(log_file)
            # Экранируем теги, чтобы телеграм не ругался на <module> и т.д.
            error_msg = error_msg.replace("<", "&lt;").replace(">", "&gt;")
            
            report.append(f"❌ <b>{name}</b>: DOWN 💀\n<pre>{error_msg}</pre>")
            all_alive = False
            
    msk_time = get_moscow_time()
    header = f"🛡 <b>Система в норме</b> (МСК: {msk_time})" if all_alive else f"🚨 <b>СБОЙ!</b> (МСК: {msk_time})"
    return f"{header}\n\n" + "\n\n".join(report)

# --- КЛАВИАТУРА ---
def get_keyboard():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔄 Обновить статус", callback_data="refresh"))
    return markup

# --- ХЕНДЛЕРЫ ---
@bot.message_handler(commands=['start', 'status'])
def send_status(message):
    bot.send_message(message.chat.id, generate_report(), reply_markup=get_keyboard(), parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data == "refresh")
def refresh_callback(call):
    try:
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, 
                              text=generate_report(), reply_markup=get_keyboard(), parse_mode="HTML")
    except: pass
    bot.answer_callback_query(call.id, "Обновлено!")

def background_checker():
    while True:
        time.sleep(1800)
        try:
            text = generate_report()
            if "❌" in text and ADMIN_CHAT_ID:
                bot.send_message(ADMIN_CHAT_ID, f"🚨 <b>АВТО-ТРЕВОГА!</b>\n\n{text}", parse_mode="HTML")
        except: pass

if __name__ == "__main__":
    if not MONITOR_TOKEN:
        print("⛔ Нет токена (проверь .env)")
    else:
        threading.Thread(target=background_checker, daemon=True).start()
        print("🤖 Monitor Bot (с чтением логов) запущен...")
        bot.polling(none_stop=True)