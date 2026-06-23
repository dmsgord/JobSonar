# -*- coding: utf-8 -*-
import time
import sys
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

from config import TG_TOKEN, TG_CHAT_ID, PROFILES, TARGET_AREAS, MIN_SALARY, DB_NAME
from config_coo import COO_PROFILES
from db import init_db, is_sent, mark_as_sent, get_daily_stats
from utils import (
    BotContext, get_moscow_time, smart_contains, get_clean_category,
    get_smart_sleep_time, init_updates, report_error, send_daily_stats,
    build_details, format_salary, format_pub_date
)

try:
    from whitelist import APPROVED_COMPANIES
except ImportError:
    APPROVED_COMPANIES = {}

ALL_PROFILES = {**COO_PROFILES, **PROFILES}
ALL_IDS = list(APPROVED_COMPANIES.keys())

bot = BotContext(TG_TOKEN, TG_CHAT_ID, STATUS_FILE, os.path.join(BASE_DIR, DB_NAME))


def set_status(text):
    bot.set_status(text)

def send_telegram(text):
    bot.send_telegram(text)

def check_remote_stop():
    bot.check_remote_stop()

def fetch_company_vacancies(employer_ids, area=None, schedule=None, period=3):
    return bot.fetch_company_vacancies(employer_ids, area=area, schedule=schedule, period=period)

def fetch_hh_paginated_global(text, period=7, max_pages=1):
    return bot.fetch_hh_paginated(text, period=period, max_pages=max_pages)


def or_batches(phrases, size=6):
    """Объединяет ключевики в OR-запросы hh: '"A" OR "B" …' — меньше запросов к hh.ru
    (а значит меньше шанс словить 403) и быстрее цикл. Пост-фильтр не меняется."""
    for i in range(0, len(phrases), size):
        yield " OR ".join(f'"{p}"' for p in phrases[i:i + size])



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
        context_words = rules.get('role_context', rules.get('hr_context', []))
        has_role_context = any(smart_contains(title, w) for w in context_words)
        is_combo_hit = has_role_level and has_role_context

        if not (is_direct_hit or is_combo_hit):
            skipped_title += 1
            continue

        exp = item.get('experience', {})
        if exp.get('id') == 'noExperience':
            skipped_title += 1
            continue

        details, details_text = build_details(item)

        is_remote_explicit = 'удал' in details_text or 'remote' in details_text
        has_office_marker = any(x in details_text for x in ['офис', 'на месте', 'office', 'гибрид', 'hybrid', 'разъездной'])

        area_id = item.get('area', {}).get('id', '0')
        area_name = item.get('area', {}).get('name', '').lower()
        is_target_area = area_id in TARGET_AREAS or 'москв' in area_name

        if not is_target_area and not is_remote_explicit:
            skipped_geo += 1
            continue

        threshold = rules.get('global_min_salary', 250000) if is_global else rules.get('min_salary', MIN_SALARY)
        salary_text, is_bold_salary, skip_salary = format_salary(item.get('salary'), threshold)
        if skip_salary:
            skipped_salary += 1
            continue

        emp = item.get('employer', {})
        emp_id = str(emp.get('id', ''))

        cat_raw = APPROVED_COMPANIES.get(emp_id, {}).get('cat', 'Остальные')
        cat_emoji = get_clean_category(cat_raw)
        is_whitelist = emp_id in APPROVED_COMPANIES

        pub_date = format_pub_date(item)

        fire_marker = ""
        if is_whitelist and is_remote_explicit and not has_office_marker:
            fire_marker = "🔥 "

        salary_html = f"<b>{salary_text}</b>" if is_bold_salary else salary_text

        msg = (
            f"{fire_marker}{cat_emoji} <b>{emp.get('name')}</b>\n\n"
            f"<a href='{item['alternate_url']}'><b>{item['name']}</b></a>\n\n"
            f"📌 {', '.join(details)}\n"
            f"🎓 {exp.get('name')}\n"
            f"💰 {salary_html} | 🗓 {pub_date}"
        )

        send_telegram(msg)
        mark_as_sent(vac_id, category=cat_emoji)
        logging.info(f"✅ HR Sent: {title}")
        processed += 1
        time.sleep(0.5)

    logging.info(f"📊 HR batch: total={total} db={skipped_db} title={skipped_title} geo={skipped_geo} salary={skipped_salary} sent={processed}")
    return processed


def main_loop():
    init_db()
    bot.last_update_id = init_updates(TG_TOKEN)
    last_stats_date = None
    logging.info("🚀 HR Bot v8.0 Started")
    send_telegram("🟢 <b>HR Bot v8.0 Started</b>")

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

                for _role, _rules in ALL_PROFILES.items():
                    filter_and_process(list(found_map.values()), _rules)

            set_status("🔎 Global поиск (OR-батчи)...")
            for role, rules in ALL_PROFILES.items():
                for orq in or_batches(rules["keywords"], size=6):
                    check_remote_stop()
                    # OR-батч объединяет до 6 ключевиков в один запрос → читаем 3 стр.,
                    # чтобы не потерять полноту по отдельным словам (поведение фильтра то же).
                    items = fetch_hh_paginated_global(orq, period=3, max_pages=3)
                    filter_and_process(items, rules, is_global=True)

            now = get_moscow_time()
            seconds, next_run = get_smart_sleep_time()
            stats = get_daily_stats()
            total = sum(stats.values())
            today = now.date()

            if now.hour >= 23 and last_stats_date != today:
                send_daily_stats("HR", TG_TOKEN, TG_CHAT_ID, stats)
                last_stats_date = today

            set_status(f"💤 Сон до {next_run.strftime('%H:%M')}. За сегодня: {total}")

            while seconds > 0:
                check_remote_stop()
                time.sleep(min(seconds, 10))
                seconds -= 10

        except Exception as e:
            report_error(e, TG_TOKEN, TG_CHAT_ID, context="main_loop")
            time.sleep(60)


if __name__ == "__main__":
    main_loop()
