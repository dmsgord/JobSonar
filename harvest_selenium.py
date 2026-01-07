import time
import re
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By

# Ссылки на все вкладки рейтинга
URLS = [
    "https://rating.hh.ru/history/rating2024/summary?tab=giant",  # Крупнейшие
    "https://rating.hh.ru/history/rating2024/summary?tab=big",    # Крупные
    "https://rating.hh.ru/history/rating2024/summary?tab=regular",# Средние
    "https://rating.hh.ru/history/rating2024/summary?tab=small"   # Небольшие
]

def get_ids_via_browser():
    print("🤖 Запускаю браузерный агент...")
    
    # Автоматическая установка драйвера Chrome
    options = webdriver.ChromeOptions()
    # options.add_argument("--headless") # Если раскомментировать, браузер будет невидимым
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    
    all_ids = set()

    try:
        for url in URLS:
            print(f"🚀 Перехожу на: {url}")
            driver.get(url)
            
            # Ждем 5 секунд, пока сайт прогрузит скрипты и таблицу
            print("⏳ Жду загрузки таблицы...")
            time.sleep(5)
            
            # Прокручиваем страницу вниз, чтобы подгрузились ленивые элементы
            # Делаем это несколько раз
            for _ in range(3):
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1)

            # Ищем ВСЕ ссылки на странице
            links = driver.find_elements(By.TAG_NAME, "a")
            print(f"👀 Найдено {len(links)} ссылок на странице. Анализирую...")

            count_on_page = 0
            for link in links:
                try:
                    href = link.get_attribute("href")
                    if href and "hh.ru/employer/" in href:
                        # Вытаскиваем цифры из ссылки
                        match = re.search(r'employer/(\d+)', href)
                        if match:
                            emp_id = match.group(1)
                            all_ids.add(emp_id)
                            count_on_page += 1
                except:
                    continue # Если ссылка битая, идем дальше
            
            print(f"✅ На этой странице найдено компаний: {count_on_page}")
            
    except Exception as e:
        print(f"🔥 Ошибка: {e}")
    finally:
        driver.quit()
        print("🤖 Браузер закрыт.")

    # Вывод результатов
    result_list = sorted(list(all_ids), key=lambda x: int(x))
    print("\n" + "="*40)
    print(f"🎉 ВСЕГО СОБРАНО УНИКАЛЬНЫХ ID: {len(result_list)}")
    print("="*40)
    
    # Форматируем для вставки
    print("TARGET_EMPLOYERS = [")
    chunk_size = 10
    for i in range(0, len(result_list), chunk_size):
        chunk = result_list[i:i + chunk_size]
        line = ", ".join([f'"{eid}"' for eid in chunk])
        print(f"    {line},")
    print("]")

if __name__ == "__main__":
    get_ids_via_browser()