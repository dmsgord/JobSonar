# CitySonar — сеть Telegram-каналов «город × роль»

Дата: 2026-08-12
Статус: дизайн согласован, к реализации

## 1. Задача

Человек из крупного города должен первым видеть хорошие вакансии для себя: либо
классную удалёнку в топ-компании, либо что-то стоящее внутри своей агломерации.

Единица системы — **канал = пара (город, роль)**. Например «Краснодар · Аналитика»,
«Казань · HR линейный». Роли узкие намеренно: подписчик не должен фильтровать ленту сам.

Топ-10 городов по фактическому объёму вакансий (замеряется, не угадывается).
Дальше раскатка на остальные — конфигом, не кодом.

## 2. Почему не расширение существующих ботов

Текущий JobSonar: 7 процессов, ось = роль, каждый бот сам ходит в hh.ru.
Прямое размножение на сетку городов даёт 10 × 7 = 70 процессов — невозможно
ни по памяти, ни по анти-боту hh.

Конкретные блокеры, выявленные аудитом кода:

| Находка | Где | Следствие |
|---|---|---|
| Гео зашито в **fetch**, не только в фильтр | `main_analyst.py:194`, `main.py:175`, `main_cs.py:165` — `fetch_company_vacancies(..., area=TARGET_AREAS)` | Топ-компании ищутся только в Москве/НН. Ветка «удалёнка топов по стране» физически не запрашивается |
| Remote детектится текстом | `main.py:102`, `main_analyst.py:107`, `main_cs.py:62`, `main_sales.py:96` — `'удал' in details_text` | Не различает «строго офис» и «офис + удалёнка». Уже давало баг с е/ё. Структурный `work_format` читает только `main_po.py:109` |
| Sales требует remote для всего | `main_sales.py:97` | В городском канале локальные вакансии не пройдут вообще |
| Пороги зарплат глобальные | Analyst 200k, PO 150k, CS 100k | В регионах отсекает почти всё |
| Троттл попроцессный | `utils.py:335` `_last_request_ts` module-level | 7 процессов не видят друг друга → всплески к hh.ru → 403 |
| БД не хранит вакансию | `db.py` — таблица `(id, category, created_at)` | Нельзя раздать одну вакансию в N каналов без повторного запроса |
| Дедуп мульти-город в памяти | `main_po.py:98` `SENT_SIGNATURES` | Перезапуск → дубли |

Переиспользуется как есть: парсер SSR-стейта (`_extract_state_json`,
`_normalize_vacancy`), анти-бот обвязка (`_throttle`/`_refresh_session`/детект
`vpncheeck`), пагинация через `paging.lastPage`, семантика `format_salary`,
уроки фильтрации из памяти проекта.

## 3. Правило публикации

```
publish(v, channel(city C, role R)) ⟸
    R.matches(v)                                  # L1: чистая роль, без гео/формата/зп
    AND (
        LOCAL:        v.area ∈ C.area_ids         # формат ЛЮБОЙ, включая неизвестный
        OR REMOTE_TOP:   is_remote(v) AND employer ∈ ТОП
        OR REMOTE_RICH:  is_remote(v) AND salary ≥ min_salary_remote(C,R)
    )
    AND quality_gate(v, C, R)
```

`LOCAL` не фильтрует формат намеренно: человек в этом городе — ему годится офис,
гибрид и удалёнка отсюда одинаково. Строгость формата нужна только в REMOTE-ветках.

`REMOTE` требует «топ-компания ИЛИ высокая зарплата» — иначе удалёнка вырождается
в поток низкооплачиваемого шлака.

`quality_gate` применяется по ветке, а не одинаково ко всем:

| Ветка | Порог зарплаты | Прочее |
|---|---|---|
| LOCAL | `min_salary_local` (p50 город×роль) | `skip_no_experience` |
| REMOTE_TOP | не применяется — членство в топ-листе и есть критерий | `skip_no_experience` |
| REMOTE_RICH | `min_salary_remote` (p70 по роли) — он же условие ветки | `skip_no_experience` |

Семантика зарплаты сохраняется из текущего кода: не указана → показываем
(там часто прячутся хорошие); указана в RUR и ниже порога → скрываем;
USD/EUR → показываем всегда.

