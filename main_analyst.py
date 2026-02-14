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
LOG_FILE = os.path.join(BASE_DIR, "log_analyst.txt")
STATUS_FILE = os.path.join(BASE_DIR, "status_analyst.txt")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

from config_analyst import TG_TOKEN, TG_CHAT_ID, PROFILES, MIN_SALARY, SEARCH_PERIOD, BLACKLISTED_AREAS, USER_AGENT, DB_NAME, TARGET_AREAS, BANAL_SKILLS
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

def set_status(text):
    try:
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            now = (datetime.utcnow() + timedelta(hours=3)).strftime("%H:%M")
            f.write(f"[{now}] {text}")
    except: pass

def signal_handler(sig, frame):
    logging.info("🛑 Stop signal.")
    sys.exit(0)

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

def send_telegram(text):
    try:
        requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", 
                      json={"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
                      timeout=10)
    except: pass

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
                    if "стоп" in text: sys.exit(0)
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
            if skill in ['sql', 'etl', 'dwh', 'bi', 'api', 'rest', 'json', 'xml', 'bpmn']:
                found.add(skill.upper())
            else:
                found.add(skill.title())
    return list(found)

# Вытягиваем харды из API
def get_vacancy_skills(vac_id):
    try:
        resp = session.get(f"https://api.hh.ru/vacancies/{vac_id}", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            raw_skills = [s['name'] for s in data.get('key_skills', [])]
            clean_skills = [skill for skill in raw_skills if skill.lower() not in BANAL_SKILLS]
            return clean_skills[:5] 
    except:
        pass
    return []

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
        except: break
    return all_items

def fetch_hh_paginated_global(text, period=7):
    all_items = []
    page = 0
    params = {"text": text, "order_by": "publication_time", "per_page": 100, "search_field": "name", "period": period, "schedule": "remote"}
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
    processed = 0

    for item in unique_items:
        vac_id = item['id']
        title = item['name']
        title_lower = title.lower()
        
        if is_sent(vac_id): continue

        is_relevant = False
        for k in rules["keywords"]:
            if smart_contains(title, k):
                is_relevant = True
                break
        if not is_relevant: continue

        if any(stop_w in title_lower for stop_w in rules["stop_words"]): continue

        dev_stop_words = ['разработки', 'development', 'developer', 'разработчик', 'programmer', 'golang', 'java', 'backend', 'frontend']
        if any(w in title_lower for w in dev_stop_words): continue

        details = []
        raw_schedule = item.get('schedule', {})
        raw_formats = item.get('work_format', [])
        if raw_schedule:
             if raw_schedule.get('name') not in [f['name'] for f in raw_formats]:
                 details.append(raw_schedule.get('name'))
        for f in raw_formats: details.append(f['name'])

        details_text = ", ".join(details).lower()
        
        # Маркеры локации
        has_office_marker = any(x in details_text for x in ['гибрид', 'офис', 'на месте', 'office', 'hybrid', 'разъездной'])
        is_remote_explicit = 'удален' in details_text or 'remote' in details_text
        is_clean_remote = is_remote_explicit and not has_office_marker

        area_id = item.get('area', {}).get('id', '0')
        area_name = item.get('area', {}).get('name', '').lower()
        
        # ✅ ПРОВЕРКА НА СИСТЕМНОГО АНАЛИТИКА
        is_system_analyst = 'system analyst' in title_lower or 'системный аналитик' in title_lower or 'системный' in title_lower
        
        if is_system_analyst:
            # Для СА: Строжайшая удаленка, никаких гибридов и офисов!
            if not is_remote_explicit or has_office_marker:
                continue
        else:
            # Для остальных аналитиков
            if is_global and has_office_marker: continue
            if not is_clean_remote:
                if area_id in BLACKLISTED_AREAS or 'казахстан' in area_name or 'kazakhstan' in area_name:
                    continue

        emp = item.get('employer', {})
        emp_id = str(emp.get('id', ''))
        cat_raw = APPROVED_COMPANIES.get(emp_id, {}).get('cat', 'Остальные')
        cat_emoji = get_clean_category(cat_raw)
        is_whitelist = emp_id in APPROVED_COMPANIES

        found_skills = extract_skills(item, rules['target_skills'])
        is_ba_title = 'business analyst' in title_lower or 'бизнес-аналитик' in title_lower or 'бизнес аналитик' in title_lower
        
        # --- 💰 ЛОГИКА ЗАРПЛАТ ---
        sal = item.get('salary')
        salary_text = "-"
        is_bold_salary = False
        threshold = MIN_SALARY
        has_good_salary = False
        
        if sal:
            currency = sal.get('currency')
            if currency == 'RUR':
                lower = sal.get('from')
                upper = sal.get('to')

                if lower and lower >= threshold:
                    salary_text = f"от {lower} ₽"
                    is_bold_salary = True
                    has_good_salary = True
                elif upper and upper >= threshold:
                    salary_text = f"до {upper} ₽"
                    is_bold_salary = True
                    has_good_salary = True
                else:
                    if not has_good_salary: continue
            elif currency: 
                continue
        
        # ✅ СКИЛЛЫ И ФИЛЬТРАЦИЯ СТЕКА
        if not is_system_analyst:
            # Если это обычный аналитик, проверяем хард-скиллы
            min_skills = 1 if is_whitelist else 2
            if not is_ba_title:
                 if len(found_skills) < min_skills: continue
                 
            if not has_good_salary:
                if not is_whitelist:
                    weak_stack = {'Jira', 'Confluence', 'Atlassian', 'Джира', 'Конфлюенс'}
                    if all(skill in weak_stack for skill in found_skills): continue 
        
        # Тянем красивые навыки из API
        real_skills = get_vacancy_skills(vac_id)
        if not real_skills and found_skills:
            real_skills = list(found_skills)[:5]
        skills_str = ", ".join(real_skills)

        dt = item.get('published_at', '').split('T')[0]
        pub_date = f"{dt.split('-')[2]}.{dt.split('-')[1]}"

        fire_marker = ""
        if is_whitelist and is_clean_remote:
             fire_marker = "🔥 "

        salary_html = f"<b>{salary_text}</b>" if is_bold_salary else salary_text

        msg = (
            f"{fire_marker}{cat_emoji} <b>{emp.get('name')}</b>\n\n"
            f"<a href='{item['alternate_url']}'><b>{title}</b></a>\n\n"
            f"🛠 <b>{skills_str}</b>\n"
            f"📌 {', '.join(details)}\n"
            f"💰 {salary_html} | 🗓 {pub_date}"
        )
        
        send_telegram(msg)
        mark_as_sent(vac_id, category=cat_emoji)
        logging.info(f"✅ Analyst Sent: {title}")
        processed += 1
        time.sleep(0.5)
    return processed

def get_smart_sleep_time():
    now = datetime.utcnow() + timedelta(hours=3)
    if now.weekday() == 6 and now.hour >= 20:
        target = (now + timedelta(days=1)).replace(hour=8, minute=0, second=0)
        return (target - now).total_seconds(), target

    if now.weekday() >= 5: 
        if now.hour < 11:
             target = now.replace(hour=11, minute=0, second=0) + timedelta(minutes=random.randint(0, 30))
        elif now.hour < 23:
             minutes_wait = 45 + random.randint(-5, 15)
             target = now + timedelta(minutes=minutes_wait)
        else:
             target = (now + timedelta(days=1)).replace(hour=11, minute=0, second=0)
    else: 
        if now.hour >= 23 or now.hour < 7:
             base_date = now if now.hour < 7 else now + timedelta(days=1)
             target = base_date.replace(hour=7, minute=10, second=0) + timedelta(minutes=random.randint(0, 20))
        else:
             minutes_wait = 20 + random.randint(0, 10)
             target = now + timedelta(minutes=minutes_wait)
             
    if target <= now: target = now + timedelta(minutes=5)
    return max(10, (target - now).total_seconds()), target

def main_loop():
    init_db()
    init_updates()
    logging.info("🚀 Analyst Bot v6.8 (Sys Analyst + Skills) Started")
    send_telegram("🟢 <b>Analyst Bot v6.8 Started</b>")
    
    while True:
        try:
            check_remote_stop()
            set_status("🚀 Поиск...")
            
            batch_size = 20
            batches = [ALL_IDS[i:i + batch_size] for i in range(0, len(ALL_IDS), batch_size)]
            
            for i, batch_ids in enumerate(batches):
                check_remote_stop()
                found_map = {}
                per = 3 if i < 10 else 7 
                
                remote_items = fetch_company_vacancies(batch_ids, schedule="remote", period=per)
                for item in remote_items: found_map[item['id']] = item
                
                area_items = fetch_company_vacancies(batch_ids, area=TARGET_AREAS, period=per)
                for item in area_items: found_map[item['id']] = item
                
                filter_and_process(list(found_map.values()), PROFILES['Analyst'])
                time.sleep(1)

            set_status("🔎 Global поиск...")
            for role, rules in PROFILES.items():
                for q in rules["keywords"]:
                    check_remote_stop()
                    items = fetch_hh_paginated_global(q, period=3) 
                    filter_and_process(items, rules, is_global=True)
            
            now = datetime.utcnow() + timedelta(hours=3)
            seconds, next_run = get_smart_sleep_time()
            stats = get_daily_stats()
            total = sum(stats.values())
            
            if now.hour >= 23:
                 msg = f"🌙 <b>Итоги Analyst:</b>\nТоп компании: {stats.get('Топ компании',0)}\nОстальные: {stats.get('Остальные',0)}"
                 send_telegram(msg)

            set_status(f"💤 Сон до {next_run.strftime('%H:%M')}. За сегодня: {total}")
            
            while seconds > 0:
                check_remote_stop()
                time.sleep(min(seconds, 10))
                seconds -= 10
        
        except Exception as e:
            logging.error(f"Error: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main_loop()