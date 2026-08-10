# -*- coding: utf-8 -*-
# Product Owner бот. Собирает ТОЛЬКО владельцев продукта (Product Owner),
# а НЕ Product Manager / продуктового аналитика / project manager.
#
# Правило названия: в тайтле обязан быть PO-маркер (config_po.po_markers).
#   Совмещённые названия («Product Owner / Product Manager», «Продакт-менеджер (Product Owner)»)
#   берём — PO-обязанности там заявлены. Чистый PM без маркера отсекается сам.
# Правило формата: строго-офисные вакансии НЕ берём. Удалёнка — из любого региона,
#   гибрид и «офис + ещё варианты» — только Москва/Нижний Новгород.
import re
import time
import sys
import logging
import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "log_po.txt")
STATUS_FILE = os.path.join(BASE_DIR, "status_po.txt")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(LOG_FILE, encoding='utf-8'), logging.StreamHandler(sys.stdout)]
)

from config_po import (
    TG_TOKEN, TG_CHAT_ID, PROFILES, DB_NAME, MIN_SALARY, SEARCH_PERIOD,
    TARGET_AREAS, MOSCOW_AREA, BLACKLISTED_AREAS, ALLOW_UNKNOWN_FORMAT,
    PROFESSIONAL_ROLES_PRIMARY, PROFESSIONAL_ROLES_EXTRA,
    REJECT_PM_COMBO, PM_COMBO_MARKERS
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

RULES = PROFILES['PO']

bot = BotContext(TG_TOKEN, TG_CHAT_ID, STATUS_FILE, os.path.join(BASE_DIR, DB_NAME))


def set_status(text): bot.set_status(text)
def send_telegram(text): bot.send_telegram(text)
def check_remote_stop(): bot.check_remote_stop()


def or_batches(phrases, size=6):
    """Объединяет ключевики в OR-запросы hh: '"A" OR "B" OR ...' (меньше запросов)."""
    for i in range(0, len(phrases), size):
        yield " OR ".join(f'"{p}"' for p in phrases[i:i + size])


def marker_pos(title_lower):
    """Позиция первого PO-маркера в названии, -1 если маркера нет."""
    hits = [title_lower.find(m) for m in RULES['po_markers'] if m in title_lower]
    return min(hits) if hits else -1


def has_po_marker(title):
    """В названии есть явный маркер владельца продукта."""
    return marker_pos(title.lower()) >= 0


def _stop_hit(title_lower, word):
    """Одиночное латинское слово — только по границам слова ('intern' не должен ловить 'Internal').
    Русские корни и фразы — обычной подстрокой."""
    if word.isascii() and ' ' not in word:
        return re.search(r'\b' + re.escape(word) + r'\b', title_lower) is not None
    return word in title_lower


def title_rejected(title):
    """Стоп-фильтр названия (применяется уже после проверки PO-маркера)."""
    title_lower = title.lower()
    if any(_stop_hit(title_lower, w) for w in RULES['stop_words']):
        return True
    # Стопы «только перед маркером»: грейд/обслуга слева от Product Owner
    head = title_lower[:max(marker_pos(title_lower), 0)]
    if any(w in head for w in RULES['prefix_stop_words']):
        return True
    if REJECT_PM_COMBO and any(m in title_lower for m in PM_COMBO_MARKERS):
        return True
    return False


# Подписи уже отправленных вакансий (живут пока живёт процесс) — защита от мульти-город дублей,
# которые дедуп по hh id не ловит: у каждого города свой id.
SENT_SIGNATURES = set()


def spam_signature(item):
    """Одна вакансия, опубликованная по N городам, имеет разные hh id — ловим по
    работодатель+название, иначе прилетает 5-6 одинаковых сообщений."""
    emp_id = str(item.get('employer', {}).get('id', ''))
    title_key = re.sub(r'[^a-zа-я0-9]+', '', item.get('name', '').lower())
    return f"{emp_id}_{title_key}"


def work_modes(item):
    """(is_remote, is_hybrid, is_known) по данным hh.ru о формате работы.

    work_format приходит из стейта hh (REMOTE/HYBRID/ON_SITE/FIELD), schedule — из @workSchedule.
    is_known=False означает, что hh вообще не сказал про формат.
    """
    fmt_ids = {str(f.get('id', '')).lower() for f in (item.get('work_format') or [])}
    sched_id = str(item.get('schedule', {}).get('id', '')).lower()
    is_remote = 'remote' in fmt_ids or sched_id == 'remote'
    is_hybrid = 'hybrid' in fmt_ids
    is_known = bool(fmt_ids) or sched_id == 'remote'
    return is_remote, is_hybrid, is_known


def passes_format_geo(item):
    """Строго офис → нет. Удалёнка → откуда угодно. Гибрид/офис+варианты → только Москва/НН.

    «Офис + через запятую другие варианты» проходит, потому что среди форматов есть
    remote или hybrid; вакансия только с ON_SITE (и/или FIELD) отбрасывается.
    """
    is_remote, is_hybrid, is_known = work_modes(item)

    area_id = str(item.get('area', {}).get('id', '0'))
    area_name = item.get('area', {}).get('name', '').lower()
    in_target_area = area_id in TARGET_AREAS or 'москв' in area_name or 'нижний новгород' in area_name

    if is_remote:
        # Удалёнка откуда угодно, кроме ближнего зарубежья
        if area_id in BLACKLISTED_AREAS or 'казахстан' in area_name:
            return False
        return True

    if is_hybrid:
        return in_target_area

    if not is_known:
        return ALLOW_UNKNOWN_FORMAT and in_target_area

    # Остались ON_SITE / FIELD без единого удалённого варианта — это строго офис
    return False


def format_badge(item):
    is_remote, is_hybrid, _ = work_modes(item)
    if is_remote and is_hybrid:
        return "🏠 Удалёнка + 🔀 Гибрид"
    if is_remote:
        return "🏠 Удалёнка"
    if is_hybrid:
        return "🔀 Гибрид"
    return "🏢 Офис"


def extract_skills(item, target_skills):
    found = []
    title = item.get('name', '')
    for skill in target_skills:
        if smart_contains(title, skill):
            found.append(skill.upper() if len(skill) <= 3 else skill.title())
    return found


def filter_and_process(items, rules):
    unique_items = list({v['id']: v for v in items}.values())
    total = len(unique_items)
    skipped_db = skipped_title = skipped_fmt = skipped_exp = skipped_salary = skipped_dup = processed = 0
    min_salary = rules.get('min_salary', MIN_SALARY)

    for item in unique_items:
        vac_id = item['id']
        title = item['name']

        if is_sent(vac_id):
            skipped_db += 1
            continue

        if not has_po_marker(title):
            skipped_title += 1
            continue

        if title_rejected(title):
            skipped_title += 1
            continue

        exp = item.get('experience', {})
        if rules.get('skip_no_experience') and exp.get('id') == 'noExperience':
            skipped_exp += 1
            continue

        if not passes_format_geo(item):
            skipped_fmt += 1
            continue

        salary_text, is_bold_salary, skip_salary = format_salary(item.get('salary'), min_salary)
        if skip_salary:  # указана и ниже порога (даже как «от») → не показываем
            skipped_salary += 1
            continue

        sig = spam_signature(item)
        if sig in SENT_SIGNATURES:  # та же вакансия, опубликованная по другому городу
            skipped_dup += 1
            continue

        details, _ = build_details(item)
        salary_html = f"<b>{salary_text}</b>" if is_bold_salary else salary_text
        pub_date = format_pub_date(item)

        emp = item.get('employer', {})
        emp_id = str(emp.get('id', ''))
        is_whitelist = emp_id in APPROVED_COMPANIES
        cat_emoji = get_clean_category(APPROVED_COMPANIES.get(emp_id, {}).get('cat', 'Остальные'))
        is_remote, _, _ = work_modes(item)
        fire = "🔥 " if (is_whitelist and is_remote) else ""

        skills = extract_skills(item, rules['target_skills'])
        skills_block = f"🛠 <b>{', '.join(skills[:5])}</b>\n" if skills else ""
        area_name = item.get('area', {}).get('name', '') or '—'

        msg = (
            f"{fire}{cat_emoji} <b>{emp.get('name')}</b>\n"
            f"📍 {area_name} · {format_badge(item)}\n\n"
            f"🧩 <a href='{item['alternate_url']}'><b>{title}</b></a>\n\n"
            f"{skills_block}"
            f"📌 {', '.join(d for d in details if d) or '—'}\n"
            f"🎓 {exp.get('name') or '—'}\n"
            f"💰 {salary_html} | 🗓 {pub_date}"
        )

        send_telegram(msg)
        mark_as_sent(vac_id, category=cat_emoji)
        SENT_SIGNATURES.add(sig)
        logging.info(f"✅ PO Sent: {title} ({area_name})")
        processed += 1
        time.sleep(0.5)

    logging.info(f"📊 PO batch: total={total} db={skipped_db} title={skipped_title} "
                 f"fmt={skipped_fmt} exp={skipped_exp} sal={skipped_salary} dup={skipped_dup} "
                 f"sent={processed}")
    return processed


def main_loop():
    init_db()
    bot.last_update_id = init_updates(TG_TOKEN)
    last_stats_date = None
    logging.info("🚀 PO Bot v1.0 Started (Product Owner)")
    send_telegram("🟢 <b>Product Owner Bot v1.0 Started</b>")

    while True:
        try:
            check_remote_stop()

            # 1. OR-батчи по названию — основной канал (PO-маркеры очень характерные)
            set_status("🔎 Поиск по названиям...")
            for orq in or_batches(RULES['keywords'], size=6):
                check_remote_stop()
                items = bot.fetch_hh_search(
                    {"text": orq, "search_field": "name", "period": SEARCH_PERIOD}, max_pages=3)
                filter_and_process(items, RULES)

            # 2. professional_role=73 «Менеджер продукта» — сетка покрытия под кривые названия
            set_status("🔎 professional_role (сетка)...")
            for role in PROFESSIONAL_ROLES_PRIMARY:
                for extra in ({"area": MOSCOW_AREA}, {"area": "66"}, {"work_format": "remote"}):
                    check_remote_stop()
                    params = {"professional_role": role, "period": SEARCH_PERIOD}
                    params.update(extra)
                    filter_and_process(bot.fetch_hh_search(params, max_pages=5), RULES)

            # 3. Смежные роли — там PO попадается редко, читаем поверхностно
            set_status("🔎 Смежные роли...")
            for role in PROFESSIONAL_ROLES_EXTRA:
                for extra in ({"area": MOSCOW_AREA}, {"work_format": "remote"}):
                    check_remote_stop()
                    params = {"professional_role": role, "period": SEARCH_PERIOD}
                    params.update(extra)
                    filter_and_process(bot.fetch_hh_search(params, max_pages=2), RULES)

            now = get_moscow_time()
            seconds, next_run = get_smart_sleep_time()
            stats = get_daily_stats()
            total = sum(stats.values())
            today = now.date()
            if now.hour >= 23 and last_stats_date != today:
                send_daily_stats("Product Owner", TG_TOKEN, TG_CHAT_ID, stats)
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
