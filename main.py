import time
import requests
import re
import sys
import signal
import logging
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
            logging.info(f"Игнорируем сообщения до ID: {LAST_UPDATE_ID}")
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

def smart_contains(title, word):
    word = word.lower()
    title = title.lower()
    if bool(re.search('[а-яА-Я]', word)) or len(word) > 3:
        return word in title
    pattern = r'\b' + re.escape(word) + r'\b'
    return re.search(pattern, title) is not None

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
            time.sleep(0.3)
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

        # --- ФИЛЬТР: Исключаем "Нет опыта" ---
        exp = item.get('experience', {})
        if exp.get('id') == 'noExperience': continue

        has_hr = any(smart_contains(title, w) for w in rules["must_have_hr"])
        has_role = any(smart_contains(title, w) for w in rules["must_have_role"])
        is_direct = any(smart_contains(title, x) for x in ['hrd', 'hrbp'])
        
        if not (is_direct or (has_hr and has_role)): continue

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

        fire_marker = ""
        if is_whitelist and is_remote_explicit and not has_office_marker:
            if salary_value > 250000:
                if cat_emoji == '🏆':
                    fire_marker = "🔥🔥🔥 "
                else:
                    fire_marker = "🔥🔥 "
            else:
                fire_marker = "🔥 "

        salary_html = f"<b>{salary_text}</b>" if is_bold_salary else salary_text

        # ФОРМАТ v4.26: Без ID, без эмодзи перед названием, опыт есть
        msg = (
            f"{fire_marker}{cat_emoji} <b>{emp.get('name')}</b>\n\n"
            f"<a href='{item['alternate_url']}'><b>{item['name']}</b></a>\n\n"
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

def get_daily_slots(date_obj):
    is_weekend = date_obj.weekday() >= 5
    slots = []
    if is_weekend:
        slots.append(date_obj.replace(hour=11, minute=10, second=0, microsecond=0))
        slots.append(date_obj.replace(hour=23, minute=10, second=0, microsecond=0))
    else:
        current = date_obj.replace(hour=7, minute=10, second=0, microsecond=0)
        end_time = date_obj.replace(hour=23, minute=10, second=0, microsecond=0)
        while current <= end_time:
            slots.append(current)
            if current.hour < 10: step = 60
            elif 10 <= current.hour < 20: step = 40
            else: step = 60
            current += timedelta(minutes=step)
    return slots

def get_wait_time():
    now = datetime.now()
    slots_today = get_daily_slots(now)
    for slot in slots_today:
        if slot > now: return (slot - now).total_seconds(), slot
    tomorrow = now + timedelta(days=1)
    slots_tomorrow = get_daily_slots(tomorrow)
    return (slots_tomorrow[0] - now).total_seconds(), slots_tomorrow[0]

def main_loop():
    init_db()
    init_updates()
    logging.info("🚀 HR Bot v4.26 Started")
    send_telegram("🟢 <b>HR-мониторинг запущен (v4.26)</b>")
    
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

        seconds, next_run = get_wait_time()
        logging.info(f"💤 Спим {int(seconds)} сек. до {next_run.strftime('%H:%M %d.%m')}")
        
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