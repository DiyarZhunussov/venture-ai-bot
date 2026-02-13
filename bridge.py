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
GEMINI_API_KEY      = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID")
TELEGRAM_ADMIN_ID   = os.getenv("TELEGRAM_ADMIN_ID")
SUPABASE_URL        = os.getenv("SUPABASE_URL")
SUPABASE_KEY        = os.getenv("SUPABASE_KEY")
UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY")
POST_TYPE           = os.getenv("POST_TYPE", "news")  # "news" or "education"

if not all([GEMINI_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, SUPABASE_URL, SUPABASE_KEY]):
    print("Missing required environment variables.")
    sys.exit(1)

# ────────────────────────────────────────────────
# INITIALIZATION
# ────────────────────────────────────────────────
genai.configure(api_key=GEMINI_API_KEY)
model    = genai.GenerativeModel('gemini-3-flash-preview')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
bot      = Bot(token=TELEGRAM_BOT_TOKEN)

# ────────────────────────────────────────────────
# RSS SOURCES
# ────────────────────────────────────────────────
RSS_SOURCES = [
    {"url": "https://kursiv.kz/rss/all",           "region": "Kazakhstan"},
    {"url": "https://digitalbusiness.kz/feed/",     "region": "Kazakhstan"},
    {"url": "https://forbes.kz/rss/allarticles",    "region": "Kazakhstan"},
    {"url": "https://capital.kz/rss/",              "region": "Kazakhstan"},
    {"url": "https://www.spot.uz/ru/rss/",          "region": "CentralAsia"},
    {"url": "https://www.wepost.media/rss",         "region": "CentralAsia"},
    {"url": "https://techcrunch.com/feed/",         "region": "World"},
    {"url": "https://news.ycombinator.com/rss",     "region": "World"},
    {"url": "https://vc.ru/rss/all",                "region": "World"},
]

REGION_PRIORITY = {"Kazakhstan": 0, "CentralAsia": 1, "World": 2}

REGION_LABEL = {
    "Kazakhstan":  "Kazakhstan",
    "CentralAsia": "Central Asia",
    "World":       "World",
}

REGION_EMOJI = {
    "Kazakhstan":  "KZ Kazakhstan",
    "CentralAsia": "Central Asia",
    "World":       "World",
}

EDUCATION_TOPICS = [
    "What is venture capital and how it works",
    "How startups go through a seed round",
    "Difference between pre-seed, seed and Series A",
    "What is a term sheet and what to look for",
    "How a startup cap table works",
    "What is product-market fit and how to find it",
    "Unit economics: how to calculate CAC and LTV",
    "How to pitch investors: pitch deck structure",
    "What is due diligence and how to prepare",
    "Vesting and cliff: how employee option programs work",
    "What is runway and burn rate",
    "Bootstrapping vs venture funding: pros and cons",
    "How accelerators work and how they differ from incubators",
    "What is a convertible note and SAFE",
    "How venture funds make money",
]

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
    try:
        res = supabase.table("posted_news").select("count", count="exact").execute()
        return res.count or 0
    except Exception as e:
        print(f"Failed to get post count: {e}")
        return 999

