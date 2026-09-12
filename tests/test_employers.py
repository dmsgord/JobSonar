# -*- coding: utf-8 -*-
"""Кэш работодателей: стабильный скор между циклами + возможность посмотреть топ."""
import employers


def emp(**kw):
    base = {"id": "777", "name": "Тест", "rating": 4.3, "reviews_count": 128, "category": "COMPANY"}
    base.update(kw)
    return base


def test_remembered_employer_is_read_back(tmp_path):
    db = str(tmp_path / "hr.db")
    employers.init_employer_cache(db)
    employers.remember_employer(db, emp(), score=36)

    row = employers.get_employer(db, "777")
    assert (row["name"], row["rating"], row["reviews_count"], row["score"]) == ("Тест", 4.3, 128, 36)
    assert row["updated_at"]


def test_remember_is_idempotent_and_updates_score(tmp_path):
    db = str(tmp_path / "hr.db")
    employers.init_employer_cache(db)
    employers.remember_employer(db, emp(), score=36)
    employers.remember_employer(db, emp(rating=4.6, reviews_count=900), score=50)

    assert len(employers.top_employers(db)) == 1
    assert employers.get_employer(db, "777")["score"] == 50


def test_top_employers_sorted_by_score_desc(tmp_path):
    db = str(tmp_path / "hr.db")
    employers.init_employer_cache(db)
    employers.remember_employer(db, emp(id="1", name="Средняя"), score=30)
    employers.remember_employer(db, emp(id="2", name="Топ"), score=70)
    employers.remember_employer(db, emp(id="3", name="Слабая"), score=10)

    assert [r["name"] for r in employers.top_employers(db, limit=2)] == ["Топ", "Средняя"]


def test_unknown_employer_returns_none(tmp_path):
    db = str(tmp_path / "hr.db")
    employers.init_employer_cache(db)
    assert employers.get_employer(db, "нет-такого") is None


def test_init_is_safe_to_call_twice(tmp_path):
    db = str(tmp_path / "hr.db")
    employers.init_employer_cache(db)
    employers.remember_employer(db, emp(), score=36)
    employers.init_employer_cache(db)
    assert employers.get_employer(db, "777")["score"] == 36
