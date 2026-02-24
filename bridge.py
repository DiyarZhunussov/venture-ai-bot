import os
import sys
import asyncio
import requests
from datetime import datetime, timezone
from supabase import create_client, Client
from groq import Groq
from telegram import Bot
from telegram.error import TelegramError
from tavily import TavilyClient

# ────────────────────────────────────────────────
# ENVIRONMENT VARIABLES
# ────────────────────────────────────────────────
GROQ_API_KEY        = os.getenv("GROQ_API_KEY")
TELEGRAM_BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID")
TELEGRAM_ADMIN_ID   = os.getenv("TELEGRAM_ADMIN_ID")
TELEGRAM_FOUNDER_ID = os.getenv("TELEGRAM_FOUNDER_ID")
SUPABASE_URL        = os.getenv("SUPABASE_URL")
SUPABASE_KEY        = os.getenv("SUPABASE_KEY")
UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY")
TAVILY_API_KEY      = os.getenv("TAVILY_API_KEY")
POST_TYPE           = os.getenv("POST_TYPE", "news")

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
groq_client = Groq(api_key=GROQ_API_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
bot      = Bot(token=TELEGRAM_BOT_TOKEN)
tavily   = TavilyClient(api_key=TAVILY_API_KEY) if TAVILY_API_KEY else None

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
# NOTIFY RECIPIENTS (admin + founder if set)
# ────────────────────────────────────────────────
async def notify_recipients(message: str):
    await bot.send_message(TELEGRAM_ADMIN_ID, message)
    if TELEGRAM_FOUNDER_ID and TELEGRAM_FOUNDER_ID != TELEGRAM_ADMIN_ID:
        try:
            await bot.send_message(TELEGRAM_FOUNDER_ID, message)
        except Exception as e:
            print(f"Failed to notify founder: {e}")

# ────────────────────────────────────────────────
# SEARCH QUERIES BY REGION
# ────────────────────────────────────────────────
SEARCH_QUERIES = [
    {"query": "Казахстан стартап инвестиции раунд февраль 2026",         "region": "Kazakhstan",  "priority": 0},
    {"query": "Kazakhstan startup funding round raised February 2026",    "region": "Kazakhstan",  "priority": 0},
    {"query": "Kazakhstan venture capital deal announcement 2026",        "region": "Kazakhstan",  "priority": 0},
    {"query": "Узбекистан Кыргызстан стартап инвестиции раунд 2026",     "region": "CentralAsia", "priority": 1},
    {"query": "Central Asia startup investment round raised 2026",        "region": "CentralAsia", "priority": 1},
    {"query": "Центральная Азия венчур фонд сделка февраль 2026",        "region": "CentralAsia", "priority": 1},
    {"query": "startup raised million Series A B funding February 2026",  "region": "World",       "priority": 2},
    {"query": "venture capital deal announced this week February 2026",   "region": "World",       "priority": 2},
    {"query": "AI startup funding round announced February 2026",         "region": "World",       "priority": 2},
]

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
    """
    FIX #1: Check if this URL is already sitting in pending_posts awaiting approval.
    Without this check, the bot generates the same article every day if nobody approves it.
    """
    if not url:
        return False
    try:
        res = supabase.table("pending_posts").select("id").eq("url", url).eq("status", "pending").execute()
        return len(res.data) > 0
    except Exception as e:
        print(f"Supabase pending check error: {e}")
        return False

def expire_old_pending_posts():
    """
    FIX #2: Mark pending posts older than 2 days as 'expired'.
    This cleans up the queue and prevents stale posts from blocking new ones.
    """
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
    """
    FIX #3: Logs all loaded constraints so you can see them in GitHub Actions logs.
    This makes the 'learning' visible and debuggable.
    """
    try:
        res = supabase.table("negative_constraints").select("feedback, created_at").execute()
        constraints = [row["feedback"].lower() for row in res.data]
        if constraints:
            print(f"=== NEGATIVE CONSTRAINTS LOADED ({len(constraints)}) ===")
            for i, c in enumerate(constraints):
                print(f"  [{i+1}] {c}")
            print("=" * 40)
        else:
            print("No negative constraints in database — no rejections have been saved yet.")
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
    """
    FIX #4: Load titles of rejected posts so the AI explicitly avoids covering same topics again.
    Previously rejected posts had no effect on future article selection.
    """
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
# TAVILY SEARCH
# ────────────────────────────────────────────────
def tavily_search(query: str, max_results: int = 5) -> list:
    if not tavily:
        return []
    try:
        response = tavily.search(
            query=query,
            search_depth="basic",
            max_results=max_results,
            days=3,
        )
        results = []
        cutoff = datetime.utcnow().timestamp() - 86400 * 3
        from dateutil import parser as dateparser
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

        for r in response.get("results", []):
            url = r.get("url", "")

            if any(domain in url for domain in BLOCKED_DOMAINS):
                print(f"Blocked aggregator: {url}")
                continue

            pub_date = r.get("published_date")

            if not pub_date:
                import re
                url_date_match = re.search(r'/(20\d{2})[/-](\d{2})[/-](\d{2})', url)
                if url_date_match:
                    y, m, d = url_date_match.groups()
                    pub_date = f"{y}-{m}-{d}"
                    print(f"Date from URL ({pub_date}): {url}")
                else:
                    url_ym_match = re.search(r'/(20\d{2})/(\d{2})/', url)
                    if url_ym_match:
                        y, m = url_ym_match.groups()
                        pub_date = f"{y}-{m}-01"
                        print(f"Date from URL month ({pub_date}): {url}")

            if not pub_date:
                print(f"No date found, skipping: {url}")
                continue

            if pub_date:
                try:
                    pub_ts = dateparser.parse(pub_date).timestamp()
                    if pub_ts < cutoff:
                        print(f"Too old ({pub_date}): {url}")
                        continue
                except Exception:
                    pass

            results.append({
                "title":    r.get("title", ""),
                "url":      url,
                "snippet":  r.get("content", "")[:400],
                "pub_date": pub_date or "",
            })
        return results
    except Exception as e:
        print(f"Tavily search error: {e}")
        return []

# ────────────────────────────────────────────────
# VC RELEVANCE KEYWORD FILTER
# FIX #5: Stricter keywords + hard excludes for geopolitics/crypto/etc
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

def is_vc_relevant(title: str, snippet: str, negative_rules: list) -> bool:
    content = (title + " " + snippet).lower()

    for kw in HARD_EXCLUDE_KEYWORDS:
        if kw in content:
            print(f"Hard excluded ({kw}): {title[:60]}")
            return False

    for rule in negative_rules:
        if rule in content:
            print(f"Negative constraint matched ({rule!r}): {title[:60]}")
            return False

    matched = [kw for kw in VC_KEYWORDS if kw in content]
    if matched:
        return True

    print(f"No VC keywords matched: {title[:60]}")
    return False

# ────────────────────────────────────────────────
# GEMINI: PICK BEST ARTICLE
# FIX #6: Now passes negative constraints + rejected titles to the AI for better selection
# ────────────────────────────────────────────────
async def pick_best_with_gemini(candidates: list, negative_constraints: list, rejected_titles: list) -> dict:
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    articles_text = ""
    for i, c in enumerate(candidates[:10]):
        articles_text += f"{i+1}. [{c['region']}] {c['title']}\n   {c['snippet']}\n\n"

    avoid_context = ""
    if negative_constraints:
        avoid_context += "\nPreviously REJECTED for these reasons — avoid similar content:\n"
        for nc in negative_constraints[:10]:
            avoid_context += f"  - {nc}\n"
    if rejected_titles:
        avoid_context += "\nPreviously REJECTED post titles — do not cover same stories:\n"
        for rt in rejected_titles[:10]:
            avoid_context += f"  - {rt}\n"

    try:
        prompt = (
            "You are a venture capital news editor for a Central Asian VC Telegram channel.\n"
            "From this list, pick ONE article MOST relevant to startups and venture capital.\n"
            "Must be about: startup funding rounds, VC fund news, major tech/AI company investments, "
            "startup ecosystem news, or venture market trends.\n"
            "Do NOT pick: consumer finance, personal taxes, sports, politics, geopolitics, "
            "general government policy, cryptocurrency, real estate.\n"
            f"{avoid_context}\n"
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
# FIX #7: Also checks against rejected post titles, not just published ones
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
            await bot.send_message(
                text=text,
                disable_web_page_preview=False,
                **kwargs
            )
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
async def run_news(posted_count: int, approval_mode: bool, negative_rules: list):
    print("MODE: NEWS (08:00)")

    all_candidates = []

    print("Searching via Tavily...")
    for search in SEARCH_QUERIES:
        results = tavily_search(search["query"], max_results=10)
        for r in results:
            if is_already_posted(r["url"]):
                print(f"Already in posted_news: {r['url'][:60]}")
                continue
            if is_already_pending(r["url"]):
                print(f"Already pending approval: {r['url'][:60]}")
                continue
            if not is_vc_relevant(r["title"], r["snippet"], negative_rules):
                continue
            all_candidates.append({
                "title":    r["title"],
                "url":      r["url"],
                "snippet":  r["snippet"],
                "region":   search["region"],
                "priority": search["priority"],
                "key":      r["url"],
            })

    seen = set()
    unique = []
    for c in all_candidates:
        if c["url"] not in seen:
            seen.add(c["url"])
            unique.append(c)
    all_candidates = unique

    print(f"Candidates after filter: {len(all_candidates)}")

    if not all_candidates:
        print("No suitable news found.")
        await notify_recipients("Main Bot: сегодня не нашлось подходящих новостей.")
        return

    all_candidates.sort(key=lambda c: c["priority"])

    recent_titles   = get_recent_post_titles()
    rejected_titles = get_rejected_post_summaries()
    print(f"Loaded {len(recent_titles)} recent + {len(rejected_titles)} rejected titles for duplicate check.")

    best = None
    remaining = list(all_candidates)

    while remaining:
        candidate = await pick_best_with_gemini(remaining, negative_rules, rejected_titles)
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
        await notify_recipients("Main Bot: все найденные новости — дубли недавних публикаций. Пост сегодня не выйдет.")
        return

    print(f"Selected [{best['region']}]: {best['title']}")
    region_header = REGION_HEADER.get(best["region"], best["region"])

    region_country_hint = {
        "Kazakhstan":  "Казахстан",
        "CentralAsia": "укажи конкретную страну (Казахстан, Узбекистан, Кыргызстан и т.д.) — не пиши просто 'президент' или 'правительство' без названия страны",
        "World":       "укажи конкретную страну или компанию — не пиши просто 'президент' или 'правительство' без названия страны",
    }.get(best["region"], "")

    constraint_context = ""
    if negative_rules:
        constraint_context = "\nПредыдущие причины отклонений (не повторяй подобный контент):\n"
        for rule in negative_rules[:8]:
            constraint_context += f"  - {rule}\n"

    try:
        prompt = (
            "Ты редактор Telegram-канала о венчурном капитале в Центральной Азии.\n"
            "Напиши новостной пост на РУССКОМ языке строго по этой статье.\n\n"
            f"Заголовок статьи: {best['title']}\n"
            f"Содержание: {best['snippet']}\n"
            f"Ссылка: {best['url']}\n\n"
            f"ВАЖНО про страну: {region_country_hint}. "
            "Никогда не пиши просто 'президент', 'правительство', 'министр' — всегда добавляй страну. "
            "Например: 'президент Узбекистана', 'правительство Казахстана'.\n"
            f"{constraint_context}\n"
            f"Начни пост ТОЧНО со слова: {region_header}\n"
            "Затем пустая строка, затем сам пост.\n\n"
            "Структура поста — ровно 2 предложения:\n"
            "1. Что произошло — кто, что, сколько (конкретные цифры и факты из статьи).\n"
            "2. Конкретный вывод или последствие для рынка — без общих фраз.\n\n"
            "Правила:\n"
            "- Нейтральный деловой язык, без восторгов\n"
            "- Без эмодзи и смайликов\n"
            "- Без хэштегов\n"
            "- Только факты из статьи\n"
            "- Длина: 200-350 символов\n"
        )
        post_text = gemini_generate(prompt)

        if not post_text.startswith(region_header):
            post_text = f"{region_header}\n\n{post_text}"

        post_text = f"{post_text}\n\n{best['url']}"

        image_url = None
        try:
            from bs4 import BeautifulSoup
            page = requests.get(best["url"], timeout=8)
            soup = BeautifulSoup(page.text, "lxml")
            img  = soup.find("meta", property="og:image")
            if img and img.get("content"):
                image_url = img["content"]
                print(f"Image from og:image: {image_url[:50]}...")
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
                if any(w in keywords for w in ["ai", "artificial intelligence", "ии"]):
                    search_terms.append("technology")
                query = search_terms[0] if search_terms else "venture capital"
                resp = requests.get(
                    f"https://api.unsplash.com/photos/random?query={query}&orientation=landscape",
                    headers={"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"},
                    timeout=5
                )
                if resp.status_code == 200:
                    image_url = resp.json()["urls"]["regular"]
                    print(f"Image from Unsplash ({query}): {image_url[:50]}...")
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
        preview = (
            f"НОВОСТЬ НА ОДОБРЕНИЕ (#{posted_count + 1}/100)\n"
            f"--------------------\n"
            f"{post_text}\n"
            f"--------------------\n"
            f"Одобрить: /approve {pending_id}\n"
            f"Отклонить: /reject {pending_id} причина"
        )
        await notify_recipients(preview)
        print(f"Sent for approval. ID: {pending_id}")
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

    candidate = {"title": topic, "url": youtube_url, "region": "Education", "key": dedup_key}
    source_tag = f"Activat VC: {youtube_url}" if use_activat else "Global VC topic"

    if approval_mode:
        pending_id = save_pending_post(candidate, post_text, None)
        if not pending_id:
            await notify_recipients("Не удалось сохранить обучающий пост.")
            return
        preview = (
            f"ОБУЧЕНИЕ НА ОДОБРЕНИЕ (#{posted_count + 1}/100)\n"
            f"Источник: {source_tag}\n"
            f"--------------------\n"
            f"{post_text}\n"
            f"--------------------\n"
            f"Одобрить: /approve {pending_id}\n"
            f"Отклонить: /reject {pending_id} причина"
        )
        await notify_recipients(preview)
        print(f"Education sent for approval. ID: {pending_id}")
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

    # FIX: Expire stale pending posts first — this is what caused daily duplicates
    expired = expire_old_pending_posts()
    print(f"Cleaned up {expired} expired pending posts.")

    negative_rules = fetch_negative_constraints()

    posted_count  = get_posted_count()
    approval_mode = posted_count < 100
    print(f"Posts published: {posted_count} | Mode: {'APPROVAL' if approval_mode else 'AUTO'}")

    if POST_TYPE == "education":
        await run_education(posted_count, approval_mode)
    else:
        await run_news(posted_count, approval_mode, negative_rules)


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
