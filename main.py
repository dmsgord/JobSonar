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
LOG_FILE = os.path.join(BASE_DIR, "log_hr.txt")
STATUS_FILE = os.path.join(BASE_DIR, "status_hr.txt")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

from config import TG_TOKEN, TG_CHAT_ID, PROFILES, TARGET_AREAS, MIN_SALARY, SEARCH_PERIOD, USER_AGENT, DB_NAME
from db import init_db, is_sent, mark_as_sent, set_db_name, get_daily_stats

try:
    from whitelist import APPROVED_COMPANIES
except ImportError:
    APPROVED_COMPANIES = {}

ALL_IDS = list(APPROVED_COMPANIES.keys())
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

HR_HARD_SKILLS = [
    '1с', '1c', 'зуп', 'zup', 'sap', 'bitrix', 'битрикс', 'kpi', 'okr', 'c&b', 
    'budgeting', 'бюджетирование', 'english', 'английский', 'potok', 'huntflow'
]

FACTORY_STOP_WORDS = [
    'производств', 'цех', 'завод', 'мастер', 'участок', 'линия', 'смен', 
    'двигател', 'машиностроен', 'металлург', 'конструктор', 'технолог', 
    'промышлен', 'оборудован', 'апк', 'агро'
]

def set_status(text):
    try:
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            now = (datetime.utcnow() + timedelta(hours=3)).strftime("%H:%M")
            f.write(f"[{now}] {text}")
    except Exception as e:
        logging.error(f"Error writing status: {e}")

def signal_handler(sig, frame):
    logging.info("🛑 Получен сигнал остановки.")
    send_telegram("🛑 <b>HR-мониторинг остановлен</b>")
    sys.exit(0)

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

def send_telegram(text):
    try:
        requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", 
                      json={"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
                      timeout=10)
    except Exception as e:
        logging.error(f"Ошибка отправки в ТГ: {e}")

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
                    if "стоп" in text or "stop" in text:
                        send_telegram("🛑 <b>HR-мониторинг остановлен командой</b>")
                        sys.exit(0)
    except: pass

def smart_contains(text, word):
    word_lower = word.lower()
    text_lower = text.lower()
    if len(word_lower) <= 3 and word_lower.isascii():
        return re.search(r'\b' + re.escape(word_lower) + r'\b', text_lower) is not None
    return word_lower in text_lower

def extract_skills(item, target_skills):
    found = set()
    search_text = (item.get('name', '') + ' ' + (item.get('snippet', {}).get('requirement', '') or '')).lower()
    for skill in target_skills:
        if smart_contains(search_text, skill):
            found.add(skill.title())
    return list(found)

def get_clean_category(cat_raw):
    clean = re.sub(r'[^\w\s]', '', cat_raw).strip().upper()
    return CAT_ALIASES.get(clean, '🌐')

def fetch_company_vacancies(employer_ids, area=None, schedule=None, period=3):
    all_items = []
    page = 0
    params = {"order_by": "publication_time", "per_page": 100, "period": period}
    
    if employer_ids: params["employer_id"] = employer_ids
    if area: params["area"] = area
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
            time.sleep(0.2)
        except Exception as e:
            logging.error(f"HH API Error: {e}")
            break
    return all_items

def fetch_hh_paginated_global(text, period=7):
    all_items = []
    page = 0
    # 🔥 УБРАЛИ schedule='remote', чтобы ловить скрытую удаленку
    params = {"text": text, "order_by": "publication_time", "per_page": 100, "search_field": "name", "period": period}
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
        except: break
    return all_items

