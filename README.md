#VentureAIBot

A Telegram bot for automatically publishing news about venture capital investments in Central Asia. The bot searches for the latest news via RSS and Tavily, generates posts using LLaMA 3.3, submits them to the founder for approval, and learns from their feedback.

---

## How it works

```
cron-job.org / GitHub Actions
↓ (08:00 and 17:00 Astana time)
bridge.py
↓
RSS feeds (14 sources)
+ Tavily Search (13-16 queries)
↓
Filtering: date, VC relevance, duplicates, anti-cases
↓
LLaMA 3.3 (Groq): choosing the best article + generating a post
↓
Quality Score (0-100): auto-regenerate if < 60
↓
Supabase: save as pending_post
↓
feedback_bot.py (Render): notification with buttons
↓
Founder: [✅ Approve] / [❌ Reject]
↓
Approved → published in Telegram Channel
Rejected → Reason → Negative_Constraints → Considered in future posts
```

---

## Architecture

| File | Where Runs | Purpose |
|---|---|---|
| `bridge.py` | GitHub Actions | Search, Generate, Submit for Approval |
| `feedback_bot.py` | Render (24/7) | Process Approvals/Rejections, Commands |
| `requirements.txt` | Both | Python Dependencies |

---

## News Sources

### RSS feeds (direct reading, no indexing delay)

**Kazakhstan:**
- digitalbusiness.kz
- astanatimes.com
- the-tech.kz
- timesca.com
- forbes.kz

**Central Asia:**
- daryo.uz
- gazeta.uz
- kun.uz
- dunyo.info
- economist.kg

**Global VC:**
- techcrunch.com/startups
- siliconangle.com
- venturebeat.com
- theaiinsider.tech

### Tavily Search (13-16 queries)
Search by keywords about Kazakhstan, Central Asia, and global venture capital with dynamic dates (updated automatically every month).

---

## Feedback Learning System

The bot improves over time through three mechanisms:

**1. Keyword filter (instant)**
Words from anti-cases block articles before the AI ​​sees them.

**2. Context in the prompt**
Reasons for rejections and suggestions are passed to the AI ​​each time an article is selected.

**3. Few-shot on approved posts**
Each approved post becomes a style example for subsequent generations. The AI ​​copies the length, tone, and structure, but takes facts only from the source.

**Hallucination protection:** the source is clearly separated from the examples in the prompt. The prompt prohibits adding facts not from the source. The quality scorer filters out posts without numbers and with general phrases.

---

## feedback_bot commands

| Command | Description |
|---|---|
| `/start` | List of all commands |
| `/pending` | Posts pending approval |
| `/rejected` | Latest rejected posts + reasons |
| `/list` | All anti-cases |
| `/delete <id>` | Delete anti-case |
| `/stats` | Statistics by region |
| `/digest` | 7-day summary |
| Any text | Add an anti-case |

**Buttons under the post:**
- ✅ Approve — publishes to the channel
- ❌ Reject → reason menu: Not about VC / Geopolitics / Old news / Too general / Duplicate / Your own reason / ← Back

---

## Operating modes

| Mode | Condition | Behavior |
|---|---|---|
| Approval | first 100 posts | every post is subject to approval |
| Auto | after 100 posts | publication without approval |

---

## Database (Supabase)

| Table | Purpose |
|---|---|
| `posted_news` | Published posts (for deduplication) |
| `pending_posts` | Approval queue (pending / approved / rejected / expired) |
| `negative_constraints` | Feedback anti-cases |
| `tracked_entities` | Companies to track (entity_name, entity_type, website) |

---

## Environment Variables

Required in GitHub Actions Secrets and Render Environment:

```
GROQ_API_KEY
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
TELEGRAM_ADMIN_ID
TELEGRAM_FOUNDER_ID
SUPABASE_URL
SUPABASE_KEY
TAVILY_API_KEY
UNSPLASH_ACCESS_KEY
TELEGRAM_NEWS_THREAD_ID
TELEGRAM_EDUCATION_THREAD_ID
RENDER_EXTERNAL_URL (Render only)
PORT (Render only, usually 10000)
POST_TYPE (news or education, GitHub Actions only)
```
