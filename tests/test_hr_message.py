# -*- coding: utf-8 -*-
"""Сообщения в Telegram: несколько вакансий одной компании — одним сообщением."""
from hr_filter import Decision
from hr_message import MAX_VACANCIES_PER_MESSAGE, build_messages, format_details


def item(vac_id, name, emp_id="777", emp_name="Тест Компани", rating=4.6, reviews=800):
    return {
        "id": vac_id,
        "name": name,
        "alternate_url": f"https://hh.ru/vacancy/{vac_id}",
        "employer": {
            "id": emp_id, "name": emp_name, "rating": rating,
            "reviews_count": reviews, "category": "COMPANY",
        },
        "published_at": "2026-09-10T10:00:00+0300",
    }


def decision(tier="💎", score=71, salary="от 300000 ₽"):
    return Decision(True, "ok", tier, score, salary, True, ["Удалённо"],
                    {"id": "between3And6", "name": "От 3 до 6 лет"})


def test_single_vacancy_message_has_company_title_and_link():
    msgs = build_messages([(item("1", "HRD"), decision())])
    assert len(msgs) == 1
    text, vac_ids, tier = msgs[0]
    assert "Тест Компани" in text
    assert "★4.6" in text
    assert "💬800" in text
    assert "https://hh.ru/vacancy/1" in text
    assert vac_ids == ["1"]
    assert tier == "💎"


def test_two_vacancies_of_one_employer_are_merged():
    msgs = build_messages([
        (item("1", "HRD"), decision()),
        (item("2", "HR Business Partner"), decision()),
    ])
    assert len(msgs) == 1
    text, vac_ids, _tier = msgs[0]
    assert text.count("Тест Компани") == 1
    assert "HRD" in text and "HR Business Partner" in text
    assert vac_ids == ["1", "2"]


def test_different_employers_get_separate_messages():
    msgs = build_messages([
        (item("1", "HRD"), decision()),
        (item("2", "HRD", emp_id="888", emp_name="Другая"), decision()),
    ])
    assert len(msgs) == 2
    assert {m[1][0] for m in msgs} == {"1", "2"}


def test_group_keeps_best_tier_of_its_vacancies():
    msgs = build_messages([
        (item("1", "HRD"), decision(tier="⚪", score=25)),
        (item("2", "HRBP"), decision(tier="💎", score=71)),
    ])
    text, _ids, tier = msgs[0]
    assert tier == "💎"
    assert text.startswith("💎")


def test_large_group_is_split_into_chunks():
    entries = [(item(str(i), f"Вакансия {i}"), decision()) for i in range(MAX_VACANCIES_PER_MESSAGE + 2)]
    msgs = build_messages(entries)
    assert len(msgs) == 2
    assert len(msgs[0][1]) == MAX_VACANCIES_PER_MESSAGE
    assert len(msgs[1][1]) == 2
    assert all("Тест Компани" in m[0] for m in msgs)


def test_blank_line_between_title_and_details():
    text, _ids, _tier = build_messages([(item("1", "HRD"), decision())])[0]
    assert "</a>\n\n📌" in text


def test_agency_is_marked_in_header():
    agency_item = item("1", "HRD")
    agency_item["employer"]["category"] = "AGENCY"
    text, _ids, _tier = build_messages([(agency_item, decision())])[0]
    assert "агентство" in text


def test_employer_without_rating_has_no_star():
    plain = item("1", "HRD", rating=None, reviews=0)
    text, _ids, _tier = build_messages([(plain, decision())])[0]
    assert "★" not in text
    assert "💬" not in text


def test_experience_is_not_shown():
    """Опыт учтён в отборе — в карточке он только занимает место."""
    text, _ids, _tier = build_messages([(item("1", "HRD"), decision())])[0]
    assert "🎓" not in text
    assert "От 3 до 6 лет" not in text


def test_details_keep_only_remote_and_hybrid():
    assert format_details(["Полный день", "На месте работодателя", "Гибрид"]) == "Гибрид"
    assert format_details(["Удалённо", "Гибрид"]) == "Удалённо, Гибрид"
    assert format_details(["Удалённо"]) == "Удалённо"
    assert format_details(["Полный день", "На месте работодателя"]) == ""
    assert format_details(["Сменный", "Разъездной"]) == ""
    # офис в перечне не мешает: показываем только то, ради чего вакансию взяли
    assert format_details(["На месте работодателя", "Удалённо"]) == "Удалённо"
    assert format_details(["Удалённо", "Разъездной"]) == "Удалённо"
    assert format_details(["Полный день", "На месте работодателя",
                           "Удалённо", "Гибрид"]) == "Удалённо, Гибрид"


def test_both_formats_are_printed():
    """Есть и удалёнка, и гибрид — пишем оба слова, порядок как отдал hh."""
    d = decision()._replace(details=["Полный день", "Удалённо", "Гибрид"])
    text, _ids, _tier = build_messages([(item("1", "HRD"), d)])[0]
    assert "📌 Удалённо, Гибрид\n" in text


def test_details_line_dropped_when_nothing_to_show():
    """Пустая 📌-строка не остаётся: без удалёнки/гибрида её просто нет."""
    d = decision()._replace(details=["Полный день", "На месте работодателя"])
    text, _ids, _tier = build_messages([(item("1", "HRD"), d)])[0]
    assert "📌" not in text
    assert "</a>\n\n💰" in text


def test_it_accredited_employer_is_marked():
    it_item = item("1", "HRD")
    it_item["employer"]["accredited_it"] = True
    text, _ids, _tier = build_messages([(it_item, decision())])[0]
    assert "· IT" in text


def test_non_it_employer_has_no_it_mark():
    text, _ids, _tier = build_messages([(item("1", "HRD"), decision())])[0]
    assert "· IT" not in text


def test_message_fits_telegram_limit():
    entries = [(item(str(i), "Руководитель отдела персонала и организационного развития"), decision())
               for i in range(MAX_VACANCIES_PER_MESSAGE)]
    text, _ids, _tier = build_messages(entries)[0]
    assert len(text) < 4096
