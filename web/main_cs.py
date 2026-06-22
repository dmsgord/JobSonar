# -*- coding: utf-8 -*-
# Head of Customer Service бот.
# Гео/формат: Москва — любой формат; вся остальная Россия+СНГ — только полная удалёнка.
# Ядро поиска: whitelist (приоритет) → professional_role=105 (сетка покрытия) → OR-батчи ключевиков.
import time
import sys
import logging
import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "log_cs.txt")
STATUS_FILE = os.path.join(BASE_DIR, "status_cs.txt")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(LOG_FILE, encoding='utf-8'), logging.StreamHandler(sys.stdout)]
)

from config_cs import (
    TG_TOKEN, TG_CHAT_ID, PROFILES, DB_NAME, MOSCOW_AREA, PROFESSIONAL_ROLES, SEARCH_PERIOD
)
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

ALL_IDS = list(APPROVED_COMPANIES.keys())
RULES = PROFILES['CS']

bot = BotContext(TG_TOKEN, TG_CHAT_ID, STATUS_FILE, os.path.join(BASE_DIR, DB_NAME))


def set_status(text): bot.set_status(text)
def send_telegram(text): bot.send_telegram(text)
def check_remote_stop(): bot.check_remote_stop()


def or_batches(phrases, size=6):
    """Объединяет ключевики в OR-запросы hh: '"A" OR "B" OR ...' (меньше запросов)."""
    for i in range(0, len(phrases), size):
        yield " OR ".join(f'"{p}"' for p in phrases[i:i + size])


def passes_geo_format(item):
    """Москва — любой формат; иначе — только полная удалёнка (есть 'удал', нет офиса/гибрида)."""
    area_id = str(item.get('area', {}).get('id', '0'))
    area_name = item.get('area', {}).get('name', '').lower()
    if area_id == MOSCOW_AREA or 'москв' in area_name:
        return True
    _, details_text = build_details(item)
    is_remote = 'удал' in details_text or 'remote' in details_text
    has_office = any(x in details_text for x in ['офис', 'на месте', 'office', 'гибрид', 'hybrid', 'разъездн'])
    return is_remote and not has_office


def title_relevant(title, rules):
    """Прямое попадание ИЛИ (уровень + контекст). Стоп-слова — отдельно у вызывающего."""
    is_direct = any(smart_contains(title, w) for w in rules['direct_titles'])
    has_level = any(smart_contains(title, w) for w in rules['role_levels'])
    has_context = any(smart_contains(title, w) for w in rules['role_context'])
    return is_direct or (has_level and has_context)


def filter_and_process(items, rules):
    unique_items = list({v['id']: v for v in items}.values())
    total = len(unique_items)
    skipped_db = skipped_title = skipped_geo = skipped_exp = processed = 0

    for item in unique_items:
        vac_id = item['id']
        title = item['name']
        title_lower = title.lower()

        if is_sent(vac_id):
            skipped_db += 1
            continue

        if any(stop_w in title_lower for stop_w in rules['stop_words']):
            skipped_title += 1
            continue

        if not title_relevant(title, rules):
            skipped_title += 1
            continue

        exp = item.get('experience', {})
        if rules.get('skip_no_experience') and exp.get('id') == 'noExperience':
            skipped_exp += 1
            continue

        if not passes_geo_format(item):
            skipped_geo += 1
            continue

        details, details_text = build_details(item)
        salary_text, is_bold_salary, _ = format_salary(item.get('salary'), 0)  # порог не фильтруем
        salary_html = f"<b>{salary_text}</b>" if is_bold_salary else salary_text
        pub_date = format_pub_date(item)

        emp = item.get('employer', {})
        emp_id = str(emp.get('id', ''))
        is_whitelist = emp_id in APPROVED_COMPANIES
        cat_emoji = get_clean_category(APPROVED_COMPANIES.get(emp_id, {}).get('cat', 'Остальные'))
        is_remote = 'удал' in details_text or 'remote' in details_text
        fire = "🔥 " if (is_whitelist and is_remote) else ""

        area_name = item.get('area', {}).get('name', '')

        msg = (
            f"{fire}{cat_emoji} <b>{emp.get('name')}</b>\n"
            f"📍 {area_name}\n\n"
            f"<a href='{item['alternate_url']}'><b>{title}</b></a>\n\n"
            f"📌 {', '.join(d for d in details if d) or '—'}\n"
            f"🎓 {exp.get('name') or '—'}\n"
            f"💰 {salary_html} | 🗓 {pub_date}"
        )

        send_telegram(msg)
        mark_as_sent(vac_id, category=cat_emoji)
        logging.info(f"✅ CS Sent: {title} ({area_name})")
        processed += 1
        time.sleep(0.5)

    logging.info(f"📊 CS batch: total={total} db={skipped_db} title={skipped_title} "
                 f"geo={skipped_geo} exp={skipped_exp} sent={processed}")
    return processed


def main_loop():
    init_db()
    bot.last_update_id = init_updates(TG_TOKEN)
    last_stats_date = None
    logging.info("🚀 CS Bot v1.0 Started (Head of Customer Service)")
    send_telegram("🟢 <b>Head of Customer Service Bot v1.0 Started</b>")

    while True:
        try:
            check_remote_stop()

            # 1. Whitelist — приоритет (Москва-любой + remote)
            set_status("🚀 Whitelist...")
            batch_size = 20
            batches = [ALL_IDS[i:i + batch_size] for i in range(0, len(ALL_IDS), batch_size)]
            for i, batch_ids in enumerate(batches):
                check_remote_stop()
                per = SEARCH_PERIOD if i < 10 else 14
                found = {}
                for it in bot.fetch_company_vacancies(batch_ids, schedule="remote", period=per): found[it['id']] = it
                for it in bot.fetch_company_vacancies(batch_ids, area=[MOSCOW_AREA], period=per): found[it['id']] = it
                filter_and_process(list(found.values()), RULES)

            # 2. professional_role=105 — сетка покрытия по Москве (ловит «кривые» тайтлы)
            set_status("🔎 professional_role (Москва)...")
            for role in PROFESSIONAL_ROLES:
                check_remote_stop()
                role_items = bot.fetch_hh_search(
                    {"professional_role": role, "area": MOSCOW_AREA, "period": SEARCH_PERIOD}, max_pages=6)
                filter_and_process(role_items, RULES)

            # 3. OR-батчи ключевиков — глобально (Москва-любой + remote-отовсюду через post-filter)
            set_status("🔎 OR-поиск по названиям...")
            for orq in or_batches(RULES['keywords'], size=6):
                check_remote_stop()
                items = bot.fetch_hh_search(
                    {"text": orq, "search_field": "name", "period": SEARCH_PERIOD}, max_pages=3)
                filter_and_process(items, RULES)

            now = get_moscow_time()
            seconds, next_run = get_smart_sleep_time()
            stats = get_daily_stats()
            total = sum(stats.values())
            today = now.date()
            if now.hour >= 23 and last_stats_date != today:
                send_daily_stats("Customer Service", TG_TOKEN, TG_CHAT_ID, stats)
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
