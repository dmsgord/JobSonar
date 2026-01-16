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
LOG_FILE = os.path.join(BASE_DIR, "log_sales.txt")
STATUS_FILE = os.path.join(BASE_DIR, "status_sales.txt")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

from config_sales import TG_TOKEN, TG_CHAT_ID, PROFILES, MIN_SALARY, SEARCH_PERIOD, BLACKLISTED_AREAS, USER_AGENT, DB_NAME
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
    send_telegram("🛑 <b>Sales-мониторинг остановлен</b>")
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
                        send_telegram("🛑 <b>Sales-бот остановлен</b>")
                        sys.exit(0)
    except: pass

def smart_contains(text, word):
    word_lower = word.lower()
    text_lower = text.lower()
    if len(word_lower) <= 3 and word_lower.isascii():
        return re.search(r'\b' + re.escape(word_lower) + r'\b', text_lower) is not None
    return word_lower in text_lower

def is_individual_person(emp_name):
    name_lower = emp_name.lower().strip()
    
    if 'ип ' in name_lower or ' ип' in name_lower or '(ип' in name_lower:
        return True

    if '.' in name_lower: return True 
    parts = re.split(r'[\s-]+', name_lower)
    for part in parts:
        if part.endswith('вич') or part.endswith('вна'): return True
        if part.endswith('оглы') or part.endswith('кызы'): return True
    if len(parts) == 1:
        surname_endings = ('ов', 'ова', 'ев', 'ева', 'ин', 'ина', 'ский', 'ская', 'ая', 'ый')
        if name_lower.endswith(surname_endings):
            safe_singles = ['снаб', 'торг', 'пром', 'строй', 'групп', 'group', 'софт', 'soft']
            if not any(s in name_lower for s in safe_singles):
                 return True
    corp_whitelist = [
        'ооо', 'ао', 'пао', 'зао', 'llc', 'ltd', 'inc', 'gmbh',
        'групп', 'group', 'холдинг', 'holding',
        'софт', 'soft', 'tech', 'тех', 'lab', 'лаб', 'it', 'ит',
        'studio', 'студия', 'agency', 'агентство', 'бюро', 'центр', 'center',
        'school', 'школа', 'academy', 'академия', 'университет', 'институт',
        'сервис', 'service', 'систем', 'system', 'solution', 'решени',
        'digital', 'диджитал', 'media', 'медиа', 'marketing', 'маркетинг',
        'team', 'команда', 'company', 'компания', 'партнер', 'partner',
        'завод', 'фабрика', 'банк', 'bank', 'shop', 'магазин',
        'consult', 'консалт', 'invest', 'инвест', 'trade', 'трейд',
        'network', 'сеть', 'mobile', 'мобайл', 'dev', 'web', 'веб',
        'club', 'клуб', 'platform', 'платформ', 'pro', 'про',
        'онлайн', 'online', 'business', 'бизнес'
    ]
    if any(marker in name_lower for marker in corp_whitelist):
        return False
    if 2 <= len(parts) <= 4:
        if bool(re.search('[а-я]', name_lower)):
            return True
    return False

def check_domain_relevance(item, markers, stop_domains):
    snippet = item.get('snippet', {}) or {}
    req = snippet.get('requirement') or ''
    resp = snippet.get('responsibility') or ''
    full_text = (item.get('name', '') + ' ' + req + ' ' + resp).lower()
    
    for stop in stop_domains:
        if smart_contains(full_text, stop):
            return False 
            
    has_digital = False
    for marker in markers:
        if smart_contains(full_text, marker):
            has_digital = True
            break
            
    return has_digital

def fetch_hh_paginated(text, schedule=None, period=SEARCH_PERIOD):
    all_items = []
    page = 0
    params = {"text": text, "order_by": "publication_time", "per_page": 100, "search_field": "name", "period": period}
    if schedule: params["schedule"] = schedule

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

