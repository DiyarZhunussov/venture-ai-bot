"""
bulk_seed.py — одноразовый скрипт для массовой генерации постов из архивных новостей.

Запуск: python bulk_seed.py

Что делает:
  1. Ищет ~100 VC-новостей за последние 90 дней через Tavily (расширенное окно)
  2. Генерирует посты по каждой через LLaMA
  3. Сохраняет в pending_posts со статусом 'bulk_pending'
  4. Марат просматривает их в Telegram через команду /bulk в feedback_bot
     и нажимает [✅ Одобрить] / [❌ Отклонить] для каждого (или [✅ Одобрить все])
  5. Одобренные → posted_news (счётчик растёт → авто-режим) + few-shot примеры
     Отклонённые с причиной → negative_constraints

После запуска: /bulk в боте покажет первые 10 постов с кнопками.
"""

import os
import sys
import time
import requests
from datetime import datetime, timedelta, timezone
from supabase import create_client, Client
from groq import Groq
from tavily import TavilyClient
try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

# ────────────────────────────────────────────────
# ENV
# ────────────────────────────────────────────────
GROQ_API_KEY        = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY      = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_ADMIN_ID   = os.getenv("TELEGRAM_ADMIN_ID")
TELEGRAM_FOUNDER_ID = os.getenv("TELEGRAM_FOUNDER_ID")
SUPABASE_URL        = os.getenv("SUPABASE_URL")
SUPABASE_KEY        = os.getenv("SUPABASE_KEY")
TAVILY_API_KEY      = os.getenv("TAVILY_API_KEY")

if not all([TELEGRAM_BOT_TOKEN, SUPABASE_URL, SUPABASE_KEY, TAVILY_API_KEY]):
    print("Missing required environment variables.")
    sys.exit(1)

if not GROQ_API_KEY and not GEMINI_API_KEY:
    print("Need either GROQ_API_KEY or GEMINI_API_KEY")
    sys.exit(1)

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
tavily = TavilyClient(api_key=TAVILY_API_KEY)

# Инициализируем Gemini если доступен
gemini_model = None
if GEMINI_AVAILABLE and GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel("gemini-1.5-flash")
    print("Generator: Gemini 1.5 Flash (основной)")
elif GROQ_API_KEY:
    print("Generator: Groq LLaMA (основной)")
else:
    print("ERROR: нет генератора")
    sys.exit(1)

TARGET_COUNT = 100   # сколько постов сгенерировать
SEARCH_DAYS  = 90    # смотрим на 90 дней назад

# ────────────────────────────────────────────────
# ПОИСКОВЫЕ ЗАПРОСЫ ДЛЯ АРХИВА (расширенные)
# ────────────────────────────────────────────────
ARCHIVE_QUERIES = [
    # Казахстан — новые темы
    {"query": "Казахстан технологии раунд инвестиции 2026",         "region": "Kazakhstan"},
    {"query": "Kazakhstan fintech startup raised 2025",              "region": "Kazakhstan"},
    {"query": "Kazakhstan edtech healthtech startup 2025",           "region": "Kazakhstan"},
    {"query": "AIFC Almaty startup investment deal 2025",            "region": "Kazakhstan"},
    {"query": "Казахстан IPO выход биржа стартап 2025 2026",         "region": "Kazakhstan"},
    {"query": "Kazakhstan accelerator batch graduates 2025",         "region": "Kazakhstan"},
    {"query": "Казахстан раунд A B seed pre-seed 2025",              "region": "Kazakhstan"},
    {"query": "QazTech Almaty startup ecosystem news 2025",          "region": "Kazakhstan"},
    # Центральная Азия — новые темы
    {"query": "Uzbekistan fintech investment round 2025 2026",       "region": "CentralAsia"},
    {"query": "Узбекистан юникорн единорог стартап 2025",            "region": "CentralAsia"},
    {"query": "Uzbekistan IT Park startup funding deal",             "region": "CentralAsia"},
    {"query": "Central Asia startup exit acquisition 2025",          "region": "CentralAsia"},
    {"query": "Казахстан Узбекистан стартап сделка раунд 2026",      "region": "CentralAsia"},
    {"query": "Kyrgyzstan startup raised investment 2025",           "region": "CentralAsia"},
    {"query": "Tajikistan Turkmenistan startup tech 2025",           "region": "CentralAsia"},
    # Мировые — конкретные свежие сделки
    {"query": "biotech startup series A raised million 2026",        "region": "World"},
    {"query": "climate tech startup funding round 2026",             "region": "World"},
    {"query": "deeptech robotics startup raised 2025 2026",          "region": "World"},
    {"query": "SaaS B2B startup seed round closed 2026",             "region": "World"},
    {"query": "healthtech medtech startup funding 2026",             "region": "World"},
    {"query": "crypto web3 startup raised million 2026",             "region": "World"},
    {"query": "spacetech defense startup raised 2025 2026",          "region": "World"},
]

