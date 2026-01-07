import requests
from bs4 import BeautifulSoup
import re
import time

# Ссылки на рейтинги (Вкладки: Небольшие, Гиганты, Крупные, Средние)
URLS = [
    "https://rating.hh.ru/history/rating2024/summary?tab=small",
    "https://rating.hh.ru/history/rating2024/summary?tab=giant",
    "https://rating.hh.ru/history/rating2024/summary?tab=big",
    "https://rating.hh.ru/history/rating2024/summary?tab=regular"
]

# Притворяемся браузером
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
}

def extract_ids_from_url(url):
    print(f"⏳ Сканирую: {url} ...")
    found_ids = set()
    
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # Ищем ВСЕ ссылки на странице
        for link in soup.find_all('a', href=True):
            href = link['href']
            
            # Ищем паттерн /employer/ЦИФРЫ
            # Примеры ссылок: https://hh.ru/employer/1740?from=rating
            match = re.search(r'employer/(\d+)', href)
            
            if match:
                emp_id = match.group(1)
                found_ids.add(emp_id)
                
    except Exception as e:
        print(f"❌ Ошибка при чтении {url}: {e}")
        
    print(f"   -> Найдено уникальных ID: {len(found_ids)}")
    return found_ids

def main():
    all_employers = set()
    
    print("🚜 Запускаю Харвестер (Сборщик ID)...")
    
    for url in URLS:
        ids = extract_ids_from_url(url)
        all_employers.update(ids)
        time.sleep(1) # Пауза вежливости
        
    # Форматируем для конфига
    result_list = sorted(list(all_employers), key=lambda x: int(x))
    
    print("\n" + "="*40)
    print(f"🎉 ИТОГО СОБРАНО: {len(result_list)} компаний")
    print("="*40)
    print("Скопируй этот список и вставь в TARGET_EMPLOYERS в config.py:\n")
    
    # Печатаем красиво отформатированный список Python
    print("TARGET_EMPLOYERS = [")
    # Разбиваем на строки по 10 штук для читаемости
    chunk_size = 10
    for i in range(0, len(result_list), chunk_size):
        chunk = result_list[i:i + chunk_size]
        formatted_chunk = ", ".join([f'"{eid}"' for eid in chunk])
        print(f"    {formatted_chunk},")
    print("]")

if __name__ == "__main__":
    main()