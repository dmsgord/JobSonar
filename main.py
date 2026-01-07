import time
import requests
import random
from datetime import datetime
from config import TG_TOKEN, TG_CHAT_ID, PROFILES, TARGET_AREAS, MIN_SALARY, CHECK_INTERVAL, SEARCH_PERIOD
from db import init_db, is_sent, mark_as_sent

try:
    from whitelist import APPROVED_COMPANIES
except ImportError:
    print("❌ ОШИБКА: Нет файла whitelist.py! Запусти сначала filter_100.py")
    exit()

ALL_IDS = list(APPROVED_COMPANIES.keys())

def chunked(iterable, n):
    for i in range(0, len(iterable), n):
        yield iterable[i:i + n]

def send_telegram(text):
    try:
        requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", 
                      json={"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
                      timeout=10)
    except Exception as e:
        print(f"⚠️ Ошибка ТГ: {e}")

def format_date(date_str):
    try:
        dt = datetime.strptime(date_str.split('T')[0], "%Y-%m-%d")
        return dt.strftime("%d.%m")
    except: return "?"

def fetch_hh_by_employers(text, employer_ids, area=None, schedule=None):
    params = {
        "text": text, 
        "order_by": "publication_time", 
        "per_page": 100, 
        "search_field": "name",
        "employer_id": employer_ids,
        "period": SEARCH_PERIOD
    }
    if area: params["area"] = area
    if schedule: params["schedule"] = schedule

    try:
        headers = {'User-Agent': 'JobSonarBot/1.0'}
        resp = requests.get("https://api.hh.ru/vacancies", params=params, headers=headers, timeout=10)
        return resp.json().get("items", [])
    except: return []

def run_cycle():
    print(f"\n☕ --- НОВЫЙ КРУГ ПОИСКА ---")
    
    CHUNK_SIZE = 20
    employer_chunks = list(chunked(ALL_IDS, CHUNK_SIZE))
    total_found = 0
    
    for role, rules in PROFILES.items():
        for q in rules["keywords"]:
            print(f"🔎 Ключ: '{q}'...")
            
            for batch_ids in employer_chunks:
                
                # Лог в консоль
                batch_names = [APPROVED_COMPANIES.get(i, {}).get('name', 'ID'+i) for i in batch_ids]
                names_str = ", ".join(batch_names[:2])
                left = len(batch_ids) - 2
                suffix = f" и еще {left}" if left > 0 else ""
                print(f"   🏢 Проверяю: {names_str}{suffix}...")

                time.sleep(random.uniform(1.0, 3.0))

                items = []
                items.extend(fetch_hh_by_employers(q, batch_ids, schedule="remote"))
                items.extend(fetch_hh_by_employers(q, batch_ids, area=TARGET_AREAS))
                
                if not items: continue

                unique_items = {v['id']: v for v in items}.values()
                
                for item in unique_items:
                    vac_id = item['id']
                    if is_sent(vac_id): continue

                    title = item['name'].lower()

                    # Стоп-слова
                    if any(w in title for w in rules["stop_words"]): continue

                    # Must Have
                    must_have_list = rules.get('must_have', [])
                    if must_have_list and not any(w in title for w in must_have_list):
                        continue

                    # ЗП
                    sal = item.get('salary')
                    salary_text = "ЗП не указана"
                    if sal and sal['from']:
                        if sal['currency'] == 'RUR' and sal['from'] < MIN_SALARY:
                            continue
                        salary_text = f"от {sal['from']} {sal.get('currency','₽')}"

                    emp = item.get('employer', {})
                    emp_id = str(emp.get('id', ''))
                    cat_name = APPROVED_COMPANIES.get(emp_id, {}).get('cat', 'Топ')
                    pub_date = format_date(item.get('published_at', ''))
                    
                    # --- 🔥 НОВЫЕ ПОЛЯ ИЗ ЗАПРОСА ---
                    # 1. Опыт работы (1–3 года, 3–6 лет и т.д.)
                    exp_name = item.get('experience', {}).get('name', 'Не указано')
                    
                    # 2. Тип занятости (Полная занятость, Частичная...)
                    employment_name = item.get('employment', {}).get('name', 'Не указано')
                    
                    # 3. График (Полный день, Удаленная работа, Гибкий график)
                    schedule_name = item.get('schedule', {}).get('name', 'Не указано')
                    
                    # Формируем иконку для заголовка
                    sched_id = item.get('schedule', {}).get('id')
                    city = item.get('area', {}).get('name', 'Город?')
                    
                    if sched_id == 'remote':
                        header_tag = "🌍 УДАЛЕНКА"
                    elif sched_id == 'flexible':
                        header_tag = f"⚡ ГИБРИД ({city})"
                    else:
                        header_tag = f"🏢 ОФИС ({city})"
                    # -------------------------------------

                    msg = (
                        f"🔔 <b>{role}</b> | {header_tag}\n\n"
                        f"🏢 <b>{emp.get('name')}</b>\n"
                        f"🏆 {cat_name}\n\n"
                        f"💼 <a href='{item['alternate_url']}'><b>{item['name']}</b></a>\n"
                        f"🎓 Опыт: <b>{exp_name}</b>\n"
                        f"📌 {employment_name}, {schedule_name}\n"
                        f"💰 {salary_text}\n"
                        f"📅 {pub_date}"
                    )
                    
                    send_telegram(msg)
                    mark_as_sent(vac_id)
                    print(f"✅ НАЙДЕНО: {item['name']}")
                    total_found += 1
                    time.sleep(1)

    print(f"🏁 Круг завершен. Новых: {total_found}")

if __name__ == "__main__":
    init_db()
    send_telegram(f"🟢 JobSonar: Добавлен вывод опыта и графика.")
    while True:
        try:
            run_cycle()
        except Exception as e:
            print(f"🔥 Ошибка: {e}")
        print(f"💤 Отдыхаю {CHECK_INTERVAL} сек...")
        time.sleep(CHECK_INTERVAL)