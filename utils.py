# -*- coding: utf-8 -*-
import re
import sys
import time
import signal
import logging
import random
import requests
from datetime import datetime, timedelta, timezone

MOSCOW_TZ = timezone(timedelta(hours=3))

CAT_ALIASES = {
    'ГИГАНТЫ': '🏆',
    'КРУПНЫЕ': '🥇',
    'СРЕДНИЕ': '🥈',
    'НЕБОЛЬШИЕ': '🥉',
    'ОСТАЛЬНЫЕ': '🌐'
}

def get_moscow_time():
    return datetime.now(MOSCOW_TZ)

def set_status(status_file, text):
    try:
        with open(status_file, "w", encoding="utf-8") as f:
            f.write(f"[{get_moscow_time().strftime('%H:%M')}] {text}")
    except:
        pass

def signal_handler(sig, frame):
    logging.info("🛑 Stop signal.")
    sys.exit(0)

def send_telegram(token, chat_id, text):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=10
        )
        if not r.ok:
            logging.warning(f"TG send failed: {r.status_code} {r.text[:200]}")
    except Exception as e:
        logging.warning(f"TG send error: {e}")

def init_updates(token):
    try:
        resp = requests.get(
            f"https://api.telegram.org/bot{token}/getUpdates",
            params={"limit": 1, "offset": -1}, timeout=5
        ).json()
        if resp.get("result"):
            return resp["result"][0]["update_id"]
    except:
        pass
    return 0

def check_remote_stop(token, chat_id, bot_id, last_update_id):
    try:
        resp = requests.get(
            f"https://api.telegram.org/bot{token}/getUpdates",
            params={"limit": 5, "offset": last_update_id + 1}, timeout=5
        ).json()
        if resp.get("result"):
            for update in resp["result"]:
                last_update_id = update["update_id"]
                msg = update.get("message", {})
                from_id = str(msg.get("from", {}).get("id", ""))
                text = msg.get("text", "").lower()
                if from_id == bot_id:
                    continue
                if str(msg.get("chat", {}).get("id")) == str(chat_id):
                    if "стоп" in text:
                        sys.exit(0)
    except:
        pass
    return last_update_id

def smart_contains(text, word):
    word_lower = word.lower()
    text_lower = text.lower()
    if len(word_lower) <= 3 and word_lower.isascii():
        return re.search(r'\b' + re.escape(word_lower) + r'\b', text_lower) is not None
    return word_lower in text_lower

def get_clean_category(cat_raw):
    clean = re.sub(r'[^\w\s]', '', cat_raw).strip().upper()
    return CAT_ALIASES.get(clean, '🌐')

def fetch_company_vacancies(session, employer_ids, area=None, schedule=None, period=7):
    all_items = []
    page = 0
    params = {"order_by": "publication_time", "per_page": 100, "period": period}
    if employer_ids:
        params["employer_id"] = employer_ids
    if area:
        params["area"] = area
    if schedule:
        params["schedule"] = schedule
    while page < 10:
        params["page"] = page
        try:
            resp = session.get("https://api.hh.ru/vacancies", params=params, timeout=10)
            if resp.status_code != 200:
                logging.warning(f"HH API company fetch: HTTP {resp.status_code}, page {page}")
                break
            data = resp.json()
            items = data.get("items", [])
            if not items:
                break
            all_items.extend(items)
            if page >= data.get('pages', 0) - 1:
                break
            page += 1
            time.sleep(0.2)
        except Exception as e:
            logging.warning(f"HH API error (company fetch, page {page}): {e}")
            break
    return all_items

def fetch_hh_paginated(session, text, period=7, schedule=None):
    all_items = []
    page = 0
    params = {"text": text, "order_by": "publication_time", "per_page": 100, "search_field": "name", "period": period}
    if schedule:
        params["schedule"] = schedule
    while page < 10:
        params["page"] = page
        try:
            resp = session.get("https://api.hh.ru/vacancies", params=params, timeout=10)
            if resp.status_code != 200:
                logging.warning(f"HH API search '{text}': HTTP {resp.status_code}, page {page}")
                break
            data = resp.json()
            items = data.get("items", [])
            if not items:
                break
            all_items.extend(items)
            if page >= data.get('pages', 0) - 1:
                break
            page += 1
            time.sleep(random.uniform(0.3, 1.0))
        except Exception as e:
            logging.warning(f"HH API error (search '{text}', page {page}): {e}")
            break
    return all_items

def get_vacancy_skills(session, vac_id, banal_skills):
    try:
        resp = session.get(f"https://api.hh.ru/vacancies/{vac_id}", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            raw_skills = [s['name'] for s in data.get('key_skills', [])]
            return [s for s in raw_skills if s.lower() not in banal_skills][:5]
    except Exception as e:
        logging.debug(f"Skills API error for vacancy {vac_id}: {e}")
    return []

def get_smart_sleep_time():
    now = get_moscow_time()
    if now.weekday() == 6 and now.hour >= 20:
        target = (now + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
        return (target - now).total_seconds(), target
    if now.weekday() >= 5:
        if now.hour < 11:
            target = now.replace(hour=11, minute=0, second=0, microsecond=0) + timedelta(minutes=random.randint(0, 30))
        elif now.hour < 23:
            target = now + timedelta(minutes=45 + random.randint(-5, 15))
        else:
            target = (now + timedelta(days=1)).replace(hour=11, minute=0, second=0, microsecond=0)
    else:
        if now.hour >= 23 or now.hour < 7:
            base_date = now if now.hour < 7 else now + timedelta(days=1)
            target = base_date.replace(hour=7, minute=10, second=0, microsecond=0) + timedelta(minutes=random.randint(0, 20))
        else:
            target = now + timedelta(minutes=20 + random.randint(0, 10))
    if target <= now:
        target = now + timedelta(minutes=5)
    return max(10, (target - now).total_seconds()), target
