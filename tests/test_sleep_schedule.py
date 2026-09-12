# -*- coding: utf-8 -*-
"""Умный сон: HR-бот работает в выходные так же, как в будни."""
from datetime import datetime

import pytest

import utils

SATURDAY_MORNING = datetime(2026, 9, 12, 9, 0)   # суббота
SATURDAY_NOON = datetime(2026, 9, 12, 14, 0)
SUNDAY_EVENING = datetime(2026, 9, 13, 21, 0)    # воскресенье
MONDAY_NOON = datetime(2026, 9, 14, 14, 0)


@pytest.fixture
def frozen(monkeypatch):
    def freeze(moment):
        monkeypatch.setattr(utils, "get_moscow_time", lambda: moment)
    return freeze


def test_weekend_pause_until_eleven_by_default(frozen):
    frozen(SATURDAY_MORNING)
    seconds, target = utils.get_smart_sleep_time()
    assert target.hour >= 11


def test_weekend_works_like_weekday_when_asked(frozen):
    frozen(SATURDAY_MORNING)
    seconds, _target = utils.get_smart_sleep_time(weekend_like_weekday=True)
    assert 20 * 60 <= seconds <= 31 * 60


def test_weekend_daytime_cycle_is_shorter_when_asked(frozen):
    frozen(SATURDAY_NOON)
    weekend_seconds, _t = utils.get_smart_sleep_time()
    weekday_seconds, _t2 = utils.get_smart_sleep_time(weekend_like_weekday=True)
    assert weekday_seconds < weekend_seconds


def test_sunday_evening_does_not_sleep_until_monday_when_asked(frozen):
    frozen(SUNDAY_EVENING)
    seconds, target = utils.get_smart_sleep_time(weekend_like_weekday=True)
    assert seconds <= 31 * 60
    assert target.day == SUNDAY_EVENING.day


def test_sunday_evening_sleeps_until_monday_by_default(frozen):
    frozen(SUNDAY_EVENING)
    _seconds, target = utils.get_smart_sleep_time()
    assert (target.day, target.hour) == (14, 8)


def test_night_sleep_is_kept_for_weekend_like_weekday(frozen):
    frozen(datetime(2026, 9, 12, 2, 0))
    _seconds, target = utils.get_smart_sleep_time(weekend_like_weekday=True)
    assert target.hour == 7


def test_weekday_behaviour_is_unchanged(frozen):
    frozen(MONDAY_NOON)
    plain, _t = utils.get_smart_sleep_time()
    flagged, _t2 = utils.get_smart_sleep_time(weekend_like_weekday=True)
    assert 20 * 60 <= plain <= 31 * 60
    assert 20 * 60 <= flagged <= 31 * 60


def test_custom_cycle_length_is_respected(frozen):
    frozen(MONDAY_NOON)
    seconds, _target = utils.get_smart_sleep_time(cycle_minutes=(7, 8))
    assert 7 * 60 <= seconds <= 8 * 60


def test_custom_cycle_length_applies_on_weekend_like_weekday(frozen):
    frozen(SATURDAY_NOON)
    seconds, _t = utils.get_smart_sleep_time(weekend_like_weekday=True, cycle_minutes=(7, 8))
    assert 7 * 60 <= seconds <= 8 * 60


def test_custom_cycle_length_does_not_break_night_sleep(frozen):
    frozen(datetime(2026, 9, 14, 2, 0))
    _seconds, target = utils.get_smart_sleep_time(cycle_minutes=(7, 8))
    assert target.hour == 7
