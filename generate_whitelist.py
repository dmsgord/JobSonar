import csv
import os

# --- НАСТРОЙКИ ---
FILENAME = 'companies.csv'  # Имя твоего файла
LIMITS = {
    '1': 150, # Гиганты (Топ-150)
    '2': 250, # Крупные (Топ-250)
    '3': 200, # Средние (Топ-200)
    '4': 200  # Небольшие (Топ-200)
}

CAT_MAP_OUT = {
    '1': 'Гиганты',
    '2': 'Крупные',
    '3': 'Средние',
    '4': 'Небольшие'
}

def get_delimiter(file_path):
    with open(file_path, 'r', encoding='utf-8-sig') as f:
        line = f.readline()
        if ';' in line: return ';'
        if ',' in line: return ','
    return ',' # По умолчанию

def generate():
    if not os.path.exists(FILENAME):
        # Пробуем найти файл с длинным именем, если юзер не переименовал
        long_name = 'companies (1).xlsx - companies.csv.csv'
        if os.path.exists(long_name):
            print(f"⚠️ Нашел файл '{long_name}', использую его.")
            target_file = long_name
        else:
            print(f"❌ Файл {FILENAME} не найден!")
            return
    else:
        target_file = FILENAME

    companies = {'1': [], '2': [], '3': [], '4': []}
    delim = get_delimiter(target_file)
    print(f"⚙️ Использую разделитель: '{delim}'")

    try:
        with open(target_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f, delimiter=delim)
            
            # Читаем все строки
            all_rows = []
            for row in reader:
                all_rows.append(row)

            print(f"📂 Всего строк в файле: {len(all_rows)}")

            for row in all_rows:
                if len(row) < 3: continue
                
                # Пропускаем заголовок
                if 'id' in row[0].lower() and 'name' in row[1].lower(): continue

                cid = row[0].strip()
                name = row[1].strip()
                cat_text = row[2].strip().upper()
                
                # Пытаемся найти ранг (4-я колонка), если нет - ставим 999999
                rank = 999999
                if len(row) >= 4 and row[3].strip().isdigit():
                    rank = int(row[3].strip())

                # Определяем категорию
                cat = '4'
                if 'ГИГАНТ' in cat_text: cat = '1'
                elif 'КРУПН' in cat_text: cat = '2'
                elif 'СРЕДН' in cat_text: cat = '3'
                elif 'НЕБОЛЬШ' in cat_text or 'МАЛ' in cat_text: cat = '4'
                
                if cid.isdigit():
                    # Сохраняем как кортеж (РАНГ, ID, ИМЯ) для сортировки
                    companies[cat].append({'rank': rank, 'id': cid, 'name': name})
                    
    except Exception as e:
        print(f"❌ Ошибка чтения: {e}")
        return

    final_dict = {}
    print("\n📊 Обработка списка (Сортировка по рейтингу):")
    
    total_found = 0
    for cat, limit in LIMITS.items():
        # СОРТИРОВКА! Самое важное: от 1 к 1000
        sorted_list = sorted(companies[cat], key=lambda x: x['rank'])
        
        # Берем ТОП-N
        selected = sorted_list[:limit]
        
        print(f"   Category {cat} ({CAT_MAP_OUT[cat]}): взято {len(selected)} (Лучший ранг: {selected[0]['rank']}, Худший: {selected[-1]['rank']})")
        
        for item in selected:
            clean_name = item['name'].replace("'", "").replace('"', '')
            cat_label = CAT_MAP_OUT[cat].upper() # ГИГАНТЫ
            # Эмодзи добавит сам бот, нам нужен только ключ (ГИГАНТЫ, КРУПНЫЕ...)
            # Но в конфиге main.py ключи: 'ГИГАНТЫ': '🏆'.
            # Пишем в файл чистый ключ
            final_dict[item['id']] = {'name': clean_name, 'cat': cat_label}
            total_found += 1

    with open('whitelist.py', 'w', encoding='utf-8') as f:
        f.write("# AUTO-GENERATED WHITELIST (SORTED BY RANK)\n")
        f.write("APPROVED_COMPANIES = {\n")
        for cid, data in final_dict.items():
            f.write(f"    '{cid}': {{'name': '{data['name']}', 'cat': '{data['cat']}'}},\n")
        f.write("}\n")
    
    print(f"\n✅ Готово! Файл whitelist.py создан. Всего компаний: {total_found}")

if __name__ == "__main__":
    generate()