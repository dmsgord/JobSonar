# -*- coding: utf-8 -*-
"""Решение по вакансии: заголовок → гео → качество компании ↔ зарплата."""
import pytest

from config import PROFILES
from hr_filter import decide

RULES = PROFILES["HR"]


def vacancy(**kw):
    item = {
        "id": "1",
        "name": "HR Business Partner",
        "alternate_url": "https://hh.ru/vacancy/1",
        "employer": {
            "id": "777",
            "name": "Тест Компани",
            "rating": 4.6,
            "reviews_count": 800,
            "category": "COMPANY",
            "accredited_it": False,
            "has_logo": True,
            "branding": True,
            "on_additional_check": False,
        },
        "salary": {"from": 300000, "to": None, "currency": "RUR"},
        "area": {"id": "1", "name": "Москва", "path": ".113.232.1."},
        "schedule": {"id": "remote", "name": "Удалённо"},
        "work_format": [{"id": "remote", "name": "Удалённо"}],
        "experience": {"id": "between3And6", "name": "От 3 до 6 лет"},
        "published_at": "2026-09-10T10:00:00+0300",
    }
    for key, value in kw.items():
        if isinstance(value, dict) and isinstance(item.get(key), dict):
            item[key] = {**item[key], **value}
        else:
            item[key] = value
    return item


def test_good_vacancy_is_sent_with_tier():
    d = decide(vacancy(), RULES)
    assert d.send is True
    assert d.tier == "💎"
    assert d.score >= 55


def test_stop_word_in_title_rejects():
    assert decide(vacancy(name="Ведущий HR Business Partner"), RULES).reason == "title"


def test_unrelated_title_rejects():
    assert decide(vacancy(name="Курьер на личном авто"), RULES).reason == "title"


def test_combo_of_level_and_context_passes_title_check():
    d = decide(vacancy(name="Руководитель направления обучения персонала"), RULES)
    assert d.send is True


def test_no_experience_rejects():
    d = decide(vacancy(experience={"id": "noExperience", "name": "Нет опыта"}), RULES)
    assert d.reason == "title"


def test_foreign_remote_vacancy_rejects():
    tashkent = vacancy(area={"id": "2759", "name": "Ташкент", "path": ".97.2759."})
    assert decide(tashkent, RULES).reason == "geo"


def test_office_vacancy_outside_target_cities_rejects():
    spb_office = vacancy(
        area={"id": "2", "name": "Санкт-Петербург", "path": ".113.231.2."},
        schedule={"id": "fullDay", "name": "Полный день"},
        work_format=[{"id": "onSite", "name": "На месте работодателя"}],
    )
    assert decide(spb_office, RULES).reason == "geo"


def test_remote_vacancy_anywhere_in_russia_is_accepted():
    kazan_remote = vacancy(area={"id": "88", "name": "Казань", "path": ".113.1624.88."})
    assert decide(kazan_remote, RULES).send is True


def test_private_individual_rejects():
    assert decide(vacancy(employer={"category": "PRIVATE_INDIVIDUAL"}), RULES).reason == "company"


def test_weak_company_rejects_even_with_salary():
    weak = vacancy(employer={"rating": 3.2, "reviews_count": 60, "has_logo": False, "branding": False})
    assert decide(weak, RULES).reason == "company"


def test_mid_company_needs_higher_salary():
    """Скор 36 (4.3 + 128 отзывов) → планка 250k: 210k не проходит, 260k проходит."""
    mid = {"rating": 4.3, "reviews_count": 128, "has_logo": False, "branding": False}
    low_pay = vacancy(employer=mid, salary={"from": 210000, "to": None, "currency": "RUR"})
    ok_pay = vacancy(employer=mid, salary={"from": 260000, "to": None, "currency": "RUR"})
    assert decide(low_pay, RULES).reason == "salary"
    assert decide(ok_pay, RULES).send is True


def test_vacancy_without_salary_is_sent_for_strong_company():
    assert decide(vacancy(salary=None), RULES).send is True


def test_vacancy_without_salary_is_rejected_for_weak_company():
    """Зарплаты нет — вилка «скор ↔ зарплата» не работает; пускаем только 💎/🔥."""
    weak = vacancy(
        employer={"rating": 4.0, "reviews_count": 40, "has_logo": False, "branding": False},
        salary=None,
    )
    d = decide(weak, RULES)
    assert (d.send, d.reason, d.tier) == (False, "salary", "⚪")


def test_empty_compensation_counts_as_no_salary():
    """hh отдаёт compensation с пустыми from/to — это «зарплата не указана»."""
    weak = vacancy(
        employer={"rating": 4.0, "reviews_count": 40, "has_logo": False, "branding": False},
        salary={"from": None, "to": None, "currency": "RUR"},
    )
    assert decide(weak, RULES).reason == "salary"


def test_agency_is_marked_and_scored_lower():
    agency = vacancy(employer={"category": "AGENCY"})
    plain = vacancy()
    assert decide(agency, RULES).score == decide(plain, RULES).score - 20
