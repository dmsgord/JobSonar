import os
from dotenv import load_dotenv

load_dotenv()

# --- ТОКЕНЫ HR ---
TG_TOKEN = os.getenv("TG_TOKEN_HR")
TG_CHAT_ID = os.getenv("TG_CHAT_ID_HR")

# --- НАСТРОЙКИ ---
USER_AGENT = 'JobSonarBot/4.8 (HR)'
DB_NAME = "jobsonar_hr.db" # Своя база

CHECK_INTERVAL = 600
MIN_SALARY = 200000 
TARGET_AREAS = ["1", "66"] # Москва, Екб
SEARCH_PERIOD = 14 # Для Whitelist

PROFILES = {
    'HR': {
        'keywords': [
            'HR Director', 'Директор по персоналу', 'HRD', 'Head of HR', 
            'HRBP', 'HR Business Partner', 'People Partner', 
            'Руководитель отдела персонала', 'Начальник управления персоналом',
            'Head of Recruitment', 'Руководитель подбора', 'C&B', 'T&D', 'HR Brand'
        ],
        
        'must_have_hr': [
            'hr', 'персонал', 'кадр', 'люд', 'человеч', 'талант', 'наем', 'найм', 
            'подбор', 'рекрут', 'обучен', 'развити', 'компенсац', 'льгот', 
            'оплат', 'труд', 'бренд', 'культур', 'отношен', 'социальн',
            'people', 'talent', 'human', 'recruit', 'learning', 'c&b', 'rewards'
        ],

        'must_have_role': [
            'hrd', 'hrbp', 'директор', 'director', 'head', 'lead', 'partner', 'партнер', 
            'руководител', 'начальник', 'заместител', 'глава', 'лидер', 'chief'
        ],

        'stop_words': [
            'казахстан', 'kazakhstan', 'алматы', 'астана', 'ташкент', 'минск',
            'инженер', 'разработчик', 'developer', 'аналитик', 'it-проект', 
            'безопасн', 'hardware', 'embedded', 'телефония', 'вкс', 'тестиров',
            'брокерск', 'залогов', 'ипотека', 'авто', 'кредит', 'операц', 'процессов',
            'финанс', 'мониторинг', 'методолог', 'вэд', 'мсфо', 'бухгалтер',
            'имуществен', 'наследия', 'билетов', 'пользовательского опыта',
            'продаж', 'sales', 'клиент', 'маркетинг', 'smm', 'контент', 'геймификац',
            'ахо', 'ремонт', 'монтаж', 'стройк', 'склад', 'младший', 'junior', 
            'ассистент', 'стажер', 'intern', 'менеджер', 'specialist'
        ]
    }
}