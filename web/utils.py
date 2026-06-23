# -*- coding: utf-8 -*-
import os
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


def fetch_hh_search(session, params, max_pages=1):
    """Гибкий поиск hh.ru по произвольному набору параметров (professional_role, OR-text и т.д.)."""
    base = {"order_by": "publication_time", "per_page": 20}
    base.update(params)
    all_items = []
    for page in range(max(1, max_pages)):
        items, total_pages = _fetch_page(session, base, page)
        all_items.extend(items)
        if not items or page >= total_pages - 1:
            break
    return all_items


# ─────────────────────────────────────────────
#  Хабр Карьера — keyless JSON-фид фронта (без ключа/регистрации). Только для NN-бота.
# ─────────────────────────────────────────────

HABR_VAC_API = "https://career.habr.com/api/frontend/vacancies"


def _normalize_habr(raw, area_name=""):
    """Вакансия Хабр Карьеры → наш стандартный словарь (как _normalize_vacancy для hh)."""
    vac_id = str(raw.get("id", ""))
    name = raw.get("title", "") or ""
    href = raw.get("href", "") or ""
    url = f"https://career.habr.com{href}" if href.startswith("/") else (href or f"https://career.habr.com/vacancies/{vac_id}")

    comp = raw.get("company") or {}
    sal = raw.get("salary") or {}
    sfrom, sto = sal.get("from"), sal.get("to")
    cur = sal.get("currency") or "RUR"
    cur = {"rub": "RUR", "RUB": "RUR", "rur": "RUR"}.get(cur, str(cur).upper())
    salary = {"from": sfrom, "to": sto, "currency": cur} if (sfrom or sto) else None

    pub = raw.get("publishedDate") or {}
    published_at = pub.get("date", "") if isinstance(pub, dict) else ""

    EMP_MAP = {"full_time": "Полный день", "part_time": "Частичная занятость", "project": "Проектная работа", "internship": "Стажировка"}
    schedule = {"id": "", "name": EMP_MAP.get(raw.get("employment", ""), "")}
    work_format = []
    if raw.get("remoteWork"):
        work_format.append({"id": "remote", "name": "Удалённо"})

    return {
        "id": vac_id,
        "name": name,
        "alternate_url": url,
        "employer": {"id": str(comp.get("id", "")), "name": comp.get("title", "") or ""},
        "salary": salary,
        "area": {"id": "", "name": area_name},
        "schedule": schedule,
        "work_format": work_format,
        "experience": {"id": "", "name": ""},
        "snippet": {"requirement": "", "responsibility": ""},
        "published_at": published_at,
    }


def fetch_habr_career(location_code, location_name, period=3, max_pages=3, keyword=None):
    """Вакансии города (location_code, напр. c_715) с Хабр Карьеры по ключевику. Без ключа."""
    headers = {"User-Agent": BROWSER_HEADERS["User-Agent"], "Accept": "application/json"}
    cutoff = (get_moscow_time() - timedelta(days=period)).date()

    all_items = []
    for page in range(1, max_pages + 1):
        params = [("sort", "date"), ("type", "all"), ("page", page), ("locations[]", location_code)]
        if keyword:
            params.append(("q", keyword))
        try:
            r = requests.get(HABR_VAC_API, params=params, headers=headers, timeout=15)
            if r.status_code != 200:
                logging.warning(f"Habr Career HTTP {r.status_code}, page={page}")
                break
            data = r.json()
            lst = data.get("list", [])
            if not lst:
                break
            stop = False
            for raw in lst:
                item = _normalize_habr(raw, location_name)
                pa = (item["published_at"] or "")[:10]
                if pa:
                    try:
                        if datetime.strptime(pa, "%Y-%m-%d").date() < cutoff:
                            stop = True
                            continue
                    except ValueError:
                        pass
                all_items.append(item)
            if stop or page >= data.get("meta", {}).get("totalPages", 1):
                break
            time.sleep(0.4)
        except Exception as e:
            logging.warning(f"Habr Career fetch error (page={page}): {e}")
            break
    return all_items