REMOTE-ветки собираются **один раз глобально на роль** и раздаются в каналы этой
роли во всех городах. Это главная экономия запросов и главный наполнитель узких
каналов в небольших городах.

## 4. Три слоя фильтра

Сейчас всё слеплено в один `filter_and_process`. Разбираем на ортогональные слои:

| Слой | Содержимое | Область действия |
|---|---|---|
| **L1 RoleProfile** | keywords, professional_role ids, маркеры / уровень+контекст, stop_words, prefix_stop_words, display_skills | Общий для всех городов. Ноль гео, ноль формата, ноль зарплаты |
| **L2 GeoFormat** | `area_ids` агломерации, `BLACKLISTED_AREAS`, политика неизвестного формата | Параметр канала |
| **L3 Quality** | `min_salary_local`, `min_salary_remote`, `skip_no_experience`, `require_top_for_remote` | На пару (город, роль) |

L1 — код + конфиг роли, пишется один раз. L2/L3 — строки в БД.
Новый город = N строк, а не N файлов.

Побочный выигрыш: L1 тестируется офлайн на фикстурах без сети. Сейчас это
невозможно — гео и формат прибиты к тому же циклу, что и HTTP.

### Интерфейс L1

```python
@dataclass
class RoleProfile:
    code: str                      # 'hr_line'
    name: str                      # 'HR линейный'
    keywords: list[str]            # OR-батчи, search_field=name
    professional_roles: list[str]  # сетка покрытия под кривые тайтлы
    def matches(self, v: Vacancy) -> bool: ...  # ТОЛЬКО тайтл
    def skills(self, v: Vacancy) -> list[str]: ...  # для отображения
```

`matches` не принимает ни город, ни формат, ни зарплату — это гарантируется тестом.

## 5. Роли

| # | code | Роль | Источник фильтра |
|---|---|---|---|
| 1 | `hr_line` | HR линейный | `config_recruiter.py` + низ `config.py` |
| 2 | `hr_lead` | HR управленческий | верх `config.py` (HRD/Head of HR/HRBP) |
| 3 | `analytics` | Аналитика | `config_analyst.py`, снять гео и порог 200k |
| 4 | `sales` | Продажи | `config_sales.py`, снять remote-only |
| 5 | `it` | IT / разработка | с нуля |
| 6 | `marketing` | Маркетинг | с нуля |
| 7 | `finance` | Финансы | с нуля |

Не включены: Customer Service, Product Owner, Операционный директор/COO — слишком
узкие для городской сетки. Хвост на будущее: отдельный «бот топов» под узкие роли.

Разделение HR по уровню: граница по маркерам в тайтле (руководитель / директор /
head / начальник / глава → `hr_lead`, иначе `hr_line`). Пограничные вроде «Ведущий
рекрутер» → `hr_line`. L1-профили взаимоисключающие: вакансия попадает ровно в один канал.

## 6. Пороги зарплат — из данных

Глобальные константы заменяются перцентилями рынка по паре (город, роль):

- `min_salary_local` = p50 распределения по (город, роль) за 30 дней
- `min_salary_remote` = p70 всероссийского распределения по роли (конкуренция шире)

Пересчёт раз в неделю, ручной override поверх (колонка в `channels` побеждает).
Зарплату указывают ~30-40% вакансий — для перцентиля достаточно.

Бутстрап: Э1 копит 7 дней без публикации, стартовые пороги ставятся по факту.

## 7. Обход hh.ru

| Ветка | Запрос | Кратность |
|---|---|---|
| LOCAL | OR-батч keywords + `area=<агломерация>` + `professional_role`, инкрементально по `publication_time` | 10 городов × R ролей |
| REMOTE_TOP | `employer_id` батчами по ~40 × `work_format=remote`, **без area** | R ролей, один раз на все города |
| REMOTE_RICH | OR-батч keywords + `work_format=remote`, без employer | R ролей, один раз |

Инкрементальность: читаем страницы, пока `published_at > cursor[ключ]`.
Обычно 2-4 страницы вместо слепого `period=7`.

Оценка при R=7: ≈ 240 запросов/цикл × 2с троттла ≈ 8 мин активной работы.
Цикл 45-60 мин → средние ~0.07 rps. Ниже текущей суммарной нагрузки 7 ботов.

