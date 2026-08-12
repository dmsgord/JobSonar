# JobSonar Refactoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Убрать дублирование кода между 4 ботами, улучшить обработку ошибок — не сломав продакшн.

**Architecture:** Общий код выносится в `web/utils.py` (уже частично там). Каждый бот остаётся отдельным процессом с отдельным токеном. Правки минимальны и обратно совместимы — боты продолжают работать после каждого шага.

**Tech Stack:** Python 3, pyTelegramBotAPI, requests, SQLite, systemd/screen на сервере.

---

## Карта файлов

| Файл | Что меняем |
|------|-----------|
| `web/utils.py` | Добавляем `send_daily_stats()` и улучшаем `send_telegram()` с уведомлением об ошибке |
| `web/main.py` | Убираем дублированный блок сводки и инициализации |
| `web/main_analyst.py` | То же |
| `web/main_sales.py` | То же |
| `web/main_recruiter.py` | То же |
| `root/README_DEPRECATED.md` | Создаём — маркируем старый код как нерабочий |

---

## Task 1: Улучшить обработку ошибок в utils.py

**Наименьший риск, наибольшая польза. Делать первым.**

**Files:**
- Modify: `web/utils.py`

- [ ] **Шаг 1: Найти функцию send_telegram в utils.py**

```bash
grep -n "def send_telegram" D:/JobSonar/web/utils.py
```

- [ ] **Шаг 2: Найти все except в ботах чтобы понять текущий паттерн**

```bash
grep -n "except Exception" D:/JobSonar/web/main.py D:/JobSonar/web/main_analyst.py D:/JobSonar/web/main_sales.py D:/JobSonar/web/main_recruiter.py
```

- [ ] **Шаг 3: Добавить функцию report_error в utils.py**

Найти конец файла `web/utils.py` и добавить:

```python
import traceback

def report_error(e: Exception, token: str, chat_id: str, context: str = ""):
    """Логирует ошибку с traceback и отправляет уведомление в Telegram."""
    tb = traceback.format_exc()
    logging.error(f"Error{f' in {context}' if context else ''}: {e}\n{tb}")
    try:
        msg = f"🔥 <b>Ошибка бота{f' ({context})' if context else ''}:</b>\n<code>{str(e)[:300]}</code>"
        _send_telegram_raw(token, chat_id, msg)
    except Exception:
        pass  # Если Telegram недоступен — не падаем повторно
```

- [ ] **Шаг 4: Убедиться что _send_telegram_raw существует или добавить алиас**

```bash
grep -n "def _send_telegram\|def send_telegram" D:/JobSonar/web/utils.py
```

Если функция называется иначе — использовать её имя в report_error.

- [ ] **Шаг 5: Обновить except блоки в каждом боте**

В каждом из 4 файлов (`main.py`, `main_analyst.py`, `main_sales.py`, `main_recruiter.py`) заменить:

```python
# БЫЛО:
except Exception as e:
    logging.error(f"Error: {e}")
    time.sleep(60)

# СТАЛО:
except Exception as e:
    report_error(e, TG_TOKEN, TG_CHAT_ID, context="main_loop")
    time.sleep(60)
```

И добавить импорт в начало каждого файла:

```python
from utils import report_error
```

- [ ] **Шаг 6: Проверить что боты запускаются**

```bash
cd D:/JobSonar/web && python -c "import main; print('HR OK')"
cd D:/JobSonar/web && python -c "import main_analyst; print('Analyst OK')"
cd D:/JobSonar/web && python -c "import main_sales; print('Sales OK')"
cd D:/JobSonar/web && python -c "import main_recruiter; print('Recruiter OK')"
```

Ожидаемый результат: каждый выводит `OK` без ошибок импорта.

- [ ] **Шаг 7: Коммит**

```bash
git add web/utils.py web/main.py web/main_analyst.py web/main_sales.py web/main_recruiter.py
git commit -m "fix: add traceback logging and Telegram error notifications"
```

---

## Task 2: Вынести дневную сводку в utils.py

**Files:**
- Modify: `web/utils.py`
- Modify: `web/main.py`, `web/main_analyst.py`, `web/main_sales.py`, `web/main_recruiter.py`

