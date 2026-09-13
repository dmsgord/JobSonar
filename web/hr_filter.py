# -*- coding: utf-8 -*-
"""Решение по одной вакансии HR-бота — чистая функция, без сети и БД.

Порядок ворот: заголовок → опыт → формат работы + гео → качество компании → зарплата.
Формат: удалёнка — из любого города РФ, гибрид — только Москва/НН. Чистый офис
(«На месте работодателя», «Разъездной») не шлём вообще: это полный офис, а он не нужен.
Зарплатная планка одна для всех, скор компании решает только «шлём или нет».
"""
from collections import namedtuple

from config import TARGET_AREAS
from scoring import BOLD_SALARY_FROM, quality_gate, score_employer
from utils import (
    build_details, format_salary, hits_stop_word, is_russian_area,
    looks_like_private_person, smart_contains,
)

Decision = namedtuple(
    "Decision", "send reason tier score salary_text bold details experience mark",
    defaults=("",),   # mark — значок профиля в карточке, есть не у всех профилей
)

REMOTE_MARKERS = ("удал", "remote")
HYBRID_MARKERS = ("гибрид", "hybrid")


def _has(text, markers):
    return any(m in text for m in markers)


def _lower_bound_ok(salary, threshold):
    """Профили с salary_lower_only: годится «от N ≥ порога» или зарплата не указана.

    «до 150000» не годится — верхняя граница ничего не обещает. Зарплату без
    указания пропускаем: у трети вакансий hh её нет вовсе, резать их — потерять класс.
    """
    if not salary:
        return True
    lower, upper = salary.get("from"), salary.get("to")
    # hh отдаёт compensation объектом даже когда зарплаты нет: {"currencyCode": "RUR"}.
    # Такой словарь truthy, но зарплата в нём не указана — это «нет данных», не «до N».
    if not lower and not upper:
        return True
    if not lower:
        return False
    if salary.get("currency") != "RUR":
        return True
    return lower >= threshold


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
    # «Нет опыта» на hh часто стоит формально. Профилям, где это режет живые
    # вакансии сильных компаний (IT-рекрутер), ворота можно открыть.
    if experience.get("id") == "noExperience" and not rules.get("allow_no_experience"):
        return _reject("title")

    details, details_text = build_details(item)
    is_remote = _has(details_text, REMOTE_MARKERS)
    is_hybrid = _has(details_text, HYBRID_MARKERS)

    area = item.get("area", {})
    if not is_russian_area(area):
        return _reject("geo")

    area_name = (area.get("name") or "").lower()
    is_target_area = str(area.get("id", "")) in target_areas or "москв" in area_name
    if rules.get("remote_only"):
        # IT-рекрутер нужен только на удалёнке — гибрид не подходит даже в Москве
        if not is_remote:
            return _reject("geo")
    # Удалёнка — из любого города РФ. Гибрид — только Москва/НН, туда реально ездить.
    # Всё остальное («Полный день + На месте работодателя», «Разъездной») — офис, режем.
    elif not (is_remote or (is_hybrid and is_target_area)):
        return _reject("geo")

    employer = item.get("employer", {})
    if looks_like_private_person(employer.get("name", "")):
        return _reject("company")

    salary = item.get("salary")
    score = score_employer(employer, salary=salary,
                           agency_penalty=not rules.get("agency_ok"))
    ok, tier, threshold, score = quality_gate(employer, salary=salary, score=score)
    if not ok:
        return _reject("company", score)

    mark = rules.get("mark", "")
    salary_text, is_bold, skip_salary = format_salary(salary, threshold, bold_from=BOLD_SALARY_FROM)
    if skip_salary:
        return Decision(False, "salary", tier, score, salary_text, is_bold, details, experience, mark)
    if rules.get("salary_lower_only") and not _lower_bound_ok(salary, threshold):
        return Decision(False, "salary", tier, score, salary_text, is_bold, details, experience, mark)

    return Decision(True, "ok", tier, score, salary_text, is_bold, details, experience, mark)