REGION_HEADER = {
    "Kazakhstan":  "Казахстан",
    "CentralAsia": "Центральная Азия",
    "World":       "Мир",
}

VC_KEYWORDS = [
    "стартап", "венчур", "инвестиц", "раунд", "финансирован",
    "startup", "venture", "funding", "raised", "series a", "series b",
    "seed", "pre-seed", "investor", "unicorn", "accelerator", "ipo",
]

BLOCKED_DOMAINS = [
    "crunchbase.com", "tracxn.com", "instagram.com", "facebook.com",
    "linkedin.com", "twitter.com", "youtube.com", "t.me",
    "wikipedia.org", "pitchbook.com", "statista.com",
]

# Заголовки содержащие эти слова — пропускаем (явные списки и дайджесты)
SKIP_TITLE_PATTERNS = [
    "list of", "[pdf]", ".pptx", "accelerator - guide",
    "venture capital firms", "startup investors",
    "top venture capital", "top vc ",
]

# ────────────────────────────────────────────────
# HELPERS
# ────────────────────────────────────────────────
def tg_post(chat_id: str, text: str) -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={
            "chat_id": chat_id,
            "text": text[:4096],
            "disable_web_page_preview": True,
        }, timeout=15)
        return resp.ok
    except Exception as e:
        print(f"tg_post failed: {e}")
        return False


def notify(msg: str):
    if TELEGRAM_ADMIN_ID:
        tg_post(TELEGRAM_ADMIN_ID, msg)
    if TELEGRAM_FOUNDER_ID and TELEGRAM_FOUNDER_ID != TELEGRAM_ADMIN_ID:
        tg_post(TELEGRAM_FOUNDER_ID, msg)


def is_already_in_db(url: str) -> bool:
    """Проверяем и posted_news и pending_posts."""
    try:
        r1 = supabase.table("posted_news").select("id").eq("url_text", url).limit(1).execute()
        if r1.data:
            return True
        r2 = supabase.table("pending_posts").select("id").eq("url", url).limit(1).execute()
        return bool(r2.data)
    except Exception:
        return False


def _call_llm(prompt: str) -> str:
    """Gemini первым (быстро, без лимитов), Groq как fallback."""
    # Пробуем Gemini
    if gemini_model:
        try:
            resp = gemini_model.generate_content(prompt)
            return resp.text.strip()
        except Exception as e:
            print(f"  Gemini error: {e} — fallback to Groq")

    # Fallback: Groq
    if groq_client:
        try:
            resp = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=400,
                temperature=0.6,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            err = str(e)
            if "rate_limit_exceeded" in err or "429" in err:
                import re
                wait = re.search(r"try again in (\d+)m", err)
                wait_sec = int(wait.group(1)) * 60 + 30 if wait else 180
                print(f"  Groq rate limit — жду {wait_sec}s...")
                time.sleep(wait_sec)
                try:
                    resp2 = groq_client.chat.completions.create(
                        model="llama-3.3-70b-versatile",
                        messages=[{"role": "user", "content": prompt}],
                        max_tokens=400,
                        temperature=0.6,
                    )
                    return resp2.choices[0].message.content.strip()
                except Exception as e2:
                    print(f"  Groq retry failed: {e2}")
            else:
                print(f"  Groq error: {e}")
    raise RuntimeError("Нет доступного генератора")


def generate_post(title: str, snippet: str, url: str, region: str) -> str:
    region_header = REGION_HEADER.get(region, region)
    region_hint = {
        "Kazakhstan":  "Казахстан",
        "CentralAsia": "укажи конкретную страну (Казахстан/Узбекистан/Кыргызстан и т.д.)",
        "World":       "укажи конкретную страну или компанию",
    }.get(region, "")

    prompt = (
        "Ты редактор Telegram-канала о венчурном капитале в Центральной Азии.\n"
        "Напиши новостной пост на РУССКОМ языке строго по этой статье.\n\n"
        "ИСТОЧНИК (используй ТОЛЬКО эти факты, не добавляй ничего от себя):\n"
        f"Заголовок: {title}\n"
        f"Содержание: {snippet}\n"
        f"Ссылка: {url}\n\n"
        f"ВАЖНО про страну: {region_hint}. "
        "Никогда не пиши 'президент', 'правительство' без названия страны.\n"
        f"Начни пост ТОЧНО со слова: {region_header}\n"
        "Затем пустая строка, затем сам пост.\n\n"
        "Структура — ровно 2 предложения:\n"
        "1. Что произошло — кто, что, сколько (конкретные цифры из источника).\n"
        "2. Конкретный вывод или последствие для рынка — только из источника.\n\n"
        "Правила: нейтральный деловой язык, без эмодзи, без хэштегов, "
        "ТОЛЬКО факты из источника, длина 200-350 символов.\n"
    )
    try:
        text = _call_llm(prompt)
        if not text.startswith(region_header):
            text = f"{region_header}\n\n{text}"
        return f"{text}\n\n{url}"
    except Exception as e:
        print(f"  Generation failed: {e}")
        return None


