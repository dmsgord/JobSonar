# -*- coding: utf-8 -*-
"""Нормализация выдачи hh.ru: сигналы качества работодателя и гео."""
import utils


def raw_vacancy(**overrides):
    """Сырая вакансия в том виде, в каком лежит в HH-Lux-InitialState."""
    raw = {
        "vacancyId": 123,
        "name": "HR Business Partner",
        "links": {"desktop": "https://hh.ru/vacancy/123"},
        "company": {
            "id": 777,
            "visibleName": "Тест Компани",
            "@category": "COMPANY",
            "@trusted": True,
            "employerReviews": {"totalRating": "4.3", "reviewsCount": 128},
            "accreditedITEmployer": True,
            "logos": {"logo": [{"@type": "small"}]},
        },
        "compensation": {"from": 250000, "to": None, "currencyCode": "RUR"},
        "area": {"@id": 1, "name": "Москва", "path": ".113.232.1."},
        "workExperience": "between3And6",
        "workFormats": [{"workFormatsElement": ["REMOTE"]}],
        "@workSchedule": "remote",
        "publicationTime": {"$": "2026-09-10T10:00:00+0300"},
        "branding": {"type": "MAKEUP"},
    }
    raw.update(overrides)
    return raw


def test_normalize_extracts_employer_quality_signals():
    emp = utils._normalize_vacancy(raw_vacancy())["employer"]
    assert emp["rating"] == 4.3
    assert emp["reviews_count"] == 128
    assert emp["category"] == "COMPANY"
    assert emp["accredited_it"] is True
    assert emp["has_logo"] is True
    assert emp["branding"] is True
    assert emp["on_additional_check"] is False


def test_normalize_survives_employer_without_reviews():
    raw = raw_vacancy()
    raw["company"] = {"id": 5, "visibleName": "Без отзывов", "@category": "AGENCY"}
    emp = utils._normalize_vacancy(raw)["employer"]
    assert emp["rating"] is None
    assert emp["reviews_count"] == 0
    assert emp["category"] == "AGENCY"
    assert emp["has_logo"] is False


def test_normalize_marks_employer_on_additional_check():
    raw = raw_vacancy()
    raw["company"]["employerOnAdditionalCheck"] = True
    assert utils._normalize_vacancy(raw)["employer"]["on_additional_check"] is True


def test_normalize_keeps_area_path():
    assert utils._normalize_vacancy(raw_vacancy())["area"]["path"] == ".113.232.1."


def test_russian_area_accepted_by_path():
    assert utils.is_russian_area({"id": "1", "name": "Москва", "path": ".113.232.1."}) is True


def test_foreign_area_rejected_by_path():
    tashkent = {"id": "2759", "name": "Ташкент", "path": ".97.2759."}
    assert utils.is_russian_area(tashkent) is False


def test_foreign_area_rejected_without_path():
    """Пути может не быть — падаем на список заведомо иностранных area id."""
    assert utils.is_russian_area({"id": "160", "name": "Алматы", "path": ""}) is False


def test_area_without_path_and_unknown_id_is_allowed():
    assert utils.is_russian_area({"id": "66", "name": "Нижний Новгород", "path": ""}) is True


def test_remote_search_sends_uppercase_work_format(monkeypatch):
    """hh молча игнорит work_format=remote в нижнем регистре (замер 2026-09-09)."""
    captured = {}

    def fake_fetch_page(session, params, page=0):
        captured.update(params)
        return [], 1

    monkeypatch.setattr(utils, "_fetch_page", fake_fetch_page)
    utils.fetch_hh_paginated(None, "HRD", schedule="remote")
    assert captured["work_format"] == "REMOTE"


def test_company_search_sends_uppercase_work_format(monkeypatch):
    captured = {}
    monkeypatch.setattr(utils, "_fetch_page", lambda s, p, page=0: (captured.update(p), ([], 1))[1])
    utils.fetch_company_vacancies(None, ["1", "2"], schedule="remote")
    assert captured["work_format"] == "REMOTE"


# ── стоп-слова: подстрока ≠ слово ──────────────────────────────────────────

def test_stop_word_does_not_match_inside_another_word():
    """'водитель' внутри 'руководитель' — не стоп-слово (баг прода до 2026-09-12)."""
    assert utils.hits_stop_word("Руководитель отдела персонала", ["водитель"]) is False


def test_stop_word_matches_word_start_with_russian_inflection():
    """Стоп-слово — стем: хвост слова свободен ('продаж' ловит 'продажам')."""
    assert utils.hits_stop_word("Менеджер по продажам", ["продаж"]) is True
    assert utils.hits_stop_word("Водитель-экспедитор", ["водитель"]) is True


def test_stop_word_matches_after_hyphen():
    assert utils.hits_stop_word("Бизнес-аналитик данных", ["аналитик"]) is True


def test_stop_word_matches_multiword_phrase():
    assert utils.hits_stop_word("Senior Specialist HR", ["senior specialist"]) is True


def test_clean_title_has_no_stop_words():
    assert utils.hits_stop_word("HR Business Partner", ["продаж", "логист"]) is False


# ── частные лица под видом компании ────────────────────────────────────────

def test_fio_employer_is_detected_as_person():
    assert utils.looks_like_private_person("Вараксин Александр Дмитриевич") is True
    assert utils.looks_like_private_person("Валиев Руслан Масхудович") is True


def test_ip_prefix_is_detected_as_person():
    assert utils.looks_like_private_person("ИП Смирнова Е.А.") is True


def test_normal_companies_are_not_persons():
    for name in ["Аптечная сеть ФармаТ", "Киберматика", "ООО Ромашка", "Seven Group",
                 "Лента, федеральная розничная сеть", "JuicyScore"]:
        assert utils.looks_like_private_person(name) is False, name