Троттл **общий на процесс** — это лечение первопричины 403, а не симптома.

`work_format` читается структурно (массив), текстовый детект remote не используется.
«Строго офис» = в массиве нет ни `remote`, ни `hybrid`.

## 8. Компоненты

Один резидентный процесс `worker.py`, стадии внутри цикла. Шов между стадиями —
таблица `outbox` в БД, а не граница процесса: упал → перезапустился → доигрывает
с курсора. Устойчивость сохранена, память минимальна.

```
worker.py  (единственный резидент, ~60-80 МБ)
  ├─ stage 1  harvest   → vacancies      единственный ходок в hh, одна сессия, один троттл
  ├─ stage 2  route     → outbox         L1 → L2 → L3 по каждому активному каналу
  ├─ stage 3  publish   → Telegram       ретрай, rate-limit, курсор по outbox
  └─ stage 4  register                   приём my_chat_member, привязка каналов

canary.py  (cron раз в сутки, не резидент)  проверка контракта hh + дамп + диагноз
```

systemd-юнит: `MemoryMax=250M`, `Restart=always`. Утечка убивает только CitySonar,
не морозит коробку (прецедент 2026-06-10 лечился только hard power-cycle).

## 9. Схема БД (SQLite, WAL)

```sql
vacancies(
  uid TEXT PRIMARY KEY,        -- '<source>_<id>', напр. hh_12345678
  source TEXT, source_id TEXT,
  title TEXT, employer_id TEXT, employer_name TEXT,
  area_id TEXT, area_name TEXT,
  salary_from INT, salary_to INT, salary_currency TEXT,
  work_formats TEXT,           -- csv: remote,hybrid,onSite,field
  schedule_id TEXT, experience_id TEXT,
  published_at TEXT, url TEXT,
  raw TEXT,                    -- исходный json, для разбора регрессий
  first_seen TEXT,
  signature TEXT               -- employer_id + нормализованный title
);
CREATE INDEX ix_vac_pub ON vacancies(published_at);
CREATE INDEX ix_vac_sig ON vacancies(signature);
CREATE INDEX ix_vac_emp ON vacancies(employer_id);

cities(code TEXT PRIMARY KEY, name TEXT, area_ids TEXT, enabled INT);
roles(code TEXT PRIMARY KEY, name TEXT, enabled INT);

channels(
  id INTEGER PRIMARY KEY, city_code TEXT, role_code TEXT,
  chat_id TEXT UNIQUE, title TEXT,
  min_salary_local INT, min_salary_remote INT,
  skip_no_experience INT, require_top_for_remote INT,
  state TEXT,                  -- pending | active | paused
  UNIQUE(city_code, role_code)
);

outbox(
  id INTEGER PRIMARY KEY, channel_id INT, vacancy_uid TEXT,
  branch TEXT,                 -- local | remote_top | remote_rich
  score REAL, state TEXT,      -- queued | sent | failed | skipped
  created_at TEXT, sent_at TEXT, error TEXT,
  UNIQUE(channel_id, vacancy_uid)
);

crawl_cursor(key TEXT PRIMARY KEY, last_published_at TEXT, last_run TEXT);
  -- key: 'hh:local:<city>:<role>' | 'hh:remote_top:<role>' | 'hh:remote_rich:<role>'

employers(
  id TEXT PRIMARY KEY, name TEXT, tier TEXT,
  remote_seen INT, total_seen INT, last_seen TEXT, source TEXT
);

salary_stats(
  city_code TEXT, role_code TEXT, branch TEXT,
  p50 INT, p70 INT, n INT, computed_at TEXT,
  PRIMARY KEY(city_code, role_code, branch)
);

canary_runs(id INTEGER PRIMARY KEY, run_at TEXT, ok INT, report TEXT, dump_path TEXT);
```

Дедуп мульти-город — по `signature` в БД (TTL 14 дней), а не в памяти процесса.
Одна вакансия, опубликованная по 12 городам, уходит в свой городской канал один раз.

## 10. Регистрация каналов

Один бот-токен на все каналы: Telegram-бот админит неограниченное число каналов.

Владелец создаёт канал с названием по шаблону `<Город> · <Роль>` и добавляет бота
админом. Бот получает апдейт `my_chat_member` с `chat.id` и `chat.title`, парсит
название, находит пару (город, роль), пишет строку в `channels` со `state=active`.

