# -*- coding: utf-8 -*-
"""Поиск HR-бота по трём гео-осям.

Whitelist убран: он протух как справочник «крутых компаний» и стоил ~89 запросов
к hh за цикл. Вместо него — три оси, каждая гоняется и по ключевикам заголовка,
и по professional_role (ловит нестандартные тайтлы, ради которых жил whitelist).

Ось A: удалёнка по всей РФ (work_format=REMOTE + area=113 — без area в выдачу
лезут Ташкент/Алматы). Ось B: Москва. Ось C: Нижний Новгород, любой формат.
"""

# HR-роли hh.ru (замер 2026-09-09): 38, 171, 69, 117, 118
HR_PROFESSIONAL_ROLES = ["38", "171", "69", "117", "118"]

SEARCH_AXES = [
    {"name": "remote_rf", "params": {"work_format": "REMOTE", "area": "113"}},
    {"name": "moscow", "params": {"area": "1"}},
    {"name": "nn", "params": {"area": "66"}},
]

OR_BATCH_SIZE = 8


def or_batches(phrases, size=OR_BATCH_SIZE):
    """Склеивает ключевики в один OR-запрос hh: '"A" OR "B"' — меньше запросов, меньше 403."""
    for i in range(0, len(phrases), size):
        yield " OR ".join(f'"{p}"' for p in phrases[i:i + size])


def build_axis_queries(axes, profiles, professional_roles, period=3, batch_size=OR_BATCH_SIZE):
    """[(имя_оси, params для fetch_hh_search)] — ключевики всех профилей + роли, на каждой оси.

    Профиль с remote_only (IT-рекрутер) гоняется только по оси удалёнки: на осях
    Москвы и НН он всё равно отсеет всё по формату, а запросы к hh стоят денег.
    """
    queries = []
    for axis in axes:
        axis_name = axis["name"]
        for profile in profiles.values():
            if profile.get("remote_only") and axis_name != "remote_rf":
                continue
            for orq in or_batches(profile.get("keywords", []), size=batch_size):
                params = dict(axis["params"])
                params.update({"text": orq, "search_field": "name", "period": period})
                queries.append((axis_name, params))

        if professional_roles:
            params = dict(axis["params"])
            params.update({"professional_role": list(professional_roles), "period": period})
            queries.append((axis_name, params))
    return queries
