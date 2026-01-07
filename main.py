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
    """Превращает '2023-10-25T14:30:00+0300' в '25.10'"""
    try:
        dt = datetime.strptime(date_str.split('T')[0], "%Y-%m-%d")
        return dt.strftime("%d.%m")
    except:
        return "?"

def fetch_hh_by_employers(text, employer_ids, area=None, schedule=None):
    params = {
        "text": text, 
        "order_by": "publication_time", 
        "per_page": 100, 
        "search_field": "name",
        "employer_id": employer_ids,
        "period": SEARCH_PERIOD # 🔥 Берем вакансии только за последние N дней
    }
    
    if area: params["area"] = area
    if schedule: params["schedule"] = schedule

    try:
        headers = {'User-Agent': 'JobSonarBot/1.0 (relax_mode)'}
        resp = requests.get("https://api.hh.ru/vacancies", params=params, headers=headers, timeout=10)
        return resp.json().get("items", [])
    except Exception as e:
        print(f"⚠️ Ошибка API: {e}")
        return []

def run_cycle():
    print(f"\n☕ --- НОВЫЙ КРУГ ПОИСКА ---")
    
    # Режем компании на пачки по 20 штук
    CHUNK_SIZE = 20
    employer_chunks = list(chunked(ALL_IDS, CHUNK_SIZE))
    
    total_found = 0
    
    for role, rules in PROFILES.items():
        for q in rules["keywords"]:
            print(f"🔎 Ключ: '{q}'...")
            
            # Идем по пачкам работодателей
            for batch_ids in employer_chunks:
                
                # 🎲 Jitter: Случайная пауза, как будто человек листает страницы
                sleep_time = random.uniform(2.5, 6.0)
                time.sleep(sleep_time)

                items = []
                # 1. Удаленка
                items.extend(fetch_hh_by_employers(q, batch_ids, schedule="remote"))
                # 2. Офис
                items.extend(fetch_hh_by_employers(q, batch_ids, area=TARGET_AREAS))
                
                if not items: continue

                unique_items = {v['id']: v for v in items}.values()
                
                for item in unique_items:
                    vac_id = item['id']
                    if is_sent(vac_id): continue

                    # Фильтры
                    title = item['name'].lower()
                    if any(w in title for w in rules["stop_words"]): continue
                    
                    sal = item.get('salary')
                    salary_text = "ЗП не указана"
                    if sal and sal['from']:
                        if sal['currency'] == 'RUR' and sal['from'] < MIN_SALARY:
                            continue
                        salary_text = f"от {sal['from']} {sal.get('currency','₽')}"

                    # Данные для сообщения
                    emp = item.get('employer', {})
                    emp_id = str(emp.get('id', ''))
                    cat_name = APPROVED_COMPANIES.get(emp_id, {}).get('cat', 'Топ')
                    
                    # Дата
                    pub_date = format_date(item.get('published_at', ''))
                    
                    # Формат работы
                    sched_id = item.get('schedule', {}).get('id')
                    city_name = item.get('area', {}).get('name', 'Не указано')
                    format_tag = "🌍 Удаленка" if sched_id == 'remote' else f"🏙 {city_name}"

                    msg = (
                        f"🔔 <b>{role}</b> | {format_tag}\n"
                        f"📅 {pub_date} | 🏢 <b>{emp.get('name')}</b>\n"
                        f"🏆 <b>{cat_name}</b> (Топ-100)\n"
                        f"💼 <a href='{item['alternate_url']}'>{item['name']}</a>\n"
                        f"💰 {salary_text}"
                    )
                    
                    send_telegram(msg)
                    mark_as_sent(vac_id)
                    print(f"✅ НАЙДЕНО: {item['name']} ({pub_date})")
                    total_found += 1
                    
                    # Пауза между отправкой сообщений (тоже важно!)
                    time.sleep(random.uniform(1.0, 3.0))

    print(f"🏁 Круг завершен. Отправлено новых: {total_found}")

if __name__ == "__main__":
    init_db()
    send_telegram(f"🟢 JobSonar: Тихий режим.\nИщем за последние {SEARCH_PERIOD} дн.")
    while True:
        try:
            run_cycle()
        except Exception as e:
            print(f"🔥 Ошибка: {e}")
        
        print(f"💤 Отдыхаю {CHECK_INTERVAL} сек...")
        time.sleep(CHECK_INTERVAL)