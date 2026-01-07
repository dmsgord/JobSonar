import time
import requests
import random
import re
import sys
from datetime import datetime
from config import TG_TOKEN, TG_CHAT_ID, PROFILES, TARGET_AREAS, MIN_SALARY, CHECK_INTERVAL, SEARCH_PERIOD
from db import init_db, is_sent, mark_as_sent

try:
    from whitelist import APPROVED_COMPANIES
except ImportError:
    print("❌ ОШИБКА: Файл whitelist.py не найден!")
    exit()

ALL_IDS = list(APPROVED_COMPANIES.keys())
session = requests.Session()
session.headers.update({'User-Agent': 'JobSonarBot/3.7'})

def send_telegram(text):
    try:
        requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", 
                      json={"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
                      timeout=10)
    except Exception as e:
        print(f"⚠️ Ошибка ТГ: {e}")

def is_cyrillic(text):
    return bool(re.search('[а-яА-Я]', text))

def smart_contains(title, word):
    word = word.lower()
    title = title.lower()
    if is_cyrillic(word) or len(word) > 3:
        return word in title
    pattern = r'\b' + re.escape(word) + r'\b'
    return re.search(pattern, title) is not None

def fetch_hh_paginated(text, employer_ids=None, area=None, schedule=None, period=SEARCH_PERIOD):
    all_items = []
    page = 0
    params = {"text": text, "order_by": "publication_time", "per_page": 100, "search_field": "name", "period": period, "page": page}
    if employer_ids: params["employer_id"] = employer_ids
    if area: params["area"] = area
    if schedule: params["schedule"] = schedule

    while True:
        try:
            params["page"] = page
            resp = session.get("https://api.hh.ru/vacancies", params=params, timeout=10)
            data = resp.json()
            items = data.get("items", [])
            if not items: break
            all_items.extend(items)
            if page >= data.get('pages', 0) - 1: break
            page += 1
            time.sleep(0.1) 
        except: break
    return all_items

def process_items(items, role, rules, strict_remote=False, strict_salary=False):
    processed_count = 0
    for item in {v['id']: v for v in items}.values():
        vac_id = item['id']
        title = item['name']
        title_lower = title.lower()

        if is_sent(vac_id): continue

        # 1. СТОП-СЛОВА
        if any(stop_w in title_lower for stop_w in rules["stop_words"]): continue

        # 2. УМНЫЙ ДВОЙНОЙ ФИЛЬТР (HR + ROLE)
        has_hr = any(smart_contains(title, w) for w in rules["must_have_hr"])
        has_role = any(smart_contains(title, w) for w in rules["must_have_role"])
        is_direct = any(smart_contains(title, x) for x in ['hrd', 'hrbp'])
        
        if not (is_direct or (has_hr and has_role)): continue

        # 3. ЗАРПЛАТА
        sal = item.get('salary')
        salary_text = "ЗП не указана"
        threshold = 250000 if strict_salary else MIN_SALARY
        if sal and sal['from']:
            if sal['currency'] == 'RUR' and sal['from'] < threshold: continue
            salary_text = f"от {sal['from']} {sal.get('currency','₽')}"

        # 4. ДАННЫЕ (Убираем капс)
        emp = item.get('employer', {})
        company_data = APPROVED_COMPANIES.get(str(emp.get('id', '')), {})
        cat_raw = company_data.get('cat', 'Global')
        cat_pretty = cat_raw.title() if cat_raw.isupper() else cat_raw
        
        dt = item.get('published_at', '').split('T')[0]
        pub_date = f"{dt.split('-')[2]}.{dt.split('-')[1]}"
        
        details = [wf['name'] for wf in item.get('work_format', [])]
        if item.get('schedule', {}).get('name') not in details:
            details.append(item.get('schedule', {}).get('name'))
        details_str = ", ".join(details)
        
        if strict_remote and 'удален' not in details_str.lower(): continue

        # 5. СООБЩЕНИЕ
        msg = (
            f"🏢 <b>{emp.get('name')}</b> ({cat_pretty})\n"
            f"💼 <a href='{item['alternate_url']}'><b>{item['name']}</b></a>\n"
            f"📌 {details_str}\n"
            f"🎓 Опыт: {item.get('experience', {}).get('name')}\n"
            f"💰 <b>{salary_text}</b> | 📅 {pub_date}"
        )
        
        send_telegram(msg)
        mark_as_sent(vac_id)
        print(f"   ✅ {title}")
        processed_count += 1
        time.sleep(0.5)
        
    return processed_count

def main_loop():
    init_db()
    print("🚀 JobSonar v3.7 Started...")
    while True:
        now = datetime.now().strftime('%H:%M')
        print(f"[{now}] Scanning Whitelist...")
        total = 0
        for role, rules in PROFILES.items():
            for q in rules["keywords"]:
                print(f"🔎 Ключ: {q}", end='\r')
                for batch in [ALL_IDS[i:i + 20] for i in range(0, len(ALL_IDS), 20)]:
                    items = []
                    items.extend(fetch_hh_paginated(q, employer_ids=batch, schedule="remote"))
                    items.extend(fetch_hh_paginated(q, employer_ids=batch, area=TARGET_AREAS))
                    total += process_items(items, role, rules)
        
        if total < 10:
            print("\n🔍 Global scan triggered...")
            for role, rules in PROFILES.items():
                for q in rules["keywords"]:
                    items = fetch_hh_paginated(q, employer_ids=None, schedule="remote", period=3)
                    process_items(items, role, rules, strict_remote=True, strict_salary=True)

        print(f"\n⏳ Спим {CHECK_INTERVAL} сек...")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main_loop()