def filter_and_process(items, rules, is_global=False):
    unique_items = {v['id']: v for v in items}.values()

    for item in unique_items:
        vac_id = item['id']
        title = item['name']
        title_lower = title.lower()
        
        if is_sent(vac_id): continue

        if any(stop_w in title_lower for stop_w in rules["stop_words"]): continue
        if any(stop_w in title_lower for stop_w in FACTORY_STOP_WORDS): continue

        extended_hr_keywords = rules["must_have_hr"] + ['talent', 'people', 'acquisition', 'human']
        extended_role_keywords = rules["must_have_role"] + ['partner', 'lead', 'head']

        has_hr = any(smart_contains(title, w) for w in extended_hr_keywords)
        has_role = any(smart_contains(title, w) for w in extended_role_keywords)
        is_direct = any(smart_contains(title, x) for x in ['hrd', 'hrbp', 'hr director', 'hr-директор'])
        
        if not (is_direct or (has_hr and has_role)): continue

        exp = item.get('experience', {})
        if exp.get('id') == 'noExperience': continue

        # --- АНАЛИЗ ГРАФИКА РАБОТЫ (Детектор скрытой удаленки) ---
        details = []
        raw_schedule = item.get('schedule', {})
        raw_formats = item.get('work_format', [])
        
        if raw_schedule:
             if raw_schedule.get('name') not in [f['name'] for f in raw_formats]:
                 details.append(raw_schedule.get('name'))
        for f in raw_formats:
            details.append(f['name'])

        details_text = ", ".join(details).lower()
        
        # Проверяем текст требований на слова "удаленка" и "гибрид"
        snippet = item.get('snippet', {}) or {}
        req_text = (snippet.get('requirement') or '') + ' ' + (snippet.get('responsibility') or '')
        req_text_lower = req_text.lower()
        
        has_remote_in_text = 'удален' in req_text_lower or 'remote' in req_text_lower or 'гибрид' in req_text_lower
        
        # Стандартные маркеры API
        is_remote_explicit = 'удален' in details_text or 'remote' in details_text
        has_office_marker = any(x in details_text for x in ['офис', 'на месте', 'office']) and not ('гибрид' in details_text)

        # Логика пропуска:
        # Если это Глобал поиск и нет маркеров удаленки (ни в API, ни в тексте) -> Пропускаем
        if is_global:
            if not (is_remote_explicit or has_remote_in_text):
                continue
            # Если написано "Только офис" и в тексте нет про гибрид/удаленку -> Пропускаем
            if has_office_marker and not has_remote_in_text:
                continue

        found_skills = extract_skills(item, HR_HARD_SKILLS)
        skills_str = ", ".join(sorted(found_skills))

        sal = item.get('salary')
        salary_text = "-"
        is_bold_salary = False
        threshold = 250000 if is_global else MIN_SALARY
        salary_value = 0

        if sal and sal.get('from'):
            if sal.get('currency') != 'RUR': continue
            if sal.get('from') < threshold: continue
            salary_text = f"от {sal.get('from')} {sal.get('currency','₽')}"
            is_bold_salary = True
            salary_value = sal.get('from')
        
        # Вакансии без ЗП в глобале теперь проходят (мы убрали блок elif is_global: continue)

        emp = item.get('employer', {})
        emp_id = str(emp.get('id', ''))
        
        cat_raw = APPROVED_COMPANIES.get(emp_id, {}).get('cat', 'Остальные')
        cat_emoji = get_clean_category(cat_raw)
        is_whitelist = emp_id in APPROVED_COMPANIES
        
        dt = item.get('published_at', '').split('T')[0]
        pub_date = f"{dt.split('-')[2]}.{dt.split('-')[1]}"
        
        fire_marker = ""
        # Если нашли скрытую удаленку, ставим огонек
        if has_remote_in_text and not is_remote_explicit:
            fire_marker = "🕵️ " 
        elif is_whitelist:
            if salary_value > 250000:
                fire_marker = "🔥🔥🔥 " if cat_emoji == '🏆' else "🔥🔥 "
            else:
                fire_marker = "🔥 "

        salary_html = f"<b>{salary_text}</b>" if is_bold_salary else salary_text
        skills_block = f"🛠 <b>{skills_str}</b>\n" if skills_str else ""

        msg = (
            f"{fire_marker}{cat_emoji} <b>{emp.get('name')}</b>\n\n"
            f"<a href='{item['alternate_url']}'><b>{item['name']}</b></a>\n\n"
            f"{skills_block}"
            f"📌 {', '.join(details)}\n"
            f"🎓 {exp.get('name')}\n"
            f"💰 {salary_html} | 🗓 {pub_date}"
        )
        
        send_telegram(msg)
        mark_as_sent(vac_id, category=cat_emoji)
        logging.info(f"✅ Отправлено: {title} [ID: {vac_id}]")
        time.sleep(0.5)

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
    if target <= now: target = now + timedelta(minutes=5)
    return max(10, (target - now).total_seconds()), target

def main_loop():
    init_db()
    init_updates()
    logging.info("🚀 HR Bot v5.8 (Generalist & Hidden Remote) Started")
    send_telegram("🟢 <b>HR-мониторинг запущен (Gen & Hidden)</b>")
    set_status("🚀 Запуск системы...")
    
    while True:
        try:
            check_remote_stop()
            logging.info("=== Старт проверки (HR) ===")
            set_status("🚀 Начинаю поиск по компаниям...")
            
            # --- SMART BATCHING ---
            batch_size = 20
            all_ids_list = ALL_IDS
            batches = [all_ids_list[i:i + batch_size] for i in range(0, len(all_ids_list), batch_size)]
            
            for i, batch_ids in enumerate(batches):
                check_remote_stop()
                found_items_map = {}
                
                smart_period = 1 if i < 10 else 5
                
                remote_items = fetch_company_vacancies(batch_ids, schedule="remote", period=smart_period)
                for item in remote_items: found_items_map[item['id']] = item
                
                area_items = fetch_company_vacancies(batch_ids, area=TARGET_AREAS, period=smart_period)
                for item in area_items: found_items_map[item['id']] = item
                
                rules = PROFILES['HR']
                filter_and_process(list(found_items_map.values()), rules)
                time.sleep(1)

            # --- GLOBAL SEARCH ---
            set_status("🔎 Global поиск...")
            for role, rules in PROFILES.items():
                for q in rules["keywords"]:
                    check_remote_stop()
                    # Ищем ВСЁ подряд за 3 дня (без фильтра по удаленке в API)
                    items = fetch_hh_paginated_global(q, period=3) 
                    filter_and_process(items, rules, is_global=True)
            
            now = datetime.utcnow() + timedelta(hours=3)
            seconds, next_run = get_smart_sleep_time()
            
            stats = get_daily_stats()
            total_today = sum(stats.values())
            
            if now.hour >= 23:
                 msg = (
                    f"🌙 <b>Итоги дня (HR):</b>\n"
                    f"🔹 Топ компании: +{stats.get('Топ компании', 0)}\n"
                    f"🔹 Остальные: +{stats.get('Остальные', 0)}"
                )
                 send_telegram(msg)

            logging.info(f"💤 Спим до {next_run.strftime('%H:%M')}")
            set_status(f"💤 Сон до {next_run.strftime('%H:%M')}. За сегодня: {total_today}")
            
            while seconds > 0:
                check_remote_stop() 
                sleep_chunk = min(seconds, 10) 
                time.sleep(sleep_chunk)
                seconds -= sleep_chunk
        
        except Exception as e:
            logging.error(f"CRITICAL ERROR in main loop: {e}")
            send_telegram(f"⚠️ Ошибка HR: {e}")
            time.sleep(60)

if __name__ == "__main__":
    try:
        main_loop()
    except KeyboardInterrupt:
        pass