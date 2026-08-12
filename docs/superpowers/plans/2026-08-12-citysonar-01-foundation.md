# CitySonar — План 1: фундамент и сбор данных (Э0 + Э1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Поднять харвестер, который собирает вакансии с hh.ru в собственную БД и следит за контрактом страницы, ничего не публикуя. Через 24 часа работы данных хватает на расчёт порогов зарплат — дальше идёт План 2.

**Про свежесть:** ни одна собранная здесь вакансия не попадёт в канал по факту накопления. Публикация появляется только в Плане 2 и гейтится двумя условиями сразу: `published_at ≥ now - 48ч` и `first_seen ≥ момент go-live канала` (спека §6a). Гейт стоит на `published_at` намеренно — холодный старт тянет `period=7`, и семидневной давности вакансия получила бы `first_seen = сейчас`, то есть отсечка только по `first_seen` пропустила бы старьё в канал.

**Architecture:** Один резидентный процесс `worker.py` со стадиями внутри цикла; шов между стадиями — таблицы SQLite. Парсинг hh.ru — извлечение SSR JSON-стейта из HTML-страницы поиска (официальный API закрыт). Валидация формы стейта — pydantic-модель, чтобы смена разметки давала громкую ошибку, а не тихие нули.

**Tech Stack:** Python 3.8, `requests`, `pydantic` v2, SQLite (WAL), pytest, systemd.

**Спека:** `docs/superpowers/specs/2026-08-12-citysonar-design.md`. Расхождение плана со спекой — ошибка плана; при обнаружении править план, а не молча отклоняться.

## Global Constraints

- **Python 3.8** — целевая версия (Ubuntu 20.04 на сервере). Каждый модуль начинается с `from __future__ import annotations`. Запрещены во время выполнения: `list[str]` / `dict[str, int]` в местах, вычисляемых в рантайме (dataclass-поля, `TypeAdapter`), оператор `|` в аннотациях типов, `str.removeprefix`, `math.lcm`, walrus в comprehension-условиях со сложной областью видимости.
- **CitySonar не импортирует ничего из `web/`.** Ни одного `from utils import`, ни одного `sys.path` хака. Код парсинга копируется и живёт своей жизнью. Правка CitySonar не должна иметь физической возможности сломать 7 рабочих ботов.
- **Ни один файл в `web/`, `config*.py`, `utils.py`, `db.py`, `whitelist.py` не изменяется этим планом.**
- **Все временные метки — UTC ISO-8601** (`2026-08-12T09:30:00+00:00`). Курсор сравнивается как строка, поэтому единый формат обязателен.
- **Каждый HTTP-запрос к hh.ru проходит через `throttle.acquire()`.** Прямые `session.get` к hh вне этой обёртки запрещены.
- **Никаких браузеров** (Playwright/Selenium) — 1 ГБ RAM на сервере.
- **Комментарии, докстринги и сообщения в Telegram — по-русски**, как в существующем коде проекта.
- **Тесты не ходят в сеть.** Всё, что касается парсинга, тестируется на сохранённых фикстурах. Единственное исключение — `tools/`-скрипты, они не тесты.
- Коммиты частые, префиксы `feat:` / `fix:` / `test:` / `docs:` / `chore:`.

## File Structure

```
citysonar/
  __init__.py
  worker.py                 резидент: цикл стадий
  canary.py                 разовый запуск по таймеру
  core/
    __init__.py
    store.py                соединение, pragma, схема, доступ к таблицам
    throttle.py             межпроцессный троттл через таблицу rate_token
    schema.py               pydantic-модели SSR-стейта hh.ru
    hh.py                   HTTP, извлечение стейта, нормализация, пагинация
    cursor.py               инкрементальные курсоры обхода
    retention.py            TTL, incremental_vacuum, ротация дампов
  config/
    cities.yaml             города и area_id агломераций
    roles.yaml              роли и ключевики для обхода
  tools/
    capture_fixture.py      сохранить живую страницу hh в фикстуру
    measure_volumes.py      замер Э0: города, роли, объёмы
  tests/
    __init__.py
    conftest.py
    fixtures/
      search_page.html.gz   живая страница поиска hh
    test_store.py
    test_throttle.py
    test_schema.py
    test_hh_normalize.py
    test_hh_paging.py
    test_cursor.py
    test_retention.py
    test_canary.py
  citysonar.service
  citysonar-canary.service
  citysonar-canary.timer
  citysonar-alert@.service
  requirements.txt
  README.md
```

Ответственности не пересекаются: `hh.py` знает про HTTP и форму данных hh, но не знает про БД сверх передачи соединения в троттл; `store.py` знает про SQLite, но не про hh; `cursor.py` знает про инкрементальность, но не про то, откуда берутся вакансии.

---

### Task 1: Каркас проекта и проверка окружения

**Files:**
- Create: `citysonar/__init__.py`, `citysonar/core/__init__.py`, `citysonar/tests/__init__.py`
- Create: `citysonar/requirements.txt`
- Create: `citysonar/tests/conftest.py`
- Create: `citysonar/README.md`
- Create: `citysonar/.gitignore`

**Interfaces:**
- Consumes: ничего
- Produces: `tmp_db` pytest-фикстура — путь к временной БД (`pathlib.Path`), пересоздаётся на каждый тест

- [ ] **Step 1: Проверить версию Python на сервере**

Прямой SSH на BY-сервер с машины владельца не идёт — ходим через RU-сервер как jump host (см. память проекта, `server_config.md`).

Run:
```bash
ssh -J root@194.87.248.87 root@45.134.26.151 'python3 --version && free -m && df -h / && swapon --show'
```

Ожидается: `Python 3.8.x`. Записать фактический вывод в `citysonar/README.md` разделом «Окружение сервера на момент старта».

Если версия окажется **ниже 3.8** — остановиться и сообщить: план рассчитан на 3.8.
Если **3.9+** — ограничение из Global Constraints остаётся в силе (пишем совместимо с 3.8), но зафиксировать факт в README.

Заодно это выполняет замер RAM из Э0 (§8 спеки): если свободной памяти меньше 250 МБ — остановиться и вынести вопрос о железе владельцу с цифрами.

- [ ] **Step 2: Проверить, что pydantic v2 ставится на серверный Python**

Run:
```bash
ssh -J root@194.87.248.87 root@45.134.26.151 'python3 -m pip download "pydantic>=2.0,<2.10" -d /tmp/pydcheck --no-deps -q && ls /tmp/pydcheck && rm -rf /tmp/pydcheck'
```

Ожидается: скачался wheel вида `pydantic-2.9.x-py3-none-any.whl`.
Верхняя граница `<2.10` стоит потому, что pydantic 2.10+ поднял минимальную версию Python до 3.9.

Если wheel не скачивается (нет сети / нет pip) — остановиться и сообщить.

- [ ] **Step 3: Создать структуру каталогов и файлы пакета**

```bash
mkdir -p citysonar/core citysonar/config citysonar/tools citysonar/tests/fixtures
touch citysonar/__init__.py citysonar/core/__init__.py citysonar/tests/__init__.py
```

`citysonar/requirements.txt`:
```
requests>=2.28
pydantic>=2.0,<2.10
PyYAML>=5.4
```

`citysonar/.gitignore`:
```
*.db
*.db-wal
*.db-shm
dumps/
log_*.txt
status_*.txt
__pycache__/
```

`citysonar/README.md`:
```markdown
# CitySonar

Сеть Telegram-каналов «город × роль» на вакансиях hh.ru.
Дизайн: `docs/superpowers/specs/2026-08-12-citysonar-design.md`

Код полностью изолирован от `web/` — ничего оттуда не импортирует.
Правка CitySonar не может сломать работающие боты JobSonar.

## Окружение сервера на момент старта

(заполняется в Task 1 Step 1)

## Запуск тестов

    python -m pytest citysonar/tests -v

Тесты не ходят в сеть.
```

- [ ] **Step 4: Написать conftest.py**

`citysonar/tests/conftest.py`:
```python
from __future__ import annotations

import gzip
import pathlib

import pytest

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture
def tmp_db(tmp_path):
    """Путь к временной БД. Файла ещё нет — схему создаёт сам тест."""
    return tmp_path / "citysonar_test.db"


@pytest.fixture
def search_page_html():
    """HTML живой страницы поиска hh.ru из фикстуры (Task 3)."""
    path = FIXTURES / "search_page.html.gz"
    if not path.exists():
        pytest.skip("фикстура search_page.html.gz не снята, см. tools/capture_fixture.py")
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return fh.read()
```

- [ ] **Step 5: Поставить dev-зависимости локально и убедиться, что pytest видит пакет**

Run:
```bash
python -m pip install -r citysonar/requirements.txt pytest
python -m pytest citysonar/tests -v
```

Ожидается: `no tests ran` (тестов ещё нет), **без ошибок импорта или коллекции**.

- [ ] **Step 6: Commit**

```bash
git add citysonar/
git commit -m "chore(citysonar): каркас проекта, зависимости, pytest conftest"
```

---

### Task 2: Хранилище — соединение, pragma, схема

**Files:**
- Create: `citysonar/core/store.py`
- Test: `citysonar/tests/test_store.py`

**Interfaces:**
- Consumes: `tmp_db` из conftest
- Produces:
  - `store.connect(db_path: str) -> sqlite3.Connection` — одно долгоживущее соединение с выставленными pragma
  - `store.init_schema(conn) -> None` — идемпотентное создание всех таблиц
  - `store.upsert_vacancy(conn, v: dict) -> bool` — `True` если строка новая, `False` если уже была
  - `store.count_vacancies(conn) -> int`
  - Ключи словаря вакансии (используются во всех последующих задачах): `uid, source, source_id, title, employer_id, employer_name, area_id, area_name, salary_from, salary_to, salary_currency, work_formats, schedule_id, experience_id, published_at, url, raw, signature`

- [ ] **Step 1: Написать падающие тесты**

`citysonar/tests/test_store.py`:
```python
from __future__ import annotations

from citysonar.core import store


def _vac(uid="hh_1", title="Аналитик данных", employer_id="1740"):
    return {
        "uid": uid,
        "source": "hh",
        "source_id": uid.split("_", 1)[1],
        "title": title,
        "employer_id": employer_id,
        "employer_name": "Яндекс",
        "area_id": "1",
        "area_name": "Москва",
        "salary_from": 200000,
        "salary_to": None,
        "salary_currency": "RUR",
        "work_formats": "remote,hybrid",
        "schedule_id": "remote",
        "experience_id": "between3And6",
        "published_at": "2026-08-12T09:00:00+00:00",
        "url": "https://hh.ru/vacancy/1",
        "raw": '{"vacancyId": 1}',
        "signature": "1740_аналитикданных",
    }


def test_pragmas_applied(tmp_db):
    conn = store.connect(str(tmp_db))
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    # auto_vacuum INCREMENTAL == 2
    assert conn.execute("PRAGMA auto_vacuum").fetchone()[0] == 2


def test_init_schema_creates_all_tables(tmp_db):
    conn = store.connect(str(tmp_db))
    store.init_schema(conn)
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    names = {r[0] for r in rows}
    expected = {
        "vacancies", "cities", "roles", "channels", "outbox",
        "crawl_cursor", "rate_token", "tg_offset", "employers",
        "salary_stats", "canary_runs",
    }
    assert expected <= names


def test_init_schema_is_idempotent(tmp_db):
    conn = store.connect(str(tmp_db))
    store.init_schema(conn)
    store.init_schema(conn)  # второй раз не должен падать
    assert store.count_vacancies(conn) == 0


def test_upsert_vacancy_returns_true_for_new_false_for_existing(tmp_db):
    conn = store.connect(str(tmp_db))
    store.init_schema(conn)
    assert store.upsert_vacancy(conn, _vac()) is True
    assert store.upsert_vacancy(conn, _vac()) is False
    assert store.count_vacancies(conn) == 1


def test_upsert_vacancy_sets_first_seen(tmp_db):
    conn = store.connect(str(tmp_db))
    store.init_schema(conn)
    store.upsert_vacancy(conn, _vac())
    got = conn.execute("SELECT first_seen FROM vacancies WHERE uid='hh_1'").fetchone()[0]
    assert got is not None and got.endswith("+00:00")


def test_upsert_vacancy_does_not_overwrite_first_seen(tmp_db):
    conn = store.connect(str(tmp_db))
    store.init_schema(conn)
    store.upsert_vacancy(conn, _vac())
    first = conn.execute("SELECT first_seen FROM vacancies WHERE uid='hh_1'").fetchone()[0]
    v = _vac()
    v["title"] = "Аналитик данных (обновлено)"
    store.upsert_vacancy(conn, v)
    second = conn.execute("SELECT first_seen FROM vacancies WHERE uid='hh_1'").fetchone()[0]
    assert first == second
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `python -m pytest citysonar/tests/test_store.py -v`
Ожидается: FAIL — `ModuleNotFoundError: No module named 'citysonar.core.store'`

- [ ] **Step 3: Написать store.py**

`citysonar/core/store.py`:
```python
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS vacancies (
  uid TEXT PRIMARY KEY,
  source TEXT, source_id TEXT,
  title TEXT, employer_id TEXT, employer_name TEXT,
  area_id TEXT, area_name TEXT,
  salary_from INTEGER, salary_to INTEGER, salary_currency TEXT,
  work_formats TEXT,
  schedule_id TEXT, experience_id TEXT,
  published_at TEXT,
  url TEXT,
  raw TEXT,
  first_seen TEXT,
  signature TEXT
);
CREATE INDEX IF NOT EXISTS ix_vac_pub ON vacancies(published_at);
CREATE INDEX IF NOT EXISTS ix_vac_sig ON vacancies(signature);
CREATE INDEX IF NOT EXISTS ix_vac_emp ON vacancies(employer_id);

