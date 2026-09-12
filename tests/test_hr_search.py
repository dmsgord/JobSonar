# -*- coding: utf-8 -*-
"""Построение запросов HR-бота: три гео-оси вместо перебора whitelist."""
import hr_search


PROFILES = {
    "HR": {"keywords": ["HRD", "HR Business Partner", "Head of HR"]},
    "COO": {"keywords": ["COO", "Операционный директор"]},
}
ROLES = ["38", "171"]


def build():
    return hr_search.build_axis_queries(hr_search.SEARCH_AXES, PROFILES, ROLES, period=3)


def test_or_batches_groups_phrases_into_quoted_or_query():
    assert list(hr_search.or_batches(["A", "B", "C"], size=2)) == ['"A" OR "B"', '"C"']


def test_every_axis_produces_keyword_and_role_queries():
    by_axis = {}
    for axis, params in build():
        by_axis.setdefault(axis, []).append(params)

    assert set(by_axis) == {"remote_rf", "moscow", "nn"}
    for axis, queries in by_axis.items():
        assert any("text" in q for q in queries), f"ось {axis} без поиска по ключевикам"
        assert any("professional_role" in q for q in queries), f"ось {axis} без поиска по ролям"


def test_remote_axis_filters_russia_and_uses_uppercase_work_format():
    remote = [p for axis, p in build() if axis == "remote_rf"]
    assert all(p["work_format"] == "REMOTE" for p in remote)
    assert all(p["area"] == "113" for p in remote)


def test_city_axes_do_not_constrain_work_format():
    city = [p for axis, p in build() if axis in ("moscow", "nn")]
    assert all("work_format" not in p for p in city)
    assert {p["area"] for p in city} == {"1", "66"}


def test_all_profile_keywords_are_covered():
    texts = " ".join(p.get("text", "") for _axis, p in build())
    for profile in PROFILES.values():
        for kw in profile["keywords"]:
            assert f'"{kw}"' in texts


def test_keyword_queries_search_in_title_only():
    for _axis, params in build():
        if "text" in params:
            assert params["search_field"] == "name"


def test_role_query_carries_every_professional_role():
    role_queries = [p for _a, p in build() if "professional_role" in p]
    assert all(p["professional_role"] == ROLES for p in role_queries)
    assert len(role_queries) == 3  # по одному на ось


def test_period_is_passed_through():
    assert all(p["period"] == 3 for _a, p in build())


def test_query_budget_is_far_below_old_whitelist_pass():
    """Старый проход по whitelist: ~89 запросов за цикл. Новый — единицы."""
    assert len(build()) <= 15
