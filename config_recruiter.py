import os
from dotenv import load_dotenv

load_dotenv()

# --- ТОКЕНЫ ---
TG_TOKEN = os.getenv("TG_TOKEN_RECRUITER")
TG_CHAT_ID = os.getenv("TG_CHAT_ID_RECRUITER")

# --- НАСТРОЙКИ ---
USER_AGENT = 'JobSonarBot/1.0 (Recruiter)'
DB_NAME = "jobsonar_recruiter.db"

CHECK_INTERVAL = 600
MIN_SALARY = 100000  # Строго от 100к (или скрытая)
SEARCH_PERIOD = 3     # Ищем свежее

PROFILES = {
    'Recruiter': {
        'keywords': [
            'IT Recruiter', 'IT Рекрутер', 'IT-рекрутер',
            'Recruiter', 'Рекрутер',
            'Sourcer', 'Сорсер',
            'Talent Acquisition', 'Talent Manager',
            'Менеджер по подбору', 'Специалист по подбору',
            'Talent Scout', 'Researcher'
        ],

        # Стоп-слова В ЗАГОЛОВКЕ (чтобы отсечь начальников и кадровиков)
        'stop_words_title': [
            # Начальство
            'director', 'директор', 'head', 'lead', 'лидер', 'руководитель', 
            'chief', 'начальник', 'senior', 'ведущий', # Обычно "ведущий" это уже не линейный, но можно оставить если зп пролезает. Давай уберем Senior/Ведущий из стоп, вдруг жирная вакансия.
            # Хотя ты просил "Исполнителя", но Senior Recruiter - это исполнитель. Оставим Senior.
            # Уберем только управленцев:
            'team lead', 'тимлид', 'group head', 'заместитель',
            
            # Не те роли
            'generalist', 'дженералист', 'hrg',
            'hrbp', 'partner', 'партнер',
            'admin', 'админ', 'assistant', 'ассистент', 'стажер', 'intern',
            'happiness', 'brand', 'бренд', 'marhr', 'devrel',
            'c&b', 't&d', 'l&d', 'train', 'обучени', 'методолог',
            'culture', 'культур', 'event', 'ивент', 'office', 'офис',
            'account', 'sales', 'продаж',
            
            # Кадровики / Бумажки
            'кдп', 'кадр', 'делопроизвод', 'инспектор', 'табель', 'охрана труда', 'военн'
        ],

        # Фильтр сфер (как в Sales)
        'digital_markers': [], # Не используем, ищем всех рекрутеров
        
        'stop_domains': [
            'casino', 'казино', 'bet', 'ставк', 'gambling', 'poker', 'crypto', 'крипт',
            'webcam', 'вебкам', 'model', 'dating', 'знакомств', 'escort',
            'форекс', 'forex', 'trader', 'trading', 'invest', 'инвест', 'пирамид',
            'залог', 'банкрот', 'коллектор', 'займ', 'микрофинанс', 'мфо',
            'call', 'колл', 'оператор'
        ]
    }
}