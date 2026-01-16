# -*- coding: utf-8 -*-
import time
import requests
import re
import sys
import signal
import logging
import random
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "log_recruiter.txt")
STATUS_FILE = os.path.join(BASE_DIR, "status_recruiter.txt")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

from config_recruiter import TG_TOKEN, TG_CHAT_ID, PROFILES, MIN_SALARY, SEARCH_PERIOD, USER_AGENT, DB_NAME
from db import init_db, is_sent, mark_as_sent, set_db_name, get_daily_stats

try:
    from whitelist import APPROVED_COMPANIES
except ImportError:
    APPROVED_COMPANIES = {}

session = requests.Session()
session.headers.update({'User-Agent': USER_AGENT})

set_db_name(os.path.join(BASE_DIR, DB_NAME))
BOT_ID = TG_TOKEN.split(':')[0] if TG_TOKEN else "0"
LAST_UPDATE_ID = 0

CAT_ALIASES = {
    'ГИГАНТЫ': '🏆',
    'КРУПНЫЕ': '🥇',
    'СРЕДНИЕ': '🥈',
    'НЕБОЛЬШИЕ': '🥉',
    'ОСТАЛЬНЫЕ': '🌐'
}

def set_status(text):
    try:
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            now = (datetime.utcnow() + timedelta(hours=3)).strftime("%H:%M")
            f.write(f"[{now}] {text}")
    except: pass

def signal_handler(sig, frame):
    logging.info("🛑 Получен сигнал остановки.")
    send_telegram("🛑 <b>Recruiter-мониторинг остановлен</b>")
    sys.exit(0)

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

def send_telegram(text):
    try:
        requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", 
                      json={"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
                      timeout=10)
    except Exception as e:
        logging.error(f"Ошибка ТГ: {e}")

def init_updates():
    global LAST_UPDATE_ID
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates"
        resp = requests.get(url, params={"limit": 1, "offset": -1}, timeout=5).json()
        if resp.get("result"):
            LAST_UPDATE_ID = resp["result"][0]["update_id"]
    except: pass

def check_remote_stop():
    global LAST_UPDATE_ID
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates"
        params = {"limit": 5, "offset": LAST_UPDATE_ID + 1}
        resp = requests.get(url, params=params, timeout=5).json()
        if resp.get("result"):
            for update in resp["result"]:
                LAST_UPDATE_ID = update["update_id"]
                msg = update.get("message", {})
                from_id = str(msg.get("from", {}).get("id", ""))
                text = msg.get("text", "").lower()
                if from_id == BOT_ID: continue
                if str(msg.get("chat", {}).get("id")) == str(TG_CHAT_ID):
                    if "стоп" in text:
                        send_telegram("🛑 <b>Recruiter-бот остановлен</b>")
                        sys.exit(0)
    except: pass

def smart_contains(text, word):
    word_lower = word.lower()
    text_lower = text.lower()
    if len(word_lower) <= 3 and word_lower.isascii():
        return re.search(r'\b' + re.escape(word_lower) + r'\b', text_lower) is not None
    return word_lower in text_lower

def fetch_hh_paginated(text, period=SEARCH_PERIOD):
    all_items = []
    page = 0
    # Ищем ТОЛЬКО schedule=remote на уровне API
    params = {
        "text": text, 
        "order_by": "publication_time", 
        "per_page": 100, 
        "search_field": "name", 
        "period": period,
        "schedule": "remote" 
    }

    while page < 10:
        params["page"] = page
        try:
            resp = session.get("https://api.hh.ru/vacancies", params=params, timeout=10)
            data = resp.json()
            items = data.get("items", [])
            if not items: break
            all_items.extend(items)
            if page >= data.get('pages', 0) - 1: break
            page += 1
            time.sleep(random.uniform(0.3, 1.0))
        except Exception as e:
            logging.error(f"HH API Error: {e}")
            break
    return all_items

def get_clean_category(cat_raw):
    clean = re.sub(r'[^\w\s]', '', cat_raw).strip().upper()
    return CAT_ALIASES.get(clean, '🌐')

