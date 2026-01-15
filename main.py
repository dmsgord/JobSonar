import time
import requests
import re
import sys
import signal
import logging
import random
from datetime import datetime, timedelta

from config import TG_TOKEN, TG_CHAT_ID, PROFILES, TARGET_AREAS, MIN_SALARY, SEARCH_PERIOD, USER_AGENT, DB_NAME
from db import init_db, is_sent, mark_as_sent, set_db_name

try:
    from whitelist import APPROVED_COMPANIES
except ImportError:
    print("❌ ОШИБКА: Файл whitelist.py не найден! Проверьте кодировку UTF-8.")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

ALL_IDS = list(APPROVED_COMPANIES.keys())
session = requests.Session()
session.headers.update({'User-Agent': USER_AGENT})

set_db_name(DB_NAME)
BOT_ID = TG_TOKEN.split(':')[0] if TG_TOKEN else "0"
LAST_UPDATE_ID = 0

CAT_ALIASES = {
    'ГИГАНТЫ': '🏆',
    'КРУПНЫЕ': '🥇',
    'СРЕДНИЕ': '🥈',
    'НЕБОЛЬШИЕ': '🥉',
    'ОСТАЛЬНЫЕ': '🌐'
}

# --- СПИСОК HR-ХАРДОВ (ИНСТРУМЕНТЫ, ЗАКОНЫ, МЕТОДИКИ) ---
HR_HARD_SKILLS = [
    # Софт и системы
    '1с', '1c', 'зуп', 'zup', 'sap', 'bitrix', 'битрикс', 'amo', 'amocrm',
    'excel', 'эксель', 'vlookup', 'впр', 'сводные таблицы',
    'jira', 'confluence', 'slack', 'miro', 'notion',
    
    # ATS и Job-сайты (как инструменты)
    'e-staff', 'estaff', 'potok', 'поток', 'huntflow', 'хантфлоу',
    'sfl', 'сберподбор', 'hurma', 'bamboo', 'greenhouse',
    'hh.ru', 'linkedin', 'линкедин', 'avito', 'авито',
    
    # Харды и законодательство
    'тк рф', 'трудовое право', 'кдп', 'кадровое делопроизводство',
    'воинский учет', 'охрана труда', 'соут',
    'консультант', 'гарант',
    
    # Методики и метрики
    'kpi', 'okr', 'ipr', 'ипр', 'grades', 'грейды',
    'фот', 'бюджетирование', 'budgeting', 'c&b',
    'exit interview', 'onboarding', 'adaptation', 'адаптация',
    'performance review', 'оценка персонала', '360',
    'сорсинг', 'sourcing', 'boolean', 'x-ray',
    
    # Языки
    'english', 'английский', 'upper-intermediate', 'advanced'
]

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
    word = word.lower()
    text = text.lower()
    if bool(re.search('[а-яА-Я]', word)) or len(word) > 3:
        return word in text
    pattern = r'\b' + re.escape(word) + r'\b'
    return re.search(pattern, text) is not None

def extract_skills(item, target_skills):
    """Вытаскивает только хард-скиллы из текста вакансии"""
    found = set()
    # Ищем и в названии, и в требованиях
    search_text = (item.get('name', '') + ' ' + (item.get('snippet', {}).get('requirement', '') or '')).lower()
    
    for skill in target_skills:
        if smart_contains(search_text, skill):
            # Красивое форматирование для известных аббревиатур
            if skill in ['1с', '1c', 'зуп', 'zup', 'sap', 'kpi', 'okr', 'sql', 'hh.ru', 'кдп', 'тк рф']:
                found.add(skill.upper().replace('ТК РФ', 'ТК РФ').replace('КДП', 'КДП'))
            else:
                found.add(skill.title())
    return list(found)

