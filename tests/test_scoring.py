# -*- coding: utf-8 -*-
"""Скоринг работодателя по сигналам из выдачи hh.ru."""
import pytest

from scoring import (
    SKIP,
    TIER_DIAMOND,
    TIER_FIRE,
    TIER_PLAIN,
    quality_gate,
    required_salary,
    score_employer,
)


def employer(**kw):
    base = {
        "id": "1",
        "name": "Тест",
        "rating": None,
        "reviews_count": 0,
        "category": "COMPANY",
        "accredited_it": False,
        "has_logo": False,
        "branding": False,
        "on_additional_check": False,
    }
    base.update(kw)
    return base


def test_top_rating_and_many_reviews_scores_above_diamond_threshold():
    assert score_employer(employer(rating=4.6, reviews_count=800)) == 50


def test_no_rating_falls_back_to_base_score_not_zero():
    assert score_employer(employer(rating=None, reviews_count=0)) == 20


def test_bad_rating_with_enough_reviews_is_penalized():
    # 3.4 при 40 отзывах: -25, отзывы 30-100 дают +8
    assert score_employer(employer(rating=3.4, reviews_count=40)) == 0


def test_bad_rating_with_few_reviews_is_not_penalized():
    # выборка меньше 10 отзывов не считается вовсе — ни штрафа, ни бонуса, базовые 20
    assert score_employer(employer(rating=3.4, reviews_count=5)) == 20


def test_branding_logo_and_it_accreditation_add_up():
    assert score_employer(
        employer(rating=4.3, reviews_count=150, branding=True, has_logo=True, accredited_it=True)
    ) == 55


def test_agency_is_penalized():
    plain = employer(rating=4.3, reviews_count=150)
    agency = employer(rating=4.3, reviews_count=150, category="AGENCY")
    assert score_employer(agency) == score_employer(plain) - 20


def test_high_salary_adds_bonus():
    sal = {"from": 350000, "to": None, "currency": "RUR"}
    assert score_employer(employer(rating=4.3, reviews_count=150), salary=sal) == 46


def test_private_individual_is_skipped():
    assert score_employer(employer(category="PRIVATE_INDIVIDUAL")) is SKIP


def test_employer_on_additional_check_is_skipped():
    assert score_employer(employer(rating=4.8, reviews_count=900, on_additional_check=True)) is SKIP


def test_score_is_clamped_to_0_100():
    maxed = employer(
        rating=5.0, reviews_count=5000, branding=True, has_logo=True, accredited_it=True
    )
    assert 0 <= score_employer(maxed, salary={"from": 900000, "currency": "RUR"}) <= 100
    assert score_employer(employer(rating=1.0, reviews_count=5000, category="AGENCY")) == 0


@pytest.mark.parametrize(
    "score,expected",
    [(100, 150000), (55, 150000), (54, 200000), (35, 200000), (34, 250000), (20, 250000), (19, None)],
)
def test_required_salary_ladder(score, expected):
    assert required_salary(score) == expected


@pytest.mark.parametrize(
    "score,expected", [(70, TIER_DIAMOND), (55, TIER_DIAMOND), (40, TIER_FIRE), (25, TIER_PLAIN)]
)
def test_tier_emoji_by_score(score, expected):
    assert quality_gate(employer(), score=score)[1] == expected


def test_quality_gate_rejects_low_score():
    ok, tier, threshold, score = quality_gate(employer(rating=3.4, reviews_count=40))
    assert ok is False
    assert threshold is None


def test_quality_gate_returns_threshold_for_good_company():
    # 4.6 + 800 отзывов = 50 → 🔥, планка 200k; лого добавляет 3 и всё ещё 🔥
    ok, tier, threshold, score = quality_gate(employer(rating=4.6, reviews_count=800))
    assert (ok, tier, threshold, score) == (True, TIER_FIRE, 200000, 50)


def test_quality_gate_diamond_requires_extra_signals():
    top = employer(rating=4.6, reviews_count=800, has_logo=True, branding=True)
    ok, tier, threshold, score = quality_gate(top)
    assert (ok, tier, threshold, score) == (True, TIER_DIAMOND, 150000, 61)


def test_rating_on_tiny_sample_is_ignored():
    """★5.0 при 7 отзывах — шум, а не сигнал: считаем как «рейтинга нет»."""
    assert score_employer(employer(rating=5.0, reviews_count=7)) == 20


def test_rating_counts_from_ten_reviews():
    assert score_employer(employer(rating=5.0, reviews_count=10)) == 30
