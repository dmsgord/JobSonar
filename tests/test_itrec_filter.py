# -*- coding: utf-8 -*-
"""Профиль IT-рекрутера: только удалёнка, «от 100k» или зарплата не указана.

Названия в MUST_PASS/MUST_FAIL взяты с живой выдачи hh (замер 2026-09-13,
133 удалённые рекрутерские вакансии) — это не выдуманные строки.
"""
import pytest

from config_itrec import ITREC_PROFILES
from hr_filter import _title_matches, decide
from utils import hits_stop_word

RULES = ITREC_PROFILES["ITREC"]


def vacancy(**kw):
    item = {
        "id": "1",
        "name": "IT-рекрутер",
        "alternate_url": "https://hh.ru/vacancy/1",
        "employer": {
            "id": "777", "name": "Тест Компани", "rating": 4.6,
            "reviews_count": 800, "category": "COMPANY",
            "accredited_it": False, "has_logo": True, "branding": True,
            "on_additional_check": False,
        },
        "salary": {"from": 150000, "to": None, "currency": "RUR"},
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


def title_ok(title):
    return not hits_stop_word(title, RULES["stop_words"]) and _title_matches(title, RULES)[0]


MUST_PASS = [
    "IT-рекрутер",
    "ИТ-рекрутер",
    "IT рекрутер / менеджер по подбору персонала",
    "Technical Recruiter / IT рекрутер",
    "Senior IT Recruiter / Talent Hunter",
    "HR recruiter в IT компанию (Fintech)",
    "ИТ-ресечер",
    "Tech Recruiter",
    "IT Sourcer",
    "Технический рекрутер",
    "Рекрутер по подбору разработчиков",
    "Специалист по подбору IT-специалистов",
    "Айти рекрутер",
    "IT Headhunter",
    "Talent Acquisition Specialist (IT)",
]

MUST_FAIL = [
    # прямое отрицание
    "Recruiter (IGaming, non-IT)",
    # продажи под видом рекрутинга
    "HR (Рекрутер) - менеджер по продажам IT-решения",
    # обычный рекрутер без IT
    "Рекрутер",
    "Менеджер по подбору персонала",
    "Специалист по подбору персонала",
    "Рекрутер (массовый подбор)",
    "Рекрутер на массовый подбор персонала",
    # подбор не людей
    "Специалист по подбору автозапчастей",
    "Менеджер по подбору водителей в таксопарк",
    # уровень не тот
    "Junior IT-рекрутер",
    "Помощник рекрутера / Младший HR-специалист",
    # не подбор
    "Менеджер по кадровому делопроизводству",
]


@pytest.mark.parametrize("title", MUST_PASS)
def test_it_recruiter_title_passes(title):
    assert title_ok(title), f"«{title}» — айтишный подборщик, а профиль его не берёт"


@pytest.mark.parametrize("title", MUST_FAIL)
def test_non_it_recruiter_title_rejected(title):
    assert not title_ok(title), f"«{title}» — не айтишный подборщик, а профиль его берёт"


def test_remote_is_required():
    """Гибрид не годится даже в Москве — нужна именно удалёнка."""
    hybrid = vacancy(
        schedule={"id": "fullDay", "name": "Полный день"},
        work_format=[{"id": "hybrid", "name": "Гибрид"}],
    )
    assert decide(hybrid, RULES).reason == "geo"


def test_office_rejected():
    office = vacancy(
        schedule={"id": "fullDay", "name": "Полный день"},
        work_format=[{"id": "onSite", "name": "На месте работодателя"}],
    )
    assert decide(office, RULES).reason == "geo"


def test_remote_outside_target_cities_passes():
    assert decide(vacancy(area={"id": "88", "name": "Казань", "path": ".113.1624.88."}),
                  RULES).send is True


def test_salary_from_100k_passes():
    assert decide(vacancy(salary={"from": 100000, "to": None, "currency": "RUR"}),
                  RULES).send is True


def test_salary_without_amount_passes():
    """Зарплаты нет — пропускаем: у 10 из 16 живых IT-рекрутеров её не указывают."""
    d = decide(vacancy(salary=None), RULES)
    assert d.send is True
    assert d.salary_text == "-"


def test_empty_compensation_object_counts_as_no_salary():
    """hh шлёт compensation объектом даже без сумм: {"currency": "RUR"}.

    Такой словарь truthy — раньше он читался как «зарплата есть, но нижней
    границы нет» и вакансия резалась. Это «зарплата не указана», её пропускаем.
    """
    d = decide(vacancy(salary={"from": None, "to": None, "currency": "RUR"}), RULES)
    assert d.send is True
    assert d.salary_text == "-"


def test_salary_only_upper_bound_rejected():
    """«до 150000» не обещает ничего — такие не берём."""
    d = decide(vacancy(salary={"from": None, "to": 150000, "currency": "RUR"}), RULES)
    assert d.send is False
    assert d.reason == "salary"


def test_salary_below_100k_rejected():
    d = decide(vacancy(salary={"from": 60000, "to": None, "currency": "RUR"}), RULES)
    assert d.send is False
    assert d.reason == "salary"


def test_agency_is_not_penalised():
    """Кадровое агентство нанимает рекрутеров чаще всех — штраф −20 их выбивал."""
    agency = vacancy(employer={"category": "AGENCY", "rating": 4.2, "reviews_count": 10,
                               "branding": False})
    assert decide(agency, RULES).send is True


def test_agency_penalty_still_applies_to_hr_profile():
    """Послабление только для IT-рекрутера, HR-профиль скорит агентства как раньше."""
    from config import PROFILES
    agency = vacancy(name="Директор по персоналу",
                     employer={"category": "AGENCY", "rating": 4.2, "reviews_count": 10,
                               "branding": False, "has_logo": False})
    assert decide(agency, PROFILES["HR"]).reason == "company"


def test_no_experience_is_allowed():
    """Метка «Нет опыта» на hh формальна: так помечены вакансии сильных компаний."""
    d = decide(vacancy(experience={"id": "noExperience", "name": "Нет опыта"}), RULES)
    assert d.send is True


def test_no_experience_still_rejected_for_hr_profile():
    from config import PROFILES
    d = decide(vacancy(name="Директор по персоналу",
                       experience={"id": "noExperience", "name": "Нет опыта"}),
               PROFILES["HR"])
    assert d.reason == "title"


def test_decision_carries_profile_mark():
    assert decide(vacancy(), RULES).mark == "💻"


def test_other_profiles_have_no_mark():
    from config import PROFILES
    d = decide(vacancy(name="Директор по персоналу"), PROFILES["HR"])
    assert d.send is True
    assert d.mark == ""
