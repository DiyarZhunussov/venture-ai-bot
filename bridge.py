import os
import sys
import asyncio
import requests
from datetime import datetime
from supabase import create_client, Client
import google.generativeai as genai
from telegram import Bot
from telegram.error import TelegramError

# ────────────────────────────────────────────────
# ENVIRONMENT VARIABLES
# ────────────────────────────────────────────────
GEMINI_API_KEY          = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN      = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID        = os.getenv("TELEGRAM_CHAT_ID")         # channel OR supergroup ID
TELEGRAM_ADMIN_ID       = os.getenv("TELEGRAM_ADMIN_ID")
SUPABASE_URL            = os.getenv("SUPABASE_URL")
SUPABASE_KEY            = os.getenv("SUPABASE_KEY")
UNSPLASH_ACCESS_KEY     = os.getenv("UNSPLASH_ACCESS_KEY")
GOOGLE_SEARCH_API_KEY   = os.getenv("GOOGLE_SEARCH_API_KEY")
GOOGLE_SEARCH_ENGINE_ID = os.getenv("GOOGLE_SEARCH_ENGINE_ID")
POST_TYPE               = os.getenv("POST_TYPE", "news")        # "news" or "education"

# Supergroup topic thread IDs (optional — leave empty to post to channel instead)
NEWS_THREAD_ID          = os.getenv("TELEGRAM_NEWS_THREAD_ID")       # e.g. "12345"
EDUCATION_THREAD_ID     = os.getenv("TELEGRAM_EDUCATION_THREAD_ID")  # e.g. "12346"

if not all([GEMINI_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, SUPABASE_URL, SUPABASE_KEY]):
    print("Missing required environment variables.")
    sys.exit(1)

if not GOOGLE_SEARCH_API_KEY or not GOOGLE_SEARCH_ENGINE_ID:
    print("Warning: GOOGLE_SEARCH_API_KEY or GOOGLE_SEARCH_ENGINE_ID not set. Search will be skipped.")

# ────────────────────────────────────────────────
# INITIALIZATION
# ────────────────────────────────────────────────
genai.configure(api_key=GEMINI_API_KEY)
model    = genai.GenerativeModel('gemini-3-flash-preview')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
bot      = Bot(token=TELEGRAM_BOT_TOKEN)

# ────────────────────────────────────────────────
# GOOGLE SEARCH QUERIES BY REGION
# Results are filtered by Gemini for VC relevance
# ────────────────────────────────────────────────
SEARCH_QUERIES = [
    # Kazakhstan — high priority
    {"query": "стартапы венчурные инвестиции Казахстан 2026",         "region": "Kazakhstan",  "priority": 0},
    {"query": "Kazakhstan startup venture capital funding 2026",       "region": "Kazakhstan",  "priority": 0},
    {"query": "Казахстан венчурный фонд раунд инвестиции",            "region": "Kazakhstan",  "priority": 0},

    # Central Asia
    {"query": "стартапы венчурные инвестиции Центральная Азия 2026",  "region": "CentralAsia", "priority": 1},
    {"query": "Central Asia startup investment funding 2026",          "region": "CentralAsia", "priority": 1},
    {"query": "Узбекистан Кыргызстан стартап инвестиции",             "region": "CentralAsia", "priority": 1},

    # World — Tier-1 only
    {"query": "OpenAI Anthropic NVIDIA Google funding news 2026",      "region": "World",       "priority": 2},
    {"query": "top venture capital deal Series A B funding 2026",      "region": "World",       "priority": 2},
    {"query": "startup unicorn IPO major investment news 2026",        "region": "World",       "priority": 2},
]

REGION_EMOJI = {
    "Kazakhstan":  "Kazakhstan",
    "CentralAsia": "Central Asia",
    "World":       "World",
}

