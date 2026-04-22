# -*- coding: utf-8 -*-
import time
import requests
import re
import sys
import signal
import logging
import os
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

from config_sales import TG_TOKEN, TG_CHAT_ID, PROFILES, MIN_SALARY, USER_AGENT, DB_NAME
from db import init_db, is_sent, mark_as_sent, set_db_name, get_daily_stats
from utils import (
    get_moscow_time, signal_handler, smart_contains, get_clean_category,
    get_smart_sleep_time, set_status as _set_status, send_telegram as _send_telegram,
    init_updates, check_remote_stop as _check_remote_stop, fetch_hh_paginated
)

try:
    from whitelist import APPROVED_COMPANIES
except ImportError:
    APPROVED_COMPANIES = {}

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

def fetch_hh(text, schedule=None, period=14):
    return fetch_hh_paginated(session, text, period=period, schedule=schedule)


def is_individual_person(emp_name):
    name_lower = emp_name.lower().strip()
    if 'ип ' in name_lower or ' ип' in name_lower or '(ип' in name_lower: return True
    if '.' in name_lower: return True
    parts = re.split(r'[\s-]+', name_lower)
    for part in parts:
        if part.endswith('вич') or part.endswith('вна'): return True
        if part.endswith('оглы') or part.endswith('кызы'): return True
    if len(parts) == 1:
        surname_endings = ('ов', 'ова', 'ев', 'ева', 'ин', 'ина', 'ский', 'ская', 'ая', 'ый')
        if name_lower.endswith(surname_endings):
            if not any(s in name_lower for s in ['групп', 'софт', 'tech']): return True
    corp_whitelist = ['ооо', 'ао', 'пао', 'llc', 'групп', 'софт', 'tech', 'студия', 'agency', 'онлайн', 'бизнес']
    if any(marker in name_lower for marker in corp_whitelist): return False
    if 2 <= len(parts) <= 4 and bool(re.search('[а-я]', name_lower)): return True
    return False

def check_domain_relevance(item, markers, stop_domains):
    snippet = item.get('snippet', {}) or {}
    full_text = (item.get('name', '') + ' ' + (snippet.get('requirement') or '')).lower()
    for stop in stop_domains:
        if smart_contains(full_text, stop): return False
    for marker in markers:
        if smart_contains(full_text, marker): return True
    return False


def process_items(items, role, rules, is_global=False):
    processed = 0
    unique_items = list({v['id']: v for v in items}.values())
    total = len(unique_items)
    skipped_db = skipped_title = skipped_geo = skipped_domain = skipped_salary = 0
    spam_deduplication_cache = set()

    for item in unique_items:
        vac_id = item['id']
        title = item['name']
        title_lower = title.lower()

        if is_sent(vac_id):
            skipped_db += 1
            continue
        if any(stop_w in title_lower for stop_w in rules["stop_words_title"]):
            skipped_title += 1
            continue

        emp = item.get('employer', {})
        emp_name = emp.get('name', '')
        emp_id = str(emp.get('id', ''))

        if is_individual_person(emp_name):
            skipped_title += 1
            continue

        spam_signature = f"{emp_id}_{title_lower}"
        if spam_signature in spam_deduplication_cache:
            continue
        spam_deduplication_cache.add(spam_signature)

        details = []
        raw_schedule = item.get('schedule', {})
        raw_formats = item.get('work_format', [])
        if raw_schedule:
            if raw_schedule.get('name') not in [f['name'] for f in raw_formats]:
                details.append(raw_schedule.get('name'))
        for f in raw_formats:
            details.append(f['name'])
        details_text = ", ".join(details).lower()

        if any(x in details_text for x in ['гибрид', 'hybrid', 'офис', 'office', 'на месте']):
            skipped_geo += 1
            continue
        is_remote_explicit = 'удален' in details_text or 'remote' in details_text
        if not is_remote_explicit:
            skipped_geo += 1
            continue

        if not check_domain_relevance(item, rules['digital_markers'], rules['stop_domains']):
            skipped_domain += 1
            continue

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
            elif currency in ['USD', 'EUR']:
                salary_text = f"{sal.get('from', '')} - {sal.get('to', '')} {currency}".replace("None", "").strip("- ")
                is_bold_salary = True
                has_good_salary = True

        if not has_good_salary and sal and sal.get('currency') == 'RUR':
            skipped_salary += 1
            continue

        cat_raw = APPROVED_COMPANIES.get(emp_id, {}).get('cat', 'Остальные')
        cat_emoji = get_clean_category(cat_raw)
        is_whitelist = emp_id in APPROVED_COMPANIES

        dt = item.get('published_at', '').split('T')[0]
        pub_date = f"{dt.split('-')[2]}.{dt.split('-')[1]}"

        fire_marker = "🤝 "
        if is_whitelist:
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
        logging.info(f"✅ Sales Sent: {title}")
        processed += 1
        time.sleep(0.5)

    if total > 0:
        logging.info(f"📊 Sales batch: total={total} db={skipped_db} title={skipped_title} geo={skipped_geo} domain={skipped_domain} salary={skipped_salary} sent={processed}")
    return processed


def main_loop():
    global LAST_UPDATE_ID
    init_db()
    LAST_UPDATE_ID = init_updates(TG_TOKEN)
    logging.info("🚀 Sales Bot v6.3 Started")
    send_telegram("🟢 <b>Sales Bot v6.3 Started</b>")

    while True:
        try:
            check_remote_stop()
            set_status("🚀 Поиск...")

            for role, rules in PROFILES.items():
                for q in rules["keywords"]:
                    set_status(f"🔎 Ищу: {q}")
                    check_remote_stop()
                    items = fetch_hh(q, schedule="remote", period=7)
                    if items:
                        process_items(items, role, rules, is_global=True)

            now = get_moscow_time()
            seconds, next_run = get_smart_sleep_time()
            stats = get_daily_stats()
            total = sum(stats.values())

            if now.hour >= 23:
                msg = f"🌙 <b>Итоги Sales:</b>\nТоп компании: {stats.get('Топ компании', 0)}\nОстальные: {stats.get('Остальные', 0)}"
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
