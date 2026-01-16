import sqlite3
import logging
from datetime import datetime

DB_NAME = "jobsonar.db"

def set_db_name(name):
    global DB_NAME
    DB_NAME = name

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS vacancies (
            id TEXT PRIMARY KEY,
            category TEXT DEFAULT 'Остальные',
            created_at DATE DEFAULT CURRENT_DATE
        )
    ''')
    try: cursor.execute("ALTER TABLE vacancies ADD COLUMN category TEXT DEFAULT 'Остальные'")
    except: pass
    try: cursor.execute("ALTER TABLE vacancies ADD COLUMN created_at DATE DEFAULT CURRENT_DATE")
    except: pass
    conn.commit()
    conn.close()

def is_sent(vac_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM vacancies WHERE id = ?", (vac_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def mark_as_sent(vac_id, category="Остальные"):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT OR IGNORE INTO vacancies (id, category, created_at) VALUES (?, ?, date('now', 'localtime'))", 
            (vac_id, category)
        )
        conn.commit()
    except Exception as e:
        logging.error(f"DB Error: {e}")
    conn.close()

def get_daily_stats():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT category, COUNT(*) 
        FROM vacancies 
        WHERE created_at = date('now', 'localtime')
        GROUP BY category
    """)
    rows = cursor.fetchall()
    conn.close()
    
    stats = {"Топ компании": 0, "Остальные": 0}
    for cat, count in rows:
        clean_cat = "Топ компании" if cat in ['🏆', '🥇', '🥈', '🥉'] else "Остальные"
        stats[clean_cat] += count
    return stats