def process_items(items, role, rules, is_global=False):
    processed_count = 0
    unique_items = {v['id']: v for v in items}.values()
    
    spam_deduplication_cache = set()

    # 🔥 ДАТА ОТСЕЧЕНИЯ
    cutoff_date = "2026-01-16"

    for item in unique_items:
        vac_id = item['id']
        title = item['name']
        title_lower = title.lower()
        pub_date_raw = item.get('published_at', '').split('T')[0]

        if is_sent(vac_id): continue
        if any(stop_w in title_lower for stop_w in rules["stop_words_title"]): continue

        # --- ТИХИЙ РЕЖИМ ---
        if pub_date_raw < cutoff_date:
            emp = item.get('employer', {})
            emp_id = str(emp.get('id', ''))
            cat_raw = APPROVED_COMPANIES.get(emp_id, {}).get('cat', 'Остальные')
            cat_emoji = get_clean_category(cat_raw)
            mark_as_sent(vac_id, category=cat_emoji)
            continue 
        # -------------------

        emp = item.get('employer', {})
        emp_name = emp.get('name', '')
        emp_id = str(emp.get('id', ''))
        
        spam_signature = f"{emp_id}_{title_lower}"
        if spam_signature in spam_deduplication_cache:
            mark_as_sent(vac_id, category='Остальные')
            logging.info(f"♻️ Спам-фильтр: Скрыт дубль {title} (ID: {vac_id})")
            continue
        else:
            spam_deduplication_cache.add(spam_signature)

        if is_individual_person(emp_name):
            continue

        details = []
        raw_schedule = item.get('schedule', {})
        raw_formats = item.get('work_format', [])
        
        if raw_schedule:
             if raw_schedule.get('name') not in [f['name'] for f in raw_formats]:
                 details.append(raw_schedule.get('name'))
        for f in raw_formats:
            details.append(f['name'])

        details_text = ", ".join(details).lower()
        stop_location_markers = ['гибрид', 'hybrid', 'офис', 'office', 'на месте', 'месте', 'территори', 'разъезд', 'travel']
        
        has_office_marker = any(x in details_text for x in stop_location_markers)
        is_remote_explicit = 'удален' in details_text or 'remote' in details_text

        if not (is_remote_explicit and not has_office_marker):
            continue
            
        if not check_domain_relevance(item, rules['digital_markers'], rules['stop_domains']):
            continue

        sal = item.get('salary')
        salary_text = "-"
        is_bold_salary = False
        threshold = MIN_SALARY
        salary_value = 0
        
        if sal and sal['from']:
            if sal['currency'] not in ['RUR', 'USD', 'EUR']:
                continue

            if sal['currency'] == 'RUR':
                 if sal['from'] < threshold:
                     continue 
                 salary_text = f"от {sal['from']} {sal.get('currency','₽')}"
                 is_bold_salary = True
                 salary_value = sal['from']
            else:
                 salary_text = f"от {sal['from']} {sal.get('currency')}"
                 is_bold_salary = True
                 salary_value = 999999 
        
        cat_raw = APPROVED_COMPANIES.get(emp_id, {}).get('cat', 'Остальные')
        cat_emoji = get_clean_category(cat_raw)
        
        is_whitelist = emp_id in APPROVED_COMPANIES
        
        dt = item.get('published_at', '').split('T')[0]
        pub_date = f"{dt.split('-')[2]}.{dt.split('-')[1]}"
        
        fire_marker = "🤝 " 
        if is_whitelist and salary_value >= threshold:
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
        logging.info(f"✅ Found Sales: {title} [ID: {vac_id}]")
        processed_count += 1
        time.sleep(0.5)
    return processed_count

def get_smart_sleep_time():
    now = datetime.utcnow() + timedelta(hours=3)
    
    if now.weekday() >= 5: 
        if now.hour < 11:
             target = now.replace(hour=11, minute=0, second=0) + timedelta(minutes=random.randint(0, 30))
        elif now.hour < 23:
             minutes_wait = 45 + random.randint(-5, 15)
             target = now + timedelta(minutes=minutes_wait)
        else:
             target = (now + timedelta(days=1)).replace(hour=11, minute=0, second=0) + timedelta(minutes=random.randint(0, 30))
    else: 
        if now.hour >= 23 or now.hour < 7:
             base_date = now if now.hour < 7 else now + timedelta(days=1)
             target = base_date.replace(hour=7, minute=10, second=0) + timedelta(minutes=random.randint(0, 20))
        elif 7 <= now.hour < 10:
             minutes_wait = 20 + random.randint(0, 10)
             target = now + timedelta(minutes=minutes_wait)
        elif 10 <= now.hour < 20:
             minutes_wait = 10 + random.randint(0, 5)
             target = now + timedelta(minutes=minutes_wait)
        else:
             minutes_wait = 20 + random.randint(0, 10)
             target = now + timedelta(minutes=minutes_wait)

    if target <= now:
        target = now + timedelta(minutes=5)
    return max(10, (target - now).total_seconds()), target

def main_loop():
    init_db()
    init_updates()
    logging.info("🚀 Sales Bot v5.3 (Production Ready) Started")
    send_telegram("🟢 <b>Sales-мониторинг запущен (MSK)</b>")
    set_status("🚀 Запуск системы...")
    
    while True:
        try:
            check_remote_stop()
            logging.info("=== Старт проверки (Sales) ===")
            set_status("🚀 Начинаю новый цикл...")
            
            for role, rules in PROFILES.items():
                for q in rules["keywords"]:
                    set_status(f"🔎 Ищу: {q}")
                    check_remote_stop()
                    items = fetch_hh_paginated(q, schedule="remote", period=7)
                    if items:
                        logging.info(f"🔎 Checking '{q}'")
                        process_items(items, role, rules, is_global=True)
            
            now = datetime.utcnow() + timedelta(hours=3)
            seconds, next_run = get_smart_sleep_time()
            
            stats = get_daily_stats()
            total_today = sum(stats.values())
            
            if now.hour >= 23:
                msg = (
                    f"🌙 <b>Итоги дня (Sales):</b>\n"
                    f"🔹 Топ компании: +{stats['Топ компании']}\n"
                    f"🔹 Остальные: +{stats['Остальные']}"
                )
                send_telegram(msg)
            
            logging.info(f"💤 Спим до {next_run.strftime('%H:%M %d.%m')}")
            set_status(f"💤 Сплю до {next_run.strftime('%H:%M')}. За сегодня: {total_today}")
            
            while seconds > 0:
                check_remote_stop()
                sleep_chunk = min(seconds, 10)
                time.sleep(sleep_chunk)
                seconds -= sleep_chunk
        
        except Exception as e:
            logging.error(f"CRITICAL ERROR in main loop: {e}")
            send_telegram(f"⚠️ <b>Ошибка в Sales боте:</b> {e}. Перезапуск через 1 мин.")
            time.sleep(60)

if __name__ == "__main__":
    try:
        main_loop()
    except KeyboardInterrupt:
        pass