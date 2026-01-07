import os
import sqlite3

DB_FILE = "jobsonar.db"

def reset_database():
    # Вариант 1: Просто удаляем файл (самый надежный способ)
    if os.path.exists(DB_FILE):
        try:
            os.remove(DB_FILE)
            print(f"🗑  Файл {DB_FILE} удален. История очищена полностью.")
        except PermissionError:
            print(f"⚠️ Ошибка: Файл занят. Закрой бота и попробуй снова.")
            return
    else:
        print(f"ℹ️ Файла {DB_FILE} нет, база и так чистая.")

    # Создаем новую пустую таблицу сразу, чтобы всё было готово
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS history (id TEXT PRIMARY KEY)")
    conn.commit()
    conn.close()
    
    print("✨ Новая пустая база создана! Бот готов к работе.")

if __name__ == "__main__":
    reset_database()