# ────────────────────────────────────────────────
# ACTIVAT VC COURSE LESSONS
# Sourced from activat.vc/startup-course/
# ────────────────────────────────────────────────
ACTIVAT_LESSONS = [
    {"title": "Какой путь проходят стартапы",          "url": "https://activat.vc/startup-course/lesson/kakoi-put-prohodyat-startapy"},
    {"title": "Что такое MVP и зачем он нужен",        "url": "https://activat.vc/startup-course/lesson/chto-takoe-mvp-i-zachem-on-nuzhen"},
    {"title": "Как найти product-market fit",          "url": "https://activat.vc/startup-course/lesson/kak-naiti-product-market-fit"},
    {"title": "Как привлечь первых клиентов",          "url": "https://activat.vc/startup-course/lesson/kak-privlech-pervyh-klientov"},
    {"title": "Юнит-экономика для стартапов",          "url": "https://activat.vc/startup-course/lesson/yunit-ekonomika-dlya-startapov"},
    {"title": "Как сделать питч-дек",                  "url": "https://activat.vc/startup-course/lesson/kak-sdelat-pitch-deck"},
    {"title": "Как работают венчурные инвестиции",     "url": "https://activat.vc/startup-course/lesson/kak-rabotayut-venchurnye-investicii"},
    {"title": "Что такое cap table",                   "url": "https://activat.vc/startup-course/lesson/chto-takoe-cap-table"},
    {"title": "Как проходит due diligence",            "url": "https://activat.vc/startup-course/lesson/kak-prohodit-due-diligence"},
    {"title": "Что такое term sheet",                  "url": "https://activat.vc/startup-course/lesson/chto-takoe-term-sheet"},
]