CREATE TABLE IF NOT EXISTS cities (
  code TEXT PRIMARY KEY, name TEXT, area_ids TEXT, enabled INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS roles (
  code TEXT PRIMARY KEY, name TEXT, enabled INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS channels (
  id INTEGER PRIMARY KEY,
  city_code TEXT, role_code TEXT,
  chat_id TEXT UNIQUE, title TEXT,
  min_salary_local INTEGER, min_salary_remote INTEGER,
  skip_no_experience INTEGER DEFAULT 1,
  require_top_for_remote INTEGER DEFAULT 1,
  state TEXT DEFAULT 'pending',
  UNIQUE(city_code, role_code)
);

CREATE TABLE IF NOT EXISTS outbox (
  id INTEGER PRIMARY KEY,
  channel_id INTEGER, vacancy_uid TEXT,
  branch TEXT, score REAL, state TEXT DEFAULT 'queued',
  tg_message_id INTEGER, attempts INTEGER DEFAULT 0,
  created_at TEXT, sent_at TEXT, error TEXT,
  UNIQUE(channel_id, vacancy_uid)
);

CREATE TABLE IF NOT EXISTS crawl_cursor (
  key TEXT PRIMARY KEY, last_published_at TEXT, last_run TEXT
);

CREATE TABLE IF NOT EXISTS rate_token (
  host TEXT PRIMARY KEY, last_request_at REAL
);

CREATE TABLE IF NOT EXISTS tg_offset (
  id INTEGER PRIMARY KEY CHECK(id = 1), last_update_id INTEGER
);

CREATE TABLE IF NOT EXISTS employers (
  id TEXT PRIMARY KEY, name TEXT, tier TEXT,
  remote_seen INTEGER DEFAULT 0, total_seen INTEGER DEFAULT 0,
  last_seen TEXT, source TEXT
);

CREATE TABLE IF NOT EXISTS salary_stats (
  scope TEXT, key TEXT, p50 INTEGER, p70 INTEGER, n INTEGER, computed_at TEXT,
  PRIMARY KEY(scope, key)
);

CREATE TABLE IF NOT EXISTS canary_runs (
  id INTEGER PRIMARY KEY, run_at TEXT, ok INTEGER,
  verdict TEXT, report TEXT, dump_path TEXT
);
"""

VACANCY_COLUMNS = (
    "uid", "source", "source_id", "title", "employer_id", "employer_name",
    "area_id", "area_name", "salary_from", "salary_to", "salary_currency",
    "work_formats", "schedule_id", "experience_id", "published_at", "url",
    "raw", "signature",
)


def utc_now_iso() -> str:
    """Текущее время в UTC ISO-8601. Единый формат на весь проект."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path: str) -> sqlite3.Connection:
    """Одно долгоживущее соединение с выставленными pragma.

    auto_vacuum ставится ДО создания таблиц: на непустой БД смена режима
    молча игнорируется, и место после DELETE не вернётся операционной системе.
    """
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA auto_vacuum = INCREMENTAL")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA wal_autocheckpoint = 1000")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def upsert_vacancy(conn: sqlite3.Connection, v: dict) -> bool:
    """Пишет вакансию. Возвращает True, если строка новая.

    first_seen проставляется только при вставке — при повторной встрече
    вакансии оно не сдвигается, иначе сломается отсечка backlog на go-live.
    """
    placeholders = ", ".join("?" for _ in VACANCY_COLUMNS)
    columns = ", ".join(VACANCY_COLUMNS)
    values = [v.get(c) for c in VACANCY_COLUMNS]
    cur = conn.execute(
        "INSERT OR IGNORE INTO vacancies ({}, first_seen) VALUES ({}, ?)".format(
            columns, placeholders
        ),
        values + [utc_now_iso()],
    )
    conn.commit()
    return cur.rowcount == 1


def count_vacancies(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM vacancies").fetchone()[0]
```

- [ ] **Step 4: Запустить тесты, убедиться что проходят**

Run: `python -m pytest citysonar/tests/test_store.py -v`
Ожидается: 6 passed

- [ ] **Step 5: Commit**

```bash
git add citysonar/core/store.py citysonar/tests/test_store.py
git commit -m "feat(citysonar): store — соединение, pragma, схема БД, upsert вакансий"
```

---

### Task 3: Межпроцессный троттл + снятие фикстуры

**Files:**
- Create: `citysonar/core/throttle.py`
- Create: `citysonar/tools/capture_fixture.py`
- Create: `citysonar/tests/fixtures/search_page.html.gz` (снимается скриптом)
- Test: `citysonar/tests/test_throttle.py`

**Interfaces:**
- Consumes: `store.connect`, `store.init_schema`
- Produces:
  - `throttle.acquire(conn, host: str, min_gap: float = 1.0, max_gap: float = 2.0) -> float` — блокирует до истечения паузы, возвращает фактическое время сна в секундах
  - `throttle.HH_HOST = "hh.ru"`

Троттл живёт в БД, а не в переменной модуля, потому что процессов два: `worker.py`
и `canary.py`. Именно попроцессный `_last_request_ts` в `web/utils.py:335` —
причина всплесков и 403 у существующих ботов.

- [ ] **Step 1: Написать падающие тесты**

`citysonar/tests/test_throttle.py`:
```python
from __future__ import annotations

import time

from citysonar.core import store, throttle


def test_first_acquire_does_not_sleep(tmp_db):
    conn = store.connect(str(tmp_db))
    store.init_schema(conn)
    slept = throttle.acquire(conn, "example.test", min_gap=0.2, max_gap=0.2)
    assert slept == 0.0


def test_second_acquire_waits_the_gap(tmp_db):
    conn = store.connect(str(tmp_db))
    store.init_schema(conn)
    throttle.acquire(conn, "example.test", min_gap=0.2, max_gap=0.2)
    started = time.monotonic()
    slept = throttle.acquire(conn, "example.test", min_gap=0.2, max_gap=0.2)
    elapsed = time.monotonic() - started
    assert slept > 0
    assert elapsed >= 0.15  # с запасом на разрешение таймера


def test_gap_is_per_host(tmp_db):
    conn = store.connect(str(tmp_db))
    store.init_schema(conn)
    throttle.acquire(conn, "a.test", min_gap=5.0, max_gap=5.0)
    slept = throttle.acquire(conn, "b.test", min_gap=5.0, max_gap=5.0)
    assert slept == 0.0


def test_second_connection_sees_the_same_token(tmp_db):
    """Ключевое свойство: два процесса делят одну паузу."""
    conn_a = store.connect(str(tmp_db))
    store.init_schema(conn_a)
    conn_b = store.connect(str(tmp_db))
    throttle.acquire(conn_a, "shared.test", min_gap=0.2, max_gap=0.2)
    slept = throttle.acquire(conn_b, "shared.test", min_gap=0.2, max_gap=0.2)
    assert slept > 0
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `python -m pytest citysonar/tests/test_throttle.py -v`
Ожидается: FAIL — `ModuleNotFoundError: No module named 'citysonar.core.throttle'`

- [ ] **Step 3: Написать throttle.py**

`citysonar/core/throttle.py`:
```python
from __future__ import annotations

import random
import sqlite3
import time

HH_HOST = "hh.ru"


def acquire(
    conn: sqlite3.Connection,
    host: str,
    min_gap: float = 1.0,
    max_gap: float = 2.0,
) -> float:
    """Разрешение на один запрос к host. Блокирует до истечения паузы.

    Пауза хранится в БД, а не в памяти процесса: worker и canary — разные
    процессы, ходящие на один хост с одного IP. BEGIN IMMEDIATE берёт
    write-лок, поэтому два процесса не могут одновременно решить, что
    пауза истекла.
    """
    gap = random.uniform(min_gap, max_gap)
    now = time.time()

    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT last_request_at FROM rate_token WHERE host = ?", (host,)
        ).fetchone()
        last = row[0] if row else None

        if last is None:
            wait = 0.0
            next_at = now
        else:
            wait = max(0.0, last + gap - now)
            next_at = now + wait

        conn.execute(
            "INSERT INTO rate_token (host, last_request_at) VALUES (?, ?) "
            "ON CONFLICT(host) DO UPDATE SET last_request_at = excluded.last_request_at",
            (host, next_at),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    if wait > 0:
        time.sleep(wait)
    return wait
```

- [ ] **Step 4: Запустить тесты, убедиться что проходят**

Run: `python -m pytest citysonar/tests/test_throttle.py -v`
Ожидается: 4 passed

- [ ] **Step 5: Написать скрипт снятия фикстуры**

`citysonar/tools/capture_fixture.py`:
```python
"""Снимает живую страницу поиска hh.ru в фикстуру для офлайн-тестов.

Запускать вручную с машины, откуда hh.ru отвечает:
    python citysonar/tools/capture_fixture.py

Перезапускать при смене разметки hh, чтобы тесты проверяли актуальную форму.
"""
from __future__ import annotations

import gzip
import pathlib
import sys

import requests

OUT = pathlib.Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "search_page.html.gz"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}

PARAMS = {
    "text": "аналитик",
    "search_field": "name",
    "order_by": "publication_time",
    "per_page": 100,
    "page": 0,
}


def main() -> int:
    r = requests.get("https://hh.ru/search/vacancy", params=PARAMS, headers=HEADERS, timeout=20)
    if r.status_code != 200 or "vpncheeck" in r.url:
        print("hh.ru не отдал страницу: HTTP {} url={}".format(r.status_code, r.url))
        return 1
    if "HH-Lux-InitialState" not in r.text:
        print("на странице нет HH-Lux-InitialState — разметка изменилась, разобраться вручную")
        return 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT, "wt", encoding="utf-8") as fh:
        fh.write(r.text)
    print("сохранено: {} ({} КБ)".format(OUT, OUT.stat().st_size // 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: Снять фикстуру**

Run: `python citysonar/tools/capture_fixture.py`
Ожидается: `сохранено: .../search_page.html.gz (NNN КБ)`

Если печатает «на странице нет HH-Lux-InitialState» — hh снова сменил разметку;
остановиться, разобраться с реальной страницей и обновить план.

- [ ] **Step 7: Commit**

```bash
git add citysonar/core/throttle.py citysonar/tests/test_throttle.py \
        citysonar/tools/capture_fixture.py citysonar/tests/fixtures/search_page.html.gz
git commit -m "feat(citysonar): межпроцессный троттл через rate_token + фикстура страницы hh"
```

---

### Task 4: pydantic-модель SSR-стейта

**Files:**
- Create: `citysonar/core/schema.py`
- Test: `citysonar/tests/test_schema.py`

**Interfaces:**
- Consumes: фикстура `search_page_html` из conftest
- Produces:
  - `schema.StateContractError(Exception)` — атрибуты `.detail: str`, `.missing: list`
  - `schema.extract_state_json(html: str) -> dict` — поднимает `StateContractError`, если стейт не найден
  - `schema.validate_state(state: dict) -> SearchResult` — поднимает `StateContractError` с перечнем отвалившихся полей
  - `schema.RawVacancy` — pydantic-модель одной вакансии из стейта
  - `schema.SearchResult` — модель с полями `vacancies: List[RawVacancy]`, `total_pages: int`

Смысл слоя: когда hh меняет форму (как 2026-07-17, когда стейт переехал в
`<template id="HH-Lux-InitialState">` и все боты молча слали нули) — получить
громкую ошибку с указанием поля, а не пустой список.

- [ ] **Step 1: Написать падающие тесты**

`citysonar/tests/test_schema.py`:
```python
from __future__ import annotations

import json

import pytest

from citysonar.core import schema


def test_extract_state_from_live_fixture(search_page_html):
    state = schema.extract_state_json(search_page_html)
    assert isinstance(state, dict)
    assert "vacancySearchResult" in state


def test_extract_state_raises_on_missing_template():
    with pytest.raises(schema.StateContractError) as exc:
        schema.extract_state_json("<html><body>ничего нет</body></html>")
    assert "HH-Lux-InitialState" in exc.value.detail


def test_validate_live_fixture_gives_vacancies(search_page_html):
    state = schema.extract_state_json(search_page_html)
    result = schema.validate_state(state)
    assert len(result.vacancies) > 0
    assert result.total_pages >= 1
    first = result.vacancies[0]
    assert first.vacancyId
    assert first.name


def test_validate_reports_missing_field():
    state = {
        "vacancySearchResult": {
            "vacancies": [{"name": "Аналитик"}],  # нет vacancyId
            "paging": {"lastPage": {"page": 0}},
        }
    }
    with pytest.raises(schema.StateContractError) as exc:
        schema.validate_state(state)
    assert "vacancyId" in exc.value.detail


def test_validate_reports_missing_search_result():
    with pytest.raises(schema.StateContractError) as exc:
        schema.validate_state({"somethingElse": {}})
    assert "vacancySearchResult" in exc.value.detail


def test_paging_absent_means_single_page():
    state = {
        "vacancySearchResult": {
            "vacancies": [{"vacancyId": 1, "name": "Аналитик"}],
        }
    }
    result = schema.validate_state(state)
    assert result.total_pages == 1


def test_optional_fields_may_be_absent():
    """Зарплата, формат и опыт часто отсутствуют — это не поломка контракта."""
    state = {
        "vacancySearchResult": {
            "vacancies": [{"vacancyId": 7, "name": "Аналитик"}],
            "paging": {"lastPage": {"page": 2}},
        }
    }
    result = schema.validate_state(state)
    assert result.total_pages == 3
    assert result.vacancies[0].compensation is None
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `python -m pytest citysonar/tests/test_schema.py -v`
Ожидается: FAIL — `ModuleNotFoundError: No module named 'citysonar.core.schema'`

- [ ] **Step 3: Написать schema.py**

`citysonar/core/schema.py`:
```python
from __future__ import annotations

import html as _html
import json
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class StateContractError(Exception):
    """Форма страницы hh.ru не та, которую мы умеем читать."""

    def __init__(self, detail: str, missing: Optional[List[str]] = None):
        super().__init__(detail)
        self.detail = detail
        self.missing = missing or []


class Compensation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    from_: Optional[int] = Field(default=None, alias="from")
    to: Optional[int] = None
    currencyCode: Optional[str] = None


class Company(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: Optional[int] = None
    visibleName: Optional[str] = None
    name: Optional[str] = None


class Area(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    id: Optional[int] = Field(default=None, alias="@id")
    name: Optional[str] = None


class WorkFormat(BaseModel):
    model_config = ConfigDict(extra="ignore")
    workFormatsElement: List[str] = Field(default_factory=list)


class PublicationTime(BaseModel):
    model_config = ConfigDict(extra="ignore")
    value: Optional[str] = Field(default=None, alias="$")


class Links(BaseModel):
    model_config = ConfigDict(extra="ignore")
    desktop: Optional[str] = None


class RawVacancy(BaseModel):
    """Вакансия в том виде, в каком её кладёт hh в SSR-стейт.

    Обязательны только vacancyId и name — без них вакансия бессмысленна,
    и их пропажа означает поломку контракта. Всё прочее опционально:
    зарплату и формат работодатели указывают не всегда.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    vacancyId: int
    name: str
    company: Optional[Company] = None
    compensation: Optional[Compensation] = None
    area: Optional[Area] = None
    workFormats: List[WorkFormat] = Field(default_factory=list)
    workSchedule: Optional[str] = Field(default=None, alias="@workSchedule")
    workExperience: Optional[str] = None
    publicationTime: Optional[PublicationTime] = None
    links: Optional[Links] = None


class SearchResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    vacancies: List[RawVacancy]
    total_pages: int = 1


def extract_state_json(html: str) -> Dict[str, Any]:
    """Достаёт JSON-стейт со страницы поиска hh.ru.

    С июля 2026 стейт лежит в <template id="HH-Lux-InitialState">, причём
    HTML-экранированным (&#34; вместо "). Старый формат
    (data-ssr-state-length="N">{…}) оставлен запасным путём.
    """
    m = re.search(r'id="HH-Lux-InitialState"[^>]*>', html)
    if m:
        start = m.end()
        end = html.find("</template>", start)
        if end != -1:
            try:
                data = json.loads(_html.unescape(html[start:end]))
            except ValueError as e:
                raise StateContractError(
                    "HH-Lux-InitialState найден, но JSON не разбирается: {}".format(e)
                )
            if isinstance(data, dict):
                return data
            raise StateContractError("HH-Lux-InitialState содержит не объект, а {}".format(type(data).__name__))

    m = re.search(r'data-ssr-state-length="\d+"[^>]*>', html)
    if m:
        start = m.end()
        if start < len(html) and html[start] == "{":
            try:
                data, _ = json.JSONDecoder().raw_decode(html, start)
            except ValueError as e:
                raise StateContractError("старый формат стейта не разбирается: {}".format(e))
            if isinstance(data, dict):
                return data

    raise StateContractError(
        "на странице нет ни HH-Lux-InitialState, ни data-ssr-state-length — "
        "разметка hh.ru изменилась"
    )


def _total_pages(vsr: Dict[str, Any]) -> int:
    """Число страниц лежит в paging.lastPage.page (или max по paging.pages).

    Отсутствие paging — законная ситуация: одна страница результатов.
    """
    paging = vsr.get("paging") or {}
    last = paging.get("lastPage")
    if isinstance(last, dict) and last.get("page") is not None:
        return int(last["page"]) + 1
    pages = paging.get("pages") or []
    if pages:
        return max(int(p.get("page", 0)) for p in pages) + 1
    return 1


def validate_state(state: Dict[str, Any]) -> SearchResult:
    """Проверяет форму стейта. Поднимает StateContractError с именами полей."""
    vsr = state.get("vacancySearchResult")
    if not isinstance(vsr, dict):
        raise StateContractError(
            "в стейте нет vacancySearchResult — верхний уровень изменился",
            missing=["vacancySearchResult"],
        )

    raw_items = None
    for key in ("vacancies", "items", "results"):
        if key in vsr:
            raw_items = vsr[key]
            break
    if raw_items is None:
        nested = vsr.get("searchResult") or {}
        for key in ("vacancies", "items"):
            if key in nested:
                raw_items = nested[key]
                break
    if raw_items is None:
        raise StateContractError(
            "в vacancySearchResult нет списка вакансий (искали vacancies/items/results)",
            missing=["vacancySearchResult.vacancies"],
        )

    try:
        return SearchResult(vacancies=raw_items, total_pages=_total_pages(vsr))
    except ValidationError as e:
        missing = []
        for err in e.errors():
            loc = ".".join(str(p) for p in err["loc"])
            missing.append("{} ({})".format(loc, err["type"]))
        raise StateContractError(
            "форма вакансии изменилась: {}".format("; ".join(missing[:10])),
            missing=missing,
        )
```

- [ ] **Step 4: Запустить тесты, убедиться что проходят**

Run: `python -m pytest citysonar/tests/test_schema.py -v`
Ожидается: 7 passed

- [ ] **Step 5: Commit**

```bash
git add citysonar/core/schema.py citysonar/tests/test_schema.py
git commit -m "feat(citysonar): pydantic-модель SSR-стейта hh — громкая ошибка вместо тихих нулей"
```

---

### Task 5: Нормализация вакансии

**Files:**
- Create: `citysonar/core/hh.py`
- Test: `citysonar/tests/test_hh_normalize.py`

**Interfaces:**
- Consumes: `schema.RawVacancy`, `schema.extract_state_json`, `schema.validate_state`
- Produces:
  - `hh.normalize(raw: schema.RawVacancy) -> dict` — словарь с ключами из `store.VACANCY_COLUMNS`
  - `hh.make_signature(employer_id: str, title: str) -> str`
  - `hh.is_remote(work_formats: str, schedule_id: str) -> bool`
  - `hh.is_office_only(work_formats: str, schedule_id: str) -> bool`

`work_formats` хранится строкой через запятую (`"remote,hybrid"`), потому что
SQLite не имеет массивов, а разбирать её нужно в одном месте — в этих двух
предикатах.

- [ ] **Step 1: Написать падающие тесты**

`citysonar/tests/test_hh_normalize.py`:
```python
from __future__ import annotations

from citysonar.core import hh, schema, store


def _raw(**over):
    base = {
        "vacancyId": 12345678,
        "name": "Аналитик данных",
        "company": {"id": 1740, "visibleName": "Яндекс"},
        "compensation": {"from": 200000, "to": None, "currencyCode": "RUR"},
        "area": {"@id": 1, "name": "Москва"},
        "workFormats": [{"workFormatsElement": ["REMOTE"]}],
        "@workSchedule": "remote",
        "workExperience": "between3And6",
        "publicationTime": {"$": "2026-08-12T09:00:00+03:00"},
        "links": {"desktop": "https://hh.ru/vacancy/12345678"},
    }
    base.update(over)
    return schema.RawVacancy.model_validate(base)


def test_normalize_produces_all_store_columns():
    v = hh.normalize(_raw())
    for column in store.VACANCY_COLUMNS:
        assert column in v, "не хватает поля {}".format(column)


def test_normalize_basic_fields():
    v = hh.normalize(_raw())
    assert v["uid"] == "hh_12345678"
    assert v["source"] == "hh"
    assert v["title"] == "Аналитик данных"
    assert v["employer_id"] == "1740"
    assert v["employer_name"] == "Яндекс"
    assert v["area_id"] == "1"
    assert v["area_name"] == "Москва"
    assert v["salary_from"] == 200000
    assert v["salary_currency"] == "RUR"
    assert v["url"] == "https://hh.ru/vacancy/12345678"


def test_published_at_converted_to_utc():
    v = hh.normalize(_raw())
    # 09:00 по МСК (+03:00) это 06:00 UTC
    assert v["published_at"] == "2026-08-12T06:00:00+00:00"


def test_published_at_absent_is_none():
    v = hh.normalize(_raw(publicationTime=None))
    assert v["published_at"] is None


def test_work_formats_joined():
    v = hh.normalize(_raw(workFormats=[{"workFormatsElement": ["ON_SITE", "HYBRID"]}]))
    assert v["work_formats"] == "onSite,hybrid"


def test_url_fallback_when_links_absent():
    v = hh.normalize(_raw(links=None))
    assert v["url"] == "https://hh.ru/vacancy/12345678"


def test_missing_salary_is_none():
    v = hh.normalize(_raw(compensation=None))
    assert v["salary_from"] is None
    assert v["salary_to"] is None
    assert v["salary_currency"] is None


def test_signature_ignores_case_and_punctuation():
    a = hh.make_signature("1740", "Аналитик данных (Middle)")
    b = hh.make_signature("1740", "аналитик  данных, middle")
    assert a == b


def test_signature_differs_by_employer():
    assert hh.make_signature("1740", "Аналитик") != hh.make_signature("15478", "Аналитик")


def test_is_remote_reads_structure_not_text():
    assert hh.is_remote("remote", "fullDay") is True
    assert hh.is_remote("", "remote") is True
    assert hh.is_remote("onSite,hybrid", "fullDay") is False


def test_office_only_means_no_remote_and_no_hybrid():
    assert hh.is_office_only("onSite", "fullDay") is True
    assert hh.is_office_only("onSite,field", "fullDay") is True
    assert hh.is_office_only("onSite,hybrid", "fullDay") is False
    assert hh.is_office_only("", "fullDay") is False  # формат неизвестен, не «строго офис»


def test_normalize_real_fixture(search_page_html):
    state = schema.extract_state_json(search_page_html)
    result = schema.validate_state(state)
    normalized = [hh.normalize(r) for r in result.vacancies]
    assert len(normalized) > 10
    assert all(v["uid"].startswith("hh_") for v in normalized)
    assert all(v["title"] for v in normalized)
    # У живой выдачи хотя бы у части вакансий проставлен регион
    assert any(v["area_id"] and v["area_id"] != "0" for v in normalized)
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `python -m pytest citysonar/tests/test_hh_normalize.py -v`
Ожидается: FAIL — `ModuleNotFoundError: No module named 'citysonar.core.hh'`

- [ ] **Step 3: Написать hh.py (часть 1 — нормализация)**

`citysonar/core/hh.py`:
```python
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Optional

from citysonar.core import schema

WF_MAP = {
    "REMOTE": "remote",
    "ON_SITE": "onSite",
    "HYBRID": "hybrid",
    "FIELD": "field",
    "FIELD_WORK": "field",
}

_SIG_CLEAN = re.compile(r"[^a-zа-яё0-9]+")


def make_signature(employer_id: str, title: str) -> str:
    """Подпись «работодатель + название» для дедупа мульти-город публикаций.

    Одна роль, размещённая по N городам, имеет N разных hh id, но одну подпись.
    Применяется ТОЛЬКО в remote-ветках: в локальной ветке каждый город обязан
    получить свою публикацию в свой канал.
    """
    return "{}_{}".format(employer_id or "", _SIG_CLEAN.sub("", (title or "").lower()))


def _to_utc_iso(value: Optional[str]) -> Optional[str]:
    """hh отдаёт время с офсетом МСК. Курсор сравнивается строкой, поэтому
    приводим всё к UTC — иначе '+03:00' и '+00:00' сортируются неверно."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def normalize(raw: schema.RawVacancy) -> dict:
    """Вакансия из стейта hh → словарь под колонки таблицы vacancies."""
    vac_id = str(raw.vacancyId)

    company = raw.company
    employer_id = str(company.id) if company is not None and company.id is not None else ""
    employer_name = ""
    if company is not None:
        employer_name = company.visibleName or company.name or ""

    comp = raw.compensation
    salary_from = comp.from_ if comp is not None else None
    salary_to = comp.to if comp is not None else None
    salary_currency = comp.currencyCode if comp is not None else None

    area = raw.area
    area_id = str(area.id) if area is not None and area.id is not None else "0"
    area_name = area.name if area is not None and area.name else ""

    formats = []
    for wf in raw.workFormats:
        for element in wf.workFormatsElement:
            formats.append(WF_MAP.get(element, element.lower()))

    url = ""
    if raw.links is not None and raw.links.desktop:
        url = raw.links.desktop
    if not url:
        url = "https://hh.ru/vacancy/{}".format(vac_id)

    published_at = None
    if raw.publicationTime is not None:
        published_at = _to_utc_iso(raw.publicationTime.value)

    title = raw.name or ""

    return {
        "uid": "hh_{}".format(vac_id),
        "source": "hh",
        "source_id": vac_id,
        "title": title,
        "employer_id": employer_id,
        "employer_name": employer_name,
        "area_id": area_id,
        "area_name": area_name,
        "salary_from": salary_from,
        "salary_to": salary_to,
        "salary_currency": salary_currency,
        "work_formats": ",".join(formats),
        "schedule_id": raw.workSchedule or "",
        "experience_id": raw.workExperience or "",
        "published_at": published_at,
        "url": url,
        "raw": json.dumps(raw.model_dump(by_alias=True), ensure_ascii=False),
        "signature": make_signature(employer_id, title),
    }


def is_remote(work_formats: str, schedule_id: str) -> bool:
    """Удалёнка определяется структурой, а не текстом.

    Текстовый детект ('удал' in details) в старых ботах не различал
    «строго офис» и «офис + удалёнка» и ломался на е/ё.
    """
    parts = {p for p in (work_formats or "").split(",") if p}
    return "remote" in parts or (schedule_id or "") == "remote"


def is_office_only(work_formats: str, schedule_id: str) -> bool:
    """Строго офис: формат известен, и в нём нет ни remote, ни hybrid.

    Пустой набор форматов — это «формат неизвестен», а не «офис».
    """
    parts = {p for p in (work_formats or "").split(",") if p}
    if not parts and (schedule_id or "") != "remote":
        return False
    return not ({"remote", "hybrid"} & parts) and (schedule_id or "") != "remote"
```

- [ ] **Step 4: Запустить тесты, убедиться что проходят**

Run: `python -m pytest citysonar/tests/test_hh_normalize.py -v`
Ожидается: 12 passed

- [ ] **Step 5: Commit**

```bash
git add citysonar/core/hh.py citysonar/tests/test_hh_normalize.py
git commit -m "feat(citysonar): нормализация вакансии hh, структурный детект формата, подпись для дедупа"
```

---

### Task 6: Курсоры инкрементального обхода

**Files:**
- Create: `citysonar/core/cursor.py`
- Test: `citysonar/tests/test_cursor.py`

**Interfaces:**
- Consumes: `store.connect`, `store.init_schema`, `store.utc_now_iso`
- Produces:
  - `cursor.get(conn, key: str) -> Optional[str]` — последний обработанный `published_at` или `None`
  - `cursor.advance(conn, key: str, newest_published_at: Optional[str]) -> None` — двигает курсор вперёд, никогда назад
  - `cursor.is_new(cursor_value: Optional[str], published_at: Optional[str]) -> bool`
  - `cursor.COLD_START_PERIOD_DAYS = 7`, `cursor.COLD_START_MAX_PAGES = 3`

Курсор двигается **одной транзакцией после полного вычитывания ключа**. Если
двигать по мере чтения страниц, краш после страницы 0 сдвинет курсор на самую
свежую вакансию, и более старые записи со страницы 1 не вернутся никогда.

- [ ] **Step 1: Написать падающие тесты**

`citysonar/tests/test_cursor.py`:
```python
from __future__ import annotations

from citysonar.core import cursor, store


def _conn(tmp_db):
    conn = store.connect(str(tmp_db))
    store.init_schema(conn)
    return conn


def test_missing_cursor_is_none(tmp_db):
    assert cursor.get(_conn(tmp_db), "hh:local:msk:analytics") is None


def test_advance_then_get(tmp_db):
    conn = _conn(tmp_db)
    cursor.advance(conn, "k", "2026-08-12T06:00:00+00:00")
    assert cursor.get(conn, "k") == "2026-08-12T06:00:00+00:00"


def test_advance_never_moves_backwards(tmp_db):
    conn = _conn(tmp_db)
    cursor.advance(conn, "k", "2026-08-12T06:00:00+00:00")
    cursor.advance(conn, "k", "2026-08-01T06:00:00+00:00")
    assert cursor.get(conn, "k") == "2026-08-12T06:00:00+00:00"


def test_advance_with_none_keeps_value_but_updates_last_run(tmp_db):
    """Пустой проход (ничего нового) не должен обнулять курсор."""
    conn = _conn(tmp_db)
    cursor.advance(conn, "k", "2026-08-12T06:00:00+00:00")
    cursor.advance(conn, "k", None)
    assert cursor.get(conn, "k") == "2026-08-12T06:00:00+00:00"
    row = conn.execute("SELECT last_run FROM crawl_cursor WHERE key='k'").fetchone()
    assert row[0] is not None


def test_is_new_on_cold_start_accepts_everything():
    assert cursor.is_new(None, "2020-01-01T00:00:00+00:00") is True


def test_is_new_compares_strings():
    c = "2026-08-12T06:00:00+00:00"
    assert cursor.is_new(c, "2026-08-12T07:00:00+00:00") is True
    assert cursor.is_new(c, "2026-08-12T06:00:00+00:00") is False
    assert cursor.is_new(c, "2026-08-11T23:00:00+00:00") is False


def test_is_new_without_published_at_is_true():
    """Нет даты — считаем новой: лучше лишний раз записать, чем потерять."""
    assert cursor.is_new("2026-08-12T06:00:00+00:00", None) is True
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `python -m pytest citysonar/tests/test_cursor.py -v`
Ожидается: FAIL — `ModuleNotFoundError: No module named 'citysonar.core.cursor'`

- [ ] **Step 3: Написать cursor.py**

`citysonar/core/cursor.py`:
```python
from __future__ import annotations

import sqlite3
from typing import Optional

from citysonar.core.store import utc_now_iso

# Холодный старт: курсора нет. Смотрим на неделю назад, но не глубже 3 страниц
# за цикл — остальное доберут следующие циклы. Иначе первый прогон уйдёт
# читать 40 страниц на каждый из ~77 ключей.
COLD_START_PERIOD_DAYS = 7
COLD_START_MAX_PAGES = 3


def get(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute(
        "SELECT last_published_at FROM crawl_cursor WHERE key = ?", (key,)
    ).fetchone()
    return row[0] if row else None


def advance(conn: sqlite3.Connection, key: str, newest_published_at: Optional[str]) -> None:
    """Двигает курсор вперёд. Вызывать ТОЛЬКО после персиста всех страниц ключа.

    Назад курсор не откатывается никогда: иначе один сбойный проход,
    вернувший старую вакансию, заставил бы перечитывать всё заново.
    """
    current = get(conn, key)
    if newest_published_at is not None and (current is None or newest_published_at > current):
        value = newest_published_at
    else:
        value = current

    conn.execute(
        "INSERT INTO crawl_cursor (key, last_published_at, last_run) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET last_published_at = excluded.last_published_at, "
        "last_run = excluded.last_run",
        (key, value, utc_now_iso()),
    )
    conn.commit()


def is_new(cursor_value: Optional[str], published_at: Optional[str]) -> bool:
    """Свежее курсора? На холодном старте (курсора нет) — всё свежее."""
    if cursor_value is None:
        return True
    if published_at is None:
        return True
    return published_at > cursor_value
```

- [ ] **Step 4: Запустить тесты, убедиться что проходят**

Run: `python -m pytest citysonar/tests/test_cursor.py -v`
Ожидается: 7 passed

- [ ] **Step 5: Commit**

```bash
git add citysonar/core/cursor.py citysonar/tests/test_cursor.py
git commit -m "feat(citysonar): курсоры инкрементального обхода, движение только вперёд"
```

---

### Task 7: HTTP-слой и пагинация

**Files:**
- Modify: `citysonar/core/hh.py` (дописать HTTP-часть в конец файла)
- Test: `citysonar/tests/test_hh_paging.py`

**Interfaces:**
- Consumes: `throttle.acquire`, `schema.extract_state_json`, `schema.validate_state`, `hh.normalize`, `cursor.is_new`
- Produces:
  - `hh.BROWSER_HEADERS: dict`
  - `hh.SEARCH_URL: str`
  - `hh.Blocked(Exception)` — анти-бот сработал
  - `hh.make_session() -> requests.Session`
  - `hh.fetch_page(session, conn, params: dict, page: int) -> Tuple[List[dict], int]` — нормализованные вакансии и число страниц; поднимает `Blocked` и `schema.StateContractError`
  - `hh.crawl(session, conn, key: str, params: dict, max_pages: int) -> Tuple[List[dict], Optional[str]]` — все свежее курсора вакансии и максимальный `published_at` среди них

`fetch_page` не ловит `StateContractError` — она должна долетать до вызывающего,
иначе поломка разметки снова превратится в тихие нули.

- [ ] **Step 1: Написать падающие тесты**

`citysonar/tests/test_hh_paging.py`:
```python
from __future__ import annotations

import gzip
import pathlib

import pytest

from citysonar.core import cursor, hh, store

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


class FakeResponse:
    def __init__(self, text="", status_code=200, url="https://hh.ru/search/vacancy"):
        self.text = text
        self.status_code = status_code
        self.url = url


class FakeSession:
    """Отдаёт заранее подготовленные ответы по номеру страницы."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, url, params=None, timeout=None):
        page = (params or {}).get("page", 0)
        self.calls.append(dict(params or {}))
        if page >= len(self.responses):
            return FakeResponse(text="", status_code=404)
        return self.responses[page]


def _live_html():
    with gzip.open(FIXTURES / "search_page.html.gz", "rt", encoding="utf-8") as fh:
        return fh.read()


def _conn(tmp_db):
    conn = store.connect(str(tmp_db))
    store.init_schema(conn)
    return conn


def test_fetch_page_returns_normalized_and_page_count(tmp_db):
    session = FakeSession([FakeResponse(text=_live_html())])
    items, pages = hh.fetch_page(session, _conn(tmp_db), {"text": "аналитик"}, 0)
    assert len(items) > 10
    assert pages >= 1
    assert items[0]["uid"].startswith("hh_")


def test_fetch_page_raises_blocked_on_403(tmp_db):
    session = FakeSession([FakeResponse(status_code=403)])
    with pytest.raises(hh.Blocked):
        hh.fetch_page(session, _conn(tmp_db), {"text": "x"}, 0)


def test_fetch_page_raises_blocked_on_vpncheeck_redirect(tmp_db):
    """Заглушка анти-бота отдаётся с кодом 200, ловится по url."""
    session = FakeSession([FakeResponse(status_code=200, url="https://hh.ru/vpncheeck?x=1")])
    with pytest.raises(hh.Blocked):
        hh.fetch_page(session, _conn(tmp_db), {"text": "x"}, 0)


def test_fetch_page_propagates_contract_error(tmp_db):
    from citysonar.core import schema

    session = FakeSession([FakeResponse(text="<html>пусто</html>")])
    with pytest.raises(schema.StateContractError):
        hh.fetch_page(session, _conn(tmp_db), {"text": "x"}, 0)


def test_fetch_page_passes_throttle(tmp_db):
    conn = _conn(tmp_db)
    session = FakeSession([FakeResponse(text=_live_html())])
    hh.fetch_page(session, conn, {"text": "x"}, 0)
    row = conn.execute("SELECT last_request_at FROM rate_token WHERE host='hh.ru'").fetchone()
    assert row is not None


def test_crawl_stops_at_cursor(tmp_db):
    conn = _conn(tmp_db)
    html = _live_html()
    session = FakeSession([FakeResponse(text=html), FakeResponse(text=html)])

    # Первый проход на холодную — берём всё, что на странице
    items, newest = hh.crawl(session, conn, "k", {"text": "x"}, max_pages=1)
    assert len(items) > 0
    assert newest is not None

    cursor.advance(conn, "k", newest)

    # Второй проход по тем же данным — ничего нового
    items2, newest2 = hh.crawl(session, conn, "k", {"text": "x"}, max_pages=1)
    assert items2 == []
    assert newest2 is None


def test_crawl_respects_max_pages(tmp_db):
    conn = _conn(tmp_db)
    html = _live_html()
    session = FakeSession([FakeResponse(text=html)] * 5)
    hh.crawl(session, conn, "k", {"text": "x"}, max_pages=2)
    pages_requested = [c.get("page") for c in session.calls]
    assert max(pages_requested) <= 1


def test_crawl_does_not_advance_cursor_itself(tmp_db):
    """Курсор двигает вызывающий, после персиста. crawl только читает."""
    conn = _conn(tmp_db)
    session = FakeSession([FakeResponse(text=_live_html())])
    hh.crawl(session, conn, "k", {"text": "x"}, max_pages=1)
    assert cursor.get(conn, "k") is None
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `python -m pytest citysonar/tests/test_hh_paging.py -v`
Ожидается: FAIL — `AttributeError: module 'citysonar.core.hh' has no attribute 'fetch_page'`

- [ ] **Step 3: Дописать HTTP-часть в hh.py**

Добавить в конец `citysonar/core/hh.py`:
```python
# ─────────────────────────────────────────────
#  HTTP-слой
# ─────────────────────────────────────────────

import requests  # noqa: E402  (импорт внизу, чтобы верх файла оставался без сети)

from citysonar.core import cursor as _cursor  # noqa: E402
from citysonar.core import throttle as _throttle  # noqa: E402

SEARCH_URL = "https://hh.ru/search/vacancy"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


class Blocked(Exception):
    """hh.ru ответил анти-ботом: 403 или редирект на заглушку /vpncheeck."""


def make_session():
    session = requests.Session()
    session.headers.update(BROWSER_HEADERS)
    return session


def _is_blocked(response) -> bool:
    return response.status_code == 403 or "vpncheeck" in (response.url or "")


def fetch_page(session, conn, params: dict, page: int):
    """Одна страница поиска. Возвращает (нормализованные вакансии, число страниц).

    Поднимает Blocked при анти-боте и schema.StateContractError при смене
    разметки — вторая специально не глушится, иначе поломка снова станет
    тихими нулями, как 2026-07-17.
    """
    request_params = dict(params)
    request_params.setdefault("order_by", "publication_time")
    request_params.setdefault("per_page", 100)
    request_params["page"] = page

    _throttle.acquire(conn, _throttle.HH_HOST)
    response = session.get(SEARCH_URL, params=request_params, timeout=20)

    if _is_blocked(response):
        raise Blocked("hh.ru анти-бот: HTTP {} url={}".format(response.status_code, response.url))
    if response.status_code != 200:
        raise Blocked("hh.ru HTTP {}".format(response.status_code))

    state = schema.extract_state_json(response.text)
    result = schema.validate_state(state)
    return [normalize(raw) for raw in result.vacancies], result.total_pages


def crawl(session, conn, key: str, params: dict, max_pages: int):
    """Читает страницы, пока встречаются вакансии свежее курсора.

    Возвращает (список новых вакансий, максимальный published_at среди них).
    Курсор НЕ двигает — это делает вызывающий после записи вакансий в БД,
    одной транзакцией. Иначе краш между чтением и записью потеряет данные.
    """
    cursor_value = _cursor.get(conn, key)
    if cursor_value is None:
        params = dict(params)
        params.setdefault("period", _cursor.COLD_START_PERIOD_DAYS)
        max_pages = min(max_pages, _cursor.COLD_START_MAX_PAGES)

    collected = []
    newest = None

    for page in range(max(1, max_pages)):
        items, total_pages = fetch_page(session, conn, params, page)
        if not items:
            break

        fresh = [v for v in items if _cursor.is_new(cursor_value, v["published_at"])]
        for v in fresh:
            if v["published_at"] is not None and (newest is None or v["published_at"] > newest):
                newest = v["published_at"]
        collected.extend(fresh)

        # Страница отсортирована по времени публикации: если на ней не осталось
        # ничего свежего, дальше только старее — дочитывать смысла нет.
        if len(fresh) < len(items):
            break
        if page >= total_pages - 1:
            break

    return collected, newest
```

- [ ] **Step 4: Запустить тесты, убедиться что проходят**

Run: `python -m pytest citysonar/tests/test_hh_paging.py -v`
Ожидается: 8 passed

- [ ] **Step 5: Запустить весь набор — убедиться, что ничего не сломано**

Run: `python -m pytest citysonar/tests -v`
Ожидается: все тесты Task 2-7 passed (37 штук)

- [ ] **Step 6: Commit**

```bash
git add citysonar/core/hh.py citysonar/tests/test_hh_paging.py
git commit -m "feat(citysonar): HTTP-слой hh — троттл, детект анти-бота, инкрементальная пагинация"
```

---

### Task 8: Конфиг городов и ролей + справочник area

**Files:**
- Create: `citysonar/config/cities.yaml`
- Create: `citysonar/config/roles.yaml`
- Create: `citysonar/core/config.py`
- Create: `citysonar/tools/fetch_areas.py`
- Test: `citysonar/tests/test_config.py`

**Interfaces:**
- Consumes: `PyYAML`
- Produces:
  - `config.City` — dataclass с полями `code: str`, `name: str`, `area_ids: List[str]`, `enabled: bool`
  - `config.Role` — dataclass с полями `code: str`, `name: str`, `keywords: List[str]`, `professional_roles: List[str]`, `enabled: bool`
  - `config.load_cities(path: str) -> List[City]`
  - `config.load_roles(path: str) -> List[Role]`
  - `config.or_batches(phrases: List[str], size: int = 6) -> Iterator[str]`

`area_id` не угадываются. Скрипт `fetch_areas.py` тянет справочник и печатает
кандидатов; человек переносит их в yaml. Угадывание id уже стоило проекта
однажды (SuperJob `t=1751` вместо `639` потерял весь регион).

- [ ] **Step 1: Написать падающие тесты**

`citysonar/tests/test_config.py`:
```python
from __future__ import annotations

import pathlib

from citysonar.core import config

CONFIG_DIR = pathlib.Path(__file__).parent.parent / "config"


def test_cities_yaml_loads():
    cities = config.load_cities(str(CONFIG_DIR / "cities.yaml"))
    assert len(cities) >= 1
    codes = {c.code for c in cities}
    assert "nn" in codes


def test_city_has_agglomeration_area_ids():
    cities = config.load_cities(str(CONFIG_DIR / "cities.yaml"))
    nn = next(c for c in cities if c.code == "nn")
    assert "66" in nn.area_ids          # Нижний Новгород
    assert len(nn.area_ids) >= 2        # агломерация, а не один город


def test_roles_yaml_loads_all_seven():
    roles = config.load_roles(str(CONFIG_DIR / "roles.yaml"))
    codes = {r.code for r in roles}
    assert codes == {"hr_line", "hr_lead", "analytics", "sales", "it", "marketing", "finance"}


def test_every_role_has_keywords():
    for role in config.load_roles(str(CONFIG_DIR / "roles.yaml")):
        assert role.keywords, "у роли {} нет ключевиков".format(role.code)


def test_or_batches_groups_and_quotes():
    got = list(config.or_batches(["a", "b", "c"], size=2))
    assert got == ['"a" OR "b"', '"c"']


def test_or_batches_empty_input():
    assert list(config.or_batches([], size=6)) == []
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `python -m pytest citysonar/tests/test_config.py -v`
Ожидается: FAIL — `ModuleNotFoundError: No module named 'citysonar.core.config'`

- [ ] **Step 3: Написать скрипт справочника area и получить id**

`citysonar/tools/fetch_areas.py`:
```python
"""Печатает area_id городов-кандидатов из справочника hh.

Запускать вручную:
    python citysonar/tools/fetch_areas.py

api.hh.ru/areas — справочник, он открыт даже при закрытом соискательском API.
Если отдаст не 200 — id берутся вручную из URL поиска на сайте (параметр area=),
но НЕ угадываются.
"""
from __future__ import annotations

import sys

import requests

CANDIDATES = [
    "Москва", "Санкт-Петербург", "Новосибирск", "Екатеринбург", "Казань",
    "Нижний Новгород", "Челябинск", "Красноярск", "Самара", "Уфа",
    "Ростов-на-Дону", "Омск", "Краснодар", "Воронеж", "Пермь", "Волгоград",
    "Тюмень", "Саратов",
]


def walk(nodes, path=()):
    for node in nodes:
        yield node, path
        for item in walk(node.get("areas", []), path + (node["name"],)):
            yield item


def main() -> int:
    r = requests.get("https://api.hh.ru/areas", timeout=20)
    if r.status_code != 200:
        print("api.hh.ru/areas отдал HTTP {} — брать id вручную из URL поиска".format(r.status_code))
        return 1
    tree = r.json()
    wanted = {c.lower() for c in CANDIDATES}
    for node, path in walk(tree):
        if node["name"].lower() in wanted:
            print("{:>10}  {:<22} {}".format(node["id"], node["name"], " / ".join(path)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Run: `python citysonar/tools/fetch_areas.py`

Ожидается: строки вида `66  Нижний Новгород  Россия / Нижегородская область`.
Записать полученные id в `cities.yaml` на следующем шаге. **Не переносить в yaml
ничего, чего не было в выводе скрипта.**

- [ ] **Step 4: Написать конфиги**

`citysonar/config/cities.yaml` — на Э1 достаточно одного пилотного города,
остальные добавляются на Э5 после замера объёмов. `area_ids` — из вывода Step 3:

```yaml
# Города и area_id их агломераций.
# ВНИМАНИЕ: id только из вывода tools/fetch_areas.py, не по памяти.
# Первый id в списке — сам город, остальные — спутники агломерации.
cities:
  - code: nn
    name: Нижний Новгород
    area_ids: ["66", "247"]   # Нижний Новгород, Дзержинск (Нижегородская обл.)
    enabled: true
```

`citysonar/config/roles.yaml` — ключевики для обхода. Это НЕ фильтр (фильтр L1
пишется в Плане 2), а то, что уходит в `text=` при поиске:

```yaml
# Ключевики для обхода hh (search_field=name). Фильтрация тайтла — План 2.
# professional_roles по умолчанию пуст: включается точечно там, где Э1 покажет,
# что ключевики не добирают покрытие.
roles:
  - code: hr_line
    name: HR линейный
    keywords:
      - Рекрутер
      - Специалист по подбору персонала
      - Менеджер по персоналу
      - HR-менеджер
      - Сорсер
      - Специалист по кадрам
    professional_roles: []
    enabled: true

  - code: hr_lead
    name: HR управленческий
    keywords:
      - Директор по персоналу
      - Руководитель отдела персонала
      - HR Business Partner
      - HRBP
      - Head of HR
      - Руководитель отдела подбора
    professional_roles: []
    enabled: true

  - code: analytics
    name: Аналитика
    keywords:
      - Аналитик
      - Бизнес-аналитик
      - Системный аналитик
      - Аналитик данных
      - Data Analyst
      - Продуктовый аналитик
    professional_roles: []
    enabled: true

  - code: sales
    name: Продажи
    keywords:
      - Менеджер по продажам
      - Руководитель отдела продаж
      - Менеджер по развитию бизнеса
      - Sales Manager
      - Account Manager
      - Специалист по продажам
    professional_roles: []
    enabled: true

  - code: it
    name: IT / разработка
    keywords:
      - Разработчик
      - Программист
      - Backend-разработчик
      - Frontend-разработчик
      - DevOps
      - QA-инженер
      - Тестировщик
      - Python-разработчик
    professional_roles: []
    enabled: true

  - code: marketing
    name: Маркетинг
    keywords:
      - Маркетолог
      - Интернет-маркетолог
      - Руководитель отдела маркетинга
      - Продуктовый маркетолог
      - SMM-менеджер
      - Performance-маркетолог
    professional_roles: []
    enabled: true

  - code: finance
    name: Финансы
    keywords:
      - Финансовый аналитик
      - Финансовый директор
      - Финансовый менеджер
      - Главный бухгалтер
      - Финансовый контролёр
      - Экономист
    professional_roles: []
    enabled: true
```

- [ ] **Step 5: Написать config.py**

`citysonar/core/config.py`:
```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, List

import yaml


@dataclass
class City:
    code: str
    name: str
    area_ids: List[str] = field(default_factory=list)
    enabled: bool = True


@dataclass
class Role:
    code: str
    name: str
    keywords: List[str] = field(default_factory=list)
    professional_roles: List[str] = field(default_factory=list)
    enabled: bool = True


def load_cities(path: str) -> List[City]:
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return [
        City(
            code=item["code"],
            name=item["name"],
            area_ids=[str(a) for a in item.get("area_ids", [])],
            enabled=bool(item.get("enabled", True)),
        )
        for item in data.get("cities", [])
    ]


def load_roles(path: str) -> List[Role]:
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return [
        Role(
            code=item["code"],
            name=item["name"],
            keywords=list(item.get("keywords", [])),
            professional_roles=[str(r) for r in item.get("professional_roles", [])],
            enabled=bool(item.get("enabled", True)),
        )
        for item in data.get("roles", [])
    ]


def or_batches(phrases: List[str], size: int = 6) -> Iterator[str]:
    """Склеивает ключевики в OR-запросы hh: '"A" OR "B" OR ...'.

    Один запрос вместо N. Читать при этом надо несколько страниц: OR из шести
    слов на одной странице вернёт свежайшее на всю шестёрку, и редкие слова
    выпадут.
    """
    for i in range(0, len(phrases), size):
        yield " OR ".join('"{}"'.format(p) for p in phrases[i:i + size])
```

- [ ] **Step 6: Запустить тесты, убедиться что проходят**

Run: `python -m pytest citysonar/tests/test_config.py -v`
Ожидается: 6 passed

- [ ] **Step 7: Commit**

```bash
git add citysonar/config/ citysonar/core/config.py citysonar/tools/fetch_areas.py \
        citysonar/tests/test_config.py
git commit -m "feat(citysonar): конфиг городов и ролей, справочник area, OR-батчи"
```

---

### Task 9: Замер объёмов (Э0)

**Files:**
- Create: `citysonar/tools/measure_volumes.py`

**Interfaces:**
- Consumes: `config.load_cities`, `config.load_roles`, `config.or_batches`, `hh.make_session`, `hh.fetch_page`, `store.connect`, `store.init_schema`
- Produces: файл отчёта `citysonar/measurements/YYYY-MM-DD-volumes.md`

Это не тест и не резидент — разовый скрипт, чей вывод определяет сетку каналов
и топ-10 городов. Задача Э0 из спеки.

- [ ] **Step 1: Написать скрипт**

`citysonar/tools/measure_volumes.py`:
```python
"""Замер Э0: сколько вакансий в неделю даёт каждая пара (город, роль).

По результату режется сетка каналов и выбирается топ-10 городов.
Запускать вручную с машины, откуда hh отвечает:

    python citysonar/tools/measure_volumes.py --cities-all

Считает по одной странице на пару, беря total_pages × 50 как оценку объёма.
Точность здесь не нужна — нужен порядок величины, чтобы отличить живую пару
от мёртвой.
"""
from __future__ import annotations

import argparse
import datetime
import pathlib
import sys

from citysonar.core import config, hh, store

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "measurements"
PER_PAGE_REAL = 50  # hh игнорирует per_page и отдаёт ~52 на страницу (замер 2026-08-12)

# Кандидаты на топ-10. area_id ОБЯЗАТЕЛЬНО из tools/fetch_areas.py.
CANDIDATE_CITIES = [
    ("msk", "Москва", ["1"]),
    ("spb", "Санкт-Петербург", ["2"]),
    ("nsk", "Новосибирск", ["4"]),
    ("ekb", "Екатеринбург", ["3"]),
    ("kzn", "Казань", ["88"]),
    ("nn", "Нижний Новгород", ["66"]),
    ("chel", "Челябинск", ["104"]),
    ("krsk", "Красноярск", ["54"]),
    ("smr", "Самара", ["78"]),
    ("ufa", "Уфа", ["99"]),
    ("rnd", "Ростов-на-Дону", ["76"]),
    ("krd", "Краснодар", ["53"]),
    ("vrn", "Воронеж", ["26"]),
    ("perm", "Пермь", ["72"]),
]


def estimate(session, conn, params):
    """Оценка числа вакансий по первой странице."""
    try:
        items, pages = hh.fetch_page(session, conn, params, 0)
    except hh.Blocked as e:
        print("  ЗАБЛОКИРОВАНО: {}".format(e))
        return None
    except Exception as e:
        print("  ОШИБКА: {}".format(e))
        return None
    if not items:
        return 0
    return pages * PER_PAGE_REAL


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--period", type=int, default=7, help="дней назад")
    parser.add_argument("--cities-all", action="store_true",
                        help="мерить всех кандидатов, а не только cities.yaml")
    args = parser.parse_args()

    roles = config.load_roles(str(ROOT / "config" / "roles.yaml"))
    if args.cities_all:
        cities = [config.City(code=c, name=n, area_ids=a) for c, n, a in CANDIDATE_CITIES]
    else:
        cities = config.load_cities(str(ROOT / "config" / "cities.yaml"))

    conn = store.connect(str(ROOT / "measure.db"))
    store.init_schema(conn)
    session = hh.make_session()

    lines = ["# Замер объёмов Э0", "",
             "Дата: {}".format(datetime.date.today().isoformat()),
             "Период: {} дней".format(args.period), ""]

    print("=== Общий объём по городам ===")
    lines.append("## Общий объём по городам (все вакансии за период)")
    lines.append("")
    lines.append("| Город | area_id | Вакансий |")
    lines.append("|---|---|---|")
    for city in cities:
        total = estimate(session, conn, {"area": city.area_ids, "period": args.period})
        print("{:<20} {}".format(city.name, total))
        lines.append("| {} | {} | {} |".format(city.name, ",".join(city.area_ids), total))
    lines.append("")

    print("\n=== Матрица город x роль ===")
    lines.append("## Матрица «город × роль» (локальная ветка)")
    lines.append("")
    header = "| Город | " + " | ".join(r.name for r in roles) + " |"
    lines.append(header)
    lines.append("|" + "---|" * (len(roles) + 1))

    for city in cities:
        row = [city.name]
        for role in roles:
            first_batch = next(config.or_batches(role.keywords, size=6), None)
            if first_batch is None:
                row.append("-")
                continue
            total = estimate(session, conn, {
                "text": first_batch,
                "search_field": "name",
                "area": city.area_ids,
                "period": args.period,
            })
            row.append(str(total))
            print("{:<20} {:<22} {}".format(city.name, role.name, total))
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    print("\n=== Удалёнка по ролям (общая на все города) ===")
    lines.append("## Удалёнка по ролям (общий пул на все города)")
    lines.append("")
    lines.append("| Роль | Вакансий |")
    lines.append("|---|---|")
    for role in roles:
        first_batch = next(config.or_batches(role.keywords, size=6), None)
        if first_batch is None:
            continue
        total = estimate(session, conn, {
            "text": first_batch,
            "search_field": "name",
            "work_format": "remote",
            "period": args.period,
        })
        print("{:<22} {}".format(role.name, total))
        lines.append("| {} | {} |".format(role.name, total))

    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / "{}-volumes.md".format(datetime.date.today().isoformat())
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\nОтчёт: {}".format(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Прогнать замер**

Run: `python citysonar/tools/measure_volumes.py --cities-all --period 7`

Ожидается: отчёт в `citysonar/measurements/YYYY-MM-DD-volumes.md`, три таблицы.
Время работы ≈ (14 городов + 14×7 пар + 7 remote) × 1.5с ≈ **3 минуты**.

Если печатает «ЗАБЛОКИРОВАНО» больше двух раз подряд — прервать, подождать час,
повторить. Не долбить.

- [ ] **Step 3: Разобрать результат с владельцем**

Показать владельцу отчёт и получить решение по двум пунктам:
1. Какие 10 городов берём (по колонке общего объёма).
2. Какие пары «город × роль» мертвы настолько, что канал не заводим.

Дописать решение в конец отчёта разделом «Решение владельца».

Это точка синхронизации, а не автоматический шаг. Дальше по плану идти после ответа.

- [ ] **Step 4: Commit**

```bash
git add citysonar/tools/measure_volumes.py citysonar/measurements/
git commit -m "feat(citysonar): скрипт замера объёмов Э0 + первый отчёт"
```

---

### Task 10: Ретенция

**Files:**
- Create: `citysonar/core/retention.py`
- Test: `citysonar/tests/test_retention.py`

**Interfaces:**
- Consumes: `store.connect`, `store.init_schema`
- Produces:
  - `retention.RAW_TTL_DAYS = 7`, `retention.ROW_TTL_DAYS = 60`, `retention.DUMP_KEEP = 10`
  - `retention.run(conn, dumps_dir: str, now: Optional[datetime] = None) -> dict` — возвращает счётчики выполненного

Без этого `raw` даёт ~6-7 ГБ/год с индексами на 20 ГБ диске, где уже живут ОС,
семь баз и логи. SQLite после `DELETE` не отдаёт место ОС без vacuum.

- [ ] **Step 1: Написать падающие тесты**

`citysonar/tests/test_retention.py`:
```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from citysonar.core import retention, store


def _conn(tmp_db):
    conn = store.connect(str(tmp_db))
    store.init_schema(conn)
    return conn


def _insert(conn, uid, days_ago, raw='{"a":1}'):
    seen = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO vacancies (uid, source, title, raw, first_seen, published_at) "
        "VALUES (?, 'hh', 'Аналитик', ?, ?, ?)",
        (uid, raw, seen, seen),
    )
    conn.commit()


def test_raw_cleared_after_ttl(tmp_db):
    conn = _conn(tmp_db)
    _insert(conn, "hh_old", days_ago=10)
    _insert(conn, "hh_new", days_ago=1)
    retention.run(conn, dumps_dir=None)
    old_raw = conn.execute("SELECT raw FROM vacancies WHERE uid='hh_old'").fetchone()[0]
    new_raw = conn.execute("SELECT raw FROM vacancies WHERE uid='hh_new'").fetchone()[0]
    assert old_raw is None
    assert new_raw is not None


def test_rows_deleted_after_row_ttl(tmp_db):
    conn = _conn(tmp_db)
    _insert(conn, "hh_ancient", days_ago=90)
    _insert(conn, "hh_recent", days_ago=10)
    retention.run(conn, dumps_dir=None)
    uids = {r[0] for r in conn.execute("SELECT uid FROM vacancies").fetchall()}
    assert uids == {"hh_recent"}


def test_outbox_rows_deleted_after_row_ttl(tmp_db):
    conn = _conn(tmp_db)
    old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat(timespec="seconds")
    new = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
    conn.execute("INSERT INTO outbox (channel_id, vacancy_uid, created_at) VALUES (1,'a',?)", (old,))
    conn.execute("INSERT INTO outbox (channel_id, vacancy_uid, created_at) VALUES (2,'b',?)", (new,))
    conn.commit()
    retention.run(conn, dumps_dir=None)
    rows = conn.execute("SELECT vacancy_uid FROM outbox").fetchall()
    assert [r[0] for r in rows] == ["b"]


def test_dumps_rotated(tmp_path, tmp_db):
    conn = _conn(tmp_db)
    dumps = tmp_path / "dumps"
    dumps.mkdir()
    for i in range(15):
        path = dumps / "dump_{:02d}.html".format(i)
        path.write_text("x", encoding="utf-8")
        # разводим mtime, чтобы порядок был детерминирован
        import os
        os.utime(path, (1_700_000_000 + i, 1_700_000_000 + i))
    retention.run(conn, dumps_dir=str(dumps))
    remaining = sorted(p.name for p in dumps.iterdir())
    assert len(remaining) == retention.DUMP_KEEP
    assert "dump_14.html" in remaining      # самый свежий остался
    assert "dump_00.html" not in remaining  # самый старый удалён


def test_run_returns_counters(tmp_db):
    conn = _conn(tmp_db)
    _insert(conn, "hh_old", days_ago=90)
    stats = retention.run(conn, dumps_dir=None)
    assert stats["vacancies_deleted"] == 1
    assert "raw_cleared" in stats
    assert "dumps_deleted" in stats
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `python -m pytest citysonar/tests/test_retention.py -v`
Ожидается: FAIL — `ModuleNotFoundError: No module named 'citysonar.core.retention'`

- [ ] **Step 3: Написать retention.py**

`citysonar/core/retention.py`:
```python
from __future__ import annotations

import logging
import os
import pathlib
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

RAW_TTL_DAYS = 7      # сырой JSON нужен только для разбора свежих регрессий
ROW_TTL_DAYS = 60     # сами вакансии
DUMP_KEEP = 10        # сколько HTML-дампов canary хранить


def _cutoff(now: datetime, days: int) -> str:
    return (now - timedelta(days=days)).isoformat(timespec="seconds")


def run(conn: sqlite3.Connection, dumps_dir: Optional[str], now: Optional[datetime] = None) -> dict:
    """Чистит БД и дампы. Возвращает счётчики сделанного.

    Порядок важен: сначала DELETE, потом incremental_vacuum — иначе
    освобождённые страницы не вернутся операционной системе.
    """
    now = now or datetime.now(timezone.utc)
    stats = {"raw_cleared": 0, "vacancies_deleted": 0, "outbox_deleted": 0, "dumps_deleted": 0}

    cur = conn.execute(
        "UPDATE vacancies SET raw = NULL WHERE raw IS NOT NULL AND first_seen < ?",
        (_cutoff(now, RAW_TTL_DAYS),),
    )
    stats["raw_cleared"] = cur.rowcount

    cur = conn.execute("DELETE FROM vacancies WHERE first_seen < ?", (_cutoff(now, ROW_TTL_DAYS),))
    stats["vacancies_deleted"] = cur.rowcount

    cur = conn.execute("DELETE FROM outbox WHERE created_at < ?", (_cutoff(now, ROW_TTL_DAYS),))
    stats["outbox_deleted"] = cur.rowcount

    conn.commit()
    conn.execute("PRAGMA incremental_vacuum")
    conn.commit()

    if dumps_dir:
        directory = pathlib.Path(dumps_dir)
        if directory.is_dir():
            files = sorted(
                (p for p in directory.iterdir() if p.is_file()),
                key=lambda p: p.stat().st_mtime,
            )
            for path in files[:-DUMP_KEEP] if len(files) > DUMP_KEEP else []:
                try:
                    os.remove(path)
                    stats["dumps_deleted"] += 1
                except OSError as e:
                    logging.warning("не удалось удалить дамп %s: %s", path, e)

    logging.info("ретенция: %s", stats)
    return stats
```

- [ ] **Step 4: Запустить тесты, убедиться что проходят**

Run: `python -m pytest citysonar/tests/test_retention.py -v`
Ожидается: 5 passed

- [ ] **Step 5: Commit**

```bash
git add citysonar/core/retention.py citysonar/tests/test_retention.py
git commit -m "feat(citysonar): ретенция — TTL сырого JSON и строк, incremental_vacuum, ротация дампов"
```

---

### Task 11: Canary — суточная проверка контракта

**Files:**
- Create: `citysonar/canary.py`
- Test: `citysonar/tests/test_canary.py`

**Interfaces:**
- Consumes: `hh.fetch_page`, `hh.Blocked`, `schema.StateContractError`, `store`, `retention`
- Produces:
  - `canary.Verdict` — константы `OK = "OK"`, `BLOCKED = "BLOCKED"`, `SCHEMA = "SCHEMA"`
  - `canary.classify(exc: Optional[Exception]) -> str`
  - `canary.check(session, conn, dumps_dir: str) -> Tuple[str, str]` — вердикт и текст отчёта
  - `canary.save_dump(dumps_dir: str, html: str) -> str` — путь сохранённого дампа

Классификация первым делом отделяет бан от поломки схемы. Иначе canary под
баном выдаст ложный «контракт нарушен», и человек полезет чинить работающий
парсер.

- [ ] **Step 1: Написать падающие тесты**

`citysonar/tests/test_canary.py`:
```python
from __future__ import annotations

import gzip
import pathlib

from citysonar import canary
from citysonar.core import hh, schema, store

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


class FakeResponse:
    def __init__(self, text="", status_code=200, url="https://hh.ru/search/vacancy"):
        self.text = text
        self.status_code = status_code
        self.url = url


class FakeSession:
    def __init__(self, response):
        self.response = response

    def get(self, url, params=None, timeout=None):
        return self.response


def _live_html():
    with gzip.open(FIXTURES / "search_page.html.gz", "rt", encoding="utf-8") as fh:
        return fh.read()


def _conn(tmp_db):
    conn = store.connect(str(tmp_db))
    store.init_schema(conn)
    return conn


def test_classify_none_is_ok():
    assert canary.classify(None) == canary.Verdict.OK


def test_classify_blocked():
    assert canary.classify(hh.Blocked("403")) == canary.Verdict.BLOCKED


def test_classify_schema_error():
    assert canary.classify(schema.StateContractError("нет поля")) == canary.Verdict.SCHEMA


def test_check_ok_on_live_fixture(tmp_path, tmp_db):
    session = FakeSession(FakeResponse(text=_live_html()))
    verdict, report = canary.check(session, _conn(tmp_db), str(tmp_path))
    assert verdict == canary.Verdict.OK
    assert "OK" in report


def test_check_reports_blocked_not_schema(tmp_path, tmp_db):
    """Бан IP не должен выглядеть как поломка разметки."""
    session = FakeSession(FakeResponse(status_code=403))
    verdict, report = canary.check(session, _conn(tmp_db), str(tmp_path))
    assert verdict == canary.Verdict.BLOCKED
    assert "заблокирован" in report.lower()


def test_check_reports_schema_and_saves_dump(tmp_path, tmp_db):
    session = FakeSession(FakeResponse(text="<html>разметка сменилась</html>"))
    verdict, report = canary.check(session, _conn(tmp_db), str(tmp_path))
    assert verdict == canary.Verdict.SCHEMA
    dumps = list(pathlib.Path(tmp_path).iterdir())
    assert len(dumps) == 1
    assert str(dumps[0]) in report


def test_check_writes_canary_run_row(tmp_path, tmp_db):
    conn = _conn(tmp_db)
    session = FakeSession(FakeResponse(text=_live_html()))
    canary.check(session, conn, str(tmp_path))
    row = conn.execute("SELECT verdict, ok FROM canary_runs").fetchone()
    assert row[0] == canary.Verdict.OK
    assert row[1] == 1
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `python -m pytest citysonar/tests/test_canary.py -v`
Ожидается: FAIL — `ModuleNotFoundError: No module named 'citysonar.canary'`

- [ ] **Step 3: Написать canary.py**

`citysonar/canary.py`:
```python
"""Суточная проверка контракта страницы hh.ru.

Запускается таймером systemd, живёт секунды. Первым делом отделяет бан IP
от поломки разметки: под баном парсер цел, чинить нечего.
"""
from __future__ import annotations

import datetime
import logging
import os
import pathlib
import sys
from typing import Optional, Tuple

from citysonar.core import hh, retention, schema, store

FIXTURES = (
    ("обычный поиск", {"text": "аналитик", "search_field": "name", "period": 1}),
    ("поиск по работодателю", {"employer_id": "1740", "period": 7}),
    ("поиск по региону и роли", {"area": "1", "professional_role": "10", "period": 1}),
)


class Verdict:
    OK = "OK"
    BLOCKED = "BLOCKED"
    SCHEMA = "SCHEMA"


def classify(exc: Optional[Exception]) -> str:
    if exc is None:
        return Verdict.OK
    if isinstance(exc, hh.Blocked):
        return Verdict.BLOCKED
    if isinstance(exc, schema.StateContractError):
        return Verdict.SCHEMA
    return Verdict.SCHEMA


def save_dump(dumps_dir: str, html: str) -> str:
    directory = pathlib.Path(dumps_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    path = directory / "hh-{}.html".format(stamp)
    path.write_text(html or "", encoding="utf-8")
    return str(path)


def check(session, conn, dumps_dir: str) -> Tuple[str, str]:
    """Прогоняет фикстуры. Возвращает (вердикт, текст отчёта)."""
    lines = []
    verdict = Verdict.OK
    last_html = ""

    for label, params in FIXTURES:
        error = None
        items = []
        try:
            captured = {}
            original_get = session.get

            def spy(url, params=None, timeout=None, _orig=original_get, _cap=captured):
                response = _orig(url, params=params, timeout=timeout)
                _cap["text"] = getattr(response, "text", "")
                return response

            session.get = spy
            try:
                items, _pages = hh.fetch_page(session, conn, params, 0)
            finally:
                session.get = original_get
            last_html = captured.get("text", "") or last_html
        except Exception as e:  # noqa: BLE001 — вердикт решает classify
            error = e
            last_html = last_html or ""

        current = classify(error)
        if current != Verdict.OK and verdict == Verdict.OK:
            verdict = current

        if current == Verdict.OK:
            lines.append("  {}: OK, вакансий {}".format(label, len(items)))
        elif current == Verdict.BLOCKED:
            lines.append("  {}: IP заблокирован — {}".format(label, error))
        else:
            detail = getattr(error, "detail", str(error))
            lines.append("  {}: контракт нарушен — {}".format(label, detail))

    stamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    header = "canary {} вердикт: {}".format(stamp, verdict)

    dump_path = None
    if verdict == Verdict.SCHEMA:
        dump_path = save_dump(dumps_dir, last_html)
        lines.append("  чинить: citysonar/core/schema.py и citysonar/core/hh.py::normalize")
        lines.append("  дамп: {}".format(dump_path))
    elif verdict == Verdict.BLOCKED:
        lines.append("  парсер цел, чинить нечего — ждать снятия бана, снизить частоту")

    report = "\n".join([header] + lines)

    conn.execute(
        "INSERT INTO canary_runs (run_at, ok, verdict, report, dump_path) VALUES (?, ?, ?, ?, ?)",
        (stamp, 1 if verdict == Verdict.OK else 0, verdict, report, dump_path),
    )
    conn.commit()

    return verdict, report


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    base = pathlib.Path(__file__).resolve().parent
    db_path = os.environ.get("CITYSONAR_DB", str(base / "citysonar.db"))
    dumps_dir = os.environ.get("CITYSONAR_DUMPS", str(base / "dumps"))

    conn = store.connect(db_path)
    store.init_schema(conn)
    session = hh.make_session()

    verdict, report = check(session, conn, dumps_dir)
    print(report)

    retention.run(conn, dumps_dir=dumps_dir)

    return 0 if verdict == Verdict.OK else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Запустить тесты, убедиться что проходят**

Run: `python -m pytest citysonar/tests/test_canary.py -v`
Ожидается: 7 passed

- [ ] **Step 5: Прогнать canary вживую**

Run: `python -m citysonar.canary`
Ожидается: `canary ... вердикт: OK` и три строки `OK, вакансий N`, код возврата 0.

- [ ] **Step 6: Commit**

```bash
git add citysonar/canary.py citysonar/tests/test_canary.py
git commit -m "feat(citysonar): canary — суточная проверка контракта hh, разделение бана и поломки схемы"
```

---

### Task 12: Worker — цикл сбора

**Files:**
- Create: `citysonar/worker.py`
- Test: `citysonar/tests/test_worker.py`

**Interfaces:**
- Consumes: всё предыдущее
- Produces:
  - `worker.build_local_params(city: config.City, role: config.Role, batch: str) -> dict`
  - `worker.build_remote_rich_params(role: config.Role, batch: str) -> dict`
  - `worker.build_remote_top_params(employer_ids: List[str]) -> dict`
  - `worker.harvest_key(session, conn, key: str, params: dict, max_pages: int) -> int` — читает, пишет вакансии, двигает курсор; возвращает число новых
  - `worker.harvest_cycle(session, conn, cities, roles, employer_batches) -> dict` — счётчики цикла
  - `worker.EMPLOYER_BATCH_SIZE = 40`, `worker.MAX_PAGES = 3`

Публикации на этом этапе нет вовсе: Э1 копит данные. `outbox` не заполняется —
иначе на go-live паблишер выльет недельный backlog устаревших постов.

- [ ] **Step 1: Написать падающие тесты**

`citysonar/tests/test_worker.py`:
```python
from __future__ import annotations

import gzip
import pathlib

from citysonar import worker
from citysonar.core import config, cursor, store

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


class FakeResponse:
    def __init__(self, text="", status_code=200, url="https://hh.ru/search/vacancy"):
        self.text = text
        self.status_code = status_code
        self.url = url


class FakeSession:
    def __init__(self, html):
        self.html = html
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(dict(params or {}))
        return FakeResponse(text=self.html)


def _live_html():
    with gzip.open(FIXTURES / "search_page.html.gz", "rt", encoding="utf-8") as fh:
        return fh.read()


def _conn(tmp_db):
    conn = store.connect(str(tmp_db))
    store.init_schema(conn)
    return conn


def test_local_params_carry_area_and_name_search():
    city = config.City(code="nn", name="НН", area_ids=["66", "247"])
    role = config.Role(code="analytics", name="Аналитика", keywords=["Аналитик"])
    params = worker.build_local_params(city, role, '"Аналитик"')
    assert params["area"] == ["66", "247"]
    assert params["search_field"] == "name"
    assert params["text"] == '"Аналитик"'
    assert "work_format" not in params      # локальная ветка не фильтрует формат


def test_remote_rich_params_have_no_area():
    role = config.Role(code="it", name="IT", keywords=["Разработчик"])
    params = worker.build_remote_rich_params(role, '"Разработчик"')
    assert params["work_format"] == "remote"
    assert "area" not in params


def test_remote_top_params_have_no_role_and_no_area():
    """Ветка топ-удалёнки собирается один раз на всю систему, роль назначается позже."""
    params = worker.build_remote_top_params(["1740", "15478"])
    assert params["employer_id"] == ["1740", "15478"]
    assert params["work_format"] == "remote"
    assert "text" not in params
    assert "area" not in params


def test_harvest_key_writes_vacancies_and_advances_cursor(tmp_db):
    conn = _conn(tmp_db)
    session = FakeSession(_live_html())
    written = worker.harvest_key(session, conn, "hh:local:nn:analytics", {"text": "x"}, max_pages=1)
    assert written > 0
    assert store.count_vacancies(conn) == written
    assert cursor.get(conn, "hh:local:nn:analytics") is not None


def test_harvest_key_second_run_writes_nothing_new(tmp_db):
    conn = _conn(tmp_db)
    session = FakeSession(_live_html())
    first = worker.harvest_key(session, conn, "k", {"text": "x"}, max_pages=1)
    second = worker.harvest_key(session, conn, "k", {"text": "x"}, max_pages=1)
    assert first > 0
    assert second == 0


def test_harvest_key_survives_block(tmp_db):
    """Бан одного ключа не должен ронять весь цикл."""
    conn = _conn(tmp_db)

    class BlockingSession:
        def get(self, url, params=None, timeout=None):
            return FakeResponse(status_code=403)

    written = worker.harvest_key(BlockingSession(), conn, "k", {"text": "x"}, max_pages=1)
    assert written == 0
    assert cursor.get(conn, "k") is None   # курсор не двигаем при неудаче


def test_harvest_cycle_covers_all_branches(tmp_db):
    conn = _conn(tmp_db)
    session = FakeSession(_live_html())
    cities = [config.City(code="nn", name="НН", area_ids=["66"])]
    roles = [config.Role(code="analytics", name="Аналитика", keywords=["Аналитик"])]
    stats = worker.harvest_cycle(session, conn, cities, roles, employer_batches=[["1740"]])
    assert stats["local"] >= 1
    assert stats["remote_top"] >= 1
    assert stats["remote_rich"] >= 1
    assert stats["blocked"] == 0


def test_harvest_cycle_does_not_touch_outbox(tmp_db):
    """Э1 только копит. Заполнение outbox — План 2."""
    conn = _conn(tmp_db)
    session = FakeSession(_live_html())
    cities = [config.City(code="nn", name="НН", area_ids=["66"])]
    roles = [config.Role(code="analytics", name="Аналитика", keywords=["Аналитик"])]
    worker.harvest_cycle(session, conn, cities, roles, employer_batches=[["1740"]])
    assert conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 0
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `python -m pytest citysonar/tests/test_worker.py -v`
Ожидается: FAIL — `ModuleNotFoundError: No module named 'citysonar.worker'`

- [ ] **Step 3: Написать worker.py**

`citysonar/worker.py`:
```python
"""Резидентный процесс CitySonar.

Этап 1: только сбор. Публикации нет — outbox не заполняется, иначе
на go-live паблишер вылил бы недельный backlog устаревших вакансий.
"""
from __future__ import annotations

import logging
import os
import pathlib
import random
import signal
import sys
import time
from typing import List

from citysonar.core import config, cursor, hh, retention, store

EMPLOYER_BATCH_SIZE = 40
MAX_PAGES = 3
CYCLE_SECONDS = 60 * 60          # час между циклами
BLOCK_BACKOFF_BASE = 300         # 5 минут, удваивается при серии блокировок
BLOCK_BACKOFF_MAX = 3600

_stop = False


def _signal_handler(sig, frame):
    global _stop
    logging.info("получен сигнал %s, останавливаюсь", sig)
    _stop = True


def build_local_params(city: config.City, role: config.Role, batch: str) -> dict:
    """Локальная ветка: город + название. Формат НЕ фильтруется намеренно —
    человеку в этом городе годится и офис, и гибрид, и удалёнка отсюда."""
    return {
        "text": batch,
        "search_field": "name",
        "area": list(city.area_ids),
    }


def build_remote_rich_params(role: config.Role, batch: str) -> dict:
    """Жирная удалёнка: без города, только формат."""
    return {
        "text": batch,
        "search_field": "name",
        "work_format": "remote",
    }


def build_remote_top_params(employer_ids: List[str]) -> dict:
    """Удалёнка топ-компаний. Один раз на всю систему, без роли и без города —
    роль назначает фильтр L1 в памяти (План 2)."""
    return {
        "employer_id": list(employer_ids),
        "work_format": "remote",
    }


def harvest_key(session, conn, key: str, params: dict, max_pages: int = MAX_PAGES) -> int:
    """Читает один ключ обхода, пишет вакансии, двигает курсор.

    Курсор двигается ТОЛЬКО после записи всех вакансий — иначе краш между
    чтением и записью потерял бы страницы безвозвратно.
    Блокировка и поломка схемы не роняют цикл: ключ пропускается.
    """
    try:
        items, newest = hh.crawl(session, conn, key, params, max_pages)
    except hh.Blocked as e:
        logging.warning("ключ %s: заблокирован (%s)", key, e)
        raise
    except Exception as e:  # noqa: BLE001 — включая StateContractError
        logging.error("ключ %s: %s", key, e)
        return 0

    written = 0
    for vacancy in items:
        if store.upsert_vacancy(conn, vacancy):
            written += 1

    cursor.advance(conn, key, newest)
    logging.info("ключ %s: получено %d, новых %d", key, len(items), written)
    return written


def harvest_cycle(session, conn, cities, roles, employer_batches) -> dict:
    """Один полный обход: локальные ключи, топ-удалёнка, жирная удалёнка."""
    stats = {"local": 0, "remote_top": 0, "remote_rich": 0, "new": 0, "blocked": 0}

    for city in cities:
        if not city.enabled:
            continue
        for role in roles:
            if not role.enabled:
                continue
            for batch in config.or_batches(role.keywords, size=6):
                key = "hh:local:{}:{}".format(city.code, role.code)
                params = build_local_params(city, role, batch)
                try:
                    stats["new"] += harvest_key(session, conn, key, params)
                    stats["local"] += 1
                except hh.Blocked:
                    stats["blocked"] += 1

    for index, batch_ids in enumerate(employer_batches):
        key = "hh:remote_top:{}".format(index)
        try:
            stats["new"] += harvest_key(session, conn, key, build_remote_top_params(batch_ids))
            stats["remote_top"] += 1
        except hh.Blocked:
            stats["blocked"] += 1

    for role in roles:
        if not role.enabled:
            continue
        for batch in config.or_batches(role.keywords, size=6):
            key = "hh:remote_rich:{}".format(role.code)
            try:
                stats["new"] += harvest_key(session, conn, key, build_remote_rich_params(role, batch))
                stats["remote_rich"] += 1
            except hh.Blocked:
                stats["blocked"] += 1

    logging.info("цикл завершён: %s", stats)
    return stats


def load_employer_batches(conn) -> List[List[str]]:
    """Батчи id топ-компаний. На Э1 таблица employers пуста — ветка
    топ-удалёнки просто не даёт ключей, это норма (наполнение — План 3)."""
    rows = conn.execute("SELECT id FROM employers ORDER BY id").fetchall()
    ids = [str(r[0]) for r in rows]
    return [ids[i:i + EMPLOYER_BATCH_SIZE] for i in range(0, len(ids), EMPLOYER_BATCH_SIZE)]


def main() -> int:
    base = pathlib.Path(__file__).resolve().parent
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(str(base / "log_citysonar.txt"), encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    db_path = os.environ.get("CITYSONAR_DB", str(base / "citysonar.db"))
    dumps_dir = os.environ.get("CITYSONAR_DUMPS", str(base / "dumps"))

    conn = store.connect(db_path)
    store.init_schema(conn)
    session = hh.make_session()

    cities = config.load_cities(str(base / "config" / "cities.yaml"))
    roles = config.load_roles(str(base / "config" / "roles.yaml"))

    logging.info("CitySonar worker запущен: городов %d, ролей %d", len(cities), len(roles))
    backoff = BLOCK_BACKOFF_BASE

    while not _stop:
        stats = harvest_cycle(session, conn, cities, roles, load_employer_batches(conn))
        retention.run(conn, dumps_dir=dumps_dir)

        if stats["blocked"] > 0:
            logging.warning("блокировок %d, пауза %d с", stats["blocked"], backoff)
            sleep_for = backoff
            backoff = min(backoff * 2, BLOCK_BACKOFF_MAX)
        else:
            backoff = BLOCK_BACKOFF_BASE
            sleep_for = CYCLE_SECONDS + random.randint(-300, 300)

        slept = 0
        while slept < sleep_for and not _stop:
            time.sleep(min(10, sleep_for - slept))
            slept += 10

    logging.info("worker остановлен")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Запустить тесты, убедиться что проходят**

Run: `python -m pytest citysonar/tests/test_worker.py -v`
Ожидается: 8 passed

- [ ] **Step 5: Прогнать весь набор**

Run: `python -m pytest citysonar/tests -v`
Ожидается: все 60 тестов passed

- [ ] **Step 6: Commit**

```bash
git add citysonar/worker.py citysonar/tests/test_worker.py
git commit -m "feat(citysonar): worker — цикл сбора по трём веткам, backoff при блокировке"
```

---

### Task 13: systemd и деплой

**Files:**
- Create: `citysonar/citysonar.service`
- Create: `citysonar/citysonar-canary.service`
- Create: `citysonar/citysonar-canary.timer`
- Create: `citysonar/citysonar-alert@.service`
- Create: `citysonar/tools/alert.py`
- Modify: `citysonar/README.md` (раздел «Деплой»)

**Interfaces:**
- Consumes: `worker.main`, `canary.main`
- Produces: рабочие юниты на сервере

- [ ] **Step 1: Написать юниты**

`citysonar/citysonar.service`:
```ini
[Unit]
Description=CitySonar harvester
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/root/JobSonar
ExecStart=/usr/bin/python3 -u -m citysonar.worker
Environment=PYTHONPATH=/root/JobSonar
Environment=CITYSONAR_DB=/root/JobSonar/citysonar/citysonar.db
Environment=CITYSONAR_DUMPS=/root/JobSonar/citysonar/dumps

# Память: cgroup v1 на Ubuntu 20.04 даёт по MemoryMax жёсткий SIGKILL.
# RestartSec и снятый StartLimit нужны, чтобы юнит не ушёл молча в failed
# после пяти быстрых рестартов подряд.
MemoryMax=300M
Restart=always
RestartSec=30
StartLimitIntervalSec=0

# CitySonar — гарантированная жертва глобального OOM-killer, чтобы под
# давлением памяти система убила его, а не рабочие боты JobSonar.
OOMScoreAdjust=500

OnFailure=citysonar-alert@%n.service

StandardOutput=append:/root/JobSonar/citysonar/log_citysonar_systemd.txt
StandardError=append:/root/JobSonar/citysonar/log_citysonar_systemd.txt

[Install]
WantedBy=multi-user.target
```

`citysonar/citysonar-canary.service`:
```ini
[Unit]
Description=CitySonar canary — проверка контракта hh.ru

[Service]
Type=oneshot
WorkingDirectory=/root/JobSonar
ExecStart=/usr/bin/python3 -u -m citysonar.canary
Environment=PYTHONPATH=/root/JobSonar
Environment=CITYSONAR_DB=/root/JobSonar/citysonar/citysonar.db
Environment=CITYSONAR_DUMPS=/root/JobSonar/citysonar/dumps
MemoryMax=200M
OOMScoreAdjust=500
OnFailure=citysonar-alert@%n.service
StandardOutput=append:/root/JobSonar/citysonar/log_canary.txt
StandardError=append:/root/JobSonar/citysonar/log_canary.txt
```

`citysonar/citysonar-canary.timer`:
```ini
[Unit]
Description=CitySonar canary раз в сутки

[Timer]
OnCalendar=*-*-* 06:30:00
Persistent=true
RandomizedDelaySec=600

[Install]
WantedBy=timers.target
```

`citysonar/citysonar-alert@.service`:
```ini
[Unit]
Description=CitySonar alert для %i

[Service]
Type=oneshot
WorkingDirectory=/root/JobSonar
ExecStart=/usr/bin/python3 -u citysonar/tools/alert.py %i
Environment=PYTHONPATH=/root/JobSonar
```

- [ ] **Step 2: Написать alert.py**

`citysonar/tools/alert.py`:
```python
"""Отправляет в админ-чат сообщение о сбое юнита CitySonar.

Вызывается systemd через OnFailure=. Первый аргумент — имя упавшего юнита.
Токен и чат берутся из окружения, чтобы не хранить их в git:
    CITYSONAR_ADMIN_TOKEN, CITYSONAR_ADMIN_CHAT
"""
from __future__ import annotations

import os
import subprocess
import sys

import requests


def main() -> int:
    unit = sys.argv[1] if len(sys.argv) > 1 else "неизвестный юнит"
    token = os.environ.get("CITYSONAR_ADMIN_TOKEN")
    chat = os.environ.get("CITYSONAR_ADMIN_CHAT")
    if not token or not chat:
        print("нет CITYSONAR_ADMIN_TOKEN / CITYSONAR_ADMIN_CHAT — алерт не отправлен")
        return 1

    try:
        tail = subprocess.check_output(
            ["journalctl", "-u", unit, "-n", "20", "--no-pager"],
            stderr=subprocess.STDOUT,
        ).decode("utf-8", "replace")[-1500:]
    except Exception as e:  # noqa: BLE001
        tail = "journalctl недоступен: {}".format(e)

    text = "🔥 <b>CitySonar: юнит {} упал</b>\n<pre>{}</pre>".format(unit, tail)
    try:
        requests.post(
            "https://api.telegram.org/bot{}/sendMessage".format(token),
            data={"chat_id": chat, "text": text[:4000], "parse_mode": "HTML"},
            timeout=15,
        )
    except Exception as e:  # noqa: BLE001
        print("не удалось отправить алерт: {}".format(e))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Дописать раздел деплоя в README**

Добавить в `citysonar/README.md`:
```markdown
## Деплой

Прямой SSH на BY-сервер не идёт — через RU-сервер как jump host.

    ssh -J root@194.87.248.87 root@45.134.26.151

На сервере:

    cd /root/JobSonar && git pull
    python3 -m pip install -r citysonar/requirements.txt

Swap обязателен (1 ГБ RAM без swap = мгновенный глобальный OOM):

    fallocate -l 2G /swapfile && chmod 600 /swapfile
    mkswap /swapfile && swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    swapon --show

Юниты:

    cp citysonar/citysonar.service citysonar/citysonar-canary.service \
       citysonar/citysonar-canary.timer citysonar/citysonar-alert@.service \
       /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable --now citysonar.service
    systemctl enable --now citysonar-canary.timer

Проверка:

    systemctl status citysonar
    systemctl list-timers citysonar-canary.timer
    tail -f /root/JobSonar/citysonar/log_citysonar.txt

Рабочие боты JobSonar при этом НЕ трогаются: CitySonar не импортирует
ничего из web/ и не делит с ними ни БД, ни юниты.
```

- [ ] **Step 4: Commit**

```bash
git add citysonar/citysonar.service citysonar/citysonar-canary.service \
        citysonar/citysonar-canary.timer citysonar/citysonar-alert@.service \
        citysonar/tools/alert.py citysonar/README.md
git commit -m "feat(citysonar): systemd юниты, алерт при падении, инструкция деплоя"
```

- [ ] **Step 5: Задеплоить и убедиться, что рабочие боты живы**

Выполнить шаги из README на сервере, затем:

Run:
```bash
ssh -J root@194.87.248.87 root@45.134.26.151 \
  'systemctl is-active jobsonar-hr jobsonar-analyst jobsonar-recruiter jobsonar-sales jobsonar-nn jobsonar-cs jobsonar-po jobsonar-monitor citysonar; free -m'
```

Ожидается: все `jobsonar-*` по-прежнему `active`, `citysonar` тоже `active`,
свободной памяти достаточно с учётом swap.

**Если хоть один jobsonar-* перестал быть active — немедленно
`systemctl stop citysonar` и разбираться.** Рабочие боты приоритетнее.

- [ ] **Step 6: Проверить первый цикл живьём**

Run:
```bash
ssh -J root@194.87.248.87 root@45.134.26.151 \
  'sleep 300; tail -30 /root/JobSonar/citysonar/log_citysonar.txt; sqlite3 /root/JobSonar/citysonar/citysonar.db "SELECT COUNT(*) FROM vacancies;"'
```

Ожидается: строки `ключ hh:local:nn:analytics: получено N, новых M`, в БД
ненулевое число вакансий.

- [ ] **Step 7: Commit финального состояния README**

```bash
git add citysonar/README.md
git commit -m "docs(citysonar): зафиксировано окружение сервера и результат первого запуска"
```

---

## Что дальше

Э1 работает **24 часа**. По её итогам:

1. Посчитать `national_p50/p70` по ролям и `city_coef` по городам из накопленных
   `vacancies` — это входные данные для порогов Плана 2. Национальная выборка
   набирает тысячи вакансий с указанной зарплатой за несколько циклов, неделя
   для статистики не нужна.
2. Свести отчёт: сколько вакансий в сутки на пару, доля LOCAL против REMOTE,
   доля вакансий с указанной зарплатой, доля `_is_blocked`.
3. Проверить, что canary отработал хотя бы раз с вердиктом OK.

Если через сутки `n` по какой-то роли меньше 100 — эта роль стартует без
порога (и метит это в лог), а не ждёт неделю. Порог доедет со следующим
недельным пересчётом.

**План 2** (Э2-Э3): L1-профили ролей с офлайн-тестами, роутер с тремя ветками
и приоритетом, паблишер с лимитером и регистрацией каналов, пилот на одном
городе и четырёх ролях.

**План 3** (Э4-Э5): топ-лист компаний по `employer_id`, `remote_score`,
раскатка на 10 городов.

Планы 2 и 3 пишутся после разбора данных Э1 — их параметры зависят от
измеренного, а не от предположений.
