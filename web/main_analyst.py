# -*- coding: utf-8 -*-
import time
import sys
import logging
import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "log_analyst.txt")
STATUS_FILE = os.path.join(BASE_DIR, "status_analyst.txt")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

from config_analyst import TG_TOKEN, TG_CHAT_ID, PROFILES, MIN_SALARY, BLACKLISTED_AREAS, USER_AGENT, DB_NAME, TARGET_AREAS, BANAL_SKILLS
from db import init_db, is_sent, mark_as_sent, get_daily_stats
from utils import (
    BotContext, get_moscow_time, smart_contains, get_clean_category,
    get_smart_sleep_time, init_updates, report_error, send_daily_stats
)

try:
    from whitelist import APPROVED_COMPANIES
except ImportError:
    APPROVED_COMPANIES = {}

ALL_IDS = list(APPROVED_COMPANIES.keys())

bot = BotContext(TG_TOKEN, TG_CHAT_ID, STATUS_FILE, os.path.join(BASE_DIR, DB_NAME))
session = bot.session


def set_status(text):
    bot.set_status(text)

def send_telegram(text):
    bot.send_telegram(text)

def check_remote_stop():
    bot.check_remote_stop()

def fetch_company_vacancies(employer_ids, area=None, schedule=None, period=3):
    return bot.fetch_company_vacancies(employer_ids, area=area, schedule=schedule, period=period)

def fetch_hh_paginated_global(text, period=7):
    return bot.fetch_hh_paginated(text, period=period, schedule="remote")


def extract_skills(item, target_skills):
    found = set()
    search_text = (item.get('name', '') + ' ' + (item.get('snippet', {}).get('requirement', '') or '')).lower()
    for skill in target_skills:
        if smart_contains(search_text, skill):
            if skill in ['sql', 'etl', 'dwh', 'bi', 'api', 'rest', 'json', 'xml', 'bpmn']:
                found.add(skill.upper())
            else:
                found.add(skill.title())
    return list(found)


def filter_and_process(items, rules, is_global=False):
    unique_items = list({v['id']: v for v in items}.values())
    total = len(unique_items)
    skipped_db = skipped_title = skipped_geo = skipped_salary = skipped_skills = processed = 0

    for item in unique_items:
        vac_id = item['id']
        title = item['name']
        title_lower = title.lower()

        if is_sent(vac_id):
            skipped_db += 1
            continue

        is_relevant = any(smart_contains(title, k) for k in rules["keywords"])
        if not is_relevant:
            skipped_title += 1
            continue

        if any(stop_w in title_lower for stop_w in rules["stop_words"]):
            skipped_title += 1
            continue

        dev_stop_words = ['разработки', 'development', 'developer', 'разработчик', 'programmer', 'golang', 'java', 'backend', 'frontend']
        if any(w in title_lower for w in dev_stop_words):
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

        has_office_marker = any(x in details_text for x in ['гибрид', 'офис', 'на месте', 'office', 'hybrid', 'разъездной'])
        is_remote_explicit = 'удал' in details_text or 'remote' in details_text
        is_clean_remote = is_remote_explicit and not has_office_marker

        area_id = item.get('area', {}).get('id', '0')
        area_name = item.get('area', {}).get('name', '').lower()

        is_system_analyst = 'system analyst' in title_lower or 'системный аналитик' in title_lower or 'системный' in title_lower

        if is_system_analyst:
            if not is_remote_explicit or has_office_marker:
                skipped_geo += 1
                continue
        else:
            if is_global and has_office_marker:
                skipped_geo += 1
                continue
            if not is_clean_remote:
                if area_id in BLACKLISTED_AREAS or 'казахстан' in area_name or 'kazakhstan' in area_name:
                    skipped_geo += 1
                    continue

        emp = item.get('employer', {})
        emp_id = str(emp.get('id', ''))
        cat_raw = APPROVED_COMPANIES.get(emp_id, {}).get('cat', 'Остальные')
        cat_emoji = get_clean_category(cat_raw)
        is_whitelist = emp_id in APPROVED_COMPANIES

        found_skills = extract_skills(item, rules['target_skills'])
        is_ba_title = 'business analyst' in title_lower or 'бизнес-аналитик' in title_lower or 'бизнес аналитик' in title_lower

        sal = item.get('salary')
        salary_text = "-"
        is_bold_salary = False
        threshold = MIN_SALARY
        has_good_salary = False

        if sal:
            currency = sal.get('currency')
            lower = sal.get('from')
            upper = sal.get('to')
            if currency == 'RUR':
                if lower and lower >= threshold:
                    salary_text = f"от {lower} ₽"
                    is_bold_salary = True
                elif upper and upper >= threshold:
                    salary_text = f"до {upper} ₽"
                    is_bold_salary = True
            elif currency in ['USD', 'EUR']:
                if lower and upper:
                    salary_text = f"{lower}–{upper} {currency}"
                elif lower:
                    salary_text = f"от {lower} {currency}"
                elif upper:
                    salary_text = f"до {upper} {currency}"
                is_bold_salary = True

        if sal and sal.get('currency') == 'RUR' and (sal.get('from') or sal.get('to')) and not is_bold_salary:
            skipped_salary += 1
            continue

        skills_str = ", ".join(list(found_skills)[:5])

        dt = item.get('published_at', '').split('T')[0]
        pub_date = f"{dt.split('-')[2]}.{dt.split('-')[1]}"

        fire_marker = ""
        if is_whitelist and is_clean_remote:
            fire_marker = "🔥 "

        salary_html = f"<b>{salary_text}</b>" if is_bold_salary else salary_text
        skills_block = f"🛠 <b>{skills_str}</b>\n" if skills_str else ""

        msg = (
            f"{fire_marker}{cat_emoji} <b>{emp.get('name')}</b>\n\n"
            f"<a href='{item['alternate_url']}'><b>{title}</b></a>\n\n"
            f"{skills_block}"
            f"📌 {', '.join(details)}\n"
            f"💰 {salary_html} | 🗓 {pub_date}"
        )

        send_telegram(msg)
        mark_as_sent(vac_id, category=cat_emoji)
        logging.info(f"✅ Analyst Sent: {title}")
        processed += 1
        time.sleep(0.5)

    logging.info(f"📊 Analyst batch: total={total} db={skipped_db} title={skipped_title} geo={skipped_geo} salary={skipped_salary} skills={skipped_skills} sent={processed}")
    return processed


def main_loop():
    init_db()
    bot.last_update_id = init_updates(TG_TOKEN)
    last_stats_date = None
    logging.info("🚀 Analyst Bot v7.1 Started")
    send_telegram("🟢 <b>Analyst Bot v7.1 Started</b>")

    while True:
        try:
            check_remote_stop()
            set_status("🚀 Поиск...")

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

                filter_and_process(list(found_map.values()), PROFILES['Analyst'])
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

            today = now.date()
            if now.hour >= 23 and last_stats_date != today:
                send_daily_stats("Analyst", TG_TOKEN, TG_CHAT_ID, stats)
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
