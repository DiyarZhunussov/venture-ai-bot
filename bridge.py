import os
import sys
import asyncio
import feedparser
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from supabase import create_client, Client
import google.generativeai as genai
from telegram import Bot
from telegram.error import TelegramError

# ────────────────────────────────────────────────
# ENVIRONMENT VARIABLES
# ────────────────────────────────────────────────
GEMINI_API_KEY         = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN     = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID       = os.getenv("TELEGRAM_CHAT_ID")
TELEGRAM_ADMIN_ID      = os.getenv("TELEGRAM_ADMIN_ID")
SUPABASE_URL           = os.getenv("SUPABASE_URL")
SUPABASE_KEY           = os.getenv("SUPABASE_KEY")
UNSPLASH_ACCESS_KEY    = os.getenv("UNSPLASH_ACCESS_KEY")

if not all([GEMINI_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, SUPABASE_URL, SUPABASE_KEY]):
    print("❌ Missing required environment variables.")
    sys.exit(1)

# ────────────────────────────────────────────────
# INITIALIZATION
# ────────────────────────────────────────────────
genai.configure(api_key=GEMINI_API_KEY)
model    = genai.GenerativeModel('gemini-3-flash-preview')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
bot      = Bot(token=TELEGRAM_BOT_TOKEN)

# ────────────────────────────────────────────────
# RSS SOURCES — each tagged with a region
# ────────────────────────────────────────────────
RSS_SOURCES = [
    # ── Kazakhstan ──────────────────────────────
    {"url": "https://kursiv.kz/rss/all",              "region": "Казахстан"},
    {"url": "https://digitalbusiness.kz/feed/",        "region": "Казахстан"},
    {"url": "https://forbes.kz/rss/allarticles",       "region": "Казахстан"},
    {"url": "https://capital.kz/rss/",                 "region": "Казахстан"},

    # ── Central Asia ────────────────────────────
    {"url": "https://www.spot.uz/ru/rss/",             "region": "Центральная Азия"},
    {"url": "https://www.wepost.media/rss",            "region": "Центральная Азия"},

    # ── Global ──────────────────────────────────
    {"url": "https://techcrunch.com/feed/",            "region": "Мир"},
    {"url": "https://news.ycombinator.com/rss",        "region": "Мир"},
    {"url": "https://vc.ru/rss/all",                   "region": "Мир"},
]

# Local news is always preferred over global
REGION_PRIORITY = {"Казахстан": 0, "Центральная Азия": 1, "Мир": 2}

# Region emoji labels shown at the top of every post
REGION_EMOJI = {
    "Казахстан":       "🇰🇿 Казахстан",
    "Центральная Азия": "🌏 Центральная Азия",
    "Мир":             "🌍 Мир",
}

# ────────────────────────────────────────────────
# SUPABASE HELPERS
# ────────────────────────────────────────────────
def is_already_posted(url_or_text: str) -> bool:
    try:
        res = supabase.table("posted_news").select("id").eq("url_text", url_or_text).execute()
        return len(res.data) > 0
    except Exception as e:
        print(f"Supabase check error: {e}")
        return False

def add_to_posted(url_or_text: str, news_type: str, score: int, source_type: str):
    try:
        supabase.table("posted_news").insert({
            "url_text":           url_or_text,
            "news_type":          news_type,
            "shareability_score": score,
            "source_type":        source_type,
        }).execute()
    except Exception as e:
        print(f"Failed to save to posted_news: {e}")

def get_posted_count() -> int:
    """Returns total number of published posts."""
    try:
        res = supabase.table("posted_news").select("count", count="exact").execute()
        return res.count or 0
    except Exception as e:
        print(f"Failed to get post count: {e}")
        return 999  # fail-safe: skip approval mode

def save_pending_post(candidate: dict, post_text: str, image_url: str | None) -> str | None:
    """Saves a generated post awaiting admin approval. Returns row ID."""
    try:
        res = supabase.table("pending_posts").insert({
            "title":     candidate["title"],
            "url":       candidate["url"],
            "post_text": post_text,
            "image_url": image_url or "",
            "region":    candidate["region"],
            "status":    "pending",
        }).execute()
        return res.data[0]["id"]
    except Exception as e:
        print(f"Failed to save pending post: {e}")
        return None

def fetch_negative_constraints() -> list:
    try:
        res = supabase.table("negative_constraints").select("feedback").execute()
        return [row["feedback"].lower() for row in res.data]
    except Exception as e:
        print(f"Failed to load negative constraints: {e}")
        return []

# ────────────────────────────────────────────────
# UNSPLASH
# ────────────────────────────────────────────────
def get_unsplash_image(query: str) -> str | None:
    if not UNSPLASH_ACCESS_KEY:
        return None
    try:
        url = f"https://api.unsplash.com/search/photos?query={query}&per_page=1"
        headers = {"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"}
        resp = requests.get(url, headers=headers, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("results"):
                return data["results"][0]["urls"]["regular"]
    except Exception as e:
        print(f"Unsplash error: {e}")
    return None

# ────────────────────────────────────────────────
# PUBLISH HELPER
# ────────────────────────────────────────────────
async def publish_post(candidate: dict, post_text: str, image_url: str | None):
    print("📤 Публикация в канал...")
    try:
        if image_url:
            await bot.send_photo(
                chat_id=TELEGRAM_CHAT_ID,
                photo=image_url,
                caption=post_text,
                parse_mode="HTML" if "<" in post_text else None
            )
        else:
            await bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=post_text,
                disable_web_page_preview=False
            )

        add_to_posted(candidate["key"], "НОВОСТЬ", 7, candidate["region"])
        print("🎉 ОПУБЛИКОВАНО!")

        await bot.send_message(
            TELEGRAM_ADMIN_ID,
            f"✅ Опубликован пост [{candidate['region']}]:\n\n{post_text[:200]}...\n\nСсылка: {candidate['url']}"
        )
    except TelegramError as te:
        print(f"Telegram ошибка: {te}")
        await bot.send_message(TELEGRAM_ADMIN_ID, f"Ошибка отправки: {str(te)}")

