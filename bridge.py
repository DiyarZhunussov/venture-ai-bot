import os
import sys
import asyncio
import requests
from datetime import datetime
from supabase import create_client, Client
import google.generativeai as genai
from telegram import Bot
from telegram.error import TelegramError
from tavily import TavilyClient

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
TAVILY_API_KEY      = os.getenv("TAVILY_API_KEY")
POST_TYPE           = os.getenv("POST_TYPE", "news")

# Supergroup topic thread IDs (optional)
NEWS_THREAD_ID      = os.getenv("TELEGRAM_NEWS_THREAD_ID")
EDUCATION_THREAD_ID = os.getenv("TELEGRAM_EDUCATION_THREAD_ID")

if not all([GEMINI_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, SUPABASE_URL, SUPABASE_KEY]):
    print("Missing required environment variables.")
    sys.exit(1)

if not TAVILY_API_KEY:
    print("Warning: TAVILY_API_KEY not set. News search will fail.")

# ────────────────────────────────────────────────
# INITIALIZATION
# ────────────────────────────────────────────────
genai.configure(api_key=GEMINI_API_KEY)
model    = genai.GenerativeModel('gemini-3-flash-preview')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
bot      = Bot(token=TELEGRAM_BOT_TOKEN)
tavily   = TavilyClient(api_key=TAVILY_API_KEY) if TAVILY_API_KEY else None

# ────────────────────────────────────────────────
# SEARCH QUERIES BY REGION
# ────────────────────────────────────────────────
SEARCH_QUERIES = [
    # Kazakhstan (highest priority)
    {"query": "стартапы венчурные инвестиции Казахстан 2026",        "region": "Kazakhstan",  "priority": 0},
    {"query": "Kazakhstan startup venture capital funding 2026",      "region": "Kazakhstan",  "priority": 0},
    {"query": "Казахстан венчурный фонд раунд стартап",              "region": "Kazakhstan",  "priority": 0},

    # Central Asia
    {"query": "стартапы венчурные инвестиции Центральная Азия 2026", "region": "CentralAsia", "priority": 1},
    {"query": "Central Asia startup investment funding 2026",         "region": "CentralAsia", "priority": 1},
    {"query": "Узбекистан Кыргызстан стартап венчур инвестиции",     "region": "CentralAsia", "priority": 1},

    # World — Tier-1 VC/tech only
    {"query": "OpenAI Anthropic NVIDIA Google major AI funding 2026", "region": "World",       "priority": 2},
    {"query": "top venture capital deal Series A B C funding 2026",   "region": "World",       "priority": 2},
    {"query": "startup unicorn IPO major investment news 2026",       "region": "World",       "priority": 2},
]

REGION_HEADER = {
    "Kazakhstan":  "Kazakhstan",
    "CentralAsia": "Central Asia",
    "World":       "World",
}

# ────────────────────────────────────────────────
# ACTIVAT VC LESSONS
# ────────────────────────────────────────────────
ACTIVAT_LESSONS = [
    {"title": "Какой путь проходят стартапы",      "url": "https://activat.vc/startup-course/lesson/kakoi-put-prohodyat-startapy"},
    {"title": "Что такое MVP и зачем он нужен",    "url": "https://activat.vc/startup-course/lesson/chto-takoe-mvp-i-zachem-on-nuzhen"},
    {"title": "Как найти product-market fit",      "url": "https://activat.vc/startup-course/lesson/kak-naiti-product-market-fit"},
    {"title": "Как привлечь первых клиентов",      "url": "https://activat.vc/startup-course/lesson/kak-privlech-pervyh-klientov"},
    {"title": "Юнит-экономика для стартапов",      "url": "https://activat.vc/startup-course/lesson/yunit-ekonomika-dlya-startapov"},
    {"title": "Как сделать питч-дек",              "url": "https://activat.vc/startup-course/lesson/kak-sdelat-pitch-deck"},
    {"title": "Как работают венчурные инвестиции", "url": "https://activat.vc/startup-course/lesson/kak-rabotayut-venchurnye-investicii"},
    {"title": "Что такое cap table",               "url": "https://activat.vc/startup-course/lesson/chto-takoe-cap-table"},
    {"title": "Как проходит due diligence",        "url": "https://activat.vc/startup-course/lesson/kak-prohodit-due-diligence"},
    {"title": "Что такое term sheet",              "url": "https://activat.vc/startup-course/lesson/chto-takoe-term-sheet"},
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
        res = supabase.table("negative_constraints").select("feedback").execute()
        return [row["feedback"].lower() for row in res.data]
    except:
        return []

def get_recent_post_titles(limit: int = 30) -> list:
    """Get titles of recently posted/pending news for semantic duplicate detection."""
    titles = []
    try:
        # From posted_news — get recent url_text entries (titles stored as keys)
        res = supabase.table("posted_news") \
            .select("url_text, news_type") \
            .eq("news_type", "NEWS") \
            .order("created_at", desc=True) \
            .limit(limit) \
            .execute()
        titles += [row["url_text"] for row in res.data if row.get("url_text")]
    except:
        pass
    try:
        # Also check pending posts that haven't been approved yet
        res2 = supabase.table("pending_posts") \
            .select("title, url") \
            .eq("status", "pending") \
            .order("created_at", desc=True) \
            .limit(10) \
            .execute()
        for row in res2.data:
            if row.get("title"):
                titles.append(row["title"])
            if row.get("url"):
                titles.append(row["url"])
    except:
        pass
    return titles

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
            days=7,
        )
        results = []
        for r in response.get("results", []):
            results.append({
                "title":   r.get("title", ""),
                "url":     r.get("url", ""),
                "snippet": r.get("content", "")[:300],
            })
        return results
    except Exception as e:
        print(f"Tavily search error: {e}")
        return []

