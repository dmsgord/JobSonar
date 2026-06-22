# -*- coding: utf-8 -*-
# Совмещённый бот НН: HR-руководитель + Аналитик.
# Правила (по запросу владельца):
#   • вакансии обоих профилей (HR-руководитель + Аналитик);
#   • НЕТ фильтра по формату работы (офис/удалёнка/гибрид — всё проходит);
#   • НЕТ порога зарплаты (показываем как есть);
#   • НЕТ whitelist-проверки топ-компаний;
#   • КРИТИЧНО: только вакансии из Нижнего Новгорода или Дзержинска;
#   • главное — свежак (order_by=publication_time, малый period).
import time
import sys
import logging
import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "log_nn.txt")
STATUS_FILE = os.path.join(BASE_DIR, "status_nn.txt")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

from config_nn import TG_TOKEN, TG_CHAT_ID, PROFILES, DB_NAME, TARGET_AREAS, AREA_NAME_MARKERS, SEARCH_PERIOD
from db import init_db, is_sent, mark_as_sent, get_daily_stats
from utils import (
    BotContext, get_moscow_time, smart_contains,
    get_smart_sleep_time, init_updates, report_error, send_daily_stats,
    build_details, format_salary, format_pub_date
)

bot = BotContext(TG_TOKEN, TG_CHAT_ID, STATUS_FILE, os.path.join(BASE_DIR, DB_NAME))

# Разработческие стоп-слова для профиля Аналитика (как в main_analyst.py)
DEV_STOP_WORDS = ['разработки', 'development', 'developer', 'разработчик',
                  'programmer', 'golang', 'java', 'backend', 'frontend']


def set_status(text):
    bot.set_status(text)

def send_telegram(text):
    bot.send_telegram(text)

def check_remote_stop():
    bot.check_remote_stop()


def extract_skills(item, target_skills):
    """Навыки из тайтла (для отображения, не для фильтрации)."""
    found = set()
    search_text = (item.get('name', '') + ' ' + (item.get('snippet', {}).get('requirement', '') or '')).lower()
    for skill in target_skills:
        if smart_contains(search_text, skill):
            if skill in ['sql', 'etl', 'dwh', 'bi', 'api', 'rest', 'json', 'xml', 'bpmn']:
                found.add(skill.upper())
            else:
                found.add(skill.title())
    return list(found)


def title_matches(title, rules):
    """Совпадение по названию. Поддерживает оба стиля профилей."""
    title_lower = title.lower()

    # Стоп-слова — общий негативный фильтр
    if any(stop_w in title_lower for stop_w in rules["stop_words"]):
        return False

    if 'direct_titles' in rules:
        # HR-стиль: прямое попадание ИЛИ (уровень + контекст)
        is_direct = any(smart_contains(title, w) for w in rules['direct_titles'])
        has_level = any(smart_contains(title, w) for w in rules['role_levels'])
        context_words = rules.get('role_context', rules.get('hr_context', []))
        has_context = any(smart_contains(title, w) for w in context_words)
        return is_direct or (has_level and has_context)

    # Analyst-стиль: совпадение по keywords + отсечка разработчиков
    if not any(smart_contains(title, k) for k in rules['keywords']):
        return False
    if any(w in title_lower for w in DEV_STOP_WORDS):
        return False
    return True


def is_target_geo(item):
    """True только если вакансия размещена в Нижнем Новгороде или Дзержинске."""
    area_id = str(item.get('area', {}).get('id', '0'))
    area_name = item.get('area', {}).get('name', '').lower()
    if area_id in TARGET_AREAS:
        return True
    return any(m in area_name for m in AREA_NAME_MARKERS)


def filter_and_process(items, profile_name, rules):
    unique_items = list({v['id']: v for v in items}.values())
    total = len(unique_items)
    skipped_db = skipped_title = skipped_geo = skipped_exp = processed = 0

    for item in unique_items:
        vac_id = item['id']
        title = item['name']

        if is_sent(vac_id):
            skipped_db += 1
            continue

        if not title_matches(title, rules):
            skipped_title += 1
            continue

        # 📍 Главный фильтр — гео
        if not is_target_geo(item):
            skipped_geo += 1
            continue

        exp = item.get('experience', {})
        if rules.get('skip_no_experience') and exp.get('id') == 'noExperience':
            skipped_exp += 1
            continue

        details, _ = build_details(item)
        area_name = item.get('area', {}).get('name', '')

        # Зарплата: НЕ фильтруем (threshold=0 → ничего не скипаем), только показываем
        salary_text, is_bold_salary, _ = format_salary(item.get('salary'), 0)
        salary_html = f"<b>{salary_text}</b>" if is_bold_salary else salary_text

        pub_date = format_pub_date(item)
        emp = item.get('employer', {})

        # Навыки показываем только для профиля Аналитика
        skills_block = ""
        if 'target_skills' in rules:
            skills = extract_skills(item, rules['target_skills'])
            if skills:
                skills_block = f"🛠 <b>{', '.join(skills[:5])}</b>\n"

        # Эмодзи принадлежности вакансии: 👔 HR-руководитель / 📊 Аналитик
        prof_emoji = "👔" if profile_name == 'HR' else "📊"

        msg = (
            f"{prof_emoji} <b>{emp.get('name')}</b>\n"
            f"📍 {area_name}\n\n"
            f"<a href='{item['alternate_url']}'><b>{title}</b></a>\n\n"
            f"{skills_block}"
            f"📌 {', '.join(details) if details else '—'}\n"
            f"🎓 {exp.get('name') or '—'}\n"
            f"💰 {salary_html} | 🗓 {pub_date}"
        )

        send_telegram(msg)
        mark_as_sent(vac_id, category=profile_name)
        logging.info(f"✅ NN Sent [{profile_name}]: {title} ({area_name})")
        processed += 1
        time.sleep(0.5)

    logging.info(
        f"📊 NN batch [{profile_name}]: total={total} db={skipped_db} "
        f"title={skipped_title} geo={skipped_geo} exp={skipped_exp} sent={processed}"
    )
    return processed


def main_loop():
    init_db()
    bot.last_update_id = init_updates(TG_TOKEN)
    last_stats_date = None
    logging.info("🚀 NN Combined Bot v1.0 Started")
    send_telegram("🟢 <b>NN Bot v1.0 Started</b> (HR + Аналитик, Н.Новгород/Дзержинск)")

    while True:
        try:
            check_remote_stop()
            set_status("🔎 Поиск по Н.Новгороду/Дзержинску...")

            # Глобальный поиск по ключевикам обоих профилей, сразу с area-фильтром hh.ru
            for profile_name, rules in PROFILES.items():
                for q in rules["keywords"]:
                    check_remote_stop()
                    items = bot.fetch_hh_paginated(q, period=SEARCH_PERIOD, area=TARGET_AREAS, max_pages=5)
                    filter_and_process(items, profile_name, rules)

            now = get_moscow_time()
            seconds, next_run = get_smart_sleep_time()
            stats = get_daily_stats()
            total = sum(stats.values())
            today = now.date()

            if now.hour >= 23 and last_stats_date != today:
                send_daily_stats("NN", TG_TOKEN, TG_CHAT_ID, stats)
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