Название не распозналось → строка `state=pending` + алерт в админ-канал.
Ручной выковыриваемый `chat_id` не нужен ни для одного из каналов.

`getUpdates` с `allowed_updates=["my_chat_member"]` — потребитель один (worker —
единственный процесс на токен, конфликта нет).

## 11. Подача и ранжирование

Поток, без дайджестов. Обоснование: канал узкий (город × одна роль), объём низкий
по определению — дайджест здесь решал бы проблему, которой нет, и терял бы скорость,
ради которой всё делается.

Ранжирование считается, но используется для маркера, не для отсечения:

```
score = w1·tier(employer) + w2·salary_ratio(v, порог) + w3·freshness + w4·is_remote
```

🔥 — верхний дециль внутри канала за 7 дней. Бинарное правило «топ + remote»
(`main_po.py:221`) в узком канале обесценивается: там почти всё топ + remote.

Хештеги в посте: `#удалёнка` / `#гибрид` / `#офис`, `#<город>`, `#<роль>`.
Дают поиск внутри канала бесплатно.

Rate-limit Telegram: 20 сообщений/мин на канал, ~30/с глобально. Publisher держит
оба лимита, при `429` уважает `retry_after`. Ретрай с backoff — у текущего
`utils.send_telegram` ретрая нет, при моргании сети хостера вакансия теряется.

## 12. Топ-лист компаний

Текущий `whitelist.py` — 797 компаний, 4 тира, сгенерён из ручной CSV
(`generate_whitelist.py`). Проверено grep-ом: **отсутствуют** Т-Банк/Тинькофф,
Wildberries, МТС, Ростелеком, Билайн, Kaspersky, EPAM, Positive Technologies —
то есть ядро remote-friendly работодателей. При этом внутри есть АН Этажи,
Пятёрочка, КЛЮЧАВТО, Аптеки Плюс — ритейл/полевые, удалёнки не дающие.

Переделка:
1. Из `.py` в таблицу `employers` (данные, не код).
2. Поле `remote_score = remote_seen / total_seen` считает сам harvester по факту
   наблюдений. Ритейл-балласт уезжает вниз сам, без ручной чистки.
3. Закрыть дыры вручную: Т-Банк, Wildberries, МТС, Ростелеком, Билайн, Kaspersky,
   EPAM, Positive Technologies, Selectel, JetBrains, СберТех, Астра, Диасофт, ICL,
   Bercut, Nexign.
4. Авто-пополнение: раз в неделю отчёт «часто встречаются, платят выше порога,
   но не в топ-листе: X, Y, Z» → добавление одной командой.

## 13. Canary — суточная проверка контракта hh

Cron раз в сутки + триггер при N подряд пустых страницах.

Три фикстуры: обычный поиск, поиск по `employer_id`, поиск `area + professional_role`.

Ассерты:
- стейт извлекается (`HH-Lux-InitialState` → unescape → `json.loads`)
- `vacancySearchResult.vacancies` непустой
- на каждой вакансии живы: `vacancyId`, `name`, `company.visibleName`,
  `compensation.currencyCode`, `workFormats[].workFormatsElement`, `@workSchedule`,
  `publicationTime.$`, `area.@id`
- `paging.lastPage.page` присутствует

Отчёт при поломке — точный диагноз, не «ошибка»:

```
hh.ru контракт нарушен 2026-08-13 09:00
  пропало: compensation.currencyCode (20/20 вакансий)
  чинить:  core/hh.py :: normalize_vacancy, ветка salary
  дамп:    /opt/citysonar/dumps/2026-08-13T09-00.html
  ждали ключей: [...]   пришли: [...]
```

Автопатч в прод не делаем. Средний вариант: scheduled Claude-агент раз в сутки
читает отчёт + дамп и готовит патч в ветке. Мёрдж — руками.

Обоснование приоритета: 2026-07-17 hh сменил разметку стейта, **все боты молча
слали 0**, и заметили это не сразу.

## 14. Размещение

Существующий BY-сервер (1 ГБ). Новый VPS не покупается: сетевая нагрузка
CitySonar ниже, чем у нынешних 7 ботов, а RAM решается одним процессом
с `MemoryMax=250M`.