def fetch_hh_paginated(text, employer_ids=None, area=None, schedule=None, period=SEARCH_PERIOD):
    all_items = []
    page = 0
    params = {"text": text, "order_by": "publication_time", "per_page": 100, "search_field": "name", "period": period}
    if employer_ids: params["employer_id"] = employer_ids
    if area: params["area"] = area
    if schedule: params["schedule"] = schedule

    while page < 20:
        params["page"] = page
        try:
            resp = session.get("https://api.hh.ru/vacancies", params=params, timeout=10)
            data = resp.json()
            items = data.get("items", [])
            if not items: break
            all_items.extend(items)
            if page >= data.get('pages', 0) - 1: break
            page += 1
            time.sleep(random.uniform(0.5, 1.5))
        except Exception as e:
            logging.error(f"Ошибка API HH: {e}")
            break
    return all_items

def get_clean_category(cat_raw):
    clean = re.sub(r'[^\w\s]', '', cat_raw).strip().upper()
    return CAT_ALIASES.get(clean, '🌐')

def process_items(items, role, rules, is_global=False):
    processed_count = 0
    unique_items = {v['id']: v for v in items}.values()

    for item in unique_items:
        vac_id = item['id']
        title = item['name']
        title_lower = title.lower()

        if is_sent(vac_id): continue
        if any(stop_w in title_lower for stop_w in rules["stop_words"]): continue

        exp = item.get('experience', {})
        if exp.get('id') == 'noExperience': continue

        # --- 1. АНАЛИЗ ГРАФИКА И РЕГИОНА ---
        details = []
        raw_schedule = item.get('schedule', {})
        raw_formats = item.get('work_format', [])
        
        if raw_schedule:
             if raw_schedule.get('name') not in [f['name'] for f in raw_formats]:
                 details.append(raw_schedule.get('name'))
        for f in raw_formats:
            details.append(f['name'])

        details_text = ", ".join(details).lower()
        has_office_marker = any(x in details_text for x in ['гибрид', 'офис', 'на месте', 'office', 'hybrid'])
        is_remote_explicit = 'удален' in details_text or 'remote' in details_text

        is_clean_remote = is_remote_explicit and not has_office_marker

        # ⛔ ГЛОБАЛ ФИЛЬТР: Только чистая удаленка
        if is_global and has_office_marker:
            continue

        # ⛔ ГЕО ФИЛЬТР: Игнорируем регион ТОЛЬКО если это "Чистая удаленка"
        # Для HR черного списка пока нет в явном виде, но логика готова
        
        has_hr = any(smart_contains(title, w) for w in rules["must_have_hr"])
        has_role = any(smart_contains(title, w) for w in rules["must_have_role"])
        is_direct = any(smart_contains(title, x) for x in ['hrd', 'hrbp'])
        
        if not (is_direct or (has_hr and has_role)): continue

        # --- 2. ПОИСК НАВЫКОВ (НОВОЕ) ---
        found_skills = extract_skills(item, HR_HARD_SKILLS)
        skills_str = ", ".join(sorted(found_skills))

        # --- 3. ЗАРПЛАТА ---
        sal = item.get('salary')
        salary_text = "-"
        is_bold_salary = False
        threshold = 250000 if is_global else MIN_SALARY
        salary_value = 0

        if sal and sal['from']:
            if sal['currency'] != 'RUR': continue
            if sal['from'] < threshold: continue
            salary_text = f"от {sal['from']} {sal.get('currency','₽')}"
            is_bold_salary = True
            salary_value = sal['from']
        elif is_global:
            continue

        emp = item.get('employer', {})
        emp_id = str(emp.get('id', ''))
        
        company_data = APPROVED_COMPANIES.get(emp_id, {})
        cat_raw = company_data.get('cat', 'Остальные')
        cat_emoji = get_clean_category(cat_raw)
        
        is_whitelist = emp_id in APPROVED_COMPANIES
        
        dt = item.get('published_at', '').split('T')[0]
        pub_date = f"{dt.split('-')[2]}.{dt.split('-')[1]}"
        
        fire_marker = ""
        if is_whitelist and is_clean_remote:
            if salary_value > 250000:
                if cat_emoji == '🏆':
                    fire_marker = "🔥🔥🔥 "
                else:
                    fire_marker = "🔥🔥 "
            else:
                fire_marker = "🔥 "

        salary_html = f"<b>{salary_text}</b>" if is_bold_salary else salary_text

        # Формируем строку навыков (если нашли)
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
        mark_as_sent(vac_id)
        logging.info(f"✅ Отправлено: {title} [ID: {vac_id}]")
        processed_count += 1
        time.sleep(0.5)
    return processed_count

