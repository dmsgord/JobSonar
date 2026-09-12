# -*- coding: utf-8 -*-
"""Кэш работодателей HR-бота.

Скор считается из полей выдачи (scoring.py) и складывается сюда: счёт остаётся
стабильным между циклами, и всегда видно, кого бот считает топом.
Таблица живёт в той же SQLite, что и отправленные вакансии.
"""
import logging
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS employers (
    id TEXT PRIMARY KEY,
    name TEXT,
    rating REAL,
    reviews_count INTEGER DEFAULT 0,
    category TEXT,
    score INTEGER DEFAULT 0,
    updated_at TEXT
)
"""


def _connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_employer_cache(db_path):
    with _connect(db_path) as conn:
        conn.execute(SCHEMA)


def remember_employer(db_path, employer, score):
    """Upsert по id работодателя: свежие рейтинг/отзывы/скор."""
    try:
        with _connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO employers (id, name, rating, reviews_count, category, score, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    rating=excluded.rating,
                    reviews_count=excluded.reviews_count,
                    category=excluded.category,
                    score=excluded.score,
                    updated_at=excluded.updated_at
                """,
                (
                    str(employer.get("id", "")),
                    employer.get("name", ""),
                    employer.get("rating"),
                    int(employer.get("reviews_count") or 0),
                    employer.get("category", ""),
                    int(score),
                ),
            )
    except Exception as e:
        logging.error(f"Employer cache error: {e}")


def get_employer(db_path, emp_id):
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM employers WHERE id = ?", (str(emp_id),)).fetchone()
    return dict(row) if row else None


def top_employers(db_path, limit=20):
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM employers ORDER BY score DESC, reviews_count DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]
