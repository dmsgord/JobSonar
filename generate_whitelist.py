import csv
import os

# --- НАСТРОЙКИ ---
FILENAME = 'companies.csv'
LIMITS = {
    '1': 150, # Гиганты
    '2': 250, # Крупные
    '3': 200, # Средние
    '4': 200  # Небольшие
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
    return ','

def generate():
    if not os.path.exists(FILENAME):
        # Пробуем найти файл с длинным именем
        long_name = 'companies (1).xlsx - companies.csv.csv'
        if os.path.exists(long_name):
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
            
            all_rows = []
            for row in reader:
                all_rows.append(row)

            for row in all_rows:
                if len(row) < 3: continue
                if 'id' in row[0].lower() and 'name' in row[1].lower(): continue

                cid = row[0].strip()
                name = row[1].strip()
                cat_text = row[2].strip().upper()
                
                rank = 999999
                if len(row) >= 4 and row[3].strip().isdigit():
                    rank = int(row[3].strip())

                cat = '4'
                if 'ГИГАНТ' in cat_text: cat = '1'
                elif 'КРУПН' in cat_text: cat = '2'
                elif 'СРЕДН' in cat_text: cat = '3'
                elif 'НЕБОЛЬШ' in cat_text or 'МАЛ' in cat_text: cat = '4'
                
                if cid.isdigit():
                    companies[cat].append({'rank': rank, 'id': cid, 'name': name})
                    
    except Exception as e:
        print(f"❌ Ошибка чтения: {e}")
        return

    final_dict = {}
    print("\n📊 Обработка списка (Fixed Newlines):")
    
    total_found = 0
    for cat, limit in LIMITS.items():
        sorted_list = sorted(companies[cat], key=lambda x: x['rank'])
        selected = sorted_list[:limit]
        
        print(f"   Category {cat}: взято {len(selected)}")
        
        for item in selected:
            # 🔥 ФИКС: Убираем переносы строк и кавычки
            clean_name = item['name'].replace("'", "").replace('"', '').replace('\n', ' ').replace('\r', '')
            
            cat_label = CAT_MAP_OUT[cat].upper()
            final_dict[item['id']] = {'name': clean_name, 'cat': cat_label}
            total_found += 1

    with open('whitelist.py', 'w', encoding='utf-8') as f:
        f.write("# AUTO-GENERATED WHITELIST (SORTED & CLEANED)\n")
        f.write("APPROVED_COMPANIES = {\n")
        for cid, data in final_dict.items():
            f.write(f"    '{cid}': {{'name': '{data['name']}', 'cat': '{data['cat']}'}},\n")
        f.write("}\n")
    
    print(f"\n✅ Готово! Файл whitelist.py пересоздан (без переносов строк).")

if __name__ == "__main__":
    generate()