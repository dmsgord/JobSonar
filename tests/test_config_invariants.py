# -*- coding: utf-8 -*-
"""Инварианты конфига: стоп-слова не должны убивать собственные целевые тайтлы."""
import pytest

from config import PROFILES
from config_coo import COO_PROFILES
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