def process_items(items, rules):
    processed_count = 0
    unique_items = {v['id']: v for v in items}.values()
    
    spam_deduplication_cache = set()

    for item in unique_items:
        vac_id = item['id']
        title = item['name']
        title_lower = title.lower()
        
        # 1. Проверка отправки
        if is_sent(vac_id): continue
        
        # 2. Стоп-слова в заголовке (Генералисты, Директора, Кадровики)
        if any(stop_w in title_lower for stop_w in rules["stop_words_title"]): continue

        # 3. Дедупликация (Компания + Название)
        emp = item.get('employer', {})
        emp_id = str(emp.get('id', ''))
        spam_signature = f"{emp_id}_{title_lower}"
        
        if spam_signature in spam_deduplication_cache:
            mark_as_sent(vac_id, category='Остальные')
            continue
        else:
            spam_deduplication_cache.add(spam_signature)

        # 4. Проверка графика (Жесткая удаленка)
        # Хоть мы и запросили remote, проверяем, нет ли "гибрида" в деталях
        details = []
        raw_schedule = item.get('schedule', {})
        raw_formats = item.get('work_format', [])
        
        if raw_schedule:
             if raw_schedule.get('name') not in [f['name'] for f in raw_formats]:
                 details.append(raw_schedule.get('name'))
        for f in raw_formats:
            details.append(f['name'])

        details_text = ", ".join(details).lower()
        # Если есть намек на офис или гибрид - пропускаем
        if any(x in details_text for x in ['гибрид', 'hybrid', 'офис', 'office', 'на месте']):
            continue

        # 5. Стоп-сферы (Казино и т.д.)
        snippet = item.get('snippet', {}) or {}
        full_text = (item.get('name', '') + ' ' + (snippet.get('requirement') or '')).lower()
        if any(smart_contains(full_text, stop) for stop in rules['stop_domains']):
            continue

        # 6. Зарплата (>= 100к или скрыта)
        sal = item.get('salary')
        salary_text = "-"
        is_bold_salary = False
        threshold = MIN_SALARY
        salary_value = 0
        
        if sal and sal.get('from'):
            # Если валюта не рубли - считаем хорошей
            if sal.get('currency') != 'RUR':
                 salary_text = f"от {sal.get('from')} {sal.get('currency')}"
                 is_bold_salary = True
                 salary_value = 999999
            else:
                 # Рубли: проверяем порог
                 if sal.get('from') < threshold:
                     continue 
                 salary_text = f"от {sal.get('from')} {sal.get('currency','₽')}"
                 is_bold_salary = True
                 salary_value = sal.get('from')
        else:
            # Если зарплата скрыта - ПРОХОДИТ
            pass 
        
        # 7. Категория и Огоньки
        cat_raw = APPROVED_COMPANIES.get(emp_id, {}).get('cat', 'Остальные')
        cat_emoji = get_clean_category(cat_raw)
        is_whitelist = emp_id in APPROVED_COMPANIES
        
        dt = item.get('published_at', '').split('T')[0]
        pub_date = f"{dt.split('-')[2]}.{dt.split('-')[1]}"
        
        fire_marker = ""
        # Огонек ТОЛЬКО если компания из Whitelist
        if is_whitelist:
             fire_marker = "🔥 "

        salary_html = f"<b>{salary_text}</b>" if is_bold_salary else salary_text

        msg = (
            f"{fire_marker}{cat_emoji} <b>{emp.get('name')}</b>\n\n"
            f"<a href='{item['alternate_url']}'><b>{item['name']}</b></a>\n\n"
            f"📌 {', '.join(details)}\n"
            f"💰 {salary_html} | 🗓 {pub_date}"
        )
        
        send_telegram(msg)
        mark_as_sent(vac_id, category=cat_emoji)
        logging.info(f"✅ Recruiter Found: {title} [ID: {vac_id}]")
        processed_count += 1
        time.sleep(0.5)
    return processed_count

def get_smart_sleep_time():
    now = datetime.utcnow() + timedelta(hours=3)
    if now.hour >= 23 or now.hour < 9:
         # Ночью спим подольше
         return 3600, now + timedelta(hours=1)
    else:
         # Днем работаем активно (раз в 15-30 мин)
         minutes_wait = random.randint(15, 30)
         return minutes_wait * 60, now + timedelta(minutes=minutes_wait)

def main_loop():
    init_db()
    init_updates()
    logging.info("🚀 Recruiter Bot v1.0 Started")
    send_telegram("🟢 <b>Recruiter-мониторинг запущен</b>")
    set_status("🚀 Запуск системы...")
    
    while True:
        try:
            check_remote_stop()
            logging.info("=== Старт проверки (Recruiter) ===")
            set_status("🚀 Начинаю новый цикл...")
            
            rules = PROFILES['Recruiter']
            for q in rules["keywords"]:
                set_status(f"🔎 Ищу: {q}")
                check_remote_stop()
                items = fetch_hh_paginated(q, period=3)
                if items:
                    process_items(items, rules)
            
            now = datetime.utcnow() + timedelta(hours=3)
            seconds, next_run = get_smart_sleep_time()
            
            stats = get_daily_stats()
            total_today = sum(stats.values())
            
            if now.hour == 23 and now.minute < 30: # Отчет раз в сутки
                msg = (
                    f"🌙 <b>Итоги дня (Recruiter):</b>\n"
                    f"🔹 Найдено: {total_today}"
                )
                send_telegram(msg)
            
            logging.info(f"💤 Спим до {next_run.strftime('%H:%M')}")
            set_status(f"💤 Сплю до {next_run.strftime('%H:%M')}. За сегодня: {total_today}")
            
            while seconds > 0:
                check_remote_stop()
                sleep_chunk = min(seconds, 10)
                time.sleep(sleep_chunk)
                seconds -= sleep_chunk
        
        except Exception as e:
            logging.error(f"CRITICAL ERROR in main loop: {e}")
            send_telegram(f"⚠️ Ошибка Recruiter: {e}")
            time.sleep(60)

if __name__ == "__main__":
    try:
        main_loop()
    except KeyboardInterrupt:
        pass