На Э0 измеряется `free -m` и RSS каждого бота. Если свободного меньше ~250 МБ —
возврат к вопросу о железе с цифрами на руках.

Код: новый каталог `citysonar/` в существующем репозитории. Обоснование — один
`git pull` деплоит всё, и при этом код полностью изолирован: `citysonar/` не
импортирует из `web/`, а несёт свою копию парсинга hh. Правка CitySonar физически
не может сломать работающие боты.

Хвост на будущее (не в этой спеке): старые боты переезжают на общий харвестер
и перестают ходить в hh сами.

## 15. Структура каталогов

```
citysonar/
  worker.py                 резидент: harvest → route → publish → register
  canary.py                 cron
  core/
    hh.py                   сессия, троттл, стейт, нормализация, пагинация
    source.py               интерфейс Source (hh — первая реализация)
    store.py                схема + доступ
    router.py               L1 → L2 → L3 → outbox
    publisher.py            telegram, ретрай, rate-limit, регистрация каналов
    scoring.py
    thresholds.py           перцентили зарплат
  roles/
    hr_line.py  hr_lead.py  analytics.py  sales.py
    it.py  marketing.py  finance.py
  config/
    cities.yaml  roles.yaml
  tests/
    fixtures/               сохранённая выдача hh в json
    test_roles.py           L1 без сети
    test_router.py          ветки LOCAL/REMOTE_TOP/REMOTE_RICH
  citysonar.service
```

## 16. Этапы

| Э | Работа | Проверяемый выход |
|---|---|---|
| **0** | Каркас, схема БД, замер RAM сервера. Замер: топ-10 городов по `totalResults` + матрица «город × роль → вакансий/нед» | Таблица объёмов. По ней режется сетка каналов и подтверждается размещение |
| **1** | Harvester + Canary, **без публикации**, 7 дней | Распределения зарплат по парам, реальный объём, ноль поломок парсера |
| **2** | L1-профили: перенос 4 существующих (очистка от гео/формата/зарплаты) + 3 новых. Офлайн-тесты на фикстурах | Тесты зелёные без сети. Тест «L1 не видит гео» проходит |
| **3** | Router + Publisher, **1 город × 4 роли** (`hr_line`, `hr_lead`, `analytics`, `it`) живьём | 3 дня наблюдения, калибровка порогов по факту |
| **4** | Топ-лист: дыры, `remote_score`, перенос в данные | Ветка REMOTE_TOP наполняет каналы в малых городах |
| **5** | Раскатка 10 городов × 7 ролей | Конфиг, не код |
| **6** | Адаптеры rabota.ru / Хабр / SuperJob | Интерфейс `Source` готов с Э1 |

Э1 и Э3 намеренно содержат паузы на наблюдение. Раскатывать 70 каналов, не измерив
поток, значит получить 70 каналов мусора и не понять причину.

## 17. Риски

| Риск | Митигация |
|---|---|
| hh меняет разметку (было 2026-07-17) | Canary + дамп + точный диагноз; `raw` json в БД для разбора задним числом |
| Анти-бот 403 | Один троттл на процесс, инкрементальный обход, `_refresh_session` из текущего кода |
| OOM морозит сервер с рабочими ботами | `MemoryMax=250M` в юните + один процесс вместо четырёх |
| Общий IP с прод-ботами делит анти-бот бюджет | Обход CitySonar легче текущего суммарного; хвост — перевод старых ботов на общий харвестер |
| Мёртвый канал (0 постов/сутки) | Отдельная метрика в мониторе, алерт |
| Перекос порогов (мало вакансий с зарплатой) | Порог применяется только при `n ≥ 30`, иначе ветка пропускает всё и метится в лог |
| Мульти-город дубли | `signature` в БД с TTL, а не в памяти |

## 18. Открытые вопросы (не блокируют старт)

- Конкретный список топ-10 городов — определяется замером на Э0, не постулируется.
- Состав агломераций (какие `area_id` входят в город) — из справочника hh на Э0.
  Гадание по id уже стоило проекта (SuperJob `t=1751` вместо `639`).
- Узкие роли (Customer Service, Product Owner, COO) — отдельный «бот топов» позже.
- Реакции в каналах как сигнал качества (`message_reaction`) — после Э5.
