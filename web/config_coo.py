import os
from dotenv import load_dotenv

load_dotenv()

# Тот же чат что и HR бот
TG_TOKEN = os.getenv("TG_TOKEN_HR")
TG_CHAT_ID = os.getenv("TG_CHAT_ID_HR")

COO_PROFILES = {
    'COO': {
        'name': 'COO',
        'min_salary': 250000,
        'global_min_salary': 250000,

        'keywords': [
            'Операционный директор',
            'COO',
            'Chief Operating Officer',
            'Operations Director',
            'Director of Operations',
            'Head of Operations',
            'VP Operations',
            'Исполнительный директор',
            'Executive Director',
            'Managing Director',
            'Управляющий директор',
            'General Manager',
            'Директор по операциям',
            'Chief of Staff',
            'Операционный менеджер',
        ],

        'direct_titles': [
            'Операционный директор',
            'Операционный менеджер',
            'COO',
            'Chief Operating Officer',
            'Operations Director',
            'Director of Operations',
            'Head of Operations',
            'VP Operations',
            'VP of Operations',
            'Исполнительный директор',
            'Executive Director',
            'Managing Director',
            'Управляющий директор',
            'General Manager',
            'Директор по операциям',
            'Operations Manager',
            'Chief of Staff',
            'Операционный вице-президент',
        ],

        # Уровень — для combo-матча с role_context
        'role_levels': [
            'директор', 'director', 'head', 'chief', 'руководитель',
            'вице', 'vp', 'president', 'президент', 'managing',
            'менеджер', 'manager', 'управляющий',
        ],

        # Контекст — вторая половина combo
        'role_context': [
            'операци', 'операционн', 'operations', 'operation',
            'исполни', 'executive', 'execution',
            'general',
            'бизнес-процесс', 'business process',
        ],

        'stop_words': [
            # ⛔ ДРУГИЕ ДИРЕКТОРСКИЕ РОЛИ
            'финансов', 'cfo', 'chief financial',
            'технич', 'cto', 'chief technology', 'chief technical',
            'коммерч', 'chief commercial',
            'маркетинг', 'marketing', 'cmo',
            'digital', 'цифров',
            'hr', 'cpo', 'chief people',
            'юридич', 'legal', 'compliance',
            'безопасност', 'security', 'cso',
            'продукт', 'product',
            'it директор', 'it-директор',

            # ⛔ УРОВЕНЬ / МУСОР
            'стажер', 'intern', 'junior', 'trainee',
            'ассистент', 'помощник', 'assistant',

            # ⛔ СФЕРЫ БЕЗ УДАЛЁНКИ
            'ресторан', 'кафе', 'кофейн', 'общепит', 'horeca',
            'отель', 'гостиниц', 'hotel', 'resort', 'курорт',
            'фитнес', 'клиника', 'медицин', 'стоматолог',
            'розниц', 'retail', 'магазин', 'торговый центр',
            'фастфуд', 'fast food', 'столовая',

            # ⛔ ЛОГИСТИКА И ТРАНСПОРТ
            'логистик', 'логист', 'транспорт', 'перевозк', 'автосервис',
            'снабжен', 'склад', 'доставк', 'fleet', 'supply chain',

            # ⛔ СТРОИТЕЛЬСТВО И ПРОИЗВОДСТВО
            'строительств', 'construction', 'производств', 'завод',

            # ⛔ КЛИНИНГ
            'клининг', 'уборк', 'кондитерск',

            # ⛔ ТЕХНИЧЕСКИЙ МУСОР
            'devops', 'разработчик', 'developer',
            'оператор', 'колл-центр', 'call-center',

            # ⛔ ПРОДАЖИ
            'продаж', 'sales',
        ]
    }
}