# ─────────────────────────────────────────────
#  Работа.ру — парсинг JSON-LD JobPosting со страницы (без ключа). Только для NN-бота.
#  nn.rabota.ru = Нижний Новгород и область; гео-отсев по городу — в is_target_geo.
# ─────────────────────────────────────────────

RABOTA_SEARCH_URL = "https://nn.rabota.ru/vacancy/"


def _normalize_rabota(jp):
    """JobPosting (schema.org) с rabota.ru → наш стандартный словарь."""
    title = jp.get("title", "") or ""
    url = jp.get("url", "") or ""
    m = re.search(r'/vacancy/(\d+)', url)
    vac_id = m.group(1) if m else url

    org = jp.get("hiringOrganization") or {}

    bs = jp.get("baseSalary") or {}
    est_val = (jp.get("estimatedSalary") or {}).get("value") or {}
    sfrom = bs.get("minValue") or est_val.get("minValue") or None   # 0 → None
    sto = bs.get("maxValue") or None
    cur = bs.get("currency") or (jp.get("estimatedSalary") or {}).get("currency") or "RUB"
    cur = {"RUB": "RUR"}.get(cur, cur)
    salary = {"from": sfrom, "to": sto, "currency": cur} if (sfrom or sto) else None

    addr = ((jp.get("jobLocation") or {}).get("address") or {}).get("streetAddress", "") or ""
    # последний сегмент адреса = город (Нижний Новгород / Дзержинск / Арзамас …).
    # Адрес пуст → не угадываем город, но это nn-регион → метим «Нижегородская область»
    # (пройдёт по маркеру 'нижегородск'; явные не-целевые города вроде Арзамаса отсекутся).
    city = addr.split(",")[-1].strip() if addr else "Нижегородская область"

    return {
        "id": vac_id,
        "name": title,
        "alternate_url": url,
        "employer": {"id": "", "name": org.get("name", "") or ""},
        "salary": salary,
        "area": {"id": "", "name": city},
        "schedule": {"id": "", "name": ""},
        "work_format": [],
        "experience": {"id": "", "name": ""},
        "snippet": {"requirement": "", "responsibility": ""},
        "published_at": jp.get("datePosted", "") or "",
    }


# rabota.ru блокирует датацентр-IP при бёрсте запросов (TCP-таймаут). Поэтому:
# переиспользуемая сессия + прогрев, троттл между запросами и circuit breaker —
# после серии таймаутов перестаём долбить до следующего цикла.
_rabota_session = None
_rabota_fail_streak = 0
_rabota_last_ts = 0.0
_RABOTA_MIN_GAP = 3.0
_RABOTA_MAX_FAILS = 3


def reset_rabota_breaker():
    """Сброс счётчика отказов rabota.ru — вызывать в начале каждого цикла бота."""
    global _rabota_fail_streak
    _rabota_fail_streak = 0


def _get_rabota_session():
    global _rabota_session
    if _rabota_session is None:
        s = requests.Session()
        s.headers.update(BROWSER_HEADERS)
        s.headers["Accept-Language"] = "ru-RU,ru;q=0.9"
        # rabota.ru банит BY-IP → весь rabota-трафик через SOCKS-туннель на RU-сервер
        # (RABOTA_PROXY=socks5h://127.0.0.1:1080). Если не задан — ходим напрямую.
        proxy = os.getenv("RABOTA_PROXY")
        if proxy:
            s.proxies = {"http": proxy, "https": proxy}
        try:
            s.get("https://nn.rabota.ru/", timeout=(8, 15))  # прогрев: куки
        except Exception:
            pass
        _rabota_session = s
    return _rabota_session


