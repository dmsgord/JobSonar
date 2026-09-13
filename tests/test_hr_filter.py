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


def office(**kw):
    """Чистый офис: schedule «Полный день» + work_format «На месте работодателя»."""
    return vacancy(
        schedule={"id": "fullDay", "name": "Полный день"},
        work_format=[{"id": "onSite", "name": "На месте работодателя"}],
        **kw
    )


def test_office_vacancy_in_moscow_rejects():
    """Полный офис не нужен даже в целевом городе — нужна удалёнка или гибрид."""
    assert decide(office(), RULES).reason == "geo"


def test_office_vacancy_in_nizhny_novgorod_rejects():
    nn = office(area={"id": "66", "name": "Нижний Новгород", "path": ".113.1679.66."})
    assert decide(nn, RULES).reason == "geo"


def test_hybrid_in_moscow_is_accepted():
    hybrid = vacancy(
        schedule={"id": "fullDay", "name": "Полный день"},
        work_format=[{"id": "onSite", "name": "На месте работодателя"},
                     {"id": "hybrid", "name": "Гибрид"}],
    )
    assert decide(hybrid, RULES).send is True


def test_hybrid_in_nizhny_novgorod_is_accepted():
    hybrid = vacancy(
        area={"id": "66", "name": "Нижний Новгород", "path": ".113.1679.66."},
        schedule={"id": "fullDay", "name": "Полный день"},
        work_format=[{"id": "hybrid", "name": "Гибрид"}],
    )
    assert decide(hybrid, RULES).send is True


def test_office_plus_hybrid_is_accepted():
    """Частый случай hh: «Полный день, На месте работодателя, Гибрид».

    Офис в перечне не отменяет гибрид — режем только тех, у кого КРОМЕ офиса
    ничего нет. Замер по живой выдаче: таких смешанных — 35 из 285.
    """
    mixed = vacancy(
        schedule={"id": "fullDay", "name": "Полный день"},
        work_format=[{"id": "onSite", "name": "На месте работодателя"},
                     {"id": "hybrid", "name": "Гибрид"}],
    )
    assert decide(mixed, RULES).send is True


def test_office_plus_remote_is_accepted_outside_target_cities():
    """«На месте работодателя, Удалённо» — удалёнка есть, значит подходит из любого города."""
    mixed = vacancy(
        area={"id": "88", "name": "Казань", "path": ".113.1624.88."},
        schedule={"id": "fullDay", "name": "Полный день"},
        work_format=[{"id": "onSite", "name": "На месте работодателя"},
                     {"id": "remote", "name": "Удалённо"}],
    )
    assert decide(mixed, RULES).send is True


def test_field_plus_remote_is_accepted():
    """«Удалённо, Разъездной» — тоже оставляем: удалёнка в перечне есть."""
    mixed = vacancy(
        area={"id": "88", "name": "Казань", "path": ".113.1624.88."},
        schedule={"id": "remote", "name": "Удалённо"},
        work_format=[{"id": "remote", "name": "Удалённо"},
                     {"id": "field", "name": "Разъездной"}],
    )
    assert decide(mixed, RULES).send is True


def test_hybrid_outside_target_cities_rejects():
    """Гибрид в Казани — ездить туда некому, шлём только удалёнку."""
    kazan_hybrid = vacancy(
        area={"id": "88", "name": "Казань", "path": ".113.1624.88."},
        schedule={"id": "fullDay", "name": "Полный день"},
        work_format=[{"id": "hybrid", "name": "Гибрид"}],
    )
    assert decide(kazan_hybrid, RULES).reason == "geo"


def test_field_work_rejects():
    """«Разъездной» — тоже не удалёнка и не гибрид."""
    field = vacancy(
        schedule={"id": "fullDay", "name": "Полный день"},
        work_format=[{"id": "field", "name": "Разъездной"}],
    )
    assert decide(field, RULES).reason == "geo"


def test_private_individual_rejects():
    assert decide(vacancy(employer={"category": "PRIVATE_INDIVIDUAL"}), RULES).reason == "company"


def test_weak_company_rejects_even_with_salary():
    weak = vacancy(employer={"rating": 3.2, "reviews_count": 60, "has_logo": False, "branding": False})
    assert decide(weak, RULES).reason == "company"


def test_salary_below_flat_threshold_rejects():
    """Планка одна для всех — 100k, независимо от скора компании."""
    mid = {"rating": 4.3, "reviews_count": 128, "has_logo": False, "branding": False}
    low_pay = vacancy(employer=mid, salary={"from": 90000, "to": None, "currency": "RUR"})
    ok_pay = vacancy(employer=mid, salary={"from": 120000, "to": None, "currency": "RUR"})
    assert decide(low_pay, RULES).reason == "salary"
    assert decide(ok_pay, RULES).send is True


def test_modest_salary_is_shown_without_bold():
    d = decide(vacancy(salary={"from": 120000, "to": None, "currency": "RUR"}), RULES)
    assert (d.send, d.salary_text, d.bold) == (True, "от 120000 ₽", False)


def test_large_salary_is_bold():
    d = decide(vacancy(salary={"from": 300000, "to": None, "currency": "RUR"}), RULES)
    assert (d.send, d.bold) == (True, True)


def test_vacancy_without_salary_is_sent():
    """Без зарплаты — треть подходящих вакансий (замер 2026-09-12), шлём их."""
    assert decide(vacancy(salary=None), RULES).send is True


def test_vacancy_without_salary_is_sent_for_mid_company():
    mid = vacancy(
        employer={"rating": 4.0, "reviews_count": 40, "has_logo": False, "branding": False},
        salary=None,
    )
    d = decide(mid, RULES)
    assert (d.send, d.tier) == (True, "⚪")


def test_vacancy_without_salary_is_sent_for_combo_title():
    combo = vacancy(name="Руководитель направления обучения персонала", salary=None)
    assert decide(combo, RULES).send is True


def test_empty_compensation_is_shown_as_dash():
    """hh отдаёт compensation с пустыми from/to — это «зарплата не указана»."""
    d = decide(vacancy(salary={"from": None, "to": None, "currency": "RUR"}), RULES)
    assert (d.send, d.salary_text, d.bold) == (True, "-", False)


def test_weak_company_is_still_rejected_without_salary():
    weak = vacancy(
        employer={"rating": 3.2, "reviews_count": 60, "has_logo": False, "branding": False},
        salary=None,
    )
    assert decide(weak, RULES).reason == "company"


def test_agency_is_marked_and_scored_lower():
    agency = vacancy(employer={"category": "AGENCY"})
    plain = vacancy()
    assert decide(agency, RULES).score == decide(plain, RULES).score - 20
