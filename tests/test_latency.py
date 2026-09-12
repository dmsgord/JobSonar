# -*- coding: utf-8 -*-
"""Замер задержки «опубликовано на hh → отправлено в телегу»."""
from datetime import datetime, timedelta, timezone

import utils

MSK = timezone(timedelta(hours=3))
NOW = datetime(2026, 9, 12, 12, 0, tzinfo=MSK)


def test_age_of_fresh_vacancy_in_minutes():
    item = {"published_at": "2026-09-12T11:45:00+0300"}
    assert utils.vacancy_age_minutes(item, now=NOW) == 15


def test_age_across_timezones():
    """hh отдаёт дату со смещением; сравнение должно идти по абсолютному времени."""
    item = {"published_at": "2026-09-12T09:00:00+0000"}
    assert utils.vacancy_age_minutes(item, now=NOW) == 0


def test_real_hh_format_with_millis_and_colon_offset():
    """Живой формат hh: 2026-09-12T11:30:00.123+03:00 — с миллисекундами и двоеточием."""
    item = {"published_at": "2026-09-12T11:30:00.485+03:00"}
    assert utils.vacancy_age_minutes(item, now=NOW) == 29


def test_utc_z_suffix_is_parsed():
    assert utils.vacancy_age_minutes({"published_at": "2026-09-12T09:00:00Z"}, now=NOW) == 0


def test_missing_publication_date_gives_none():
    assert utils.vacancy_age_minutes({}, now=NOW) is None
    assert utils.vacancy_age_minutes({"published_at": ""}, now=NOW) is None


def test_broken_publication_date_gives_none():
    assert utils.vacancy_age_minutes({"published_at": "вчера"}, now=NOW) is None


def test_summary_reports_median_and_max():
    items = [
        {"published_at": "2026-09-12T11:50:00+0300"},   # 10 мин
        {"published_at": "2026-09-12T11:00:00+0300"},   # 60 мин
        {"published_at": "2026-09-12T10:00:00+0300"},   # 120 мин
    ]
    assert utils.age_summary(items, now=NOW) == (60, 120, 3)


def test_summary_ignores_vacancies_without_date():
    items = [{"published_at": "2026-09-12T11:30:00+0300"}, {}]
    assert utils.age_summary(items, now=NOW) == (30, 30, 1)


def test_summary_of_empty_list():
    assert utils.age_summary([], now=NOW) == (None, None, 0)
