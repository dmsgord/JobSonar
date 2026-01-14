import sqlite3
import os

# Имя базы по умолчанию
CURRENT_DB_FILE = "jobsonar.db"

def set_db_name(name):
    """Разделяет базы данных для разных процессов"""
    global CURRENT_DB_FILE
    CURRENT_DB_FILE = name

def get_connection():
    # timeout=30 предотвращает ошибку 'database is locked'
    return sqlite3.connect(CURRENT_DB_FILE, timeout=30)

def init_db():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sent_vacancies (
                id TEXT PRIMARY KEY,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()

def is_sent(vac_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT 1 FROM sent_vacancies WHERE id = ?', (vac_id,))
        return cursor.fetchone() is not None

def mark_as_sent(vac_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO sent_vacancies (id) VALUES (?)', (vac_id,))
        conn.commit()