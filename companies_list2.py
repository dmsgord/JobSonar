import csv
import re

# Настройки имен файлов
INPUT_FILE = 'companies_list.py'
OUTPUT_FILE = 'companies.csv'

def make_csv():
    print(f"📖 Читаю {INPUT_FILE}...")
    
    rows = []
    
    # Переменные для отслеживания текущей категории и места
    current_category = "Unknown"
    current_rank = 0
    
    # Регулярка ищет строки вида: '12345': 'Название',
    # Группа 1 = ID, Группа 2 = Название
    pattern = re.compile(r"^\s*'(\d+)':\s*'(.*)',?")

    try:
        with open(INPUT_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        for line in lines:
            line = line.strip()
            
            # 1. Определяем категорию по комментариям (--- ГИГАНТЫ ---)
            if "---" in line:
                if "ГИГАНТЫ" in line:
                    current_category = "💎 ГИГАНТЫ"
                    current_rank = 0
                elif "КРУПНЫЕ" in line:
                    current_category = "🏢 КРУПНЫЕ"
                    current_rank = 0
                elif "СРЕДНИЕ" in line:
                    current_category = "🏭 СРЕДНИЕ"
                    current_rank = 0
                elif "НЕБОЛЬШИЕ" in line:
                    current_category = "🏪 НЕБОЛЬШИЕ"
                    current_rank = 0
                continue

            # 2. Ищем компанию
            match = pattern.search(line)
            if match:
                emp_id = match.group(1)
                # Убираем запятую и кавычку в конце, если регулярка захватила лишнее
                name = match.group(2).rstrip("',")
                
                # Увеличиваем счетчик места
                current_rank += 1
                
                # Добавляем в список
                rows.append([emp_id, name, current_category, current_rank])

        # 3. Сохраняем в CSV
        print(f"✍️ Записываю {len(rows)} компаний в {OUTPUT_FILE}...")
        
        with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f, delimiter=';') # Точка с запятой удобнее для Excel в РФ
            # Заголовки
            writer.writerow(['id', 'name', 'category', 'rank'])
            # Данные
            writer.writerows(rows)
            
        print("✅ Готово! Файл companies.csv создан.")

    except FileNotFoundError:
        print(f"❌ Ошибка: Файл {INPUT_FILE} не найден.")

if __name__ == "__main__":
    make_csv()