import time
import re
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By

# Настройки: Сколько процентов от топа оставлять?
KEEP_PERCENT = 0.50  # 50% (Оставляем только верхнюю половину таблицы)

URLS = {
    "💎 ГИГАНТЫ": "https://rating.hh.ru/history/rating2024/summary?tab=giant",
    "🏢 КРУПНЫЕ": "https://rating.hh.ru/history/rating2024/summary?tab=big",
    "🏭 СРЕДНИЕ": "https://rating.hh.ru/history/rating2024/summary?tab=regular",
    # "🏪 НЕБОЛЬШИЕ": "https://rating.hh.ru/history/rating2024/summary?tab=small" # Можно вообще закомментировать, если мелкие не нужны
}

def get_top_tier_data():
    print(f"🎯 Запускаю Снайперский Агент (Цель: Топ-{int(KEEP_PERCENT*100)}% рейтинга)...")
    
    options = webdriver.ChromeOptions()
    # options.add_argument("--headless") 
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    
    final_dict = {}
    total_kept = 0

    try:
        for category_name, url in URLS.items():
            print(f"\n🚀 Категория: {category_name}")
            driver.get(url)
            
            print("⏳ Загружаю таблицу рейтинга...")
            time.sleep(3)
            
            # Крутим вниз до упора, чтобы загрузить ВЕСЬ список (важно для расчета топа)
            last_height = driver.execute_script("return document.body.scrollHeight")
            while True:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1.5)
                new_height = driver.execute_script("return document.body.scrollHeight")
                if new_height == last_height:
                    break
                last_height = new_height

            # Собираем ссылки В ПОРЯДКЕ ИХ ПОЯВЛЕНИЯ НА ЭКРАНЕ (это и есть рейтинг)
            links = driver.find_elements(By.TAG_NAME, "a")
            
            # Временный список для этой категории (сохраняем порядок!)
            category_companies = []
            seen_ids = set()

            for link in links:
                try:
                    href = link.get_attribute("href")
                    name = link.text.strip()
                    
                    if href and "hh.ru/employer/" in href and name:
                        match = re.search(r'employer/(\d+)', href)
                        if match:
                            emp_id = match.group(1)
                            if emp_id not in seen_ids:
                                # Чистим имя
                                clean_name = name.replace('"', '').replace("'", "")
                                category_companies.append((emp_id, clean_name))
                                seen_ids.add(emp_id)
                except:
                    continue

            # 🔥 ГЛАВНАЯ МАГИЯ: РЕЖЕМ ПО ЖИВОМУ
            total_found = len(category_companies)
            cut_point = int(total_found * KEEP_PERCENT)
            
            # Берем только срез от 0 до cut_point
            top_companies = category_companies[:cut_point]
            
            final_dict[category_name] = top_companies
            
            print(f"📊 Всего в рейтинге: {total_found}")
            print(f"✂️ Отрезаем дно. Оставляем топ: {len(top_companies)}")
            total_kept += len(top_companies)
            
    except Exception as e:
        print(f"🔥 Ошибка: {e}")
    finally:
        driver.quit()

    # --- ГЕНЕРАЦИЯ config.py ---
    print("\n💾 Перезаписываю config.py с новыми данными...")
    
    # Читаем старый конфиг, чтобы сохранить токены (если файл есть)
    header_lines = []
    try:
        with open("config.py", "r", encoding="utf-8") as f:
            for line in f:
                if "TARGET_EMPLOYERS =" in line:
                    break
                header_lines.append(line)
    except:
        # Если файла нет, создадим заголовки по умолчанию
        header_lines = [
            "import os\nfrom dotenv import load_dotenv\nload_dotenv()\n",
            "TG_TOKEN = os.getenv('TG_TOKEN')\nTG_CHAT_ID = os.getenv('TG_CHAT_ID')\n",
            "CHECK_INTERVAL = 300\nREQUEST_DELAY = 1.0\nMIN_SALARY = 200000\n",
            "HH_HEADERS = {'User-Agent': 'JobSonar/2.0', 'Accept': '*/*'}\n",
            "TARGET_AREAS = ['1', '66']\n\n"
        ]

    # Записываем новый config.py
    with open("config.py", "w", encoding="utf-8") as f:
        # Пишем шапку (токены и настройки)
        f.writelines(header_lines)
        
        f.write("# 🔥 TARGET_EMPLOYERS: ТОП-50% компаний рейтинга 2024\n")
        f.write("TARGET_EMPLOYERS = [\n")
        
        for category, items in final_dict.items():
            if not items: continue
            f.write(f"    # --- {category} (Топ {len(items)}) ---\n")
            # Сортируем внутри категории по алфавиту ТОЛЬКО ДЛЯ УДОБСТВА ЧТЕНИЯ КОДА
            # Но сам список уже содержит только лучших
            items.sort(key=lambda x: x[1])
            
            for emp_id, name in items:
                f.write(f"    '{emp_id}', # {name}\n")
            f.write("\n")
            
        f.write("]\n\n")
        
        # Дописываем профили (они стандартные)
        f.write("PROFILES = {\n")
        f.write("    'HR': {\n")
        f.write("        'keywords': ['HR Director', 'Директор по персоналу', 'HRBP', 'Head of HR', 'Руководитель подбора', 'CPO'],\n")
        f.write("        'stop_words': ['junior', 'assistant', 'ассистент', 'coordinator', 'рекрутер', 'recruiter', 'специалист', 'стажер', 'intern']\n")
        f.write("    },\n")
        f.write("    'ANALYST': {\n")
        f.write("        'keywords': ['System Analyst', 'Системный аналитик', 'Business Analyst', 'Product Analyst', 'Team Lead Analyst'],\n")
        f.write("        'stop_words': ['junior', 'стажер', 'intern', 'support', 'поддержка']\n")
        f.write("    }\n")
        f.write("}\n")
        f.write("LOG_FILE = 'jobsonar.log'\n")

    print("="*40)
    print(f"🎉 ГОТОВО! В config.py записано {total_kept} элитных компаний.")
    print("Теперь запускай: python main.py")
    print("="*40)

if __name__ == "__main__":
    get_top_tier_data()