- [ ] **Шаг 1: Проверить сигнатуру get_daily_stats в db.py**

```bash
grep -n "def get_daily_stats" D:/JobSonar/web/db.py
```

- [ ] **Шаг 2: Добавить send_daily_stats в utils.py**

```python
def send_daily_stats(bot_name: str, token: str, chat_id: str, stats: dict):
    """Отправляет дневную сводку в Telegram. Вызывать один раз в сутки при hour >= 23."""
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
```

- [ ] **Шаг 3: Заменить блок сводки в main.py**

Найти блок (около строки 232–243):

```python
# БЫЛО:
if now.hour >= 23 and last_stats_date != today:
    msg = f"🌙 <b>Итоги HR:</b>\nТоп компании: {stats.get('Топ компании', 0)}\nОстальные: {stats.get('Остальные', 0)}\nВсего: {total}"
    send_telegram(msg)
    last_stats_date = today

# СТАЛО:
if now.hour >= 23 and last_stats_date != today:
    send_daily_stats("HR", TG_TOKEN, TG_CHAT_ID, stats)
    last_stats_date = today
```

Добавить импорт: `from utils import send_daily_stats`

- [ ] **Шаг 4: То же для main_analyst.py**

```python
# БЫЛО:
if now.hour >= 23 and last_stats_date != today:
    msg = f"🌙 <b>Итоги Analyst:</b>\n..."
    send_telegram(msg)
    last_stats_date = today

# СТАЛО:
if now.hour >= 23 and last_stats_date != today:
    send_daily_stats("Analyst", TG_TOKEN, TG_CHAT_ID, stats)
    last_stats_date = today
```

- [ ] **Шаг 5: То же для main_sales.py**

```python
if now.hour >= 23 and last_stats_date != today:
    send_daily_stats("Sales", TG_TOKEN, TG_CHAT_ID, stats)
    last_stats_date = today
```

- [ ] **Шаг 6: То же для main_recruiter.py**

```python
if now.hour >= 23 and last_stats_date != today:
    send_daily_stats("Recruiter", TG_TOKEN, TG_CHAT_ID, stats)
    last_stats_date = today
```

- [ ] **Шаг 7: Проверить импорты во всех файлах**

```bash
grep -n "send_daily_stats" D:/JobSonar/web/main.py D:/JobSonar/web/main_analyst.py D:/JobSonar/web/main_sales.py D:/JobSonar/web/main_recruiter.py
```

Ожидаемый результат: 2 строки на файл (импорт + вызов).

- [ ] **Шаг 8: Проверить импорты**

```bash
cd D:/JobSonar/web && python -c "import main; import main_analyst; import main_sales; import main_recruiter; print('ALL OK')"
```

- [ ] **Шаг 9: Коммит**

```bash
git add web/utils.py web/main.py web/main_analyst.py web/main_sales.py web/main_recruiter.py
git commit -m "refactor: extract send_daily_stats to utils, remove duplicated summary blocks"
```

---

## Task 3: Убрать дублированные обёртки инициализации

**Осторожно: самый рискованный шаг. Делать последним, по одному боту.**

**Files:**
- Modify: `web/utils.py`
- Modify: `web/main.py` (сначала только этот, потом остальные)

- [ ] **Шаг 1: Посмотреть все обёртки в main.py**

```bash
grep -n "def set_status\|def send_telegram\|def check_remote_stop\|def fetch_" D:/JobSonar/web/main.py
```

- [ ] **Шаг 2: Добавить класс BotContext в utils.py**

```python
import functools

class BotContext:
    """Контекст бота — хранит конфиг и предоставляет обёртки над utils."""
    
    def __init__(self, token: str, chat_id: str, status_file: str, db_name: str):
        self.token = token
        self.chat_id = chat_id
        self.status_file = status_file
        self.session = requests.Session()
        self.session.headers.update(BROWSER_HEADERS)
        self.last_update_id = 0
        self.bot_id = token.split(':')[0] if token else "0"
        
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
        
        set_db_name(db_name)
    
    def set_status(self, text: str):
        _set_status(self.status_file, text)
    
    def send_telegram(self, text: str):
        _send_telegram(self.token, self.chat_id, text)
    
    def check_remote_stop(self):
        self.last_update_id = _check_remote_stop(
            self.token, self.chat_id, self.bot_id, self.last_update_id
        )
    
    def fetch_company_vacancies(self, employer_ids, area=None, schedule=None, period=3):
        return _fetch_company_vacancies(self.session, employer_ids, area=area, schedule=schedule, period=period)
    
    def fetch_hh_paginated(self, text: str, period: int = 7, schedule=None):
        return fetch_hh_paginated(self.session, text, period=period, schedule=schedule)
```

