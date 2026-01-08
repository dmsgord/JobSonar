import time
import requests
import re
import sys
from datetime import datetime
from config_analyst import TG_TOKEN, TG_CHAT_ID, PROFILES, TARGET_AREAS, MIN_SALARY, CHECK_INTERVAL, SEARCH_PERIOD, BLACKLISTED_AREAS
from db import init_db, is_sent, mark_as_sent

try:
    from whitelist import APPROVED_COMPANIES
except ImportError:
    print("❌ ОШИБКА: Файл whitelist.py не найден!")
    exit()

ALL_IDS = list(APPROVED_COMPANIES.keys())
session = requests.Session()
session.headers.update({'User-Agent': 'JobSonarBot_Analyst/1.1'})

BOT_ID = TG_TOKEN.split(':')[0]
LAST_UPDATE_ID = 0

def send_telegram(text):
    try:
        requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", 
                      json={"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
                      timeout=10)
    except Exception as e:
        print(f"⚠️ Ошибка ТГ: {e}")

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
        params = {"limit": 10, "offset": LAST_UPDATE_ID + 1}
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
                        send_telegram("🛑 <b>Аналитик-бот остановлен.</b>")
                        sys.exit()
    except: pass

def smart_contains(text, word):
    word = word.lower()
    text = text.lower()
    if bool(re.search('[а-яА-Я]', word)): 
        return word in text
    pattern = r'\b' + re.escape(word) + r'\b'
    return re.search(pattern, text) is not None

def extract_skills(item, target_skills):
    found = set()
    # Ищем в названии И в описании
    search_text = (item.get('name', '') + ' ' + (item.get('snippet', {}).get('requirement', '') or '')).lower()
    
    for skill in target_skills:
        if smart_contains(search_text, skill):
            if skill in ['sql', 'etl', 'dwh', 'bi', 'api', 'rest', 'soap', 'uml', 'bpmn']:
                found.add(skill.upper())
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
            time.sleep(0.1)
        except: break
    return all_items

def process_items(items, role, rules, is_global=False):
    processed_count = 0
    for item in {v['id']: v for v in items}.values():
        vac_id = item['id']
        title = item['name']
        title_lower = title.lower()

        if is_sent(vac_id): continue
        if any(stop_w in title_lower for stop_w in rules["stop_words"]): continue

        # 🚫 ФИЛЬТР ГЕО (Убираем КЗ и прочих)
        area_id = item.get('area', {}).get('id', '0')
        area_name = item.get('area', {}).get('name', '').lower()
        if area_id in BLACKLISTED_AREAS or 'казахстан' in area_name or 'kazakhstan' in area_name:
            continue
        
        # 🛠 ПОИСК НАВЫКОВ
        found_skills = extract_skills(item, rules['target_skills'])
        
        # 🔥 ЖЕСТКИЙ ФИЛЬТР: Минимум 2 навыка из списка!
        # Одинокий "API" больше не пройдет.
        if len(found_skills) < 2:
            continue

        sal = item.get('salary')
        salary_text = "ЗП не указана"
        threshold = MIN_SALARY
        
        if sal and sal['from']:
            if sal['currency'] == 'RUR' and sal['from'] < threshold:
                continue
            salary_text = f"от {sal['from']} {sal.get('currency','₽')}"
        elif is_global: 
            # В глобале без ЗП берем только если ОЧЕНЬ много навыков (>=3)
            # Если 2 навыка и нет ЗП в глобале - скипаем (чтобы мусор не лез)
            if len(found_skills) < 3:
                continue

        emp = item.get('employer', {})
        cat_raw = APPROVED_COMPANIES.get(str(emp.get('id', '')), {}).get('cat', 'Global')
        cat_pretty = cat_raw.title() if cat_raw.isupper() else cat_raw
        
        details = [wf['name'] for wf in item.get('work_format', [])]
        if item.get('schedule', {}).get('name') not in details:
            details.append(item.get('schedule', {}).get('name'))
        
        dt = item.get('published_at', '').split('T')[0]
        pub_date = f"{dt.split('-')[2]}.{dt.split('-')[1]}"

        # Сортировка навыков (SQL, Jira, BPMN...)
        skills_str = ", ".join(sorted(found_skills))

        msg = (
            f"📊 <b>{title}</b>\n"
            f"🏢 {emp.get('name')} ({cat_pretty})\n"
            f"🛠 <b>{skills_str}</b>\n"
            f"📌 {', '.join(details)}\n"
            f"💰 {salary_text} | 📅 {pub_date}\n"
            f"🔗 <a href='{item['alternate_url']}'>Смотреть вакансию</a>"
        )
        
        send_telegram(msg)
        mark_as_sent(vac_id)
        print(f"   ✅ НАЙДЕНО: {title} ({skills_str})")
        processed_count += 1
        time.sleep(0.5)
        
    return processed_count

def main_loop():
    init_db()
    init_updates()
    print("🚀 Analyst Bot Started...")
    send_telegram("🧐 <b>Аналитик-бот запущен.</b>\nФильтр: мин. 2 навыка, без 'Системный аналитик'.")
    
    while True:
        check_remote_stop()
        print(f"\n[{datetime.now().strftime('%H:%M')}] === НОВЫЙ ЦИКЛ (ANALYST) ===")
        
        # 1. WHITELIST
        total_white = 0
        for role, rules in PROFILES.items():
            for q in rules["keywords"]:
                for batch_ids in [ALL_IDS[i:i + 20] for i in range(0, len(ALL_IDS), 20)]:
                    check_remote_stop()
                    print(f"🔎 Whitelist: {q: <30}", end='\r')
                    items = []
                    items.extend(fetch_hh_paginated(q, employer_ids=batch_ids)) 
                    total_white += process_items(items, role, rules)

        # 2. GLOBAL (Удаленка > 200к)
        print(f"\n📊 Whitelist: +{total_white}. Global search...")
        total_global = 0
        for role, rules in PROFILES.items():
            for q in rules["keywords"]:
                check_remote_stop()
                print(f"🔎 Global: {q: <30}", end='\r')
                items = fetch_hh_paginated(q, employer_ids=None, schedule="remote", period=7)
                total_global += process_items(items, role, rules, is_global=True)
        
        send_telegram(f"🏁 <b>Цикл завершен</b>\n🔹 WL: +{total_white}\n🔹 Global: +{total_global}")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    try:
        main_loop()
    except KeyboardInterrupt:
        print("\n⛔ Stop.")