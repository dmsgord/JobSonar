# -*- coding: utf-8 -*-
"""Инварианты конфига: стоп-слова не должны убивать собственные целевые тайтлы."""
import pytest

from config import PROFILES
from config_coo import COO_PROFILES
from hr_filter import _title_matches
from utils import hits_stop_word

ALL_PROFILES = {**COO_PROFILES, **PROFILES}

CASES = [
    (profile_name, rules, title)
    for profile_name, rules in ALL_PROFILES.items()
    for title in list(rules["direct_titles"]) + list(rules["keywords"])
]


@pytest.mark.parametrize("profile,rules,title", CASES, ids=[f"{p}:{t}" for p, _r, t in CASES])
def test_own_target_title_is_not_killed_by_stop_words(profile, rules, title):
    assert not hits_stop_word(title, rules["stop_words"]), (
        f"{profile}: собственный тайтл «{title}» режется своим же стоп-словом"
    )


# Вакансия проверяется по ВСЕМ профилям (см. main.run_cycle), поэтому «пройдёт»
# значит «пройдёт хотя бы у одного». Стоп-слово COO не теряет HR-тайтл и наоборот.
def matching_profiles(title):
    return [
        name for name, rules in ALL_PROFILES.items()
        if not hits_stop_word(title, rules["stop_words"]) and _title_matches(title, rules)[0]
    ]


# Реальные тайтлы, которые бот терять не имеет права. Владелец: «лучше пусть
# останется немного мусора, чем срез важного».
MUST_PASS = [
    "Директор по персоналу",
    "Директор по персоналу (HRD)",
    "HR Business Partner",
    "HRBP",
    "Head of HR",
    "Руководитель отдела персонала",
    "Руководитель отдела кадров",
    "Руководитель подбора персонала",
    "Заместитель директора по персоналу",
    "Head of Recruitment",
    "Руководитель направления обучения персонала",
    "Директор по компенсациям и льготам",
    "Директор по бренду работодателя",
    "Руководитель по HR-бренду",
    "Head of Employer Brand",
    "Операционный директор",
    "Исполнительный директор",
    "Управляющий директор",
    "Head of Operations",
    "Директор по операциям",
]

# Мусор из живой выдачи, на котором бот прокалывался
MUST_FAIL = [
    "Операционный + клиентский менеджер",
    "Заведущий в швейное ателье премиального бренда (Управляющий-Директор предпиятия)",
    "Ведущий менеджер по подбору ТОП-персонала (Executive Search / Talent Mapping)",
    "Водитель категории C",
    "Курьер на личном авто",
    "Руководитель отдела продаж",
]


@pytest.mark.parametrize("title", MUST_PASS)
def test_important_title_survives_all_profiles(title):
    assert matching_profiles(title), f"«{title}» больше не проходит ни по одному профилю"


@pytest.mark.parametrize("title", MUST_FAIL)
def test_known_junk_title_is_rejected(title):
    hit = matching_profiles(title)
    assert not hit, f"мусорный тайтл «{title}» проходит по профилям {hit}"


def test_coo_does_not_take_client_and_staffing_roles():
    """Клиентские роли и подбор — не COO. Раньше «Операционный + клиентский
    менеджер» пролезал парой «менеджер» + «операци»."""
    coo = COO_PROFILES["COO"]
    for title in ("Операционный + клиентский менеджер",
                  "Операционный менеджер по работе с клиентами",
                  "Менеджер по подбору персонала",
                  "Executive Search Consultant"):
        assert hits_stop_word(title, coo["stop_words"]), f"COO не режет «{title}»"
