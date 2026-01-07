import csv
import os

INPUT_FILE = 'companies.csv'
OUTPUT_FILE = 'whitelist.py'
LIMIT = 100

def generate_whitelist():
    print(f"🔪 Собираю ТОП-{LIMIT} с категориями...")
    
    if not os.path.exists(INPUT_FILE):
        print(f"❌ Файл {INPUT_FILE} не найден! Сначала запусти парсер.")
        return

    # Словарик: Категория -> Список компаний
    categories = {
        "💎 ГИГАНТЫ": [],
        "🏢 КРУПНЫЕ": [],
        "🏭 СРЕДНИЕ": [],
        "🏪 НЕБОЛЬШИЕ": []
    }
    
    try:
        with open(INPUT_FILE, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter=';')
            for row in reader:
                cat = row['category']
                if cat in categories:
                    if len(categories[cat]) < LIMIT:
                        categories[cat].append(row)
    except Exception as e:
        print(f"❌ Ошибка чтения CSV: {e}")
        return

    total_count = 0
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write("# ЭТОТ СПИСОК СГЕНЕРИРОВАН АВТОМАТИЧЕСКИ\n")
        f.write("# Словарь: ID -> {Название, Категория}\n\n")
        
        f.write("APPROVED_COMPANIES = {\n")
        
        for cat, items in categories.items():
            f.write(f"    # --- {cat} ---\n")
            for item in items:
                # Чистим название от кавычек и переносов
                clean_name = item['name'].replace('\n', ' ').replace('\r', '').replace("'", "").replace('"', '').strip()
                clean_cat = item['category']
                
                # Пишем словарь
                f.write(f"    '{item['id']}': {{'name': '{clean_name}', 'cat': '{clean_cat}'}},\n")
                total_count += 1
            f.write("\n")
            
        f.write("}\n")
        
    print(f"✅ Файл {OUTPUT_FILE} обновлен!")
    print(f"💼 Теперь бот знает категории для {total_count} компаний.")

if __name__ == "__main__":
    generate_whitelist()