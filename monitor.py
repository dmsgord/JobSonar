import telebot
from telebot import types
import subprocess
import os
import time
import threading
from datetime import datetime

# --- НАСТРОЙКИ ---
MONITOR_TOKEN = "8250592662:AAGMMdrApsy-dWyXM1T60tcd4ACLA-sqxDE"
ADMIN_CHAT_ID = "-5101296808"

# Список ботов: (Имя скрипта) -> (Имя для отчета, Файл статуса)
BOTS = {
    "main.py":         ("HR Bot",      "status_hr.txt"),
    "main_analyst.py": ("Analyst Bot", "status_analyst.txt"),
    "main_sales.py":   ("Sales Bot",   "status_sales.txt")
}

bot = telebot.TeleBot(MONITOR_TOKEN)

# --- ЛОГИКА ---
def check_process(script_name):
    try:
        # Проверяем список процессов
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
    else:
        return "⏳ Нет данных"

def generate_report():
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
            
    timestamp = datetime.now().strftime("%H:%M:%S")
    
    if all_alive:
        header = f"🛡 <b>Система в норме</b> (Обновлено: {timestamp})"
    else:
        header = f"🚨 <b>ЕСТЬ ПРОБЛЕМЫ!</b> (Обновлено: {timestamp})"
        
    return f"{header}\n\n" + "\n\n".join(report)

# --- КЛАВИАТУРА ---
def get_keyboard():
    markup = types.InlineKeyboardMarkup()
    btn = types.InlineKeyboardButton("🔄 Обновить статус", callback_data="refresh")
    markup.add(btn)
    return markup

# --- ОБРАБОТЧИКИ TELEGRAM ---
@bot.message_handler(commands=['start', 'status'])
def send_status(message):
    try:
        text = generate_report()
        bot.send_message(message.chat.id, text, reply_markup=get_keyboard(), parse_mode="HTML")
    except Exception as e:
        print(f"Ошибка отправки: {e}")

@bot.callback_query_handler(func=lambda call: call.data == "refresh")
def refresh_callback(call):
    new_text = generate_report()
    try:
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=new_text,
            reply_markup=get_keyboard(),
            parse_mode="HTML"
        )
    except:
        # Если текст не изменился, Телеграм кидает ошибку. Игнорируем её.
        pass
    
    # Убираем значок "часиков" с кнопки
    bot.answer_callback_query(call.id, "Данные обновлены!")

# --- ФОНОВАЯ ПРОВЕРКА (Раз в 30 мин) ---
def background_checker():
    while True:
        time.sleep(1800) # 30 минут
        try:
            text = generate_report()
            # Если есть упавшие боты — шлем уведомление сами
            if "❌" in text:
                bot.send_message(ADMIN_CHAT_ID, f"🚨 <b>АВТО-ТРЕВОГА!</b>\n\n{text}", parse_mode="HTML")
        except:
            pass

if __name__ == "__main__":
    # Запуск фонового потока
    threading.Thread(target=background_checker, daemon=True).start()
    
    print("🤖 Monitor Bot с кнопкой запущен...")
    while True:
        try:
            bot.polling(none_stop=True, interval=2)
        except Exception as e:
            print(f"Ошибка поллинга: {e}")
            time.sleep(5)