def fetch_rabota(keyword, period=14):
    """Свежие вакансии rabota.ru (НН и область) по ключевику из JSON-LD JobPosting."""
    global _rabota_fail_streak, _rabota_last_ts
    if _rabota_fail_streak >= _RABOTA_MAX_FAILS:
        return []  # circuit breaker: rabota недоступна в этом цикле, не долбим

    gap = _rabota_last_ts + _RABOTA_MIN_GAP - time.monotonic()
    if gap > 0:
        time.sleep(gap)
    _rabota_last_ts = time.monotonic()

    cutoff = (get_moscow_time() - timedelta(days=period)).date()
    try:
        s = _get_rabota_session()
        r = s.get(RABOTA_SEARCH_URL, params={"query": keyword}, timeout=(8, 15))
        if r.status_code != 200:
            logging.warning(f"rabota.ru HTTP {r.status_code} (q={keyword})")
            _rabota_fail_streak += 1
            return []
        _rabota_fail_streak = 0
        m = re.search(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', r.text, re.S)
        if not m:
            return []
        arr = json.loads(m.group(1))
        jps = [x for x in (arr if isinstance(arr, list) else [arr])
               if isinstance(x, dict) and x.get("@type") == "JobPosting"]
    except Exception as e:
        _rabota_fail_streak += 1
        logging.warning(f"rabota.ru fetch error (q={keyword}): {str(e)[:120]}")
        return []

    items = []
    for jp in jps:
        item = _normalize_rabota(jp)
        pa = (item["published_at"] or "")[:10]
        if pa:
            try:
                if datetime.strptime(pa, "%Y-%m-%d").date() < cutoff:
                    continue
            except ValueError:
                pass
        items.append(item)
    return items


def _rabota_clean(x):
    if not x:
        return None
    x = x.replace("\\u002F", "/").replace("\\/", "/")
    x = re.split(r'[<"\\]', x)[0]
    x = re.sub(r'\s+', ' ', x).strip(" :,.;")
    return x[:45] or None


def fetch_rabota_details(url):
    """Дотягивает (график, опыт) со страницы вакансии rabota.ru. Best-effort → (None, None)."""
    if not url:
        return None, None
    try:
        s = _get_rabota_session()
        time.sleep(0.6)
        r = s.get(url, timeout=(8, 15))
        if r.status_code != 200:
            return None, None
        d = r.text
    except Exception as e:
        logging.debug(f"rabota details error: {e}")
        return None, None

    # Опыт: структурный блок "опыт работы X, образование Y" (надёжно)
    exp = None
    m = re.search(r'[Оо]пыт работы\s+([^<",]{2,35}?),?\s*образовани', d)
    if not m:
        m = re.search(r'[Оо]пыт работы\s+(от[^<",]{2,25}|[Бб]ез опыта)', d)
    if m:
        exp = _rabota_clean(m.group(1))

    # График: где указан явно
    sched = None
    m = re.search(r'график работы[:\s]+([^<"]{2,40})', d)
    if m:
        sched = _rabota_clean(m.group(1))
    return sched, exp


# ─────────────────────────────────────────────
#  SuperJob — официальный публичный API (X-Api-App-Id, без OAuth/оплаты для ЧТЕНИЯ вакансий).
#  Курс «без ключей» — сделано исключение по запросу владельца (сайт за капчей, парсер невозможен).
#  Гео НН/Дзержинск отдаём API через t=[town_ids]: 12=Нижний Новгород, 639=Дзержинск (Нижегор. обл.).
#  Ключ в env SUPERJOB_APP_ID; при блокировке api.superjob.ru с BY-IP — env SUPERJOB_PROXY (RU-туннель).
# ─────────────────────────────────────────────

SUPERJOB_API_URL = "https://api.superjob.ru/2.0/vacancies/"
_sj_session = None
_sj_last_ts = 0.0
_SJ_MIN_GAP = 0.6  # лимит API = 120 запросов/мин с IP → держим ≥0.5с между запросами


def _get_sj_session():
    global _sj_session
    if _sj_session is None:
        s = requests.Session()
        s.headers.update({"User-Agent": "JobSonarBot/1.0 (NN)",
                          "X-Api-App-Id": os.getenv("SUPERJOB_APP_ID", "")})
        proxy = os.getenv("SUPERJOB_PROXY")  # задать, только если BY-IP заблокирован
        if proxy:
            s.proxies = {"http": proxy, "https": proxy}
        _sj_session = s
    return _sj_session


def _normalize_superjob(o):
    """Вакансия SuperJob API → наш стандартный словарь (как _normalize_vacancy для hh)."""
    vac_id = str(o.get("id", ""))
    pf = o.get("payment_from") or 0      # 0 = зарплата не указана
    pt = o.get("payment_to") or 0
    cur = {"rub": "RUR", "RUB": "RUR"}.get(o.get("currency", "rub"),
                                           (o.get("currency") or "RUR").upper())
    salary = {"from": pf or None, "to": pt or None, "currency": cur} if (pf or pt) else None

    town = o.get("town") or {}
    place = ((o.get("place_of_work") or {}).get("title", "") or "").lower()
    if "удал" in place:
        wf = [{"id": "remote", "name": "Удалённо"}]
    elif "территории работодател" in place:
        wf = [{"id": "onSite", "name": "На месте работодателя"}]
    elif "разъезд" in place:
        wf = [{"id": "field", "name": "Разъездной"}]
    else:
        wf = []

    exp_title = (o.get("experience") or {}).get("title", "") or ""
    exp_id = "noExperience" if "без опыта" in exp_title.lower() else ""

    ts = o.get("date_published")
    published_at = ""
    if ts:
        try:
            published_at = datetime.fromtimestamp(int(ts), MOSCOW_TZ).strftime("%Y-%m-%dT%H:%M:%S")
        except (ValueError, OSError, TypeError):
            published_at = ""

    return {
        "id": vac_id,
        "name": o.get("profession", "") or "",
        "alternate_url": o.get("link", "") or f"https://www.superjob.ru/vakansii/{vac_id}.html",
        "employer": {"id": str(o.get("id_client", "")), "name": o.get("firm_name", "") or ""},
        "salary": salary,
        "area": {"id": str(town.get("id", "")), "name": town.get("title", "") or ""},
        "schedule": {"id": "", "name": (o.get("type_of_work") or {}).get("title", "") or ""},
        "work_format": wf,
        "experience": {"id": exp_id, "name": exp_title},
        "snippet": {"requirement": (o.get("candidat") or "")[:300], "responsibility": ""},
        "published_at": published_at,
    }


def fetch_superjob(keyword, town_ids=(12, 639), period=3, max_pages=2):
    """Свежие вакансии SuperJob (НН+Дзержинск через t=town_ids) по ключевику.
    Публичный /2.0/vacancies/ с X-Api-App-Id. Нет ключа/ошибка → []."""
    global _sj_last_ts
    if not os.getenv("SUPERJOB_APP_ID"):
        return []
    s = _get_sj_session()
    items = []
    for page in range(max(1, max_pages)):
        gap = _sj_last_ts + _SJ_MIN_GAP - time.monotonic()
        if gap > 0:
            time.sleep(gap)
        _sj_last_ts = time.monotonic()
        # keywords[0] с srws=1 = поиск В ДОЛЖНОСТИ (аналог hh search_field=name),
        # skwc=and = все слова. Простой keyword= даёт мусорный полнотекст ("Учетчик на склад").
        params = [("keywords[0][keys]", keyword), ("keywords[0][srws]", 1),
                  ("keywords[0][skwc]", "and"), ("period", period),
                  ("order_field", "date"), ("count", 100), ("page", page)]
        # ВАЖНО: массив городов — это t[]=12&t[]=639. Простой t=12&t=639 API схлопывает
        # до последнего города (терялся весь Нижний Новгород!). t[] = корректное объединение.
        for t in town_ids:
            params.append(("t[]", t))
        try:
            r = s.get(SUPERJOB_API_URL, params=params, timeout=(8, 15))
            if r.status_code != 200:
                logging.warning(f"SuperJob HTTP {r.status_code} (q={keyword})")
                break
            data = r.json()
        except Exception as e:
            logging.warning(f"SuperJob fetch error (q={keyword}): {str(e)[:120]}")
            break
        items.extend(_normalize_superjob(o) for o in data.get("objects", []))
        if not data.get("more"):
            break
    return items


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

    def fetch_hh_search(self, params, max_pages=1):
        return fetch_hh_search(self.session, params, max_pages=max_pages)


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
