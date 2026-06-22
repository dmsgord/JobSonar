# -*- coding: utf-8 -*-
import re
import sys
import time
import json
import signal
import logging
import random
import traceback as _traceback
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

HH_SEARCH_URL = "https://hh.ru/search/vacancy"
HH_VACANCY_URL = "https://hh.ru/vacancy/{}"

BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
}

# Маппинг area_id → варианты названий города (для geo-фильтра)
AREA_NAMES = {
    "1":  ["москва", "moscow", "московск"],
    "2":  ["санкт-петербург", "петербург", "спб", "saint-petersburg"],
    "66": ["нижний новгород", "нижегородск", "nizhny novgorod"],
    "3":  ["екатеринбург"],
    "54": ["новосибирск"],
    "88": ["казань"],
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


# ─────────────────────────────────────────────
#  Парсинг страницы hh.ru
# ─────────────────────────────────────────────

def _parse_salary(salary_text):
    """
    Парсит текст зарплаты в структуру как в старом API.
    "от 200 000 ₽" → {"from": 200000, "to": None, "currency": "RUR"}
    "до 300 000 ₽" → {"from": None, "to": 300000, "currency": "RUR"}
    "200 000 – 300 000 ₽" → {"from": 200000, "to": 300000, "currency": "RUR"}
    """
    if not salary_text:
        return None
    text = salary_text.strip().replace('\xa0', ' ').replace(' ', '')

    currency = "RUR"
    if '$' in text or 'USD' in text.upper():
        currency = "USD"
    elif '€' in text or 'EUR' in text.upper():
        currency = "EUR"

    nums = re.findall(r'\d+', text)
    if not nums:
        return None
    nums = [int(n) for n in nums if int(n) > 100]
    if not nums:
        return None

    sal_from = sal_to = None
    original = salary_text.lower()
    if 'от' in original or 'from' in original:
        sal_from = nums[0]
        if len(nums) > 1:
            sal_to = nums[1]
    elif 'до' in original or 'to' in original or 'up' in original:
        sal_to = nums[0]
    elif '–' in salary_text or '-' in salary_text or len(nums) >= 2:
        sal_from = nums[0]
        sal_to = nums[1] if len(nums) > 1 else None
    else:
        sal_from = nums[0]

    return {"from": sal_from, "to": sal_to, "currency": currency}


def _area_id_from_name(area_name):
    """Возвращает area_id по названию города, или '0' если не найден."""
    name_lower = area_name.lower()
    for area_id, variants in AREA_NAMES.items():
        if any(v in name_lower for v in variants):
            return area_id
    return "0"


def _extract_state_json(html):
    """Извлекает большой JSON-стейт страницы hh.ru."""
    try:
        # hh.ru встраивает стейт в тег с data-ssr-state-length
        m = re.search(r'data-ssr-state-length="\d+"[^>]*>', html)
        if m:
            start = m.end()
            if html[start] == '{':
                decoder = json.JSONDecoder()
                data, _ = decoder.raw_decode(html, start)
                return data
    except Exception as e:
        logging.debug(f"_extract_state_json error: {e}")
    return None


def _vacancies_from_state(state):
    """Достаёт список вакансий из стейта страницы. None = структура не распознана."""
    try:
        if "vacancySearchResult" not in state:
            return None
        vsr = state["vacancySearchResult"]
        # Ищем vacancies в разных возможных местах
        for key in ("vacancies", "items", "results"):
            if key in vsr:
                return vsr[key]
        # Иногда лежит глубже
        results = vsr.get("searchResult", {})
        for key in ("vacancies", "items"):
            if key in results:
                return results[key]
    except Exception as e:
        logging.debug(f"_vacancies_from_state error: {e}")
    return None


def _normalize_vacancy(raw):
    """
    Приводит вакансию из стейта hh.ru к формату как в старом API.
    Реальные имена полей в стейте (выявлены из анализа):
      vacancyId, name, company, compensation, publicationTime,
      area(@id), workExperience, workFormats, @workSchedule, links
    """
    # Если уже нормализовано
    if "alternate_url" in raw:
        return raw

    vac_id = str(raw.get("vacancyId", raw.get("id", "")))
    name = raw.get("name", "")
    url = (raw.get("links") or {}).get("desktop", f"https://hh.ru/vacancy/{vac_id}")

    # Работодатель
    comp = raw.get("company", raw.get("employer", {}))
    emp_id = str(comp.get("id", ""))
    emp_name = comp.get("visibleName", comp.get("name", ""))

    # Зарплата — compensation.currencyCode → currency, нет "to" в базовых данных
    comp_raw = raw.get("compensation", raw.get("salary"))
    if comp_raw:
        salary = {
            "from": comp_raw.get("from"),
            "to": comp_raw.get("to"),
            "currency": comp_raw.get("currencyCode", comp_raw.get("currency", "RUR")),
        }
    else:
        salary = None

    # Регион — area.@id (int), area.name
    area_raw = raw.get("area", {})
    area_id = str(area_raw.get("@id", area_raw.get("id", 0)))
    area_name = area_raw.get("name", "")

    # Опыт — workExperience: "between3And6" | "noExperience" | ...
    EXP_MAP = {
        "noExperience":   "Нет опыта",
        "between1And3":   "От 1 года до 3 лет",
        "between3And6":   "От 3 до 6 лет",
        "moreThan6":      "Более 6 лет",
    }
    work_exp = raw.get("workExperience", "")
    experience = {"id": work_exp, "name": EXP_MAP.get(work_exp, work_exp)}

    # Формат работы — workFormats: [{"workFormatsElement": ["REMOTE"]}]
    wf_list = raw.get("workFormats", [])
    work_format_ids = []
    for wf in wf_list:
        for el in wf.get("workFormatsElement", []):
            work_format_ids.append(el)
    WF_MAP = {
        "REMOTE": ("remote", "Удалённо"),
        "ON_SITE": ("onSite", "На месте работодателя"),
        "HYBRID": ("hybrid", "Гибрид"),
        "FIELD": ("field", "Разъездной"),
        "FIELD_WORK": ("field", "Разъездной"),
    }
    work_format = []
    for wf_id in work_format_ids:
        mapped = WF_MAP.get(wf_id, (wf_id.lower(), wf_id))
        work_format.append({"id": mapped[0], "name": mapped[1]})

    # График — @workSchedule: "remote" | "fullDay" | "shift" | ...
    SCHED_MAP = {
        "fullDay":    "Полный день",
        "remote":     "Удалённо",
        "shift":      "Сменный",
        "flexible":   "Гибкий",
        "flyInFlyOut": "Вахта",
    }
    sched_id = raw.get("@workSchedule", "")
    schedule = {"id": sched_id, "name": SCHED_MAP.get(sched_id, sched_id)}

    # Дата публикации — publicationTime.$
    pub_time = raw.get("publicationTime", {})
    published_at = pub_time.get("$", "") if isinstance(pub_time, dict) else ""

    # Сниппет — в стейте списка нет, заглушка
    snippet = {"requirement": "", "responsibility": ""}

    return {
        "id": vac_id,
        "name": name,
        "alternate_url": url,
        "employer": {"id": emp_id, "name": emp_name},
        "salary": salary,
        "area": {"id": area_id, "name": area_name},
        "schedule": schedule,
        "work_format": work_format,
        "experience": experience,
        "snippet": snippet,
        "published_at": published_at,
    }


# Анти-бот hh.ru: флагует долгоживущую сессию за частоту/объём запросов → 403 на всё.
# Свежая сессия с того же IP сразу получает 200 (проверено живыми тестами 2026-06-10).
_last_request_ts = 0.0
_next_refresh_allowed = 0.0


def _throttle():
    """Глобальная пауза между ЛЮБЫМИ запросами к hh.ru (1-2с с джиттером)."""
    global _last_request_ts
    wait = _last_request_ts + random.uniform(1.0, 2.0) - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_request_ts = time.monotonic()


def _refresh_session(session):
    """Сброс анти-бот куки + прогрев. Не чаще раза в 5 минут (если не помогло — не долбимся)."""
    global _next_refresh_allowed
    now = time.monotonic()
    if now < _next_refresh_allowed:
        return False
    _next_refresh_allowed = now + 300
    logging.info("hh.ru 403: сбрасываю сессию, пауза 20-40с, прогрев заново")
    session.cookies.clear()
    time.sleep(random.uniform(20, 40))
    try:
        session.get("https://hh.ru/", timeout=15)
        time.sleep(random.uniform(2, 4))
        return True
    except Exception as e:
        logging.warning(f"session refresh warm-up failed: {e}")
        return False


def _is_blocked(r):
    """403 или редирект на анти-бот заглушку /vpncheeck (отдаётся с кодом 200)."""
    return r.status_code == 403 or "vpncheeck" in r.url


def _fetch_page(session, params, page=0):
    """Загружает одну страницу поиска hh.ru и возвращает (items, total_pages)."""
    params = dict(params)
    params["page"] = page
    try:
        _throttle()
        r = session.get(HH_SEARCH_URL, params=params, timeout=15)
        if _is_blocked(r) and _refresh_session(session):
            _throttle()
            r = session.get(HH_SEARCH_URL, params=params, timeout=15)
        if "vpncheeck" in r.url:
            logging.warning(f"hh.ru анти-бот заглушка vpncheeck, page={page}")
            return [], 0
        if r.status_code != 200:
            logging.warning(f"hh.ru page fetch HTTP {r.status_code}, page={page}")
            return [], 0

        state = _extract_state_json(r.text)
        if not state:
            logging.warning(f"hh.ru: не удалось извлечь JSON стейт, page={page}")
            return [], 0

        raw_items = _vacancies_from_state(state)
        if raw_items is None:
            logging.warning(f"hh.ru: vacancies не найдены в стейте, page={page}")
            return [], 0

        items = [_normalize_vacancy(v) for v in raw_items]

        # Пагинация — реальное число страниц лежит в paging.lastPage / paging.pages.
        # (Старый код искал totalPages/pages на верхнем уровне — их там нет → всегда 1.)
        vsr = state.get("vacancySearchResult", {})
        total_pages = 1
        paging = vsr.get("paging") or {}
        last = paging.get("lastPage")
        if isinstance(last, dict) and last.get("page") is not None:
            total_pages = int(last["page"]) + 1
        else:
            pages_list = paging.get("pages") or []
            if pages_list:
                total_pages = max(int(p.get("page", 0)) for p in pages_list) + 1

        return items, int(total_pages)

    except Exception as e:
        logging.warning(f"hh.ru page fetch error (page={page}): {e}")
        return [], 0


# ─────────────────────────────────────────────
#  Публичные функции (те же сигнатуры что в старом utils.py)
# ─────────────────────────────────────────────

def fetch_hh_paginated(session, text, period=7, schedule=None, area=None, max_pages=1):
    """Поиск вакансий по ключевому слову через hh.ru (замена api.hh.ru).

    max_pages — сколько страниц читать максимум (по умолчанию 1: одна страница ≈ 50
    свежих вакансий). NN-бот передаёт больше; остальные боты сохраняют прежнее поведение.
    """
    params = {
        "text": text,
        "search_field": "name",
        "order_by": "publication_time",
        "per_page": 20,
    }
    if period:
        params["period"] = period
    if area:
        params["area"] = area
    # Новый параметр вместо deprecated schedule=remote
    if schedule == "remote":
        params["work_format"] = "remote"
    elif schedule:
        params["schedule"] = schedule

    all_items = []
    for page in range(max(1, max_pages)):
        items, total_pages = _fetch_page(session, params, page)
        all_items.extend(items)
        if not items or page >= total_pages - 1:
            break

    return all_items


def fetch_company_vacancies(session, employer_ids, area=None, schedule=None, period=7, max_pages=1):
    """Поиск вакансий по списку employer_id через hh.ru."""
    params = {
        "order_by": "publication_time",
        "per_page": 20,
    }
    if employer_ids:
        # hh.ru принимает несколько employer_id через &employer_id=...&employer_id=...
        params["employer_id"] = employer_ids
    if area:
        params["area"] = area
    if period:
        params["period"] = period
    if schedule == "remote":
        params["work_format"] = "remote"
    elif schedule:
        params["schedule"] = schedule

    all_items = []
    for page in range(max(1, max_pages)):
        items, total_pages = _fetch_page(session, params, page)
        all_items.extend(items)
        if not items or page >= total_pages - 1:
            break

    return all_items


def build_details(item):
    """Собирает форматы работы вакансии: (['Удалённо', ...], 'удалённо, ...')."""
    details = []
    raw_schedule = item.get('schedule', {})
    raw_formats = item.get('work_format', [])
    if raw_schedule:
        if raw_schedule.get('name') not in [f['name'] for f in raw_formats]:
            details.append(raw_schedule.get('name'))
    for f in raw_formats:
        details.append(f['name'])
    return details, ", ".join(details).lower()


def format_salary(sal, threshold):
    """
    Возвращает (salary_text, is_bold, skip).
    Семантика (одинакова для всех ботов): зарплата не указана → показываем "-";
    RUR ниже порога → skip; RUR выше порога и любые USD/EUR → жирным.
    """
    if not sal:
        return "-", False, False
    currency = sal.get('currency')
    lower = sal.get('from')
    upper = sal.get('to')
    if currency == 'RUR':
        if lower and lower >= threshold:
            return f"от {lower} ₽", True, False
        if upper and upper >= threshold:
            return f"до {upper} ₽", True, False
        if lower or upper:
            return "-", False, True
        return "-", False, False
    if currency in ['USD', 'EUR']:
        if lower and upper:
            return f"{lower}–{upper} {currency}", True, False
        if lower:
            return f"от {lower} {currency}", True, False
        if upper:
            return f"до {upper} {currency}", True, False
    return "-", False, False


def format_pub_date(item):
    """'2026-06-09T...' → '09.06'. Не падает, если дата пустая."""
    dt = item.get('published_at', '').split('T')[0]
    parts = dt.split('-')
    if len(parts) == 3:
        return f"{parts[2]}.{parts[1]}"
    return "-"


def is_individual_person(emp_name):
    """Эвристика: работодатель — частное лицо/ИП, а не компания (для Sales/Recruiter)."""
    name_lower = emp_name.lower().strip()
    if 'ип ' in name_lower or ' ип' in name_lower or '(ип' in name_lower:
        return True
    # Инициалы: "иванов и.и." (одиночная буква с точкой)
    if re.search(r'(^|\s)[а-яa-z]\.', name_lower):
        return True
    parts = re.split(r'[\s-]+', name_lower)
    for part in parts:
        if part.endswith(('вич', 'вна', 'оглы', 'кызы')):
            return True
    if len(parts) == 1:
        surname_endings = ('ов', 'ова', 'ев', 'ева', 'ин', 'ина', 'ский', 'ская', 'ая', 'ый')
        if name_lower.endswith(surname_endings):
            if not any(s in name_lower for s in ['групп', 'софт', 'tech']):
                return True
    corp_whitelist = ['ооо', 'ао', 'пао', 'llc', 'групп', 'софт', 'tech', 'студия', 'agency', 'онлайн', 'бизнес']
    if any(marker in name_lower for marker in corp_whitelist):
        return False
    if 2 <= len(parts) <= 4 and bool(re.search('[а-я]', name_lower)):
        return True
    return False


def report_error(e: Exception, token: str, chat_id: str, context: str = ""):
    tb = _traceback.format_exc()
    logging.error(f"Error{f' in {context}' if context else ''}: {e}\n{tb}")
    try:
        msg = f"🔥 <b>Ошибка бота{f' ({context})' if context else ''}:</b>\n<code>{str(e)[:300]}</code>"
        send_telegram(token, chat_id, msg)
    except Exception as _tg_err:
        logging.debug(f"report_error: failed to send Telegram notification: {_tg_err}")


def send_daily_stats(bot_name: str, token: str, chat_id: str, stats: dict):
    total = sum(stats.values())
    top = stats.get('Топ компании', 0)
    others = stats.get('Остальные', 0)
    msg = (
        f"🌙 <b>Итоги {bot_name}:</b>\n"
        f"Топ компании: {top}\n"
        f"Остальные: {others}\n"
        f"Всего: {total}"
    )
    send_telegram(token, chat_id, msg)


class BotContext:
    def __init__(self, token: str, chat_id: str, status_file: str, db_path: str):
        from db import set_db_name
        self.token = token
        self.chat_id = chat_id
        self.status_file = status_file
        self.session = requests.Session()
        self.session.headers.update(BROWSER_HEADERS)
        self.last_update_id = 0
        self.bot_id = token.split(':')[0] if token else "0"
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
        set_db_name(db_path)

    def set_status(self, text: str):
        set_status(self.status_file, text)

    def send_telegram(self, text: str):
        send_telegram(self.token, self.chat_id, text)

    def check_remote_stop(self):
        self.last_update_id = check_remote_stop(
            self.token, self.chat_id, self.bot_id, self.last_update_id
        )

    def fetch_company_vacancies(self, employer_ids, area=None, schedule=None, period=7, max_pages=1):
        return fetch_company_vacancies(self.session, employer_ids, area=area, schedule=schedule, period=period, max_pages=max_pages)

    def fetch_hh_paginated(self, text: str, period: int = 7, schedule=None, area=None, max_pages=1):
        return fetch_hh_paginated(self.session, text, period=period, schedule=schedule, area=area, max_pages=max_pages)


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
