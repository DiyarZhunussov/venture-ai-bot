import os
import sys
import feedparser
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from supabase import create_client, Client
import google.generativeai as genai
from telegram import Bot
from telegram.error import TelegramError

# ────────────────────────────────────────────────
# ENVIRONMENT VARIABLES (from GitHub Secrets)
# ────────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")           # channel ID, e.g. -1001234567890
TELEGRAM_ADMIN_ID = os.getenv("TELEGRAM_ADMIN_ID")         # your personal ID for reports
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")                   # anon public key
UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY")     # optional

if not all([GEMINI_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, SUPABASE_URL, SUPABASE_KEY]):
    print("❌ Missing required environment variables. Check GitHub Secrets.")
    sys.exit(1)

# ────────────────────────────────────────────────
# INITIALIZATION
# ────────────────────────────────────────────────
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-3-flash-preview')  # or 'gemini-1.5-pro', 'gemini-2.0-flash' etc.

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
bot = Bot(token=TELEGRAM_BOT_TOKEN)

# Example RSS sources (expand this list!)
RSS_SOURCES = [
    # Global / Tier-1 (working)
    "https://techcrunch.com/feed/",
    "https://www.crunchbase.com/feed/news",
    "https://news.ycombinator.com/rss",  # good for startup trends

    # Kazakhstan / Central Asia (check if still active; some moved)
    "https://kursiv.kz/rss/all",                # Kursiv.kz — main VC/news
    "https://digitalbusiness.kz/feed/",         # Digital Business
    "https://forbes.kz/rss/allarticles",        # Forbes Kazakhstan (may need update)
    "https://capital.kz/rss/",                  # Capital.kz
    "https://www.spot.uz/ru/rss/",              # Spot.uz (Uzbekistan)

    # Other useful
    "https://www.wepost.media/rss",             # WeProject
    "https://vc.ru/rss/all",                    # vc.ru — Russian VC, often covers CA
]

def is_already_posted(url_or_text: str) -> bool:
    """Check if URL or first 100 chars already in posted_news table"""
    try:
        response = supabase.table("posted_news").select("id").eq("url_text", url_or_text).execute()
        return len(response.data) > 0
    except Exception as e:
        print(f"Supabase check error: {e}")
        return False

def add_to_posted(url_or_text: str, news_type: str, score: int, source_type: str):
    try:
        supabase.table("posted_news").insert({
            "url_text": url_or_text,
            "news_type": news_type,          # "НОВОСТЬ" or "ОБУЧЕНИЕ"
            "shareability_score": score,
            "source_type": source_type,      # "tier1", "local", "education"
        }).execute()
    except Exception as e:
        print(f"Failed to save to posted_news: {e}")

def fetch_negative_constraints() -> list:
    try:
        response = supabase.table("negative_constraints").select("feedback").execute()
        return [row["feedback"].lower() for row in response.data]
    except Exception as e:
        print(f"Failed to load negative constraints: {e}")
        return []

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

def main():
    print("🚀 ЗАПУСК MAIN BOT")
    print(f"Время запуска: {datetime.utcnow().isoformat()} UTC")

    negative_rules = fetch_negative_constraints()
    print(f"Загружено анти-кейсов: {len(negative_rules)}")

    candidates = []

    # 1. Parse RSS
    print("📡 Парсинг RSS...")
    for source_url in RSS_SOURCES:
        try:
            feed = feedparser.parse(source_url, request_headers={"User-Agent": "VentureAIBot/1.0"})
            if not feed.entries:
                print(f"  Нет записей в {source_url}")
                continue

            for entry in feed.entries[:10]:  # limit per source
                title = entry.get("title", "").strip()
                link = entry.get("link", "")
                summary = entry.get("summary", "") or entry.get("description", "")

                # Deduplication
                check_key = link or summary[:100]
                if is_already_posted(check_key):
                    continue

                # Simple negative filter (expand logic as needed)
                content_lower = (title + " " + summary).lower()
                if any(rule in content_lower for rule in negative_rules):
                    continue

                candidates.append({
                    "title": title,
                    "url": link,
                    "summary": summary,
                    "source": source_url,
                    "key": check_key
                })
        except Exception as e:
            print(f"Ошибка парсинга {source_url}: {e}")

    print(f"📊 Найдено кандидатов после фильтров: {len(candidates)}")

    if not candidates:
        print("Нет подходящих новостей для публикации.")
        bot.send_message(TELEGRAM_ADMIN_ID, "Main Bot: Нет подходящих новостей сегодня.")
        return

    # 2. Select best candidate (simple: first for now; improve with scoring later)
    best = candidates[0]
    print(f"🎯 Выбрана новость: {best['title']}")

    # 3. Generate post with Gemini
    print("🤖 Генерация поста с Gemini...")
    try:
        prompt = f"""
Ты — редактор Telegram-канала о венчурном рынке Центральной Азии.
Напиши короткий, увлекательный пост на русском языке (300–600 символов) на основе этой новости:

Заголовок: {best['title']}
Ссылка: {best['url']}
Краткое содержание: {best['summary'][:800]}

Стиль: информативный, с лёгким анализом, эмодзи, призыв к обсуждению в комментариях.
Не добавляй хэштеги и не пиши слишком длинно.
"""
        response = model.generate_content(prompt)
        post_text = response.text.strip()

        # Add image (try parse or Unsplash)
        image_url = None
        # Option 1: try to extract from article
        if best["url"]:
            try:
                page = requests.get(best["url"], timeout=10)
                soup = BeautifulSoup(page.text, "lxml")
                img = soup.find("meta", property="og:image")
                if img and img.get("content"):
                    image_url = img["content"]
            except:
                pass

        # Option 2: Unsplash fallback
        if not image_url:
            image_url = get_unsplash_image(best["title"] or "venture capital startup")

        print(f"✅ Готов пост ({len(post_text)} символов)")
    except Exception as e:
        print(f"Gemini error: {e}")
        bot.send_message(TELEGRAM_ADMIN_ID, f"Gemini ошибка: {str(e)}")
        return

    # 4. Publish to channel
    print("📤 Публикация в канал...")
    try:
        if image_url:
            bot.send_photo(
                chat_id=TELEGRAM_CHAT_ID,
                photo=image_url,
                caption=post_text,
                parse_mode="HTML" if "<" in post_text else None
            )
        else:
            bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=post_text,
                disable_web_page_preview=False
            )

        # Mark as posted
        add_to_posted(best["key"], "НОВОСТЬ", 7, "tier1")  # example score & type

        print("🎉 ОПУБЛИКОВАНО!")
        bot.send_message(
            TELEGRAM_ADMIN_ID,
            f"✅ Опубликован пост:\n\n{post_text[:200]}...\n\nСсылка: {best['url']}"
        )
    except TelegramError as te:
        print(f"Telegram ошибка: {te}")
        bot.send_message(TELEGRAM_ADMIN_ID, f"Ошибка отправки: {str(te)}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Критическая ошибка: {e}")
        if TELEGRAM_ADMIN_ID:
            try:
                bot.send_message(TELEGRAM_ADMIN_ID, f"Main Bot крашнулся: {str(e)}")
            except:
                pass
        sys.exit(1)