- [ ] **Шаг 3: Проверить что BotContext импортируется**

```bash
cd D:/JobSonar/web && python -c "from utils import BotContext; print('BotContext OK')"
```

- [ ] **Шаг 4: Обновить main.py — только HR бот, остальные не трогать**

В начале main.py после импортов заменить блок инициализации:

```python
# БЫЛО:
session = requests.Session()
session.headers.update(BROWSER_HEADERS)
set_db_name(os.path.join(BASE_DIR, DB_NAME))
BOT_ID = TG_TOKEN.split(':')[0] if TG_TOKEN else "0"
LAST_UPDATE_ID = 0
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

def set_status(text): _set_status(STATUS_FILE, text)
def send_telegram(text): _send_telegram(TG_TOKEN, TG_CHAT_ID, text)
def check_remote_stop():
    global LAST_UPDATE_ID
    LAST_UPDATE_ID = _check_remote_stop(TG_TOKEN, TG_CHAT_ID, BOT_ID, LAST_UPDATE_ID)
def fetch_company_vacancies(...): ...

# СТАЛО:
from utils import BotContext
bot = BotContext(TG_TOKEN, TG_CHAT_ID, STATUS_FILE, os.path.join(BASE_DIR, DB_NAME))
session = bot.session

def set_status(text): bot.set_status(text)
def send_telegram(text): bot.send_telegram(text)
def check_remote_stop(): bot.check_remote_stop()
def fetch_company_vacancies(employer_ids, area=None, schedule=None, period=3):
    return bot.fetch_company_vacancies(employer_ids, area=area, schedule=schedule, period=period)
```

- [ ] **Шаг 5: Проверить HR бот**

```bash
cd D:/JobSonar/web && python -c "import main; print('HR OK')"
```

- [ ] **Шаг 6: Если OK — повторить для main_analyst.py, main_sales.py, main_recruiter.py**

Аналогичная замена в каждом файле. Проверять после каждого:

```bash
cd D:/JobSonar/web && python -c "import main_analyst; print('Analyst OK')"
cd D:/JobSonar/web && python -c "import main_sales; print('Sales OK')"
cd D:/JobSonar/web && python -c "import main_recruiter; print('Recruiter OK')"
```

- [ ] **Шаг 7: Финальная проверка всех**

```bash
cd D:/JobSonar/web && python -c "import main, main_analyst, main_sales, main_recruiter; print('ALL OK')"
```

- [ ] **Шаг 8: Коммит**

```bash
git add web/utils.py web/main.py web/main_analyst.py web/main_sales.py web/main_recruiter.py
git commit -m "refactor: extract BotContext to utils, remove duplicated init blocks"
```

---

## Task 4: Пометить мёртвый код в root/

**Files:**
- Create: `README_DEPRECATED.md` в корне репозитория

- [ ] **Шаг 1: Создать файл**

```markdown
# ⚠️ DEPRECATED — Старая API-версия

Файлы в корне репозитория (`main.py`, `main_analyst.py`, `main_sales.py`, `main_recruiter.py`)
— это **нерабочая** версия на HH.ru API, который закрыт.

**Активная версия:** `web/` папка.

Не запускать файлы из корня на сервере.
```

- [ ] **Шаг 2: Коммит**

```bash
git add README_DEPRECATED.md
git commit -m "docs: mark root/ as deprecated API version, web/ is active"
```

---

## Порядок выполнения

1. **Task 1** — ошибки (безопасно, только добавляем код)
2. **Task 4** — документация (нулевой риск)
3. **Task 2** — сводки (меняем поведение, но логика та же)
4. **Task 3** — инициализация (самый рискованный, делать последним, по одному боту)

После каждого Task — `git push`, деплой на сервер, убедиться что боты живы.
