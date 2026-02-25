import os
import sys
import asyncio
import requests
from datetime import datetime, timezone
from supabase import create_client, Client
from groq import Groq
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError
from tavily import TavilyClient

# ────────────────────────────────────────────────
# ENVIRONMENT VARIABLES
# ────────────────────────────────────────────────
GROQ_API_KEY                = os.getenv("GROQ_API_KEY")
TELEGRAM_BOT_TOKEN          = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID            = os.getenv("TELEGRAM_CHAT_ID")
TELEGRAM_ADMIN_ID           = os.getenv("TELEGRAM_ADMIN_ID")
TELEGRAM_FOUNDER_ID         = os.getenv("TELEGRAM_FOUNDER_ID")
SUPABASE_URL                = os.getenv("SUPABASE_URL")
SUPABASE_KEY                = os.getenv("SUPABASE_KEY")
UNSPLASH_ACCESS_KEY         = os.getenv("UNSPLASH_ACCESS_KEY")
TAVILY_API_KEY              = os.getenv("TAVILY_API_KEY")
POST_TYPE                   = os.getenv("POST_TYPE", "news")

NEWS_THREAD_ID      = os.getenv("TELEGRAM_NEWS_THREAD_ID")
EDUCATION_THREAD_ID = os.getenv("TELEGRAM_EDUCATION_THREAD_ID")

if not all([GROQ_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, SUPABASE_URL, SUPABASE_KEY]):
    print("Missing required environment variables.")
    sys.exit(1)

if not TAVILY_API_KEY:
    print("Warning: TAVILY_API_KEY not set. News search will fail.")

