# -*- coding: utf-8 -*-
"""Сборка сообщений HR-бота.

Компания за один проход часто вываливает 3-5 подходящих вакансий — шлём их
одним сообщением с общей шапкой, а не пятью почти одинаковыми карточками.
"""
from utils import format_pub_date

MAX_VACANCIES_PER_MESSAGE = 8  # ограничение телеги 4096 символов, берём с запасом

# Справочник hh целиком: work_format — «Удалённо», «Гибрид», «На месте работодателя»,
# «Разъездной»; schedule — «Полный день», «Сменный», «Гибкий», «Вахта», «Удалённо».
# В строке 📌 оставляем только то, ради чего вакансию вообще взяли: удалёнку и гибрид.
# Офисные варианты не показываем — до сообщения они и так больше не доходят (hr_filter).
FORMAT_MARKERS = ("удал", "remote", "гибрид", "hybrid")


def format_details(details):
    """['Полный день', 'На месте работодателя', 'Гибрид'] → 'Гибрид'.

    Оба формата сразу — оба и пишем: ['Удалённо', 'Гибрид'] → 'Удалённо, Гибрид'.
    """
    kept = [d for d in details if d and any(m in d.lower() for m in FORMAT_MARKERS)]
    return ", ".join(kept)


def _header(employer, tier):
    rating = employer.get('rating')
    rating_text = f" ★{rating}" if rating else ""
    reviews = employer.get('reviews_count') or 0
    reviews_text = f" 💬{reviews}" if reviews else ""
    agency_mark = " · агентство" if employer.get('category') == 'AGENCY' else ""
    # Отрасли компании в списочной выдаче hh нет; единственный отраслевой признак,
    # который приходит бесплатно, — аккредитация Минцифры как IT-компании.
    it_mark = " · IT" if employer.get('accredited_it') else ""
    return f"{tier} <b>{employer.get('name')}</b>{rating_text}{reviews_text}{it_mark}{agency_mark}"


def _vacancy_block(item, decision):
    """Опыт не выводим: он уже учтён в отборе и в скоринге, в карточке — лишний шум."""
    salary_html = f"<b>{decision.salary_text}</b>" if decision.bold else decision.salary_text
    fmt = format_details(decision.details)
    fmt_line = f"📌 {fmt}\n" if fmt else ""
    # Значок профиля: у IT-рекрутера свой поток и свои правила, его надо отличать глазом
    mark = f"{decision.mark} " if decision.mark else ""
    return (
        f"{mark}<a href='{item['alternate_url']}'><b>{item['name']}</b></a>\n\n"
        f"{fmt_line}"
        f"💰 {salary_html} | 🗓 {format_pub_date(item)}"
    )


def group_by_employer(entries):
    """[(item, decision)] → {emp_id: [(item, decision), ...]} с сохранением порядка."""
    groups = {}
    for item, decision in entries:
        emp_id = str(item.get('employer', {}).get('id', '')) or item['id']
        groups.setdefault(emp_id, []).append((item, decision))
    return groups


def build_messages(entries):
    """[(item, decision)] → [(текст, [id вакансий], тир)]. Одна компания — одно сообщение."""
    messages = []
    for group in group_by_employer(entries).values():
        for start in range(0, len(group), MAX_VACANCIES_PER_MESSAGE):
            chunk = group[start:start + MAX_VACANCIES_PER_MESSAGE]
            best = max(chunk, key=lambda pair: pair[1].score)[1]
            employer = chunk[0][0].get('employer', {})
            blocks = [_vacancy_block(item, decision) for item, decision in chunk]
            text = _header(employer, best.tier) + "\n\n" + "\n\n".join(blocks)
            messages.append((text, [item['id'] for item, _d in chunk], best.tier))
    return messages