def save_pending_post(candidate: dict, post_text: str, image_url) -> str:
    try:
        res = supabase.table("pending_posts").insert({
            "title":     candidate["title"],
            "url":       candidate.get("url", ""),
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
def get_unsplash_image(query: str):
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
async def publish_post(candidate: dict, post_text: str, image_url, news_type: str):
    print("Sending to channel...")
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

        add_to_posted(candidate["key"], news_type, 7, candidate["region"])
        print("PUBLISHED!")

        await bot.send_message(
            TELEGRAM_ADMIN_ID,
            f"Published [{candidate['region']}]:\n\n{post_text[:200]}..."
        )
    except TelegramError as te:
        print(f"Telegram error: {te}")
        await bot.send_message(TELEGRAM_ADMIN_ID, f"Send error: {str(te)}")

# ────────────────────────────────────────────────
# EDUCATION POST LOGIC
# ────────────────────────────────────────────────
async def run_education(posted_count: int, approval_mode: bool):
    print("MODE: EDUCATION POST (17:00)")

    topic     = EDUCATION_TOPICS[posted_count % len(EDUCATION_TOPICS)]
    dedup_key = f"education_{topic[:60]}"

    print(f"Topic: {topic}")

    if is_already_posted(dedup_key):
        print(f"Topic already used: {topic}")
        await bot.send_message(TELEGRAM_ADMIN_ID, f"Education: topic already used, skipping.")
        return

    try:
        prompt = (
            "You are the editor of a Telegram channel about venture capital in Central Asia.\n"
            "Write a short educational post in RUSSIAN about this topic:\n\n"
            f"\"{topic}\"\n\n"
            "Requirements:\n"
            "- Length: 400-700 characters\n"
            "- Start the post EXACTLY with this line: 'OBUCHENIE' (use Cyrillic: 'Обучение')\n"
            "- Actually use the Cyrillic header: start with exactly this: 'Обучение'\n"
            "- Explain the topic simply for early-stage founders\n"
            "- Use concrete examples, numbers or analogies\n"
            "- Add emojis for readability\n"
            "- End with a question or call to discussion\n"
            "- No hashtags\n"
        )
        response  = model.generate_content(prompt)
        post_text = response.text.strip()

        if not post_text.startswith("Обучение"):
            post_text = f"Обучение\n\n{post_text}"

        print(f"Education post ready ({len(post_text)} chars)")

    except Exception as e:
        print(f"Gemini error: {e}")
        await bot.send_message(TELEGRAM_ADMIN_ID, f"Gemini error (education): {str(e)}")
        return

    candidate = {"title": topic, "url": "", "region": "Education", "key": dedup_key}

    if approval_mode:
        pending_id = save_pending_post(candidate, post_text, None)
        if not pending_id:
            await bot.send_message(TELEGRAM_ADMIN_ID, "Failed to save education post for approval.")
            return

        preview = (
            f"EDUCATION POST FOR APPROVAL (#{posted_count + 1}/100)\n"
            f"--------------------\n"
            f"{post_text}\n"
            f"--------------------\n"
            f"Approve: /approve {pending_id}\n"
            f"Reject:  /reject {pending_id} reason here"
        )
        await bot.send_message(TELEGRAM_ADMIN_ID, preview)
        print(f"Education post sent for approval. ID: {pending_id}")
    else:
        await publish_post(candidate, post_text, None, "EDUCATION")

# ────────────────────────────────────────────────
# NEWS POST LOGIC
# ────────────────────────────────────────────────
async def run_news(posted_count: int, approval_mode: bool, negative_rules: list):
    print("MODE: NEWS POST (08:00)")

    candidates = []

    print("Parsing RSS...")
    for source in RSS_SOURCES:
        source_url = source["url"]
        region     = source["region"]
        try:
            feed = feedparser.parse(source_url, request_headers={"User-Agent": "VentureAIBot/1.0"})
            if not feed.entries:
                print(f"  No entries in {source_url}")
                continue

            for entry in feed.entries[:10]:
                title     = entry.get("title", "").strip()
                link      = entry.get("link", "")
                summary   = entry.get("summary", "") or entry.get("description", "")
                check_key = link or summary[:100]

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
            print(f"Parse error {source_url}: {e}")

    print(f"Candidates found: {len(candidates)}")

    if not candidates:
        print("No suitable news today.")
        await bot.send_message(TELEGRAM_ADMIN_ID, "Main Bot: No suitable news today.")
        return

    candidates.sort(key=lambda c: REGION_PRIORITY.get(c["region"], 99))
    best = candidates[0]
    print(f"Selected [{best['region']}]: {best['title']}")

    region_header = REGION_EMOJI.get(best["region"], best["region"])

    try:
        prompt = (
            "You are the editor of a Telegram channel about venture capital in Central Asia.\n"
            "Write a short engaging post in RUSSIAN (300-600 characters) based on this news:\n\n"
            f"Title: {best['title']}\n"
            f"Link: {best['url']}\n"
            f"Summary: {best['summary'][:800]}\n\n"
            f"IMPORTANT: Start the post EXACTLY with this first line: {region_header}\n"
            "Then write the post text on a new line.\n"
            "Style: informative, light analysis, emojis, call to discuss in comments.\n"
            "No hashtags. Keep it concise.\n"
        )
        response  = model.generate_content(prompt)
        post_text = response.text.strip()

        if not post_text.startswith(region_header):
            post_text = f"{region_header}\n\n{post_text}"

        # Append source link
        if best["url"]:
            post_text = f"{post_text}\n\n{best['url']}"

        # Get image
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
            image_url = get_unsplash_image(best["title"] or "venture capital")

        print(f"Post ready ({len(post_text)} chars)")

    except Exception as e:
        print(f"Gemini error: {e}")
        await bot.send_message(TELEGRAM_ADMIN_ID, f"Gemini error: {str(e)}")
        return

    if approval_mode:
        pending_id = save_pending_post(best, post_text, image_url)
        if not pending_id:
            await bot.send_message(TELEGRAM_ADMIN_ID, "Failed to save post for approval.")
            return

        preview = (
            f"POST FOR APPROVAL (#{posted_count + 1}/100)\n"
            f"--------------------\n"
            f"{post_text}\n"
            f"--------------------\n"
            f"Approve: /approve {pending_id}\n"
            f"Reject:  /reject {pending_id} reason here"
        )
        await bot.send_message(TELEGRAM_ADMIN_ID, preview)
        print(f"Post sent for approval. ID: {pending_id}")
    else:
        await publish_post(best, post_text, image_url, "NEWS")

# ────────────────────────────────────────────────
# MAIN
# ────────────────────────────────────────────────
async def main():
    print(f"STARTING MAIN BOT | {datetime.utcnow().isoformat()} UTC | TYPE: {POST_TYPE.upper()}")

    negative_rules = fetch_negative_constraints()
    print(f"Anti-cases loaded: {len(negative_rules)}")

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
