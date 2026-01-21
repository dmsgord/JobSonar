import os
from dotenv import load_dotenv

load_dotenv()

# --- ТОКЕНЫ (Analyst) ---
# ✅ СТРОГО КАК У ТЕБЯ В .ENV
TG_TOKEN = os.getenv("TG_TOKEN_TECH")
TG_CHAT_ID = os.getenv("TG_CHAT_ID_TECH")

# --- НАСТРОЙКИ ---
USER_AGENT = 'JobSonarBot/4.28 (Analyst)'
DB_NAME = "jobsonar_analyst.db"

CHECK_INTERVAL = 600
MIN_SALARY = 200000 
TARGET_AREAS = ["1", "66"] 
SEARCH_PERIOD = 14 

BLACKLISTED_AREAS = ['40', '160', '159', '97', '48'] 

PROFILES = {
    'Analyst': {
        'keywords': [
            # Вариации написания
            'Business Analyst', 'Бизнес-аналитик', 'Бизнес аналитик',
            'Data Analyst', 'Дата аналитик', 'Аналитик данных',
            'Product Analyst', 'Продуктовый аналитик',
            'BI Analyst', 'BI-аналитик',
            'Руководитель отдела аналитики', 'Lead Analyst',
            'Аналитик процессов'
        ],
        
        'target_skills': [
            'sql', 'mysql', 'postgresql', 'clickhouse', 
            'airflow', 'etl', 'dwh', 
            'python', 'pandas', 'kafka', 'кафка', 'rabbit',
            'metabase', 'datalens', 'superset', 
            'finebi', 'fine bi', 'файн биай',
            'figma', 'фигма',
            'jira', 'джира', 'confluence', 'конфлюенс', 'atlassian',
            'planfix', 'планфикс',
            'bpmn', 'управление процессами', 'оптимизация процессов', 'моделирование',
            'api', 'rest', 'json', 'xml', 'soap', 'uml'
        ],

        'stop_words': [
            # 🚫 РОЛИ
            'system analyst', 'системный аналитик', 'системный',
            'developer', 'разработчик', 'dev', 'programmer', 'программист',
            'tester', 'тестировщик', 'qa', 'testing', 'test', 'тестирование',
            'engineer', 'инженер', 'engineering',
            'architect', 'архитектор',
            'administrator', 'администратор', 'admin',
            
            # 🚫 ГЕО
            'казахстан', 'kazakhstan', 'алматы', 'астана',
            
            # 🚫 УРОВЕНЬ / МУСОР
            'junior', 'младший', 'стажер', 'intern', 'assistant', 'ассистент',
            'support', 'поддержка', 'оператор', 'продаж', 'sales', 'call-center',
            'secretary', 'секретарь', 'начальный уровень', 'без опыта',
            '1с', 'консультант', 'методолог', 'sap'
        ]
    }
}