# ────────────────────────────────────────────────
# MAIN
# ────────────────────────────────────────────────
async def main():
    print("🚀 ЗАПУСК MAIN BOT")
    print(f"Время запуска: {datetime.utcnow().isoformat()} UTC")

    negative_rules = fetch_negative_constraints()
    print(f"Загружено анти-кейсов: {len(negative_rules)}")

    posted_count  = get_posted_count()
    approval_mode = posted_count < 100
    print(f"Опубликовано постов: {posted_count} → режим: {'ОДОБРЕНИЕ' if approval_mode else 'АВТОМАТ'}")

    candidates = []

    # 1. Parse RSS
    print("📡 Парсинг RSS...")
    for source in RSS_SOURCES:
        source_url = source["url"]
        region     = source["region"]
        try:
            feed = feedparser.parse(source_url, request_headers={"User-Agent": "VentureAIBot/1.0"})
            if not feed.entries:
                print(f"  Нет записей в {source_url}")
                continue

            for entry in feed.entries[:10]:
                title   = entry.get("title", "").strip()
                link    = entry.get("link", "")
                summary = entry.get("summary", "") or entry.get("description", "")

                check_key     = link or summary[:100]
                if is_already_posted(check_key):
                    continue

                content_lower = (title + " " + summary).lower()
                if any(rule in content_lower for rule in negative_rules):
                    continue

                candidates.append({
                    "title":   title,
                    "url":     link,
                    "summary": summary,
                    "source":  source_url,
                    "region":  region,
                    "key":     check_key,
                })
        except Exception as e:
            print(f"Ошибка парсинга {source_url}: {e}")

    print(f"📊 Найдено кандидатов: {len(candidates)}")

    if not candidates:
        print("Нет подходящих новостей.")
        await bot.send_message(TELEGRAM_ADMIN_ID, "Main Bot: Нет подходящих новостей сегодня.")
        return

    # 2. Sort: Казахстан first, then ЦА, then Мир
    candidates.sort(key=lambda c: REGION_PRIORITY.get(c["region"], 99))
    best = candidates[0]
    print(f"🎯 Выбрана новость [{best['region']}]: {best['title']}")

    # 3. Generate post with Gemini
    print("🤖 Генерация поста с Gemini...")
    region_header = REGION_EMOJI.get(best["region"], best["region"])

    try:
        prompt = f"""
Ты — редактор Telegram-канала о венчурном рынке Центральной Азии.
Напиши короткий, увлекательный пост на русском языке (300–600 символов) на основе этой новости.

Заголовок: {best['title']}
Ссылка: {best['url']}
Краткое содержание: {best['summary'][:800]}

ВАЖНО: Начни пост СТРОГО с этой строки (скопируй её точно):
{region_header}

Затем с новой строки пиши сам текст поста.
Стиль: информативный, лёгкий анализ, эмодзи, призыв к обсуждению в комментариях.
Не добавляй хэштеги. Не пиши слишком длинно.
"""
        response  = model.generate_content(prompt)
        post_text = response.text.strip()

        # Guarantee the region label is always at the top
        if not post_text.startswith(region_header):
            post_text = f"{region_header}\n\n{post_text}"

        # Get image: try og:image from article, fallback to Unsplash
        image_url = None
        if best["url"]:
            try:
                page = requests.get(best["url"], timeout=10)
                soup = BeautifulSoup(page.text, "lxml")
                img  = soup.find("meta", property="og:image")
                if img and img.get("content"):
                    image_url = img["content"]
            except:
                pass
        if not image_url:
            image_url = get_unsplash_image(best["title"] or "venture capital startup")

        print(f"✅ Готов пост ({len(post_text)} символов)")

    except Exception as e:
        print(f"Gemini error: {e}")
        await bot.send_message(TELEGRAM_ADMIN_ID, f"Gemini ошибка: {str(e)}")
        return

    # Append source link to post text (for both approval and auto modes)
    if best.get("url"):
        post_text = f"{post_text}\n\n🔗 {best['url']}"

    # 4a. APPROVAL MODE — first 100 posts: ask admin before publishing
    if approval_mode:
        pending_id = save_pending_post(best, post_text, image_url)
        if not pending_id:
            await bot.send_message(TELEGRAM_ADMIN_ID, "❌ Не удалось сохранить пост на одобрение.")
            return

        preview = (
            f"📋 ПОСТ НА ОДОБРЕНИЕ (#{posted_count + 1}/100)\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{post_text}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ Опубликовать: /approve {pending_id}\n"
            f"❌ Отклонить:    /reject {pending_id} <причина>"
        )
        await bot.send_message(TELEGRAM_ADMIN_ID, preview)
        print(f"📨 Пост отправлен на одобрение. ID: {pending_id}")

    # 4b. AUTO MODE — after 100 posts: publish immediately
    else:
        await publish_post(best, post_text, image_url)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"Критическая ошибка: {e}")
        if TELEGRAM_ADMIN_ID:
            try:
                asyncio.run(bot.send_message(TELEGRAM_ADMIN_ID, f"Main Bot крашнулся: {str(e)}"))
            except:
                pass
        sys.exit(1)
