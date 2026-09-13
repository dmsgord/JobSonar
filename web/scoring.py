# -*- coding: utf-8 -*-
"""Скоринг работодателя по сигналам, которые hh.ru отдаёт прямо в выдаче.

Заменяет whitelist: вместо статического списка компаний решение принимается
по рейтингу Dream Job, объёму отзывов, типу работодателя и платным маркерам
(брендирование, лого, IT-аккредитация). Ни одного дополнительного запроса —
все поля приходят вместе со списком вакансий (см. utils._normalize_vacancy).

Порог не бинарный: чем ниже скор компании, тем выше требуемая зарплата.
"""

SKIP = object()  # работодатель-исключение: не шлём вне зависимости от зарплаты

TIER_DIAMOND = "💎"
TIER_FIRE = "🔥"
TIER_PLAIN = "⚪"

# Зарплатных правил от скора больше нет: планка одна для всех, скор решает только
# «шлём или нет» и каким значком помечена компания.
MIN_SALARY = 100000        # ниже — вакансия не показывается
BOLD_SALARY_FROM = 250000  # от этой суммы сумма выделяется жирным
MIN_SCORE_TO_SEND = 20

TIER_BANDS = (
    (55, TIER_DIAMOND),
    (35, TIER_FIRE),
    (MIN_SCORE_TO_SEND, TIER_PLAIN),
)

BASE_SCORE_NO_RATING = 20
# Рейтинг на крошечной выборке — шум: ★5.0 при 7 отзывах ничего не говорит о компании
MIN_REVIEWS_FOR_RATING = 10
SKIP_CATEGORIES = ("PRIVATE_INDIVIDUAL",)


def _rating_points(rating, reviews_count):
    if rating is None or reviews_count < MIN_REVIEWS_FOR_RATING:
        return BASE_SCORE_NO_RATING
    if rating >= 4.5:
        return 30
    if rating >= 4.2:
        return 22
    if rating >= 4.0:
        return 15
    if rating >= 3.7:
        return 5
    if rating < 3.5 and reviews_count >= 20:
        return -25
    return 0


def _reviews_points(reviews_count):
    """Объём отзывов — прокси размера и известности компании."""
    if reviews_count >= 500:
        return 20
    if reviews_count >= 100:
        return 14
    if reviews_count >= 30:
        return 8
    return 0


def score_employer(employer, salary=None, agency_penalty=True):
    """0–100, либо SKIP для работодателей, которых не шлём никогда.

    agency_penalty=False — для профилей, где агентство нормальный работодатель
    (IT-рекрутера кадровые агентства нанимают чаще всех, штраф выбивал их зря).
    """
    if employer.get("on_additional_check"):
        return SKIP
    if employer.get("category") in SKIP_CATEGORIES:
        return SKIP

    reviews_count = employer.get("reviews_count") or 0
    score = _rating_points(employer.get("rating"), reviews_count)
    score += _reviews_points(reviews_count)

    if employer.get("branding"):
        score += 8
    if employer.get("has_logo"):
        score += 3
    if employer.get("accredited_it"):
        score += 8
    if agency_penalty and employer.get("category") == "AGENCY":
        score -= 20

    if salary:
        lower = salary.get("from") or 0
        if salary.get("currency") == "RUR" and lower >= 300000:
            score += 10

    return max(0, min(100, score))


def required_salary(score):
    """Минимальная зарплата: одна для всех, None — компания не проходит по скору."""
    return MIN_SALARY if score >= MIN_SCORE_TO_SEND else None


def tier_emoji(score):
    for min_score, tier in TIER_BANDS:
        if score >= min_score:
            return tier
    return ""


def quality_gate(employer, salary=None, score=None):
    """(ok, tier, требуемая_зарплата, скор) — одно решение по работодателю."""
    if score is None:
        score = score_employer(employer, salary=salary)
    if score is SKIP:
        return False, "", None, 0
    threshold = required_salary(score)
    return threshold is not None, tier_emoji(score), threshold, score