def save_bulk_pending(title: str, url: str, post_text: str, region: str) -> str:
    try:
        res = supabase.table("pending_posts").insert({
            "title":     title,
            "url":       url,
            "post_text": post_text,
            "image_url": "",
            "region":    region,
            "status":    "bulk_pending",  # отдельный статус для bulk review
        }).execute()
        return res.data[0]["id"]
    except Exception as e:
        print(f"  Save error: {e}")
        return None


# ────────────────────────────────────────────────
# MAIN
# ────────────────────────────────────────────────
def main():
    print(f"BULK SEED | {datetime.utcnow().isoformat()} UTC")
    print(f"Target: {TARGET_COUNT} posts | Search window: {SEARCH_DAYS} days")
    print("=" * 50)

    notify(f"⚙️ Bulk seed запущен. Генерирую до {TARGET_COUNT} постов из архива за {SEARCH_DAYS} дней...")

    all_articles = []
    seen_urls    = set()

    seen_title_keys = set()  # дедупликация по теме (не только по URL)

    for search in ARCHIVE_QUERIES:
        print(f"\nSearching: {search['query'][:60]}")
        try:
            results = tavily.search(
                query=search["query"],
                search_depth="basic",
                max_results=15,
                days=SEARCH_DAYS,
            )
            for r in results.get("results", []):
                url = r.get("url", "")
                if not url or url in seen_urls:
                    continue
                if any(d in url for d in BLOCKED_DOMAINS):
                    continue
                title   = r.get("title", "").strip()
                snippet = r.get("content", "")[:500]
                combined = (title + " " + snippet).lower()

                # Фильтр списков и дайджестов
                if any(pat in title.lower() for pat in SKIP_TITLE_PATTERNS):
                    print(f"  Skip (list/digest): {title[:60]}")
                    continue

                # Фильтр VC-релевантности
                if not any(kw in combined for kw in VC_KEYWORDS):
                    continue

                # Дедупликация по теме: берём 3 ключевых слова из заголовка
                title_words = [w for w in title.lower().split()
                               if len(w) > 4 and w not in
                               {"startup","стартап","raises","привлёк","привлек",
                                "funding","venture","capital","from","that","with",
                                "казахстан","kazakhstan","узбекистан","uzbekistan"}]
                title_key = " ".join(sorted(title_words[:3]))
                if title_key and title_key in seen_title_keys:
                    print(f"  Skip (duplicate topic): {title[:60]}")
                    continue

                if is_already_in_db(url):
                    print(f"  Already in DB: {url[:60]}")
                    continue

                seen_urls.add(url)
                if title_key:
                    seen_title_keys.add(title_key)
                all_articles.append({
                    "title":   title,
                    "url":     url,
                    "snippet": snippet,
                    "region":  search["region"],
                })
            time.sleep(0.3)  # rate limit
        except Exception as e:
            print(f"  Tavily error: {e}")

    print(f"\n{'='*50}")
    print(f"Articles found: {len(all_articles)}")

    if not all_articles:
        notify("❌ Bulk seed: не нашлось статей. Проверь TAVILY_API_KEY.")
        return

    # Ограничиваем до TARGET_COUNT
    articles_to_process = all_articles[:TARGET_COUNT]
    print(f"Processing: {len(articles_to_process)} articles")

    generated = 0
    failed    = 0

    for i, article in enumerate(articles_to_process, 1):
        print(f"\n[{i}/{len(articles_to_process)}] {article['title'][:60]}")
        post_text = generate_post(
            title=article["title"],
            snippet=article["snippet"],
            url=article["url"],
            region=article["region"],
        )
        if not post_text:
            failed += 1
            continue

        pid = save_bulk_pending(
            title=article["title"],
            url=article["url"],
            post_text=post_text,
            region=article["region"],
        )
        if pid:
            generated += 1
            print(f"  ✓ Saved [{article['region']}] ID: {pid[:8]}...")
        else:
            failed += 1

        # Пауза каждые 10 запросов чтобы не перегрузить Groq rate limit
        if i % 10 == 0:
            print(f"  Rate limit pause (10 req)...")
            time.sleep(3)

    print(f"\n{'='*50}")
    print(f"DONE: {generated} posts generated, {failed} failed")

    notify(
        f"✅ Bulk seed завершён!\n"
        f"Сгенерировано: {generated} постов\n"
        f"Ошибок: {failed}\n\n"
        f"Напиши /bulk чтобы начать ревью — каждый пост придёт отдельно с кнопками фидбэка."
    )


if __name__ == "__main__":
    main()
