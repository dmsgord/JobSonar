import os
from dotenv import load_dotenv

load_dotenv()

TG_TOKEN = os.getenv("TG_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

CHECK_INTERVAL = 600
MIN_SALARY = 200000 
TARGET_AREAS = ["1", "66"]
SEARCH_PERIOD = 14 

PROFILES = {
    'HR': {
        'keywords': [
            'HR Director', 'Директор по персоналу', 'HRD', 'Head of HR', 
            'HRBP', 'HR Business Partner', 'People Partner', 
            'Руководитель отдела персонала', 'Начальник управления персоналом',
            'Head of Recruitment', 'Руководитель подбора',
            'C&B', 'Comp&Ben', 'T&D', 'DevRel', 'HR Brand'
        ],
        
        # КЛЮЧ 1: Объект (HR-тематика)
        'must_have_hr': [
            'hr', 'персонал', 'кадр', 'люд', 'человеч', 'талант', 'наем', 'найм', 
            'подбор', 'рекрут', 'обучен', 'развити', 'компенсац', 'льгот', 
            'оплат', 'труд', 'бренд', 'культур', 'отношен', 'социальн',
            'people', 'talent', 'human', 'recruit', 'learning', 'c&b', 'rewards'
        ],

        # КЛЮЧ 2: Статус (Уровень)
        'must_have_role': [
            'hrd', 'hrbp', 'директор', 'director', 'head', 'lead', 'partner', 'партнер', 
            'руководител', 'начальник', 'заместител', 'глава', 'лидер', 'chief'
        ],

        # ЖЕСТКИЙ БАН (мусорные темы)
        'stop_words': [
            'инженер', 'разработчик', 'developer', 'аналитик', 'it-проект', 
            'безопасн', 'hardware', 'продаж', 'sales', 'клиент', 'юрид', 'физич', 'вэд',
            'бухгалтер', 'мсфо', 'ахо', 'ремонт', 'монтаж', 'стройк', 'склад', 
            'младший', 'junior', 'ассистент', 'стажер', 'intern', 'менеджер', 
            'specialist', 'маркетинг', 'smm', 'контент', 'геймификац', 'обслуживан', 
            'продукта', 'product', 'мониторинг', 'методолог', 'имуществен', 'наследия'
        ]
    }
}