# ────────────────────────────────────────────────
# VC RELEVANCE KEYWORD FILTER
# ────────────────────────────────────────────────
VC_KEYWORDS = [
    "стартап", "венчур", "инвестиц", "раунд", "фонд",
    "startup", "venture", "funding", "investment", "investor",
    "series a", "series b", "series c", "seed", "pre-seed",
    "ipo", "unicorn", "единорог", "акселератор", "accelerator",
    "openai", "anthropic", "nvidia", "sequoia", "a16z", "y combinator",
    "techcrunch", "fintech", "edtech", "healthtech", "saas", "pitch",
]

def is_vc_relevant(title: str, snippet: str, negative_rules: list) -> bool:
    content = (title + " " + snippet).lower()
    if any(rule in content for rule in negative_rules):
        return False
    return any(kw in content for kw in VC_KEYWORDS)

# ────────────────────────────────────────────────
# GEMINI: PICK BEST ARTICLE
# ────────────────────────────────────────────────
async def pick_best_with_gemini(candidates: list) -> dict:
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    articles_text = ""
    for i, c in enumerate(candidates[:10]):
        articles_text += f"{i+1}. [{c['region']}] {c['title']}\n   {c['snippet']}\n\n"

    try:
        prompt = (
            "You are a venture capital news editor for a Central Asian VC Telegram channel.\n"
            "From this list, pick ONE article MOST relevant to startups and venture capital.\n"
            "Must be about: startup funding, VC fund news, major tech AI strategy "
            "(OpenAI/Anthropic/NVIDIA/Google), startup ecosystem, or venture market trends.\n"
            "Do NOT pick: consumer finance, personal taxes, sports, politics, general business.\n\n"
            f"{articles_text}"
            "Respond with ONLY the number (e.g.: 3). Nothing else."
        )
        response = model.generate_content(prompt)
        idx = int(response.text.strip().strip(".")) - 1
        if 0 <= idx < len(candidates[:10]):
            return candidates[idx]
    except Exception as e:
        print(f"Gemini pick error: {e}")

    return candidates[0]

# ────────────────────────────────────────────────
# GEMINI: SEMANTIC DUPLICATE CHECK
# ────────────────────────────────────────────────
async def is_semantic_duplicate(candidate: dict, recent_titles: list) -> bool:
    """Check if this story was already covered recently (same story, different source)."""
    if not recent_titles:
        return False
    try:
        recent_text = "\n".join(str(t) for t in recent_titles[:20])
        prompt = (
            f"New article title: {candidate['title']}\n"
            f"New article snippet: {candidate['snippet'][:200]}\n\n"
            f"Recently published articles/URLs:\n{recent_text}\n\n"
            "Is the new article covering the SAME news story as any of the recent ones? "
            "Same story means same event, same data, same announcement — just from a different source.\n"
            "Answer only YES or NO."
        )
        response = model.generate_content(prompt)
        answer = response.text.strip().upper()
        is_dup = answer.startswith("YES")
        if is_dup:
            print(f"Semantic duplicate detected: {candidate['title']}")
        return is_dup
    except Exception as e:
        print(f"Duplicate check error: {e}")
        return False

# ────────────────────────────────────────────────
# TELEGRAM SEND (supports supergroup topics)
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
        # Retry without image if image failed
        if image_url:
            try:
                await bot.send_message(
                    text=text,
                    disable_web_page_preview=False,
                    **kwargs
                )
            except TelegramError as te2:
                print(f"Retry also failed: {te2}")
                await bot.send_message(TELEGRAM_ADMIN_ID, f"Send error: {str(te2)}")

