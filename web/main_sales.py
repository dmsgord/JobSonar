# -*- coding: utf-8 -*-
import time
import sys
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

from config_sales import TG_TOKEN, TG_CHAT_ID, PROFILES, MIN_SALARY, DB_NAME
from db import init_db, is_sent, mark_as_sent, get_daily_stats
from utils import (
    BotContext, get_moscow_time, smart_contains, get_clean_category,
    get_smart_sleep_time, init_updates, report_error, send_daily_stats,
    build_details, format_salary, format_pub_date, is_individual_person
)

try:
    from whitelist import APPROVED_COMPANIES
except ImportError:
    APPROVED_COMPANIES = {}

bot = BotContext(TG_TOKEN, TG_CHAT_ID, STATUS_FILE, os.path.join(BASE_DIR, DB_NAME))


def set_status(text):
    bot.set_status(text)

def send_telegram(text):
    bot.send_telegram(text)

def check_remote_stop():
    bot.check_remote_stop()

def fetch_hh(text, schedule=None, period=14):
    return bot.fetch_hh_paginated(text, period=period, schedule=schedule)


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

        details, details_text = build_details(item)

        if any(x in details_text for x in ['гибрид', 'hybrid', 'офис', 'office', 'на месте']):
            skipped_geo += 1
            continue
        is_remote_explicit = 'удал' in details_text or 'remote' in details_text
        if not is_remote_explicit:
            skipped_geo += 1
            continue

        snippet = item.get('snippet', {}) or {}
        full_text = (item.get('name', '') + ' ' + (snippet.get('requirement') or '')).lower()
        if any(smart_contains(full_text, stop) for stop in rules['stop_domains']):
            skipped_domain += 1
            continue

        salary_text, is_bold_salary, skip_salary = format_salary(item.get('salary'), MIN_SALARY)
        if skip_salary:
            skipped_salary += 1
            continue

        cat_raw = APPROVED_COMPANIES.get(emp_id, {}).get('cat', 'Остальные')
        cat_emoji = get_clean_category(cat_raw)
        is_whitelist = emp_id in APPROVED_COMPANIES

        pub_date = format_pub_date(item)

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

    logging.info(f"📊 Sales batch: total={total} db={skipped_db} title={skipped_title} geo={skipped_geo} domain={skipped_domain} salary={skipped_salary} sent={processed}")
    return processed


def main_loop():
    init_db()
    bot.last_update_id = init_updates(TG_TOKEN)
    last_stats_date = None
    logging.info("🚀 Sales Bot v1.3 Started")
    send_telegram("🟢 <b>Sales Bot v1.3 Started</b>")

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
            today = now.date()

            if now.hour >= 23 and last_stats_date != today:
                send_daily_stats("Sales", TG_TOKEN, TG_CHAT_ID, stats)
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