def get_smart_sleep_time():
    now = datetime.now()
    if now.weekday() >= 5: 
        if now.hour < 11:
             target = now.replace(hour=11, minute=0, second=0) + timedelta(minutes=random.randint(0, 45))
        elif now.hour < 23:
             target = now.replace(hour=23, minute=0, second=0) + timedelta(minutes=random.randint(0, 45))
        else:
             target = (now + timedelta(days=1)).replace(hour=11, minute=0, second=0) + timedelta(minutes=random.randint(0, 45))
    else: 
        if now.hour >= 23 or now.hour < 7:
             base_date = now if now.hour < 7 else now + timedelta(days=1)
             target = base_date.replace(hour=7, minute=10, second=0) + timedelta(minutes=random.randint(0, 30))
        elif 7 <= now.hour < 10:
             minutes_wait = 60 + random.randint(-10, 15)
             target = now + timedelta(minutes=minutes_wait)
        elif 10 <= now.hour < 20:
             minutes_wait = 40 + random.randint(-5, 10)
             target = now + timedelta(minutes=minutes_wait)
        else:
             minutes_wait = 60 + random.randint(-5, 20)
             target = now + timedelta(minutes=minutes_wait)

    if target <= now:
        target = now + timedelta(minutes=5)
        
    seconds_to_sleep = (target - now).total_seconds()
    return max(10, seconds_to_sleep), target

def main_loop():
    init_db()
    init_updates()
    logging.info("🚀 HR Bot v4.34 (Skills + Strict Remote) Started")
    send_telegram("🟢 <b>HR-мониторинг запущен (v4.34 Skills + Remote)</b>")
    
    while True:
        check_remote_stop()
        logging.info("=== Старт проверки ===")
        
        total_white = 0
        for role, rules in PROFILES.items():
            for q in rules["keywords"]:
                for batch_ids in [ALL_IDS[i:i + 20] for i in range(0, len(ALL_IDS), 20)]:
                    check_remote_stop()
                    found_items_map = {} 
                    remote_items = fetch_hh_paginated(q, employer_ids=batch_ids, schedule="remote")
                    for i in remote_items: found_items_map[i['id']] = i
                    area_items = fetch_hh_paginated(q, employer_ids=batch_ids, area=TARGET_AREAS)
                    for i in area_items: found_items_map[i['id']] = i
                    total_white += process_items(list(found_items_map.values()), role, rules)

        logging.info(f"WL: {total_white}. Global...")
        
        total_global = 0
        for role, rules in PROFILES.items():
            for q in rules["keywords"]:
                check_remote_stop()
                items = fetch_hh_paginated(q, employer_ids=None, schedule="remote", period=7)
                total_global += process_items(items, role, rules, is_global=True)
        
        report = (
            f"🏁 Цикл завершен\n"
            f"🔹 Топ компании: +{total_white}\n"
            f"🔹 Остальные: +{total_global}"
        )
        logging.info(f"ИТОГ: WL={total_white}, Other={total_global}")
        
        if (total_white + total_global) > 0:
            send_telegram(report)

        seconds, next_run = get_smart_sleep_time()
        logging.info(f"💤 Спим {int(seconds)} сек. до {next_run.strftime('%H:%M %d.%m')} (Human interval)")
        
        while seconds > 0:
            check_remote_stop() 
            sleep_chunk = min(seconds, 60) 
            time.sleep(sleep_chunk)
            seconds -= sleep_chunk

if __name__ == "__main__":
    try:
        main_loop()
    except KeyboardInterrupt:
        pass