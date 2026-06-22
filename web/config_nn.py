# -*- coding: utf-8 -*-
# Совмещённый бот: HR-руководитель + Аналитик, ТОЛЬКО Нижний Новгород / Дзержинск.
# Без фильтра по формату работы, без порога зарплаты, без whitelist-проверки.
import os
from dotenv import load_dotenv

# Переиспользуем уже готовые профили существующих ботов,
# чтобы ключевые слова/стоп-слова держались в одном месте.
from config import PROFILES as HR_PROFILES
from config_analyst import PROFILES as ANALYST_PROFILES

load_dotenv()

# --- ТОКЕНЫ (отдельный бот, отдельный чат) ---
TG_TOKEN = os.getenv("TG_TOKEN_NN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID_NN")

# --- НАСТРОЙКИ ---
USER_AGENT = 'JobSonarBot/1.0 (NN-Combined)'
DB_NAME = "jobsonar_nn.db"

# 📍 Только Нижний Новгород (66) и Дзержинск, Нижегородская обл. (247)
TARGET_AREAS = ["66", "247"]
AREA_NAME_MARKERS = ["нижний новгород", "нижегородск", "дзержинск"]

# Свежак: насколько глубоко в днях смотреть
SEARCH_PERIOD = 3

# HR-руководитель + Аналитик в одном боте.
# skip_no_experience оставляем у HR (руководящих позиций без опыта не бывает).
PROFILES = {
    'HR': {**HR_PROFILES['HR'], 'skip_no_experience': True},
    'Analyst': ANALYST_PROFILES['Analyst'],
}