# ────────────────────────────────────────────────
# NEWS POST LOGIC (08:00)
# ────────────────────────────────────────────────
async def run_news(posted_count: int, approval_mode: bool, negative_rules: list):
    print("MODE: NEWS (08:00)")

    all_candidates = []

    print("Searching via Tavily...")
    for search in SEARCH_QUERIES:
        results = tavily_search(search["query"], max_results=5)
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

    # Deduplicate by URL
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
        await bot.send_message(TELEGRAM_ADMIN_ID, "Main Bot: No suitable news found today.")
        return

    # Sort by region priority
    all_candidates.sort(key=lambda c: c["priority"])

    # Load recent posts for semantic duplicate check
    recent_titles = get_recent_post_titles()
    print(f"Loaded {len(recent_titles)} recent post titles for duplicate check.")

    # Try candidates until we find one that isn't a semantic duplicate
    best = None
    remaining = list(all_candidates)

    while remaining:
        candidate = await pick_best_with_gemini(remaining)
        if not candidate:
            break

        if not await is_semantic_duplicate(candidate, recent_titles):
            best = candidate
            break
        else:
            # Remove this duplicate and try next best
            remaining = [c for c in remaining if c["url"] != candidate["url"]]
            print(f"Skipping duplicate, {len(remaining)} candidates left.")

    if not best:
        print("All candidates are semantic duplicates of recent posts.")
        await bot.send_message(
            TELEGRAM_ADMIN_ID,
            "Main Bot: All top candidates are duplicates of recent stories. No post today."
        )
        return

    print(f"Selected [{best['region']}]: {best['title']}")
    region_header = REGION_HEADER.get(best["region"], best["region"])

    try:
        prompt = (
            "You are the editor of a Telegram channel about venture capital in Central Asia.\n"
            "Write a short engaging post in RUSSIAN (300-600 characters) based on this news:\n\n"
            f"Title: {best['title']}\n"
            f"Summary: {best['snippet']}\n"
            f"URL: {best['url']}\n\n"
            f"IMPORTANT: Start the post EXACTLY with this line: {region_header}\n"
            "Then a blank line, then the post text.\n"
            "Style: informative, light analysis, emojis, end with a question for discussion.\n"
            "No hashtags. Concise.\n"
        )
        response  = model.generate_content(prompt)
        post_text = response.text.strip()

        if not post_text.startswith(region_header):
            post_text = f"{region_header}\n\n{post_text}"

        # Always append source link
        post_text = f"{post_text}\n\n{best['url']}"

        # Try og:image
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

    if approval_mode:
        pending_id = save_pending_post(best, post_text, image_url)
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
# Even count = Activat VC lesson, Odd count = global topic
# ────────────────────────────────────────────────
async def run_education(posted_count: int, approval_mode: bool):
    print("MODE: EDUCATION (17:00)")

    edu_count   = get_education_count()
    use_activat = (edu_count % 2 == 0)

    if use_activat:
        idx        = (edu_count // 2) % len(ACTIVAT_LESSONS)
        lesson     = ACTIVAT_LESSONS[idx]
        topic      = lesson["title"]
        source_url = lesson["url"]
        dedup_key  = f"activat_{topic[:60]}"
        print(f"Activat VC lesson #{idx}: {topic}")
    else:
        idx        = (edu_count // 2) % len(GLOBAL_EDUCATION_TOPICS)
        topic      = GLOBAL_EDUCATION_TOPICS[idx]
        source_url = ""
        dedup_key  = f"edu_global_{topic[:60]}"
        print(f"Global topic #{idx}: {topic}")

    if is_already_posted(dedup_key):
        print(f"Topic already used: {topic}")
        await bot.send_message(TELEGRAM_ADMIN_ID, "Education: topic already used, skipping.")
        return

    try:
        if use_activat:
            prompt = (
                "You are the editor of a Telegram channel about venture capital in Central Asia.\n"
                "Write a short educational post in RUSSIAN about this Activat VC course topic:\n\n"
                f"Topic: \"{topic}\"\n\n"
                "Requirements:\n"
                "- Length: 400-700 characters\n"
                "- Start EXACTLY with: Обучение | Activat VC\n"
                "- Explain simply for early-stage founders with examples\n"
                "- Add emojis for readability\n"
                f"- End with: Подробнее в курсе Activat VC: {source_url}\n"
                "- No hashtags\n"
            )
            expected = "Обучение | Activat VC"
        else:
            prompt = (
                "You are the editor of a Telegram channel about venture capital in Central Asia.\n"
                "Write a short educational post in RUSSIAN about this VC topic:\n\n"
                f"Topic: \"{topic}\"\n\n"
                "Requirements:\n"
                "- Length: 400-700 characters\n"
                "- Start EXACTLY with: Обучение\n"
                "- Explain simply for early-stage founders with concrete examples and numbers\n"
                "- Add emojis for readability\n"
                "- End with a discussion question\n"
                "- No hashtags\n"
            )
            expected = "Обучение"

        response  = model.generate_content(prompt)
        post_text = response.text.strip()

        if not post_text.startswith(expected):
            post_text = f"{expected}\n\n{post_text}"

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

    source_tag = f"Activat VC: {source_url}" if use_activat else "Global VC topic"

    if approval_mode:
        pending_id = save_pending_post(candidate, post_text, None)
        if not pending_id:
            await bot.send_message(TELEGRAM_ADMIN_ID, "Failed to save education post.")
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
        print(f"Education sent for approval. ID: {pending_id}")
    else:
        await send_to_channel(post_text, None, EDUCATION_THREAD_ID)
        add_to_posted(dedup_key, "EDUCATION", 8, "Education")
        print("EDUCATION PUBLISHED!")
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
