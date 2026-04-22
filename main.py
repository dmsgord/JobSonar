# -*- coding: utf-8 -*-
import time
import requests
import sys
import signal
import logging
import os
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

from config import TG_TOKEN, TG_CHAT_ID, PROFILES, TARGET_AREAS, MIN_SALARY, USER_AGENT, DB_NAME, BANAL_SKILLS
from db import init_db, is_sent, mark_as_sent, set_db_name, get_daily_stats
from utils import (
    get_moscow_time, signal_handler, smart_contains, get_clean_category,
    get_smart_sleep_time, get_vacancy_skills as _get_vacancy_skills,
    set_status as _set_status, send_telegram as _send_telegram,
    init_updates, check_remote_stop as _check_remote_stop,
    fetch_company_vacancies as _fetch_company_vacancies,
    fetch_hh_paginated
)

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

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


def set_status(text):
    _set_status(STATUS_FILE, text)

def send_telegram(text):
    _send_telegram(TG_TOKEN, TG_CHAT_ID, text)

def check_remote_stop():
    global LAST_UPDATE_ID
    LAST_UPDATE_ID = _check_remote_stop(TG_TOKEN, TG_CHAT_ID, BOT_ID, LAST_UPDATE_ID)

def get_vacancy_skills(vac_id):
    return _get_vacancy_skills(session, vac_id, BANAL_SKILLS)

def fetch_company_vacancies(employer_ids, area=None, schedule=None, period=3):
    return _fetch_company_vacancies(session, employer_ids, area=area, schedule=schedule, period=period)

def fetch_hh_paginated_global(text, period=7):
    return fetch_hh_paginated(session, text, period=period)


def filter_and_process(items, rules, is_global=False):
    unique_items = list({v['id']: v for v in items}.values())
    total = len(unique_items)
    skipped_db = skipped_title = skipped_geo = skipped_salary = processed = 0

    for item in unique_items:
        vac_id = item['id']
        title = item['name']
        title_lower = title.lower()

        if is_sent(vac_id):
            skipped_db += 1
            continue

        if any(stop_w in title_lower for stop_w in rules["stop_words"]):
            skipped_title += 1
            continue

        is_direct_hit = any(smart_contains(title, w) for w in rules['direct_titles'])
        has_role_level = any(smart_contains(title, w) for w in rules['role_levels'])
        has_hr_context = any(smart_contains(title, w) for w in rules['hr_context'])
        is_combo_hit = has_role_level and has_hr_context

        if not (is_direct_hit or is_combo_hit):
            skipped_title += 1
            continue

        exp = item.get('experience', {})
        if exp.get('id') == 'noExperience':
            skipped_title += 1
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

        snippet = item.get('snippet', {}) or {}
        req_text = (snippet.get('requirement') or '') + ' ' + (snippet.get('responsibility') or '')
        req_text_lower = req_text.lower()

        has_remote_in_text = 'удален' in req_text_lower or 'remote' in req_text_lower
        is_remote_explicit = 'удален' in details_text or 'remote' in details_text

        office_markers = ['офис', 'на месте', 'office', 'гибрид', 'hybrid', 'разъездной']
        has_office_marker = any(x in details_text for x in office_markers)

        area_id = item.get('area', {}).get('id', '0')

        if area_id not in TARGET_AREAS:
            if not (is_remote_explicit or has_remote_in_text):
                skipped_geo += 1
                continue

        real_skills = get_vacancy_skills(vac_id)
        skills_str = ", ".join(real_skills)

        sal = item.get('salary')
        salary_text = "-"
        is_bold_salary = False
        threshold = 250000 if is_global else MIN_SALARY
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
            elif currency in ['USD', 'EUR']:
                salary_text = f"{sal.get('from', '')} - {sal.get('to', '')} {currency}".replace("None", "").strip("- ")
                is_bold_salary = True
                has_good_salary = True

        if sal and not has_good_salary and (sal.get('from') or sal.get('to')) and sal.get('currency') == 'RUR':
            skipped_salary += 1
            continue

        emp = item.get('employer', {})
        emp_id = str(emp.get('id', ''))

        cat_raw = APPROVED_COMPANIES.get(emp_id, {}).get('cat', 'Остальные')
        cat_emoji = get_clean_category(cat_raw)
        is_whitelist = emp_id in APPROVED_COMPANIES

        dt = item.get('published_at', '').split('T')[0]
        pub_date = f"{dt.split('-')[2]}.{dt.split('-')[1]}"

        fire_marker = ""
        if is_whitelist and is_remote_explicit and not has_office_marker:
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
        logging.info(f"✅ HR Sent: {title}")
        processed += 1
        time.sleep(0.5)

    if total > 0:
        logging.info(f"📊 HR batch: total={total} db={skipped_db} title={skipped_title} geo={skipped_geo} salary={skipped_salary} sent={processed}")
    return processed


def main_loop():
    global LAST_UPDATE_ID
    init_db()
    LAST_UPDATE_ID = init_updates(TG_TOKEN)
    logging.info("🚀 HR Bot v6.7 Started")
    send_telegram("🟢 <b>HR Bot v6.7 Started</b>")

    while True:
        try:
            check_remote_stop()
            set_status("🚀 Поиск по Whitelist...")

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

                filter_and_process(list(found_map.values()), PROFILES['HR'])
                time.sleep(1)

            set_status("🔎 Global поиск...")
            for role, rules in PROFILES.items():
                for q in rules["keywords"]:
                    check_remote_stop()
                    items = fetch_hh_paginated_global(q, period=3)
                    filter_and_process(items, rules, is_global=True)

            now = get_moscow_time()
            seconds, next_run = get_smart_sleep_time()
            stats = get_daily_stats()
            total = sum(stats.values())

            if now.hour >= 23:
                msg = f"🌙 <b>Итоги HR:</b>\nТоп компании: {stats.get('Топ компании', 0)}\nОстальные: {stats.get('Остальные', 0)}"
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