# ────────────────────────────────────────────────
# INITIALIZATION
# ────────────────────────────────────────────────
groq_client  = Groq(api_key=GROQ_API_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
bot          = Bot(token=TELEGRAM_BOT_TOKEN)
# bot используется и для публикации и для сообщений на одобрение с кнопками
tavily       = TavilyClient(api_key=TAVILY_API_KEY) if TAVILY_API_KEY else None

# ────────────────────────────────────────────────
# INLINE KEYBOARD BUILDER
# ────────────────────────────────────────────────
def make_approval_keyboard(pending_id: str) -> InlineKeyboardMarkup:
    """Кнопки Одобрить / Отклонить под сообщением на одобрение."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Одобрить",  callback_data=f"approve:{pending_id}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_menu:{pending_id}"),
        ]
    ])

# ────────────────────────────────────────────────
# GROQ LLM WRAPPER
# ────────────────────────────────────────────────
def gemini_generate(prompt: str) -> str:
    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1024,
        temperature=0.7,
    )
    return response.choices[0].message.content.strip()

# ────────────────────────────────────────────────
# NOTIFY RECIPIENTS
# ────────────────────────────────────────────────
async def notify_recipients(message: str):
    """Обычное текстовое уведомление (для ошибок, статусов и т.д.)"""
    await bot.send_message(TELEGRAM_ADMIN_ID, message)
    if TELEGRAM_FOUNDER_ID and TELEGRAM_FOUNDER_ID != TELEGRAM_ADMIN_ID:
        try:
            await bot.send_message(TELEGRAM_FOUNDER_ID, message)
        except Exception as e:
            print(f"Failed to notify founder: {e}")


async def notify_approval(pending_id: str, preview_text: str):
    """
    Отправляет пост на одобрение с inline-кнопками.
    Кнопки обрабатывает feedback_bot.py (Render) — он слушает тот же TELEGRAM_BOT_TOKEN.
    """
    keyboard = make_approval_keyboard(pending_id)

    await bot.send_message(
        chat_id=TELEGRAM_ADMIN_ID,
        text=preview_text,
        reply_markup=keyboard,
    )
    if TELEGRAM_FOUNDER_ID and TELEGRAM_FOUNDER_ID != TELEGRAM_ADMIN_ID:
        try:
            await bot.send_message(
                chat_id=TELEGRAM_FOUNDER_ID,
                text=preview_text,
                reply_markup=keyboard,
            )
        except Exception as e:
            print(f"Failed to notify founder: {e}")

# ────────────────────────────────────────────────
# SEARCH QUERIES BY REGION
# ────────────────────────────────────────────────
def _build_search_queries() -> list:
    """
    Динамически генерирует поисковые запросы с актуальными датами.
    Автоматически обновляется каждый месяц — не нужно менять код вручную.
    """
    now    = datetime.utcnow()
    month_ru = {
        1: "январь", 2: "февраль", 3: "март", 4: "апрель",
        5: "май", 6: "июнь", 7: "июль", 8: "август",
        9: "сентябрь", 10: "октябрь", 11: "ноябрь", 12: "декабрь",
    }
    month_en = {
        1: "January", 2: "February", 3: "March", 4: "April",
        5: "May", 6: "June", 7: "July", 8: "August",
        9: "September", 10: "October", 11: "November", 12: "December",
    }
    m_ru = month_ru[now.month]
    m_en = month_en[now.month]
    y    = now.year

    return [
        {"query": f"Казахстан стартап инвестиции раунд {m_ru} {y}",         "region": "Kazakhstan",  "priority": 0},
        {"query": f"Kazakhstan startup funding round raised {m_en} {y}",    "region": "Kazakhstan",  "priority": 0},
        {"query": f"Kazakhstan venture capital deal announcement {y}",       "region": "Kazakhstan",  "priority": 0},
        {"query": f"Узбекистан Кыргызстан стартап инвестиции раунд {y}",    "region": "CentralAsia", "priority": 1},
        {"query": f"Central Asia startup investment round raised {y}",       "region": "CentralAsia", "priority": 1},
        {"query": f"Центральная Азия венчур фонд сделка {m_ru} {y}",        "region": "CentralAsia", "priority": 1},
        {"query": f"startup raised million Series A B funding {m_en} {y}",  "region": "World",       "priority": 2},
        {"query": f"venture capital deal announced this week {m_en} {y}",   "region": "World",       "priority": 2},
        {"query": f"AI startup funding round announced {m_en} {y}",         "region": "World",       "priority": 2},
    ]

def _build_seed_queries() -> list:
    now  = datetime.utcnow()
    m_en = {1:"January",2:"February",3:"March",4:"April",5:"May",6:"June",
            7:"July",8:"August",9:"September",10:"October",11:"November",12:"December"}[now.month]
    y    = now.year
    return [
        {"query": f"pre-seed startup funding Central Asia {y}",             "region": "CentralAsia", "priority": 0},
        {"query": f"seed round startup Kazakhstan Uzbekistan {y}",          "region": "CentralAsia", "priority": 0},
        {"query": f"pre-seed seed startup funding round {m_en} {y}",       "region": "World",       "priority": 1},
    ]

# Built at runtime so dates are always current
SEARCH_QUERIES = _build_search_queries()
SEED_QUERIES   = _build_seed_queries()

REGION_HEADER = {
    "Kazakhstan":  "Казахстан",
    "CentralAsia": "Центральная Азия",
    "World":       "Мир",
}

# ────────────────────────────────────────────────
# ACTIVAT VC LESSONS
# ────────────────────────────────────────────────
ACTIVAT_LESSONS = [
    {
        "title": "Что такое инвестиции и их параметры",
        "url": "https://activat.vc/startup-course/lesson/kakoi-put-prohodyat-startapy",
        "youtube_url": "https://youtu.be/RLWjDv7Hto4",
        "transcript": """Инвестиции — вложение средств в активы с целью сохранения и приумножения капитала. Три основных параметра: доходность, надёжность и ликвидность. Доходность = сумма дохода за год / сумма вложения × 100%. Депозит даёт ~12% годовых, но курс валюты влияет: при падении тенге доходность может вырасти до 22%, при росте — упасть до 2%. Недвижимость: аренда 12% + рост стоимости 10% = 22% годовых, при падении цен — всего 2%. Бизнес: первые выплаты — это возврат вложений, а не прибыль; за 3 года доходность составит лишь 2.7% годовых. Надёжность: депозит ~100%, недвижимость ~70%, бизнес ~0%. Ликвидность = 1 / количество дней на продажу: деньги — 100%, депозит — 33% (3 дня), квартира — 1% (3 месяца), антиквариат — 0.27%."""
    },
    {
        "title": "Что такое стартап",
        "url": "https://activat.vc/startup-course/lesson/kakoi-put-prohodyat-startapy",
        "youtube_url": "https://youtu.be/_FhExnc4bgA",
        "transcript": """Стартап — это даже не компания, а проект одного или нескольких человек, которые ищут идею. Признаки стартапа: 1) Юность — компания работает менее 3-5 лет по одной бизнес-модели. 2) Новизна идеи — не расширение существующего бизнеса, а принципиально новый подход. Пример: основатели Uber не открыли ещё один таксопарк, а придумали приложение без таксопарков — выбор маршрута, оплата, оценки. 3) Масштабируемость — способность расти многократно в короткий срок; традиционный бизнес даёт максимум 30-40% прибыли в год. 4) Технологичность — IT-продукт (программа, сайт, приложение), один программист может создать продукт без заводов и оборудования. 5) Большой рынок — возможность расширяться на огромные территории."""
    },
    {
        "title": "Инвестиционный портфель инвестора",
        "url": "https://activat.vc/startup-course/lesson/kakoi-put-prohodyat-startapy",
        "youtube_url": "https://youtu.be/mLKvHpnoGcg",
        "transcript": """Инвестиционный портфель со средним аппетитом к риску: 20% — депозиты (баланс тенге и валюты снижает валютный риск), 30% — недвижимость (Алматы и Астана для аренды, часть в Дубае или Турции для снижения политических рисков), 20% — фондовый рынок (гособлигации США — надёжно, акции S&P 500 — доходнее). Такое распределение балансирует сохранение капитала и доходность через диверсификацию по инструментам и географии."""
    },
    {
        "title": "Что такое венчурные инвестиции",
        "url": "https://activat.vc/startup-course/lesson/kakoi-put-prohodyat-startapy",
        "youtube_url": "https://youtu.be/-850n7Yu8aA",
        "transcript": """Venture — «рискованный» по-английски. Венчурные инвестиции — рискованные вложения в стартапы. Стартапы имеют высокую смертность, поэтому на венчур рекомендуется выделять не более 5-10% портфеля. Главный плюс: один успешный стартап может окупить вложения в остальные 10, давая инвесторам иксы — кратное увеличение стоимости. Этого не может дать традиционный бизнес. Пример: Uber придумал приложение без таксопарков вместо того, чтобы открыть ещё один таксопарк."""
    },
    {
        "title": "Путь венчурного инвестора: от частника до бизнес-ангела",
        "url": "https://activat.vc/startup-course/lesson/kakoi-put-prohodyat-startapy",
        "youtube_url": "https://youtu.be/ZPTmrEZSunA",
        "transcript": """Путь венчурного инвестора: 1) Начинающий частный инвестор — есть деньги, нет опыта, стартапы находит случайно (соцсети, мероприятия), инвестирует только деньгами. 2) Пассивный инвестор в синдикате — присоединяется к фондам или клубам, учится у опытных. 3) Бизнес-ангел — появляется опыт и «насмотренность», видит типичные ошибки стартапов, может давать советы и быть ментором. Даёт «умные деньги»: деньги + знания + опыт + связи. Особенно ценен, если ранее работал в корпорации или был предпринимателем."""
    },
    {
        "title": "Супер-ангел и инвестиционная компания",
        "url": "https://activat.vc/startup-course/lesson/kakoi-put-prohodyat-startapy",
        "youtube_url": "https://youtu.be/yVvhxXF8htI",
        "transcript": """Бизнес-ангел может пойти двумя путями. 1) Стать супер-ангелом — работать индивидуально, но оперировать всё большими суммами, принимая решения единолично на основе опыта и интуиции. 2) Создать инвестиционную компанию — нанять экспертов в маркетинге, юриспруденции, финансах; выстроить инвестиционный комитет и воронку продаж. В компании решения принимаются коллегиально — это повышает качество. Компания привлекает деньги других инвесторов и обрастает сообществом."""
    },
    {
        "title": "Где искать стартапы и как инвестировать: одному или в группе",
        "url": "https://activat.vc/startup-course/lesson/kakoi-put-prohodyat-startapy",
        "youtube_url": "https://youtu.be/suP2UjGu-H0",
        "transcript": """Каналы поиска стартапов: 1) Google, 2) соцсети (LinkedIn, Facebook — стартаперы публикуют прогресс), 3) Demo Day акселераторов и инкубаторов, 4) нетворкинг. Инвестировать можно самостоятельно (свобода, но сложный поиск, ограниченный бюджет, нужны знания маркетинга и продукта) или в составе клуба/компании (готовая воронка стартапов с CRM, коллективная экспертиза, возможность начинать с малых чеков, профессиональный мониторинг после инвестирования)."""
    },
    {
        "title": "Что обсудить с основателем перед инвестированием",
        "url": "https://activat.vc/startup-course/lesson/kakoi-put-prohodyat-startapy",
        "youtube_url": "https://youtu.be/foP0b8FUM80",
        "transcript": """Перед инвестированием обязательно обсудите: 1) Сумма — зафиксировать в конкретной валюте. 2) Сроки — когда именно переводятся деньги (конфликты из-за этого очень часты). 3) Условия поэтапных выплат — привязать транши к KPI (охват, выручка, клиенты). 4) Доля инвестора = сумма инвестиций / оценка стоимости компании; оценка — главный источник споров, для этого используют SAFE и конвертируемые займы. 5) Степень участия в управлении — войти в совет директоров или остаться пассивным инвестором."""
    },
    {
        "title": "Виды и формы инвестиций",
        "url": "https://activat.vc/startup-course/lesson/kakoi-put-prohodyat-startapy",
        "youtube_url": "https://youtu.be/F84ihxh9wiA",
        "transcript": """Виды инвестиций по срокам: краткосрочные (до 1 года), среднесрочные (1-3 года), долгосрочные (от 3 лет). По формам: 1) Прямые — вход в долю компании (Cash-in: деньги в компанию; Cash-out: деньги продавцу). 2) Венчурные — на ранних стадиях (pre-seed), самые рискованные. 3) Частные — физлицо или группа покупает долю/акции. 4) Инвестиционные фонды — профессиональное управление. 5) Корпоративные — крупные компании покупают стартапы для роста или новых рынков. 6) Краудфандинг — лендинговый (займ без доли) или инвестиционный (с долей)."""
    },
    {
        "title": "Способы инвестирования в бизнес",
        "url": "https://activat.vc/startup-course/lesson/kakoi-put-prohodyat-startapy",
        "youtube_url": "https://youtu.be/4RAFsA3Jm3E",
        "transcript": """Способы инвестирования: 1) Прямые инвестиции — покупка доли (Cash-in или Cash-out). 2) Договор простого товарищества — объединение вкладов без создания юрлица; прибыль делится по договору, инвестор не влияет на решения. 3) Венчурные фонды — привлекают средства нескольких инвесторов. 4) Инвестиционные фонды — профессиональное управление. 5) Краудфандинг — минимальный чек устанавливает площадка. 6) Ангельское инвестирование — чеки до $50 000. 7) Корпоративное — крупная компания выкупает стартап для присоединения к своему бизнесу."""
    },
    {
        "title": "Процесс инвестирования в стартап",
        "url": "https://activat.vc/startup-course/lesson/kakoi-put-prohodyat-startapy",
        "youtube_url": "https://youtu.be/12JaOwIvygg",
        "transcript": """Процесс инвестирования: 1) Определить цели — срок, ожидаемая доходность. 2) Найти стартапы. 3) Due Diligence — комплексная проверка: экономическая, юридическая, маркетинговая, анализ рынка. Качество DD определяет успех инвестиции. 4) Переговоры с основателями — условия фиксируются в term sheet и инвестиционных соглашениях. 5) Передача средств. 6) Мониторинг — отслеживание расходования средств, отчётность, меры при отклонениях от плана."""
    },
    {
        "title": "Условия выхода инвестора из стартапа",
        "url": "https://activat.vc/startup-course/lesson/kakoi-put-prohodyat-startapy",
        "youtube_url": "https://youtu.be/oSCxm08Nu7U",
        "transcript": """Выход — важнейший вопрос, который нужно обсудить «на берегу». Сценарии: 1) Следующий раунд — новый инвестор выкупает акции у предыдущих; стоимость вырастает, инвестор получает иксы. 2) Поглощение крупной компанией — вся компания переходит новому владельцу. Риск: корпорация может купить только 51% у фаундера, а первый инвестор остаётся «никем». 3) Опцион — стартап сам выкупает долю у инвестора. 4) Продажа доли стороннему инвестору между раундами — важно приоритетное право покупки действующих акционеров (закреплено законом в Казахстане). 5) Банкротство — инвестор стоит последним в очереди. Все сценарии нужно прописать заранее."""
    },
]

GLOBAL_EDUCATION_TOPICS = [
    "Как работает венчурный капитал: объяснение для фаундеров",
    "Разница между pre-seed, seed и Series A раундами",
    "Как считать runway и burn rate стартапа",
    "Vesting и cliff: опционная программа для команды",
    "Bootstrapping vs венчурное финансирование",
    "Как работают акселераторы и чем отличаются от инкубаторов",
    "Что такое convertible note и SAFE",
    "Как венчурные фонды зарабатывают (модель 2-20)",
    "CAC и LTV: юнит-экономика для инвесторов",
    "Как подготовиться к питчу перед венчурным инвестором",
]

# ────────────────────────────────────────────────
# FEEDBACK INTENT PARSER
#
# Разделяет фидбэк на два типа:
#   - PROHIBITIONS: что запрещено публиковать (блокирует статьи)
#   - PRIORITIES: что нужно публиковать чаще (буст приоритета кандидатов)
#
# Логика определения:
#   Пожелание = содержит "больше", "чаще", "приоритет", "важнее", "хочу", "нужно больше", "желательно"
#   Запрет = содержит "не нужно", "не публикуй", "без", "убери", "исключи", "не хочу"
#   Остальное = считается запретом (безопаснее)
# ────────────────────────────────────────────────

# Слова-маркеры для определения типа фидбэка
PRIORITY_MARKERS = [
    "больше", "чаще", "приоритет", "важнее", "хочу видеть", "нужно больше",
    "желательно", "предпочтительно", "фокус на", "акцент на", "давай больше",
    "more", "focus on", "prioritize", "prefer",
]

PROHIBITION_MARKERS = [
    "не нужно", "не публикуй", "без", "убери", "исключи", "не хочу",
    "не надо", "избегай", "пропускай", "don't", "no ", "avoid", "skip",
    "не про", "не о ", "не об ",
]

# Маппинг ключевых слов фидбэка → регион.
# Используем корни слов (без окончаний) чтобы ловить все падежи русского языка:
#   "центральная азия" / "центральной азии" / "центральную азию" → все поймаем по "центральн"+"азии|азия|азию"
# Ключи — подстроки которые ищем в тексте (достаточно одного совпадения)
REGION_BOOST_MAP = {
    # Центральная Азия — все падежные формы через корни
    "центральн":    "CentralAsia",   # центральная/центральной/центральную азия/азии/азию
    "central asia": "CentralAsia",
    "centralasia":  "CentralAsia",
    # Казахстан — все падежи
    "казахстан":    "Kazakhstan",    # казахстан/казахстана/казахстане/казахстану
    "kazakhstan":   "Kazakhstan",
    # Остальные страны ЦА
    "узбекистан":   "CentralAsia",
    "кыргызстан":   "CentralAsia",
    "таджикистан":  "CentralAsia",
    "туркменистан": "CentralAsia",
    "ца ":          "CentralAsia",   # аббревиатура "ЦА"
    " ца":          "CentralAsia",
}

STAGE_BOOST_KEYWORDS = [
    "pre-seed", "preseed", "pre seed", "seed", "ранняя стадия",
    "early stage", "early-stage", "ангельск", "angel",
]


def parse_feedback_intents(constraints: list) -> dict:
    """
    Разбирает список фидбэков на:
      - prohibitions: список строк для блокировки статей (как раньше)
      - region_boosts: список регионов которые надо поднять в приоритете
      - stage_boost: True если нужно искать pre-seed/seed статьи
      - priority_instructions: список строк для промпта ИИ (пожелания, не запреты)

    Логирует результат в консоль чтобы было видно в GitHub Actions.
    """
    prohibitions = []
    region_boosts = []
    stage_boost = False
    priority_instructions = []

    for feedback in constraints:
        text = feedback.lower().strip()

        # Определяем тип фидбэка
        is_priority = any(marker in text for marker in PRIORITY_MARKERS)
        is_prohibition = any(marker in text for marker in PROHIBITION_MARKERS)

        if is_priority and not is_prohibition:
            # Это пожелание — определяем что именно буститовать
            priority_instructions.append(feedback)

            # Проверяем регион
            for keyword, region in REGION_BOOST_MAP.items():
                if keyword in text:
                    if region not in region_boosts:
                        region_boosts.append(region)

            # Проверяем стадию
            if any(kw in text for kw in STAGE_BOOST_KEYWORDS):
                stage_boost = True

        else:
            # Это запрет (или неопределённый фидбэк — считаем запретом)
            prohibitions.append(feedback)

    # Логируем результат
    print("=== FEEDBACK INTENT ANALYSIS ===")
    print(f"  Prohibitions ({len(prohibitions)}): {prohibitions[:5]}")
    print(f"  Region boosts: {region_boosts}")
    print(f"  Stage boost (pre-seed/seed): {stage_boost}")
    print(f"  Priority instructions ({len(priority_instructions)}): {priority_instructions[:3]}")
    print("=" * 40)

    return {
        "prohibitions":          prohibitions,
        "region_boosts":         region_boosts,
        "stage_boost":           stage_boost,
        "priority_instructions": priority_instructions,
    }


def apply_priority_boosts(candidates: list, intents: dict) -> list:
    """
    Корректирует числовой приоритет кандидатов на основе пожеланий фаундера.
    Меньший priority = выбирается раньше (как в сортировке).

    Логика бустов:
      - Регион в region_boosts → priority -= 2 (поднять выше)
      - Статья содержит pre-seed/seed при stage_boost → priority -= 1
      - World при наличии region_boosts → priority += 1 (опустить ниже)
    """
    if not intents["region_boosts"] and not intents["stage_boost"]:
        return candidates  # Нет пожеланий — ничего не меняем

    boosted = []
    for c in candidates:
        new_priority = c["priority"]

        # Регион буст
        if c["region"] in intents["region_boosts"]:
            new_priority -= 2
            print(f"Priority boost (region {c['region']}): {c['title'][:50]}")

        # Стадия буст (pre-seed, seed в заголовке или сниппете)
        if intents["stage_boost"]:
            content = (c["title"] + " " + c.get("snippet", "")).lower()
            if any(kw in content for kw in STAGE_BOOST_KEYWORDS):
                new_priority -= 1
                print(f"Priority boost (stage pre-seed/seed): {c['title'][:50]}")

        # Опускаем World если есть региональный буст
        if intents["region_boosts"] and c["region"] == "World":
            new_priority += 1

        boosted.append({**c, "priority": new_priority})

    return boosted


# ────────────────────────────────────────────────
# SUPABASE HELPERS
# ────────────────────────────────────────────────
def is_already_posted(key: str) -> bool:
    try:
        res = supabase.table("posted_news").select("id").eq("url_text", key).execute()
        return len(res.data) > 0
    except Exception as e:
        print(f"Supabase check error: {e}")
        return False

def is_already_pending(url: str) -> bool:
    if not url:
        return False
    try:
        res = supabase.table("pending_posts").select("id").eq("url", url).eq("status", "pending").execute()
        return len(res.data) > 0
    except Exception as e:
        print(f"Supabase pending check error: {e}")
        return False

def expire_old_pending_posts():
    try:
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        res = supabase.table("pending_posts") \
            .update({"status": "expired"}) \
            .eq("status", "pending") \
            .lt("created_at", cutoff) \
            .execute()
        count = len(res.data) if res.data else 0
        if count > 0:
            print(f"Expired {count} old pending posts (older than 2 days).")
        return count
    except Exception as e:
        print(f"Failed to expire old pending posts: {e}")
        return 0

def add_to_posted(key: str, news_type: str, score: int, source_type: str, title: str = ""):
    try:
        supabase.table("posted_news").insert({
            "url_text":           key,
            "news_type":          news_type,
            "shareability_score": score,
            "source_type":        source_type,
            "title":              title,
        }).execute()
    except Exception as e:
        try:
            supabase.table("posted_news").insert({
                "url_text":           key,
                "news_type":          news_type,
                "shareability_score": score,
                "source_type":        source_type,
            }).execute()
        except Exception as e2:
            print(f"Failed to save to posted_news: {e2}")

def get_posted_count() -> int:
    try:
        res = supabase.table("posted_news").select("count", count="exact").execute()
        return res.count or 0
    except:
        return 999

def get_education_count() -> int:
    try:
        res = supabase.table("posted_news").select("count", count="exact").eq("news_type", "EDUCATION").execute()
        return res.count or 0
    except:
        return 0

def save_pending_post(candidate: dict, post_text: str, image_url) -> str:
    try:
        res = supabase.table("pending_posts").insert({
            "title":     candidate.get("title", ""),
            "url":       candidate.get("url", ""),
            "post_text": post_text,
            "image_url": image_url or "",
            "region":    candidate.get("region", ""),
            "status":    "pending",
        }).execute()
        return res.data[0]["id"]
    except Exception as e:
        print(f"Failed to save pending post: {e}")
        return None

def fetch_negative_constraints() -> list:
    try:
        res = supabase.table("negative_constraints").select("feedback, created_at").execute()
        constraints = [row["feedback"].lower() for row in res.data]
        if constraints:
            print(f"=== NEGATIVE CONSTRAINTS LOADED ({len(constraints)}) ===")
            for i, c in enumerate(constraints):
                print(f"  [{i+1}] {c}")
            print("=" * 40)
        else:
            print("No negative constraints in database.")
        return constraints
    except Exception as e:
        print(f"Error loading negative constraints: {e}")
        return []

def get_recent_post_titles(limit: int = 30) -> list:
    titles = []
    try:
        res = supabase.table("posted_news") \
            .select("url_text, title, news_type") \
            .in_("news_type", ["NEWS", "НОВОСТЬ"]) \
            .order("created_at", desc=True) \
            .limit(limit) \
            .execute()
        for row in res.data:
            if row.get("title"):
                titles.append(row["title"])
            elif row.get("url_text"):
                titles.append(row["url_text"])
    except:
        pass
    try:
        res2 = supabase.table("pending_posts") \
            .select("title, url") \
            .eq("status", "pending") \
            .order("created_at", desc=True) \
            .limit(20) \
            .execute()
        for row in res2.data:
            if row.get("title"):
                titles.append(row["title"])
            if row.get("url"):
                titles.append(row["url"])
    except:
        pass
    return titles

def get_rejected_post_summaries(limit: int = 20) -> list:
    summaries = []
    try:
        res = supabase.table("pending_posts") \
            .select("title, url, region") \
            .eq("status", "rejected") \
            .order("created_at", desc=True) \
            .limit(limit) \
            .execute()
        for row in res.data:
            if row.get("title"):
                summaries.append(row["title"])
            if row.get("url"):
                summaries.append(row["url"])
        if summaries:
            print(f"=== REJECTED POSTS LOADED ({len(summaries)}) — will avoid similar content ===")
            for s in summaries[:10]:
                print(f"  - {s[:80]}")
            print("=" * 40)
    except Exception as e:
        print(f"Error loading rejected posts: {e}")
    return summaries

# ────────────────────────────────────────────────
# FEW-SHOT: ЗАГРУЗКА ОДОБРЕННЫХ ПОСТОВ КАК ПРИМЕРОВ
#
# Принцип работы:
#   - Каждый раз когда фаундер одобряет пост — он голосует за качество
#   - Накапливаем эти посты в pending_posts (status=approved)
#   - При генерации нового поста показываем 2-3 лучших примера ИИ
#   - ИИ копирует СТИЛЬ примеров, но факты берёт ТОЛЬКО из сниппета
#
# Защита от галлюцинаций:
#   - Примеры используются только для стиля (длина, тон, структура)
#   - Промпт явно запрещает добавлять факты не из источника
#   - Quality scorer отсекает посты с выдуманными цифрами
# ────────────────────────────────────────────────
def get_approved_examples(region: str = None, limit: int = 3) -> list:
    """
    Загружает одобренные посты из pending_posts как few-shot примеры.
    Приоритет отдаётся постам того же региона что и текущая статья.
    Возвращает список строк — готовых постов без URL.
    """
    try:
        examples = []

        # Сначала ищем примеры того же региона
        if region:
            res = supabase.table("pending_posts") \
                .select("post_text, region") \
                .eq("status", "approved") \
                .eq("region", region) \
                .order("created_at", desc=True) \
                .limit(limit) \
                .execute()
            for row in res.data or []:
                text = row.get("post_text", "").strip()
                # Убираем URL из конца поста — пример должен быть только текстом
                lines = [l for l in text.split("\n") if not l.startswith("http")]
                clean = "\n".join(lines).strip()
                if clean and len(clean) > 80:
                    examples.append(clean)

        # Если мало примеров того же региона — добиваем из любых
        if len(examples) < limit:
            needed = limit - len(examples)
            res2 = supabase.table("pending_posts") \
                .select("post_text, region") \
                .eq("status", "approved") \
                .order("created_at", desc=True) \
                .limit(limit * 3) \
                .execute()
            for row in res2.data or []:
                if len(examples) >= limit:
                    break
                text = row.get("post_text", "").strip()
                lines = [l for l in text.split("\n") if not l.startswith("http")]
                clean = "\n".join(lines).strip()
                if clean and len(clean) > 80 and clean not in examples:
                    examples.append(clean)

        if examples:
            print(f"Few-shot examples loaded: {len(examples)} approved posts (region={region})")
        else:
            print("Few-shot: no approved posts yet — will improve after first approvals")

        return examples[:limit]

    except Exception as e:
        print(f"Few-shot load error (non-critical): {e}")
        return []



# ────────────────────────────────────────────────
# RSS DIRECT FEEDS
#
# Читаем ЦА и мировые VC-источники напрямую через RSS.
# Это независимо от Tavily — бот видит все свежие статьи
# сразу после публикации, не дожидаясь индексации.
#
# Структура RSS_FEEDS:
#   url    — адрес RSS-фида
#   region — Kazakhstan / CentralAsia / World
#   priority — как в SEARCH_QUERIES (меньше = важнее)
# ────────────────────────────────────────────────
RSS_FEEDS = [
    # ── Казахстан ──────────────────────────────────
    {"url": "https://digitalbusiness.kz/feed/",                       "region": "Kazakhstan",  "priority": 0},
    {"url": "https://astanatimes.com/feed/",                           "region": "Kazakhstan",  "priority": 0},
    {"url": "https://the-tech.kz/feed/",                              "region": "Kazakhstan",  "priority": 0},
    {"url": "https://timesca.com/feed/",                              "region": "Kazakhstan",  "priority": 0},
    {"url": "https://forbes.kz/rss/",                                 "region": "Kazakhstan",  "priority": 1},

    # ── Центральная Азия ───────────────────────────
    {"url": "https://daryo.uz/feed/",                                 "region": "CentralAsia", "priority": 1},
    {"url": "https://www.gazeta.uz/ru/rss/",                          "region": "CentralAsia", "priority": 1},
    {"url": "https://kun.uz/rss",                                     "region": "CentralAsia", "priority": 1},
    {"url": "https://dunyo.info/ru/rss",                              "region": "CentralAsia", "priority": 1},
    {"url": "https://economist.kg/feed/",                             "region": "CentralAsia", "priority": 1},

    # ── Мировые VC ─────────────────────────────────
    {"url": "https://techcrunch.com/category/startups/feed/",         "region": "World",       "priority": 2},
    {"url": "https://siliconangle.com/feed/",                         "region": "World",       "priority": 2},
    {"url": "https://venturebeat.com/category/ai/feed/",              "region": "World",       "priority": 2},
    {"url": "https://theaiinsider.tech/feed/",                        "region": "World",       "priority": 2},
]

# VC-ключевые слова для фильтрации RSS статей (те же что в is_vc_relevant)
RSS_VC_KEYWORDS = [
    "стартап", "венчур", "инвестиц", "раунд", "финансирован",
    "startup", "venture", "funding", "raised", "series a", "series b",
    "seed", "pre-seed", "investor", "unicorn", "accelerator",
    "ipo", "acquisition", "инвест",
]


def fetch_rss_candidates(days: int = 5) -> list:
    """
    Читает все RSS_FEEDS и возвращает свежие VC-релевантные статьи.
    Требует: pip install feedparser
    Если feedparser не установлен — тихо возвращает пустой список.
    """
    try:
        import feedparser
    except ImportError:
        print("feedparser not installed — RSS feeds skipped. Add to requirements.txt")
        return []

    from dateutil import parser as dateparser
    import re

    cutoff   = datetime.utcnow().timestamp() - 86400 * days
    results  = []
    seen_urls = set()

    for feed_cfg in RSS_FEEDS:
        feed_url = feed_cfg["url"]
        region   = feed_cfg["region"]
        priority = feed_cfg["priority"]

        try:
            feed = feedparser.parse(feed_url)
            if feed.bozo and not feed.entries:
                print(f"RSS parse error ({feed_url[:50]}): {feed.bozo_exception}")
                continue

            count = 0
            for entry in feed.entries:
                url = entry.get("link", "")
                if not url or url in seen_urls:
                    continue

                title   = entry.get("title", "").strip()
                snippet = entry.get("summary", "")[:400].strip()

                # Определяем дату публикации
                pub_date = None
                for date_field in ["published_parsed", "updated_parsed"]:
                    if hasattr(entry, date_field) and getattr(entry, date_field):
                        import calendar
                        pub_date = calendar.timegm(getattr(entry, date_field))
                        break

                # Fallback: дата из URL
                if not pub_date:
                    m = re.search(r'/(20\d{2})[/-](\d{2})[/-](\d{2})', url)
                    if m:
                        try:
                            pub_date = dateparser.parse(f"{m.group(1)}-{m.group(2)}-{m.group(3)}").timestamp()
                        except Exception:
                            pass

                # Пропускаем если старее окна
                if pub_date and pub_date < cutoff:
                    continue

                # Фильтр VC-релевантности (упрощённый — без prohibitions, они применятся позже)
                content_lower = (title + " " + snippet).lower()
                if not any(kw in content_lower for kw in RSS_VC_KEYWORDS):
                    continue

                seen_urls.add(url)
                results.append({
                    "title":    title,
                    "url":      url,
                    "snippet":  snippet,
                    "region":   region,
                    "priority": priority,
                    "key":      url,
                    "source":   "rss",
                })
                count += 1

            if count > 0:
                print(f"RSS [{region}] {feed_url[:45]}: {count} новых статей")

        except Exception as e:
            print(f"RSS feed failed ({feed_url[:50]}): {e}")
            continue

    print(f"RSS total candidates: {len(results)}")
    return results

# ────────────────────────────────────────────────
# TAVILY SEARCH
# ────────────────────────────────────────────────
BLOCKED_DOMAINS = [
    "tracxn.com", "crunchbase.com", "pitchbook.com",
    "statista.com", "similarweb.com", "dealroom.co",
    "dealroom.net", "topstartups.io", "openvc.app",
    "vcsheet.com", "failory.com", "fundraiseinsider.com",
    "tadviser.ru", "wikipedia.org", "wikia.com",
    "instagram.com", "facebook.com", "linkedin.com",
    "twitter.com", "t.me", "youtube.com",
    "ventureforum.asia", "startupbase.uz", "startupcup.asia",
    "shizune.co", "alleywatch.com",
]

# Источники которым доверяем даже без даты в URL
TRUSTED_NODATELESS_DOMAINS = [
    "astanahub.com", "timesca.com", "qazinform.com",
    "the-tech.kz", "aifc.kz", "gazeta.uz", "arabfounders.net",
    "dominovc.com", "investready.uz", "dunyo.info",
]

def tavily_search(query: str, max_results: int = 5, days: int = 5) -> list:
    """
    days: окно поиска. По умолчанию 5 дней.
    Статьи без даты в URL принимаются если домен в TRUSTED_NODATELESS_DOMAINS.
    """
    if not tavily:
        return []
    try:
        import re
        from dateutil import parser as dateparser

        response = tavily.search(
            query=query,
            search_depth="basic",
            max_results=max_results,
            days=days,
        )
        results = []
        cutoff = datetime.utcnow().timestamp() - 86400 * days

        for r in response.get("results", []):
            url = r.get("url", "")
            if any(domain in url for domain in BLOCKED_DOMAINS):
                print(f"Blocked: {url[:70]}")
                continue

            pub_date = r.get("published_date")

            # Попытка 1: дата из Tavily API
            # Попытка 2: дата из URL (YYYY-MM-DD)
            if not pub_date:
                m = re.search(r'/(20\d{2})[/-](\d{2})[/-](\d{2})', url)
                if m:
                    pub_date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
                else:
                    # Попытка 3: только год/месяц из URL
                    m2 = re.search(r'/(20\d{2})/(\d{2})/', url)
                    if m2:
                        pub_date = f"{m2.group(1)}-{m2.group(2)}-01"

            # Попытка 4: доверенный домен без даты — принимаем как свежий
            if not pub_date:
                is_trusted = any(d in url for d in TRUSTED_NODATELESS_DOMAINS)
                if is_trusted:
                    print(f"Trusted domain (no date): {url[:70]}")
                    pub_date = datetime.utcnow().strftime("%Y-%m-%d")
                else:
                    print(f"No date, skipping: {url[:70]}")
                    continue

            # Проверяем что не старее окна
            try:
                pub_ts = dateparser.parse(pub_date).timestamp()
                if pub_ts < cutoff:
                    print(f"Too old ({pub_date}): {url[:70]}")
                    continue
            except Exception:
                pass

            results.append({
                "title":    r.get("title", ""),
                "url":      url,
                "snippet":  r.get("content", "")[:400],
                "pub_date": pub_date,
            })
        return results
    except Exception as e:
        print(f"Tavily search error: {e}")
        return []

# ────────────────────────────────────────────────
# VC RELEVANCE KEYWORD FILTER
# ────────────────────────────────────────────────
VC_KEYWORDS = [
    "стартап", "венчурный фонд", "инвестиции в стартап", "раунд финансирования",
    "startup", "venture capital", "funding round", "raised $", "raises $",
    "series a", "series b", "series c", "seed round", "pre-seed",
    "ipo", "unicorn", "единорог", "акселератор", "accelerator",
    "openai", "anthropic", "nvidia", "sequoia", "a16z", "y combinator",
    "fintech startup", "edtech", "healthtech", "saas funding",
    "venture fund", "vc fund", "angel investment", "angel investor",
]

HARD_EXCLUDE_KEYWORDS = [
    "геополитик", "военн", "foreign policy", "military", "sanctions", "geopolitic",
    "криптовалют", "bitcoin", "ethereum", "nft", " crypto ",
    "real estate fund", "mortgage", "ипотек",
    "что стоит за", "активность сша", "активность китая",
]

def is_vc_relevant(title: str, snippet: str, prohibitions: list) -> bool:
    content = (title + " " + snippet).lower()

    for kw in HARD_EXCLUDE_KEYWORDS:
        if kw in content:
            print(f"Hard excluded ({kw}): {title[:60]}")
            return False

    for rule in prohibitions:
        if rule in content:
            print(f"Prohibition matched ({rule!r}): {title[:60]}")
            return False

    matched = [kw for kw in VC_KEYWORDS if kw in content]
    if matched:
        return True

    print(f"No VC keywords matched: {title[:60]}")
    return False

# ────────────────────────────────────────────────
# GEMINI: PICK BEST ARTICLE
# ────────────────────────────────────────────────
async def pick_best_with_gemini(
    candidates: list,
    prohibitions: list,
    rejected_titles: list,
    priority_instructions: list,
) -> dict:
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    articles_text = ""
    for i, c in enumerate(candidates[:10]):
        articles_text += f"{i+1}. [{c['region']}] {c['title']}\n   {c['snippet']}\n\n"

    avoid_context = ""
    if prohibitions:
        avoid_context += "\nREJECTED for these reasons — do NOT pick similar:\n"
        for p in prohibitions[:8]:
            avoid_context += f"  - {p}\n"
    if rejected_titles:
        avoid_context += "\nREJECTED post titles — do not cover same stories:\n"
        for rt in rejected_titles[:8]:
            avoid_context += f"  - {rt}\n"

    prefer_context = ""
    if priority_instructions:
        prefer_context += "\nEDITOR PREFERENCES — try to pick content matching these:\n"
        for pi in priority_instructions[:5]:
            prefer_context += f"  - {pi}\n"

    try:
        prompt = (
            "You are a venture capital news editor for a Central Asian VC Telegram channel.\n"
            "From this list, pick ONE article MOST relevant to startups and venture capital.\n"
            "Must be about: startup funding rounds, VC fund news, major tech/AI company investments, "
            "startup ecosystem news, or venture market trends.\n"
            "Do NOT pick: consumer finance, personal taxes, sports, politics, geopolitics, "
            "general government policy, cryptocurrency, real estate.\n"
            f"{avoid_context}"
            f"{prefer_context}\n"
            f"{articles_text}"
            "Respond with ONLY the number (e.g.: 3). Nothing else."
        )
        idx = int(gemini_generate(prompt).strip(".")) - 1
        if 0 <= idx < len(candidates[:10]):
            return candidates[idx]
    except Exception as e:
        print(f"Gemini pick error: {e}")

    return candidates[0]

# ────────────────────────────────────────────────
# GEMINI: SEMANTIC DUPLICATE CHECK
# ────────────────────────────────────────────────
async def is_semantic_duplicate(candidate: dict, recent_titles: list, rejected_titles: list) -> bool:
    all_titles = recent_titles + rejected_titles
    if not all_titles:
        return False
    try:
        recent_text = "\n".join(str(t) for t in all_titles[:30])
        prompt = (
            f"New article title: {candidate['title']}\n"
            f"New article snippet: {candidate['snippet'][:200]}\n\n"
            f"Recently published OR recently rejected articles/URLs:\n{recent_text}\n\n"
            "Is the new article covering the SAME news story as any of the above? "
            "Same story = same event, same announcement, same data — even from a different source.\n"
            "Answer only YES or NO."
        )
        answer = gemini_generate(prompt).upper()
        is_dup = answer.startswith("YES")
        if is_dup:
            print(f"Semantic duplicate detected: {candidate['title']}")
        return is_dup
    except Exception as e:
        print(f"Duplicate check error: {e}")
        return False

# ────────────────────────────────────────────────
# POST QUALITY SCORER
# Оценивает пост по 5 критериям (0-100).
# Если score < 60 — перегенерируем (макс 2 попытки).
# ────────────────────────────────────────────────
def score_post_quality(post_text: str, region: str) -> dict:
    import re
    body      = post_text.replace(region, "").strip()
    url_part  = body.split("http")[-1] if "http" in body else ""
    body_text = body.replace(f"http{url_part}", "").strip()
    issues    = []
    score     = 100

    # 1. Длина
    length = len(body_text)
    if length < 150:
        issues.append(f"слишком коротко ({length} симв)")
        score -= 25
    elif length > 450:
        issues.append(f"слишком длинно ({length} симв)")
        score -= 15

    # 2. Конкретные цифры
    has_numbers = bool(re.search(
        r'\d+[\.,]?\d*\s*(млн|млрд|тыс|%|M|B|K|\$|€|£)', body_text, re.IGNORECASE
    ))
    if not has_numbers:
        issues.append("нет конкретных цифр или сумм")
        score -= 20

    # 3. Нет общих фраз
    vague_phrases = [
        "это важно для стартапов", "регион следит за трендами",
        "аналитики отмечают", "эксперты считают", "как сообщается",
        "по имеющимся данным", "по мнению экспертов",
    ]
    for phrase in vague_phrases:
        if phrase in body_text.lower():
            issues.append(f"общая фраза: «{phrase}»")
            score -= 15
            break

    # 4. Страна указана
    if region in ("CentralAsia", "World"):
        country_words = [
            "казахстан", "узбекистан", "кыргызстан", "таджикистан",
            "сша", "китай", "индия", "европ", "великобритани",
            "казахстана", "узбекистана", "кыргызстана",
        ]
        company_words = ["openai", "anthropic", "nvidia", "google", "microsoft", "amazon"]
        if not any(w in body_text.lower() for w in country_words + company_words):
            issues.append("не указана страна или компания")
            score -= 20

    # 5. Нет эмодзи
    emoji_pattern = re.compile(
        "[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF"
        "\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF"
        "\U00002702-\U000027B0\U000024C2-\U0001F251]+",
        flags=re.UNICODE
    )
    if emoji_pattern.search(body_text):
        issues.append("содержит эмодзи")
        score -= 15

    score  = max(0, min(100, score))
    passed = score >= 60
    print(f"Post quality: {score}/100 | {'OK' if passed else 'FAIL'} | {issues or 'no issues'}")
    return {"score": score, "issues": issues, "passed": passed}


# ────────────────────────────────────────────────
# TRACKED ENTITIES
# Читает таблицу tracked_entities из Supabase.
# Если таблица не существует — возвращает пустой список.
# ────────────────────────────────────────────────
def get_tracked_entities() -> list:
    """
    Читает таблицу tracked_entities из Supabase.
    Реальные колонки: id, created_at, entity_name, entity_type, website
    entity_type используется как регион: Kazakhstan / CentralAsia / World
    """
    try:
        res = supabase.table("tracked_entities") \
            .select("entity_name, entity_type, website") \
            .execute()
        entities = res.data or []
        if entities:
            print(f"Tracked entities: {[e['entity_name'] for e in entities]}")
        else:
            print("Tracked entities table is empty.")
        return entities
    except Exception as e:
        print(f"tracked_entities not available (skipping): {e}")
        return []


def build_entity_queries(entities: list) -> list:
    """Поисковые запросы по конкретным компаниям. Priority -1 = выше всех."""
    y       = datetime.utcnow().year
    queries = []
    for entity in entities[:10]:
        name   = entity.get("entity_name", "")
        region = entity.get("entity_type", "Kazakhstan")
        if not name:
            continue
        queries.append({
            "query":    f"{name} funding investment news {y}",
            "region":   region,
            "priority": -1,
        })
    return queries


# ────────────────────────────────────────────────
# TELEGRAM SEND
# ────────────────────────────────────────────────
async def send_to_channel(text: str, image_url: str, thread_id: str = None):
    kwargs = {"chat_id": TELEGRAM_CHAT_ID}
    if thread_id:
        kwargs["message_thread_id"] = int(thread_id)

    try:
        if image_url:
            await bot.send_photo(
                photo=image_url,
                caption=text,
                parse_mode="HTML" if "<" in text else None,
                **kwargs
            )
        else:
            await bot.send_message(text=text, disable_web_page_preview=False, **kwargs)
    except TelegramError as te:
        print(f"Telegram error: {te}")
        if image_url:
            try:
                await bot.send_message(text=text, disable_web_page_preview=False, **kwargs)
            except TelegramError as te2:
                print(f"Retry also failed: {te2}")
                await notify_recipients(f"Send error: {str(te2)}")

# ────────────────────────────────────────────────
# NEWS POST LOGIC
# ────────────────────────────────────────────────
async def run_news(posted_count: int, approval_mode: bool, intents: dict):
    print("MODE: NEWS (08:00)")

    prohibitions          = intents["prohibitions"]
    region_boosts         = intents["region_boosts"]
    stage_boost           = intents["stage_boost"]
    priority_instructions = intents["priority_instructions"]

    # Build active query list: tracked entities first, then seed boost, then standard
    entities       = get_tracked_entities()
    entity_queries = build_entity_queries(entities)

    active_queries = list(SEARCH_QUERIES)
    if stage_boost:
        active_queries = SEED_QUERIES + active_queries
        print(f"Stage boost active — added {len(SEED_QUERIES)} pre-seed/seed queries.")
    if entity_queries:
        active_queries = entity_queries + active_queries
        print(f"Tracked entities — added {len(entity_queries)} company-specific queries.")

    def _collect_candidates(queries, days):
        found = []
        for search in queries:
            results = tavily_search(search["query"], max_results=10, days=days)
            for r in results:
                if is_already_posted(r["url"]):
                    print(f"Already posted: {r['url'][:65]}")
                    continue
                if is_already_pending(r["url"]):
                    print(f"Already pending: {r['url'][:65]}")
                    continue
                if not is_vc_relevant(r["title"], r["snippet"], prohibitions):
                    continue
                found.append({
                    "title":    r["title"],
                    "url":      r["url"],
                    "snippet":  r["snippet"],
                    "region":   search["region"],
                    "priority": search["priority"],
                    "key":      r["url"],
                })
        # Deduplicate by URL
        seen, unique = set(), []
        for c in found:
            if c["url"] not in seen:
                seen.add(c["url"])
                unique.append(c)
        return unique

    # ── Шаг 1: RSS-фиды (прямое чтение источников) ──
    print("Reading RSS feeds...")
    rss_raw = fetch_rss_candidates(days=5)

    # Фильтруем RSS через те же проверки что и Tavily-результаты
    rss_candidates = []
    rss_seen = set()
    for r in rss_raw:
        if r["url"] in rss_seen:
            continue
        if is_already_posted(r["url"]):
            continue
        if is_already_pending(r["url"]):
            continue
        if not is_vc_relevant(r["title"], r["snippet"], prohibitions):
            continue
        rss_seen.add(r["url"])
        rss_candidates.append(r)

    print(f"RSS candidates after filter: {len(rss_candidates)}")

    # ── Шаг 2: Tavily (поиск по запросам) ──
    print("Searching via Tavily (5-day window)...")
    tavily_candidates = _collect_candidates(active_queries, days=5)
    print(f"Tavily candidates (5-day): {len(tavily_candidates)}")

    # Fallback: расширяем до 7 дней если мало кандидатов от Tavily
    if len(tavily_candidates) < 3:
        print("Too few Tavily candidates — expanding to 7-day window...")
        tavily_candidates = _collect_candidates(active_queries, days=7)
        print(f"Tavily candidates (7-day): {len(tavily_candidates)}")

    # ── Объединяем: RSS первыми (они свежее и точнее) ──
    # Дедупликация по URL между RSS и Tavily
    tavily_urls = {c["url"] for c in rss_candidates}
    tavily_unique = [c for c in tavily_candidates if c["url"] not in tavily_urls]
    all_candidates = rss_candidates + tavily_unique

    print(f"Total candidates (RSS + Tavily): {len(all_candidates)}")

    if not all_candidates:
        print("No suitable news found.")
        await notify_recipients("Main Bot: сегодня не нашлось подходящих новостей.")
        return

    # Apply priority boosts from feedback
    all_candidates = apply_priority_boosts(all_candidates, intents)
    all_candidates.sort(key=lambda c: c["priority"])

    recent_titles   = get_recent_post_titles()
    rejected_titles = get_rejected_post_summaries()
    print(f"Loaded {len(recent_titles)} recent + {len(rejected_titles)} rejected titles for duplicate check.")

    best = None
    remaining = list(all_candidates)

    while remaining:
        candidate = await pick_best_with_gemini(
            remaining, prohibitions, rejected_titles, priority_instructions
        )
        if not candidate:
            break
        if not await is_semantic_duplicate(candidate, recent_titles, rejected_titles):
            best = candidate
            break
        else:
            remaining = [c for c in remaining if c["url"] != candidate["url"]]
            print(f"Skipping duplicate, {len(remaining)} candidates left.")

    if not best:
        print("All candidates are semantic duplicates of recent posts.")
        await notify_recipients("Main Bot: все найденные новости — дубли недавних публикаций.")
        return

    print(f"Selected [{best['region']}]: {best['title']}")
    region_header = REGION_HEADER.get(best["region"], best["region"])

    region_country_hint = {
        "Kazakhstan":  "Казахстан",
        "CentralAsia": "укажи конкретную страну (Казахстан, Узбекистан, Кыргызстан и т.д.) — не пиши просто 'президент' или 'правительство' без названия страны",
        "World":       "укажи конкретную страну или компанию — не пиши просто 'президент' или 'правительство' без названия страны",
    }.get(best["region"], "")

    constraint_context = ""
    if prohibitions:
        constraint_context = "\nПредыдущие причины отклонений (не повторяй подобный контент):\n"
        for rule in prohibitions[:8]:
            constraint_context += f"  - {rule}\n"

    # Загружаем одобренные посты как few-shot примеры стиля
    few_shot_examples = get_approved_examples(region=best["region"], limit=3)

    try:
        # Формируем блок с примерами (только если они есть)
        examples_block = ""
        if few_shot_examples:
            examples_block = (
                "\nПРИМЕРЫ ОДОБРЕННЫХ ПОСТОВ (учись СТИЛЮ, НЕ фактам):\n"
                "Изучи длину, тон, структуру этих постов. "
                "Факты для нового поста бери ТОЛЬКО из раздела Содержание ниже.\n"
            )
            for i, ex in enumerate(few_shot_examples, 1):
                examples_block += f"\n--- Пример {i} ---\n{ex}\n"
            examples_block += "--- Конец примеров ---\n"

        prompt = (
            "Ты редактор Telegram-канала о венчурном капитале в Центральной Азии.\n"
            "Напиши новостной пост на РУССКОМ языке строго по этой статье.\n"
            f"{examples_block}\n"
            "ИСТОЧНИК (используй ТОЛЬКО эти факты, не добавляй ничего от себя):\n"
            f"Заголовок: {best['title']}\n"
            f"Содержание: {best['snippet']}\n"
            f"Ссылка: {best['url']}\n\n"
            f"ВАЖНО про страну: {region_country_hint}. "
            "Никогда не пиши просто 'президент', 'правительство', 'министр' — всегда добавляй страну. "
            "Например: 'президент Узбекистана', 'правительство Казахстана'.\n"
            f"{constraint_context}\n"
            f"Начни пост ТОЧНО со слова: {region_header}\n"
            "Затем пустая строка, затем сам пост.\n\n"
            "Структура поста — ровно 2 предложения:\n"
            "1. Что произошло — кто, что, сколько (конкретные цифры и факты из источника).\n"
            "2. Конкретный вывод или последствие для рынка — только из источника, без домыслов.\n\n"
            "Правила:\n"
            "- Нейтральный деловой язык, без восторгов\n"
            "- Без эмодзи и смайликов\n"
            "- Без хэштегов\n"
            "- ТОЛЬКО факты из источника выше — никаких домыслов\n"
            "- Длина: 200-350 символов\n"
        )
        # Generate post with up to 2 retries if quality score is too low
        post_text  = None
        quality    = None
        for attempt in range(3):
            raw_text = gemini_generate(prompt)
            if not raw_text.startswith(region_header):
                raw_text = f"{region_header}\n\n{raw_text}"
            candidate_text = f"{raw_text}\n\n{best['url']}"
            quality = score_post_quality(candidate_text, region_header)
            if quality["passed"]:
                post_text = candidate_text
                break
            else:
                print(f"Attempt {attempt+1} failed (score {quality['score']}): {quality['issues']} — retrying...")
                if attempt < 2:
                    # Add issues to prompt so next attempt avoids them
                    issues_hint = "; ".join(quality["issues"])
                    prompt += f"\n\nПредыдущая попытка провалила проверку качества: {issues_hint}. Исправь это."

        if post_text is None:
            # Use last attempt even if failed
            post_text = candidate_text
            print(f"All attempts failed quality check. Using best available (score: {quality['score']}).")

        image_url = None
        try:
            from bs4 import BeautifulSoup
            page = requests.get(best["url"], timeout=8)
            soup = BeautifulSoup(page.text, "lxml")
            img  = soup.find("meta", property="og:image")
            if img and img.get("content"):
                image_url = img["content"]
        except Exception as e:
            print(f"og:image failed: {e}")

        if not image_url and UNSPLASH_ACCESS_KEY:
            try:
                keywords = best["title"].lower()
                search_terms = []
                if any(w in keywords for w in ["startup", "стартап"]):
                    search_terms.append("startup office")
                if any(w in keywords for w in ["funding", "investment", "инвестиц", "раунд"]):
                    search_terms.append("business meeting")
                if any(w in keywords for w in ["ai", "artificial intelligence"]):
                    search_terms.append("technology")
                query = search_terms[0] if search_terms else "venture capital"
                resp = requests.get(
                    f"https://api.unsplash.com/photos/random?query={query}&orientation=landscape",
                    headers={"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"},
                    timeout=5
                )
                if resp.status_code == 200:
                    image_url = resp.json()["urls"]["regular"]
            except Exception as e:
                print(f"Unsplash fallback failed: {e}")

        print(f"Post ready ({len(post_text)} chars)")

    except Exception as e:
        print(f"Gemini error: {e}")
        await notify_recipients(f"Groq error: {str(e)}")
        return

    if approval_mode:
        pending_id = save_pending_post(best, post_text, image_url)
        if not pending_id:
            await notify_recipients("Не удалось сохранить пост для одобрения.")
            return
        quality_line = ""
        if quality:
            score_icon = "OK" if quality["passed"] else "WARN"
            quality_line = f"\nКачество: {quality['score']}/100 [{score_icon}]"
            if quality["issues"]:
                quality_line += f" | {', '.join(quality['issues'])}"

        preview = (
            f"НОВОСТЬ НА ОДОБРЕНИЕ (#{posted_count + 1}/100){quality_line}\n"
            f"{'─' * 28}\n"
            f"{post_text}"
        )
        await notify_approval(pending_id, preview)
        print(f"Sent for approval with buttons. ID: {pending_id}")
    else:
        await send_to_channel(post_text, image_url, NEWS_THREAD_ID)
        add_to_posted(best["key"], "NEWS", 8, best["region"], title=best.get("title", ""))
        print("PUBLISHED!")
        await notify_recipients(f"Новость опубликована:\n{post_text[:200]}...")

# ────────────────────────────────────────────────
# EDUCATION POST LOGIC
# ────────────────────────────────────────────────
async def run_education(posted_count: int, approval_mode: bool):
    print("MODE: EDUCATION (17:00)")

    edu_count   = get_education_count()
    use_activat = (edu_count % 2 == 0)

    if use_activat:
        idx         = (edu_count // 2) % len(ACTIVAT_LESSONS)
        lesson      = ACTIVAT_LESSONS[idx]
        topic       = lesson["title"]
        youtube_url = lesson["youtube_url"]
        dedup_key   = f"activat_{topic[:60]}"
        print(f"Activat VC lesson #{idx}: {topic} | {youtube_url}")
    else:
        idx         = (edu_count // 2) % len(GLOBAL_EDUCATION_TOPICS)
        topic       = GLOBAL_EDUCATION_TOPICS[idx]
        youtube_url = ""
        dedup_key   = f"edu_global_{topic[:60]}"
        print(f"Global topic #{idx}: {topic}")

    already = is_already_posted(dedup_key)
    if not already and use_activat and youtube_url:
        already = is_already_posted(youtube_url)
    if not already:
        already = is_already_pending(youtube_url if (use_activat and youtube_url) else dedup_key)

    if already:
        print(f"Topic already used or pending: {topic}")
        if use_activat:
            next_idx    = (idx + 1) % len(ACTIVAT_LESSONS)
            next_lesson = ACTIVAT_LESSONS[next_idx]
            next_key    = f"activat_{next_lesson['title'][:60]}"
            next_yt     = next_lesson["youtube_url"]
            if (not is_already_posted(next_key) and not is_already_posted(next_yt)
                    and not is_already_pending(next_yt)):
                print(f"Switching to next lesson: {next_lesson['title']}")
                lesson      = next_lesson
                topic       = next_lesson["title"]
                youtube_url = next_lesson["youtube_url"]
                dedup_key   = next_key
            else:
                await notify_recipients("Обучение: тема уже использована или ожидает одобрения.")
                return
        else:
            await notify_recipients("Обучение: тема уже использована или ожидает одобрения.")
            return

    lesson_transcript = lesson.get("transcript", "") if use_activat else ""

    try:
        if use_activat:
            prompt = (
                "Ты редактор Telegram-канала о венчурном капитале в Центральной Азии.\n"
                "Напиши короткий обучающий пост на РУССКОМ языке строго по этому конспекту.\n\n"
                f"Тема: \"{topic}\"\n\n"
                f"Конспект:\n{lesson_transcript}\n\n"
                "Требования:\n"
                "- Только факты из конспекта\n"
                "- Длина: 200-350 символов\n"
                "- Начни ТОЧНО со слова: Обучение\n"
                "- Без эмодзи и смайликов\n"
                "- Без хэштегов\n"
                f"- Последняя строка: Смотреть урок: {youtube_url}\n"
            )
        else:
            prompt = (
                "Ты редактор Telegram-канала о венчурном капитале в Центральной Азии.\n"
                "Напиши короткий обучающий пост на РУССКОМ языке.\n\n"
                f"Тема: \"{topic}\"\n\n"
                "Требования:\n"
                "- Длина: 200-350 символов\n"
                "- Начни ТОЧНО со слова: Обучение\n"
                "- Конкретные примеры и цифры\n"
                "- Без эмодзи и смайликов\n"
                "- Без хэштегов\n"
                "- Заверши конкретным вопросом для обсуждения\n"
            )

        post_text = gemini_generate(prompt)

        if not post_text.startswith("Обучение"):
            post_text = f"Обучение\n\n{post_text}"
        if use_activat and youtube_url and youtube_url not in post_text:
            post_text = f"{post_text}\n\nСмотреть урок: {youtube_url}"

        print(f"Education post ready ({len(post_text)} chars)")

    except Exception as e:
        print(f"Gemini error: {e}")
        await notify_recipients(f"Groq error (обучение): {str(e)}")
        return

    candidate  = {"title": topic, "url": youtube_url, "region": "Education", "key": dedup_key}
    source_tag = f"Activat VC: {youtube_url}" if use_activat else "Global VC topic"

    if approval_mode:
        pending_id = save_pending_post(candidate, post_text, None)
        if not pending_id:
            await notify_recipients("Не удалось сохранить обучающий пост.")
            return
        preview = (
            f"ОБУЧЕНИЕ НА ОДОБРЕНИЕ (#{posted_count + 1}/100)\n"
            f"Источник: {source_tag}\n"
            f"{'─' * 28}\n"
            f"{post_text}"
        )
        await notify_approval(pending_id, preview)
        print(f"Education sent for approval with buttons. ID: {pending_id}")
    else:
        await send_to_channel(post_text, None, EDUCATION_THREAD_ID)
        add_to_posted(dedup_key, "EDUCATION", 8, "Education", title=topic)
        if use_activat and youtube_url:
            add_to_posted(youtube_url, "EDUCATION", 8, "Education", title=topic)
        print("EDUCATION PUBLISHED!")
        await notify_recipients(f"Обучение опубликовано:\n{post_text[:200]}...")

# ────────────────────────────────────────────────
# MAIN
# ────────────────────────────────────────────────
async def main():
    print(f"STARTING | {datetime.utcnow().isoformat()} UTC | TYPE: {POST_TYPE.upper()}")

    expired = expire_old_pending_posts()
    print(f"Cleaned up {expired} expired pending posts.")

    # Load all constraints and parse their intent
    raw_constraints = fetch_negative_constraints()
    intents         = parse_feedback_intents(raw_constraints)

    posted_count  = get_posted_count()
    approval_mode = posted_count < 100
    print(f"Posts published: {posted_count} | Mode: {'APPROVAL' if approval_mode else 'AUTO'}")

    if POST_TYPE == "education":
        await run_education(posted_count, approval_mode)
    else:
        await run_news(posted_count, approval_mode, intents)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"Critical error: {e}")
        if TELEGRAM_ADMIN_ID:
            try:
                asyncio.run(bot.send_message(TELEGRAM_ADMIN_ID, f"Main Bot crashed: {str(e)}"))
            except:
                pass
        sys.exit(1)
