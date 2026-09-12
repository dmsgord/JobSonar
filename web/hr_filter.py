# -*- coding: utf-8 -*-
"""Решение по одной вакансии HR-бота — чистая функция, без сети и БД.

Порядок ворот: заголовок → опыт → гео → качество компании → зарплата.
Зарплатная планка не фиксированная: её задаёт скор работодателя (scoring.py),
поэтому у сильной компании проходит 200k, у слабой не проходит и 290k.
"""
from collections import namedtuple

from config import TARGET_AREAS
from scoring import quality_gate, score_employer
from utils import (
    build_details, format_salary, hits_stop_word, is_russian_area,
    looks_like_private_person, smart_contains,
)

Decision = namedtuple(
    "Decision", "send reason tier score salary_text bold details experience"
)

OFFICE_MARKERS = ("офис", "на месте", "office", "гибрид", "hybrid", "разъездной")


def _reject(reason, score=0):
    return Decision(False, reason, "", score, "-", False, [], None)


def _title_matches(title, rules):
    """(подходит ли тайтл, точное ли это попадание в direct_titles)."""
    if any(smart_contains(title, w) for w in rules["direct_titles"]):
        return True, True
    has_level = any(smart_contains(title, w) for w in rules["role_levels"])
    context_words = rules.get("role_context", rules.get("hr_context", []))
    has_context = any(smart_contains(title, w) for w in context_words)
    return has_level and has_context, False


def decide(item, rules, target_areas=TARGET_AREAS):
    title = item.get("name", "")

    if hits_stop_word(title, rules["stop_words"]):
        return _reject("title")
    title_ok, _is_direct_title = _title_matches(title, rules)
    if not title_ok:
        return _reject("title")

    experience = item.get("experience", {})
    if experience.get("id") == "noExperience":
        return _reject("title")

    details, details_text = build_details(item)
    is_remote = "удал" in details_text or "remote" in details_text

    area = item.get("area", {})
    if not is_russian_area(area):
        return _reject("geo")

    area_name = (area.get("name") or "").lower()
    is_target_area = str(area.get("id", "")) in target_areas or "москв" in area_name
    if not is_target_area and not is_remote:
        return _reject("geo")

    employer = item.get("employer", {})
    if looks_like_private_person(employer.get("name", "")):
        return _reject("company")

    salary = item.get("salary")
    score = score_employer(employer, salary=salary)
    ok, tier, threshold, score = quality_gate(employer, salary=salary, score=score)
    if not ok:
        return _reject("company", score)

    salary_text, is_bold, skip_salary = format_salary(salary, threshold)
    if skip_salary:
        return Decision(False, "salary", tier, score, salary_text, is_bold, details, experience)

    return Decision(True, "ok", tier, score, salary_text, is_bold, details, experience)
