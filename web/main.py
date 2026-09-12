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

from config import TG_TOKEN, TG_CHAT_ID, PROFILES, DB_NAME, AXIS_SEARCH_PERIOD
from config_coo import COO_PROFILES
from db import init_db, is_sent, mark_as_sent, get_daily_stats
from employers import init_employer_cache, remember_employer, top_employers
from hr_filter import decide
from hr_message import build_messages
from hr_search import HR_PROFESSIONAL_ROLES, SEARCH_AXES, build_axis_queries
from utils import (
    BotContext, get_moscow_time, get_smart_sleep_time, init_updates,
    report_error, send_daily_stats
)

ALL_PROFILES = {**COO_PROFILES, **PROFILES}
DB_PATH = os.path.join(BASE_DIR, DB_NAME)

# Сколько страниц читаем на запрос. Страница hh ≈ 50 вакансий (per_page игнорируется),
# period короткий — двух страниц хватает даже осям Москвы.
MAX_PAGES = 2

# Пауза между сообщениями: у групп лимит ~20 сообщений в минуту, за ним начинается 429
SEND_PAUSE = 3.5

bot = BotContext(TG_TOKEN, TG_CHAT_ID, STATUS_FILE, DB_PATH)


def set_status(text):
    bot.set_status(text)

def send_telegram(text):
    return bot.send_telegram(text)

def check_remote_stop():
    bot.check_remote_stop()


def collect_matches(items, rules, seen_ids):
    """Прогоняет пачку вакансий через decide(); возвращает прошедшие [(item, decision)]."""
    unique_items = list({v['id']: v for v in items}.values())
    counters = {"total": len(unique_items), "dup": 0, "db": 0, "title": 0,
                "geo": 0, "company": 0, "salary": 0, "ok": 0}
    accepted = []

    for item in unique_items:
        vac_id = item['id']
        key = (vac_id, rules['name'])
        if key in seen_ids:
            counters["dup"] += 1
            continue
        seen_ids.add(key)

        if is_sent(vac_id):
            counters["db"] += 1
            continue

        decision = decide(item, rules)

        # Работодателя запоминаем, как только дошли до скоринга — так виден топ
        # и понятно, кого бот режет по зарплате.
        if decision.reason in ("ok", "salary", "company"):
            emp = item.get('employer', {})
            if emp.get('id'):
                remember_employer(DB_PATH, emp, decision.score)

        if not decision.send:
            counters[decision.reason] = counters.get(decision.reason, 0) + 1
            continue

        accepted.append((item, decision))
        counters["ok"] += 1

    logging.info("📊 HR batch: " + " ".join(f"{k}={v}" for k, v in counters.items()))
    return accepted


def publish(accepted):
    """Шлёт отобранное: вакансии одной компании уходят одним сообщением."""
    sent = 0
    for text, vac_ids, tier in build_messages(accepted):
        if not send_telegram(text):
            # Не доставлено — не помечаем: вакансия вернётся в следующем цикле
            logging.warning(f"⚠️ HR не доставлено, вернём позже: {vac_ids}")
            continue
        for vac_id in vac_ids:
            mark_as_sent(vac_id, category=tier)
        logging.info(f"✅ HR Sent [{tier}] {len(vac_ids)} вак.: {vac_ids}")
        sent += len(vac_ids)
        time.sleep(SEND_PAUSE)
    return sent


def run_cycle():
    """Один проход: три гео-оси × (ключевики + professional_role)."""
    queries = build_axis_queries(
        SEARCH_AXES, ALL_PROFILES, HR_PROFESSIONAL_ROLES, period=AXIS_SEARCH_PERIOD
    )
    seen_ids = set()
    sent = 0

    for i, (axis_name, params) in enumerate(queries, 1):
        check_remote_stop()
        set_status(f"🔎 Ось {axis_name} ({i}/{len(queries)})")
        items = bot.fetch_hh_search(params, max_pages=MAX_PAGES)
        logging.info(f"🌐 {axis_name} [{i}/{len(queries)}] items={len(items)}")

        accepted = []
        for _role, rules in ALL_PROFILES.items():
            accepted.extend(collect_matches(items, rules, seen_ids))
        # Публикуем сразу после запроса, а не в конце цикла: группировка по компании
        # всё равно работает внутри одной выдачи, зато падение цикла не съедает отправку.
        sent += publish(accepted)

    return sent


def main_loop():
    init_db()
    init_employer_cache(DB_PATH)
    bot.last_update_id = init_updates(TG_TOKEN)
    last_stats_date = None
    logging.info("🚀 HR Bot v9.0 Started (оси + скоринг, без whitelist)")
    send_telegram("🟢 <b>HR Bot v9.0 Started</b> — поиск по осям, отбор по скорингу компании")

    while True:
        try:
            check_remote_stop()
            sent = run_cycle()

            now = get_moscow_time()
            # HR: выходные работают как будни — вакансии постят и в субботу
            seconds, next_run = get_smart_sleep_time(weekend_like_weekday=True)
            stats = get_daily_stats()
            total = sum(stats.values())
            today = now.date()

            if now.hour >= 23 and last_stats_date != today:
                send_daily_stats("HR", TG_TOKEN, TG_CHAT_ID, stats)
                top = top_employers(DB_PATH, limit=5)
                if top:
                    lines = "\n".join(f"{r['score']} — {r['name']}" for r in top)
                    send_telegram(f"🏅 <b>Топ работодателей по скорингу</b>\n{lines}")
                last_stats_date = today

            set_status(f"💤 Сон до {next_run.strftime('%H:%M')}. За цикл: {sent}, за сегодня: {total}")

            while seconds > 0:
                check_remote_stop()
                time.sleep(min(seconds, 10))
                seconds -= 10

        except Exception as e:
            report_error(e, TG_TOKEN, TG_CHAT_ID, context="main_loop")
            time.sleep(60)


if __name__ == "__main__":
    main_loop()
