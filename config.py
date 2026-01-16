import os
from dotenv import load_dotenv

load_dotenv()

# --- ТОКЕНЫ HR ---
TG_TOKEN = os.getenv("TG_TOKEN_HR")
TG_CHAT_ID = os.getenv("TG_CHAT_ID_HR")

# --- НАСТРОЙКИ ---
USER_AGENT = 'JobSonarBot/5.8 (HR)'
DB_NAME = "jobsonar_hr.db"

CHECK_INTERVAL = 600
MIN_SALARY = 200000 
TARGET_AREAS = ["1", "66"] # Москва, Екб
SEARCH_PERIOD = 14 # Для Whitelist

PROFILES = {
    'HR': {
        'keywords': [
            # ТОПЫ
            'HR Director', 'Директор по персоналу', 'HRD', 'Head of HR', 
            'HRBP', 'HR Business Partner', 'People Partner', 
            'Руководитель отдела персонала', 'Начальник управления персоналом',
            'Head of Recruitment', 'Руководитель подбора', 'Head of Talent',
            
            # НОВЫЕ РОЛИ (из пропусков)
            'HR Generalist', 'HRG', 'Generalist',
            'HR Lead', 'Лидер HR', 'Team Lead HR',
            'Ведущий менеджер по персоналу', 'Ведущий HR',
            
            # УЗКИЕ СПЕЦИАЛИЗАЦИИ (Руководящие)
            'C&B', 'T&D', 'HR Brand', 'DevRel'
        ],
        
        'must_have_hr': [
            'hr', 'персонал', 'кадр', 'люд', 'человеч', 'талант', 'наем', 'найм', 
            'подбор', 'рекрут', 'обучен', 'развити', 'компенсац', 'льгот', 
            'оплат', 'труд', 'бренд', 'культур', 'отношен', 'социальн',
            'people', 'talent', 'human', 'recruit', 'learning', 'c&b', 'rewards',
            'generalist', 'gener', 'дженералист'
        ],

        'must_have_role': [
            'hrd', 'hrbp', 'директор', 'director', 'head', 'lead', 'partner', 'партнер', 
            'руководител', 'начальник', 'заместител', 'глава', 'лидер', 'chief',
            'generalist', 'hrg', 'ведущий', 'senior' # Добавили Generalist и Ведущий
        ],

        'stop_words': [
            'казахстан', 'kazakhstan', 'алматы', 'астана', 'ташкент', 'минск',
            'инженер', 'разработчик', 'developer', 'аналитик', 'it-проект', 
            'безопасн', 'hardware', 'embedded', 'телефония', 'вкс', 'тестиров',
            'брокерск', 'залогов', 'ипотека', 'авто', 'кредит', 'оператор',
            'call', 'колл', 'продаж', 'sales', 'assistant', 'ассистент',
            'стажер', 'intern', 'junior', 'джуниор', 'секретарь', 'делопроизвод',
            'курьер', 'водитель', 'уборщ', 'администратор', 'офис-менеджер'
        ]
    }
}