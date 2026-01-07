import sqlite3

DB_FILE = "jobsonar.db"

def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS history (id TEXT PRIMARY KEY)")

def is_sent(vac_id):
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.execute("SELECT 1 FROM history WHERE id = ?", (str(vac_id),))
        return cur.fetchone() is not None

def mark_as_sent(vac_id):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("INSERT OR IGNORE INTO history (id) VALUES (?)", (str(vac_id),))