# Other education topics (internet/global VC knowledge)
GLOBAL_EDUCATION_TOPICS = [
    "Как работает венчурный капитал: полное объяснение для фаундеров",
    "Разница между pre-seed, seed и Series A раундами",
    "Как считать runway и burn rate стартапа",
    "Vesting и cliff: опционная программа для команды",
    "Bootstrapping vs венчурное финансирование: плюсы и минусы",
    "Как работают акселераторы и чем отличаются от инкубаторов",
    "Что такое convertible note и SAFE",
    "Как венчурные фонды зарабатывают деньги (модель 2-20)",
    "CAC и LTV: юнит-экономика которую хотят видеть инвесторы",
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

def add_to_posted(key: str, news_type: str, score: int, source_type: str):
    try:
        supabase.table("posted_news").insert({
            "url_text":           key,
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
        res = supabase.table("negative_constraints").select("feedback").execute()
        return [row["feedback"].lower() for row in res.data]
    except Exception as e:
        print(f"Failed to load negative constraints: {e}")
        return []

def get_education_day_counter() -> int:
    """Returns how many education posts have been published, used to alternate Activat vs global."""
    try:
        res = supabase.table("posted_news").select("count", count="exact").eq("news_type", "EDUCATION").execute()
        return res.count or 0
    except:
        return 0

# ────────────────────────────────────────────────
# GOOGLE SEARCH
# ────────────────────────────────────────────────
def google_search(query: str, num: int = 5) -> list:
    """Returns list of {title, url, snippet} from Google Custom Search API."""
    if not GOOGLE_SEARCH_API_KEY or not GOOGLE_SEARCH_ENGINE_ID:
        return []
    try:
        params = {
            "key": GOOGLE_SEARCH_API_KEY,
            "cx":  GOOGLE_SEARCH_ENGINE_ID,
            "q":   query,
            "num": num,
            "dateRestrict": "d7",  # last 7 days only
            "lr": "lang_ru|lang_en",
        }
        resp = requests.get("https://www.googleapis.com/customsearch/v1", params=params, timeout=10)
        if resp.status_code != 200:
            print(f"Google Search error {resp.status_code}: {resp.text[:200]}")
            return []
        items = resp.json().get("items", [])
        return [{"title": i.get("title",""), "url": i.get("link",""), "snippet": i.get("snippet","")} for i in items]
    except Exception as e:
        print(f"Google Search exception: {e}")
        return []

def is_vc_relevant(title: str, snippet: str, negative_rules: list) -> bool:
    """Quick keyword pre-filter before sending to Gemini."""
    vc_keywords = [
        "стартап", "венчур", "инвестиц", "раунд", "фонд", "startup", "venture",
        "funding", "investment", "series a", "series b", "seed", "pre-seed",
        "ipo", "unicorn", "единорог", "акселератор", "accelerator", "pitch",
        "openai", "anthropic", "nvidia", "google deepmind", "a16z", "sequoia",
        "y combinator", "techcrunch", "fintech", "edtech", "healthtech", "saas",
    ]
    content = (title + " " + snippet).lower()
    if any(rule in content for rule in negative_rules):
        return False
    return any(kw in content for kw in vc_keywords)

async def score_and_filter_with_gemini(candidates: list) -> dict:
    """
    Send top candidates to Gemini and ask it to pick the best one
    that is genuinely about startups/VC, not just tangentially related.
    Returns the best candidate dict or None.
    """
    if not candidates:
        return None

    articles_text = ""
    for i, c in enumerate(candidates[:10]):
        articles_text += f"{i+1}. [{c['region']}] {c['title']}\n   {c['snippet']}\n   URL: {c['url']}\n\n"

    try:
        prompt = (
            "You are a venture capital news editor for a Central Asian VC Telegram channel.\n"
            "From this list of articles, pick ONLY ONE that is the most relevant to startups and venture capital.\n"
            "It must be about: startup funding rounds, VC fund news, major tech company strategy (OpenAI, Anthropic, NVIDIA, Google), "
            "startup ecosystem, or venture market trends.\n"
            "Do NOT pick: consumer finance, taxes for individuals, sports, politics, general business news.\n\n"
            f"{articles_text}\n"
            "Respond with ONLY the number of the best article (e.g.: 3). Nothing else."
        )
        response = model.generate_content(prompt)
        choice   = response.text.strip().strip(".")
        idx      = int(choice) - 1
        if 0 <= idx < len(candidates[:10]):
            return candidates[idx]
    except Exception as e:
        print(f"Gemini scoring error: {e}")

    return candidates[0]  # fallback to first

# ────────────────────────────────────────────────
# TELEGRAM SEND HELPER (supports supergroup topics)
# ────────────────────────────────────────────────
async def send_to_channel(text: str, image_url: str, thread_id: str = None):
    """Send message to channel or supergroup topic."""
    kwargs = {"chat_id": TELEGRAM_CHAT_ID}
    if thread_id:
        kwargs["message_thread_id"] = int(thread_id)

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

# ────────────────────────────────────────────────
# NEWS POST LOGIC (08:00)
# ────────────────────────────────────────────────
async def run_news(posted_count: int, approval_mode: bool, negative_rules: list):
    print("MODE: NEWS (08:00)")

    all_candidates = []

    print("Searching via Google...")
    for search in SEARCH_QUERIES:
        results = google_search(search["query"], num=5)
        for r in results:
            if is_already_posted(r["url"]):
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

    print(f"Candidates after keyword filter: {len(all_candidates)}")

    if not all_candidates:
        print("No candidates found.")
        await bot.send_message(TELEGRAM_ADMIN_ID, "Main Bot: No suitable news found today.")
        return

    # Sort by region priority first
    all_candidates.sort(key=lambda c: c["priority"])

    # Let Gemini pick the best one
    best = await score_and_filter_with_gemini(all_candidates)
    if not best:
        print("Gemini could not select a candidate.")
        return

    print(f"Selected [{best['region']}]: {best['title']}")

    region_header = REGION_EMOJI.get(best["region"], best["region"])

    try:
        prompt = (
            "You are the editor of a Telegram channel about venture capital in Central Asia.\n"
            "Write a short engaging post in RUSSIAN (300-600 characters) based on this news:\n\n"
            f"Title: {best['title']}\n"
            f"Snippet: {best['snippet']}\n"
            f"URL: {best['url']}\n\n"
            f"IMPORTANT: Start the post EXACTLY with: {region_header}\n"
            "Then a new line, then the post text.\n"
            "Style: informative, light analysis, emojis, end with a question for discussion.\n"
            "No hashtags. Concise.\n"
        )
        response  = model.generate_content(prompt)
        post_text = response.text.strip()

        if not post_text.startswith(region_header):
            post_text = f"{region_header}\n\n{post_text}"

        # Append source link
        post_text = f"{post_text}\n\n{best['url']}"

        # Try to get og:image
        image_url = None
        try:
            from bs4 import BeautifulSoup
            page = requests.get(best["url"], timeout=8)
            soup = BeautifulSoup(page.text, "lxml")
            img  = soup.find("meta", property="og:image")
            if img and img.get("content"):
                image_url = img["content"]
        except:
            pass

        print(f"Post ready ({len(post_text)} chars)")

    except Exception as e:
        print(f"Gemini error: {e}")
        await bot.send_message(TELEGRAM_ADMIN_ID, f"Gemini error: {str(e)}")
        return

    candidate = {**best}

    if approval_mode:
        pending_id = save_pending_post(candidate, post_text, image_url)
        if not pending_id:
            await bot.send_message(TELEGRAM_ADMIN_ID, "Failed to save post for approval.")
            return
        preview = (
            f"NEWS POST FOR APPROVAL (#{posted_count + 1}/100)\n"
            f"--------------------\n"
            f"{post_text}\n"
            f"--------------------\n"
            f"Approve: /approve {pending_id}\n"
            f"Reject:  /reject {pending_id} reason here"
        )
        await bot.send_message(TELEGRAM_ADMIN_ID, preview)
        print(f"Sent for approval. ID: {pending_id}")
    else:
        await send_to_channel(post_text, image_url, NEWS_THREAD_ID)
        add_to_posted(best["key"], "NEWS", 8, best["region"])
        print("PUBLISHED!")
        await bot.send_message(TELEGRAM_ADMIN_ID, f"Published news:\n{post_text[:200]}...")

# ────────────────────────────────────────────────
# EDUCATION POST LOGIC (17:00)
# Alternates: even day = Activat VC lesson, odd day = global topic
# ────────────────────────────────────────────────
async def run_education(posted_count: int, approval_mode: bool):
    print("MODE: EDUCATION (17:00)")

    edu_count = get_education_day_counter()
    use_activat = (edu_count % 2 == 0)  # even = Activat, odd = global

    if use_activat:
        lesson_idx = (edu_count // 2) % len(ACTIVAT_LESSONS)
        lesson     = ACTIVAT_LESSONS[lesson_idx]
        topic      = lesson["title"]
        source_url = lesson["url"]
        dedup_key  = f"activat_{topic[:60]}"
        source_tag = f"Activat VC | {source_url}"
        print(f"Activat VC lesson: {topic}")
    else:
        topic_idx  = (edu_count // 2) % len(GLOBAL_EDUCATION_TOPICS)
        topic      = GLOBAL_EDUCATION_TOPICS[topic_idx]
        source_url = ""
        dedup_key  = f"education_{topic[:60]}"
        source_tag = "Global VC knowledge"
        print(f"Global topic: {topic}")

    if is_already_posted(dedup_key):
        print(f"Topic already used: {topic}")
        await bot.send_message(TELEGRAM_ADMIN_ID, f"Education: topic already used, skipping.")
        return

    try:
        if use_activat:
            prompt = (
                "You are the editor of a Telegram channel about venture capital in Central Asia.\n"
                "Write a short educational post in RUSSIAN about this Activat VC course topic:\n\n"
                f"Topic: \"{topic}\"\n"
                f"Course URL: {source_url}\n\n"
                "Requirements:\n"
                "- Length: 400-700 characters\n"
                "- Start EXACTLY with: Обучение | Activat VC\n"
                "- Explain the topic simply for early-stage founders\n"
                "- Add emojis for readability\n"
                "- End with: Подробнее в курсе Activat VC: {source_url}\n"
                "- No hashtags\n"
            )
        else:
            prompt = (
                "You are the editor of a Telegram channel about venture capital in Central Asia.\n"
                "Write a short educational post in RUSSIAN about this VC topic:\n\n"
                f"Topic: \"{topic}\"\n\n"
                "Requirements:\n"
                "- Length: 400-700 characters\n"
                "- Start EXACTLY with: Обучение\n"
                "- Explain the topic simply for early-stage founders\n"
                "- Use concrete examples, numbers or analogies\n"
                "- Add emojis for readability\n"
                "- End with a question or call to discussion\n"
                "- No hashtags\n"
            )

        response  = model.generate_content(prompt)
        post_text = response.text.strip()

        expected_start = "Обучение | Activat VC" if use_activat else "Обучение"
        if not post_text.startswith(expected_start):
            post_text = f"{expected_start}\n\n{post_text}"

        print(f"Education post ready ({len(post_text)} chars)")

    except Exception as e:
        print(f"Gemini error: {e}")
        await bot.send_message(TELEGRAM_ADMIN_ID, f"Gemini error (education): {str(e)}")
        return

    candidate = {
        "title":  topic,
        "url":    source_url,
        "region": "Education",
        "key":    dedup_key,
    }

    if approval_mode:
        pending_id = save_pending_post(candidate, post_text, None)
        if not pending_id:
            await bot.send_message(TELEGRAM_ADMIN_ID, "Failed to save education post for approval.")
            return
        preview = (
            f"EDUCATION POST FOR APPROVAL (#{posted_count + 1}/100)\n"
            f"Source: {source_tag}\n"
            f"--------------------\n"
            f"{post_text}\n"
            f"--------------------\n"
            f"Approve: /approve {pending_id}\n"
            f"Reject:  /reject {pending_id} reason here"
        )
        await bot.send_message(TELEGRAM_ADMIN_ID, preview)
        print(f"Education post sent for approval. ID: {pending_id}")
    else:
        await send_to_channel(post_text, None, EDUCATION_THREAD_ID)
        add_to_posted(dedup_key, "EDUCATION", 8, "Education")
        print("EDUCATION POST PUBLISHED!")
        await bot.send_message(TELEGRAM_ADMIN_ID, f"Published education:\n{post_text[:200]}...")

# ────────────────────────────────────────────────
# MAIN
# ────────────────────────────────────────────────
async def main():
    print(f"STARTING | {datetime.utcnow().isoformat()} UTC | TYPE: {POST_TYPE.upper()}")

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
