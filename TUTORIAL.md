# Complete Setup Tutorial

This guide walks you through every step of setting up your Venture Capital News Bot from scratch. Expected time: 30-45 minutes.

## Table of Contents

1. [Prerequisites Setup](#1-prerequisites-setup)
2. [Database Configuration](#2-database-configuration)
3. [GitHub Repository Setup](#3-github-repository-setup)
4. [Feedback Bot Deployment](#4-feedback-bot-deployment)
5. [Scheduling Automation](#5-scheduling-automation)
6. [Testing & Validation](#6-testing--validation)
7. [Going Live](#7-going-live)
8. [Daily Operations](#8-daily-operations)
9. [Customization Guide](#9-customization-guide)
10. [Troubleshooting](#10-troubleshooting)
11. [Going Beyond Free Tier](#11-going-beyond-free-tier)
12. [Best Practices](#12-best-practices)
13. [FAQ](#13-faq)
14. [Support & Community](#14-support--community)

---

## 1. Prerequisites Setup

### 1.1 Create Telegram Bot

1. Open Telegram and message [@BotFather](https://t.me/botfather)
2. Send `/newbot`
3. Choose a name (e.g., "Venture News Bot")
4. Choose a username (e.g., "venture_news_bot")
5. **Save the token** → looks like `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`

### 1.2 Get Your Telegram IDs

**Your Admin ID:**
1. Message [@userinfobot](https://t.me/userinfobot)
2. Copy the number under "Id" → this is your `TELEGRAM_ADMIN_ID`

**Your Founder ID (if different person):**
1. Ask the founder to message [@userinfobot](https://t.me/userinfobot)
2. Copy their ID → this is your `TELEGRAM_FOUNDER_ID`

**Your Channel ID:**
1. Create a Telegram channel (or use existing)
2. Add your bot as administrator with "Post messages" permission
3. Forward any message from the channel to [@userinfobot](https://t.me/userinfobot)
4. Look for "Forwarded from chat" → copy that ID (will be negative, like `-1001234567890`)
5. This is your `TELEGRAM_CHAT_ID`

**Thread IDs (if your channel uses Topics):**
1. Open the desired topic thread in your channel
2. Copy the number from the URL after `?thread=`
3. News thread → `TELEGRAM_NEWS_THREAD_ID`
4. Education thread → `TELEGRAM_EDUCATION_THREAD_ID`

### 1.3 Sign Up for API Services

**Groq (AI Model):**
1. Go to [console.groq.com](https://console.groq.com)
2. Sign up with email
3. Click **API Keys** → **Create API Key**
4. Copy key (starts with `gsk_`)
5. Free tier: 1,000 requests/day

**Tavily (News Search):**
1. Go to [app.tavily.com](https://app.tavily.com)
2. Sign up
3. Dashboard → **API Keys** → copy key (starts with `tvly-`)
4. Free tier: 1,000 searches/month

**Supabase (Database):**
1. Go to [supabase.com](https://supabase.com)
2. Sign up → **New project**
3. Choose a name, database password, region
4. Wait 2 minutes for setup
5. Go to **Settings** → **API**
6. Copy **URL** (`https://xxx.supabase.co`)
7. Copy **service_role key** (long one, ~300 chars) — **NOT** the anon key

**Unsplash (Post Images — optional):**
1. Go to [unsplash.com/developers](https://unsplash.com/developers)
2. Sign up → **New Application**
3. Copy **Access Key** → this is your `UNSPLASH_ACCESS_KEY`
4. Free tier: 50 requests/hour

---

## 2. Database Configuration

### 2.1 Create Tables

1. In Supabase project, click **SQL Editor** (left sidebar)
2. Click **New query**
3. Paste this entire SQL script:

```sql
-- Table 1: Posted news (for deduplication)
CREATE TABLE posted_news (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    url_text TEXT NOT NULL,
    title TEXT,
    news_type TEXT NOT NULL,
    shareability_score INT,
    source_type TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Table 2: Pending approval posts
CREATE TABLE pending_posts (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    title TEXT,
    url TEXT,
    post_text TEXT NOT NULL,
    image_url TEXT,
    region TEXT,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT NOW()
);

-- Table 3: Negative constraints (learning from rejections)
CREATE TABLE negative_constraints (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    feedback TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Table 4: Tracked entities (companies/startups to follow)
CREATE TABLE tracked_entities (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at TIMESTAMP DEFAULT NOW(),
    entity_name TEXT,
    entity_type TEXT,
    website TEXT
);

-- Add indexes for performance
CREATE INDEX idx_posted_news_created ON posted_news(created_at DESC);
CREATE INDEX idx_posted_news_url ON posted_news(url_text);
CREATE INDEX idx_pending_status ON pending_posts(status);

-- Enable Row Level Security
ALTER TABLE posted_news ENABLE ROW LEVEL SECURITY;
ALTER TABLE pending_posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE negative_constraints ENABLE ROW LEVEL SECURITY;
ALTER TABLE tracked_entities ENABLE ROW LEVEL SECURITY;

-- Policies: allow service role full access
CREATE POLICY "Service role full access" ON posted_news FOR ALL USING (true);
CREATE POLICY "Service role full access" ON pending_posts FOR ALL USING (true);
CREATE POLICY "Service role full access" ON negative_constraints FOR ALL USING (true);
CREATE POLICY "Service role full access" ON tracked_entities FOR ALL USING (true);
```

4. Click **Run** (green button, top right)
5. Should see "Success. No rows returned"
6. Verify: Click **Table Editor** → should see 4 tables

### 2.2 Add Tracked Entities (Optional)

To make the bot follow specific companies and always search for their news:

1. Click **Table Editor** → **tracked_entities**
2. Click **Insert row** and add entries like:

| entity_name | entity_type | website |
|---|---|---|
| Higgsfield AI | Kazakhstan | higgsfield.ai |
| MoonAI | Kazakhstan | moonai.kz |
| MA7 Ventures | Kazakhstan | ma7.vc |

`entity_type` should be one of: `Kazakhstan`, `CentralAsia`, or `World`.

### 2.3 Security Check

1. Go to **Settings** → **API**
2. Confirm you copied the **service_role** key (not anon/public)
3. The service_role key should start with: `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9`

---

## 3. GitHub Repository Setup

### 3.1 Fork or Clone

**Option A: Fork this repo** (easiest)
1. Click **Fork** button on GitHub
2. Creates copy in your account

**Option B: Create new repo**
1. Create new repo on GitHub
2. Upload all project files to root:
   - `bridge.py`
   - `feedback_bot.py`
   - `requirements.txt`

### 3.2 Add GitHub Secrets

1. Go to your repo → **Settings**
2. **Secrets and variables** → **Actions**
3. Click **New repository secret** for each:

| Secret Name | Value | Where to Get |
|-------------|-------|--------------|
| `GROQ_API_KEY` | `gsk_...` | Groq dashboard |
| `TELEGRAM_BOT_TOKEN` | `123456:ABC...` | BotFather |
| `TELEGRAM_CHAT_ID` | `-1001234...` | userinfobot |
| `TELEGRAM_ADMIN_ID` | `123456789` | userinfobot |
| `TELEGRAM_FOUNDER_ID` | `987654321` | userinfobot (founder's ID) |
| `SUPABASE_URL` | `https://xxx.supabase.co` | Supabase Settings → API |
| `SUPABASE_KEY` | `eyJhbGci...` | Supabase Settings → API (service_role) |
| `TAVILY_API_KEY` | `tvly-...` | Tavily dashboard |

**Optional secrets:**
- `UNSPLASH_ACCESS_KEY` — for post images
- `TELEGRAM_NEWS_THREAD_ID` — if using supergroup topics
- `TELEGRAM_EDUCATION_THREAD_ID` — if using supergroup topics

### 3.3 Verify Workflows

1. In your repo, check `.github/workflows/` folder exists
2. Should have:
   - `main.yml` — manual trigger + cron

---

## 4. Feedback Bot Deployment

The feedback bot runs 24/7 on Render to handle post approvals via inline buttons and slash commands.

### 4.1 Create Render Account

1. Go to [render.com](https://render.com)
2. Sign up (free, no credit card needed)

### 4.2 Deploy Web Service

1. Click **New** → **Web Service**
2. **Connect GitHub account**
3. Select your `venture-ai-bot` repo
4. Configure:
   - **Name**: `venture-ai-bot` (or your choice)
   - **Region**: Choose closest to you
   - **Branch**: `main`
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python feedback_bot.py`
5. Click **Advanced**
6. Add **Environment Variables**:

```
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=-1001234...
TELEGRAM_ADMIN_ID=123456789
TELEGRAM_FOUNDER_ID=987654321
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=eyJhbGci...
TELEGRAM_NEWS_THREAD_ID=123
TELEGRAM_EDUCATION_THREAD_ID=456
```

7. **Instance Type**: `Free`
8. Click **Create Web Service**
9. Wait 3-5 minutes for deployment
10. **Copy the service URL** (e.g., `https://venture-ai-bot.onrender.com`)

### 4.3 Set Render External URL

After deployment:

1. Go to **Environment** tab in Render dashboard
2. Add one more variable:
   ```
   RENDER_EXTERNAL_URL=https://venture-ai-bot.onrender.com
   ```
   (your actual URL, no trailing slash)
3. Click **Save Changes** → service redeploys automatically

### 4.4 Test Feedback Bot

1. Send `/start` to your bot on Telegram
2. Should reply with the command menu
3. Send `/stats` → should show counts (all zeros initially)

**If no response:**
- Check Render logs (Logs tab in dashboard)
- Verify all environment variables are set
- Ensure bot is added to your channel as admin

---

## 5. Scheduling Automation

We use cron-job.org (free) to trigger GitHub Actions at specific times.

### 5.1 Get GitHub Personal Access Token

1. GitHub → **Settings** (your profile, not repo)
2. **Developer settings** → **Personal access tokens** → **Tokens (classic)**
3. **Generate new token (classic)**
4. Note: "Venture bot cron trigger"
5. Expiration: 90 days (or No expiration)
6. Check **only** `repo` scope
7. Click **Generate token**
8. **Copy token immediately** (can't see again) → starts with `ghp_`

### 5.2 Create cron-job.org Account

1. Go to [cron-job.org](https://cron-job.org)
2. Sign up (free, no credit card)
3. Verify email

### 5.3 Create News Job (08:00 Astana Time)

1. Click **Create cronjob**
2. **Title**: `Venture Bot - News`
3. **URL**: `https://api.github.com/repos/YOURUSERNAME/venture-ai-bot/dispatches`
   - Replace `YOURUSERNAME` with your GitHub username
4. **Schedule**:
   - Type: `Every day`
   - Time: `03:00` (UTC = 08:00 Astana / UTC+5)
5. **Request method**: `POST`
6. **Advanced** → **Request headers**:
   ```
   Authorization: Bearer ghp_YOUR_TOKEN_HERE
   Accept: application/vnd.github.v3+json
   Content-Type: application/json
   ```
7. **Request body**:
   ```json
   {"event_type": "news-trigger"}
   ```
8. **Save**

### 5.4 Create Education Job (17:00 Astana Time)

1. Create another cronjob (same as above)
2. **Title**: `Venture Bot - Education`
3. Same URL and headers
4. **Schedule**: `12:00` UTC (= 17:00 Astana)
5. **Request body**:
   ```json
   {"event_type": "education-trigger"}
   ```

### 5.5 Create Keep-Alive Job (Recommended)

Keeps Render bot awake for instant responses:

1. **Title**: `Keep Bot Awake`
2. **URL**: `https://venture-ai-bot.onrender.com/` (your Render URL)
3. **Schedule**: `Every 10 minutes`
4. **Method**: `GET`
5. No headers or body needed

---

## 6. Testing & Validation

### 6.1 Manual Test Run

1. GitHub → your repo → **Actions**
2. Select workflow → **Run workflow**
3. Select branch: `main`
4. Select `post_type`: `news`
5. Click **Run workflow**
6. Wait 1-2 minutes and click the running workflow to view logs

**Expected log output:**
```
STARTING | 2026-02-25 | TYPE: NEWS
Cleaned up 0 expired pending posts.
=== NEGATIVE CONSTRAINTS LOADED (0) ===
=== FEEDBACK INTENT ANALYSIS ===
  Prohibitions (0): []
  Region boosts: []
  Stage boost (pre-seed/seed): False
========================================
Posts published: 0 | Mode: APPROVAL
MODE: NEWS (08:00)
Reading RSS feeds...
RSS [Kazakhstan] https://digitalbusiness.kz/feed/: 2 новых статей
RSS [CentralAsia] https://daryo.uz/feed/: 1 новых статей
RSS total candidates: 3
Searching via Tavily (5-day window)...
Tavily candidates (5-day): 7
Total candidates (RSS + Tavily): 10
Selected [Kazakhstan]: Startup XYZ raises $2M seed round
Post quality: 85/100 | OK | no issues
Post ready (312 chars)
Sent for approval with buttons. ID: abc-123-def
```

### 6.2 Check Telegram

Within 1 minute you should receive a message with inline buttons:

```
НОВОСТЬ НА ОДОБРЕНИЕ (#1/100)
Качество: 85/100 [OK]
────────────────────────────
Казахстан

Стартап XYZ привлёк $2M в seed-раунде...

https://source.com

[✅ Одобрить]  [❌ Отклонить]
```

### 6.3 Test Approval Flow

1. Press **✅ Одобрить** — post should appear in your channel
2. Run another test, press **❌ Отклонить** → menu appears:
   ```
   [Не про VC]    [Геополитика]
   [Старая новость] [Слишком общо]
   [Дубль]        [Своя причина]
   [← Назад]
   ```
3. Press **← Назад** → returns to Одобрить/Отклонить buttons
4. Select a rejection reason → saved as anti-case

### 6.4 Test Education

1. GitHub Actions → **Run workflow**
2. Select `post_type`: `education`
3. Should get an educational post about VC concepts
4. Approve the same way

---

## 7. Going Live

### 7.1 Verify Everything Works

Checklist:
- [ ] Manual news post works end-to-end
- [ ] Manual education post works end-to-end
- [ ] Inline buttons appear under posts
- [ ] ✅ Одобрить publishes to channel
- [ ] ❌ Отклонить → reason menu → ← Назад works
- [ ] cron-job.org shows both jobs enabled
- [ ] Render bot responds to `/start` and `/stats`
- [ ] `/rejected` shows rejection history
- [ ] `/digest` shows weekly summary

### 7.2 Set Posting Schedule

Your current schedule:
- **08:00 Astana** (03:00 UTC) → News post
- **17:00 Astana** (12:00 UTC) → Education post

To change: edit cronjob schedule on cron-job.org (remember UTC conversion: Astana = UTC+5).

### 7.3 Monitor First Week

**Days 1-3:**
- Approve or reject every post
- Write clear rejection reasons (bot learns from them)
- Check `/stats` to see region distribution

**Days 4-7:**
- Quality should start improving via few-shot learning
- Check `/digest` for weekly summary
- Duplicates should be rare

**After 100 approved posts:**
- Bot switches to auto-publish mode
- You'll only get notifications, no approval needed
- Weekly digest arrives every Sunday at 18:00 Astana

---

## 8. Daily Operations

### 8.1 Approving Posts

**Good posts have:**
- Fresh news (within 5 days)
- Specific numbers and facts
- Clear headline with named company or country
- Relevant to VC/startups in Central Asia or globally

**Reject if:**
- Old news (>5 days)
- Duplicate story
- Not about VC/startups
- Too generic or vague
- Missing country/company name

### 8.2 Rejection Reasons — Be Specific

When rejecting, the reason becomes an anti-case the bot learns from:

```
Bad:  Геополитика
Good: геополитика и военные конфликты, не нужно

Bad:  Дубль
Good: дубль — уже публиковали про раунд Higgsfield AI

Bad:  Не то
Good: это про банки и потребительское кредитование, не про венчур
```

You can also just type any text message to the bot to add an anti-case directly (without linking it to a specific post).

### 8.3 Feedback That Teaches Priorities

Besides rejection reasons, you can teach the bot what to prioritize:

```
публикуй больше новостей о центральной азии
желательно pre-seed и seed стартапы
больше казахстан
```

The bot detects words like "больше", "желательно", "приоритет" and boosts matching articles instead of blocking them.

### 8.4 Bot Commands Reference

| Command | Description |
|---|---|
| `/start` | Show all available commands |
| `/pending` | Posts waiting for approval |
| `/rejected` | Last 15 rejected posts + saved reasons |
| `/list` | All anti-cases |
| `/delete <id>` | Delete an anti-case (asks for confirmation) |
| `/stats` | Statistics broken down by region |
| `/digest` | Summary of the last 7 days |
| Any text | Add as anti-case |

### 8.5 Check Quotas Weekly

Every Monday, check:

**Tavily**: [app.tavily.com](https://app.tavily.com)
- Should use ~60/1000 per month
- RSS feeds reduce Tavily usage significantly

**Groq**: [console.groq.com](https://console.groq.com) → Usage
- Should use ~200/1000 per month
- Free tier is generous

**GitHub Actions**: Repo → Settings → Billing
- Should use ~120/2000 minutes per month
- No concern on free tier

**Supabase**: Project → Settings → Billing
- Database size should be <10MB
- Free tier: 500MB limit

---

## 9. Customization Guide

### 9.1 Add RSS Feeds

Edit `bridge.py` → `RSS_FEEDS` to add new sources:

```python
RSS_FEEDS = [
    # Add your source:
    {"url": "https://yoursource.com/feed/", "region": "Kazakhstan", "priority": 0},
    # ...existing feeds
]
```

`priority`: `0` = Kazakhstan, `1` = CentralAsia, `2` = World.

### 9.2 Track Specific Companies

Add rows to `tracked_entities` table in Supabase:

```sql
INSERT INTO tracked_entities (entity_name, entity_type, website)
VALUES ('YourStartup', 'Kazakhstan', 'yourstartup.com');
```

The bot will add a dedicated search query for each tracked entity at every run.

### 9.3 Change Search Focus

Edit `bridge.py` → `_build_search_queries()` to change or add search queries. Dates update automatically each month — no manual editing needed.

### 9.4 Add Educational Topics

Edit `bridge.py` → `GLOBAL_EDUCATION_TOPICS`:

```python
GLOBAL_EDUCATION_TOPICS = [
    "Как работает венчурный капитал",
    "Your new topic here",
    # ...
]
```

### 9.5 Change Post Format

Find the post generation prompt in `bridge.py` (search for `"Ты редактор"`):

```python
prompt = (
    "Ты редактор Telegram-канала...\n"
    "Структура поста — ровно 2 предложения:\n"
    "1. Your custom structure\n"
    "2. Your requirements\n"
)
```

### 9.6 Adjust Date Filter

Edit `bridge.py` → `tavily_search()` and `fetch_rss_candidates()`:

```python
def tavily_search(query, max_results=5, days=5):  # change 5 to desired days
def fetch_rss_candidates(days=5):                 # change 5 to desired days
```

The bot also automatically expands to 7 days if fewer than 3 candidates are found.

---

## 10. Troubleshooting

### Problem: "No suitable news found"

**Cause**: All articles filtered out by date, deduplication, or VC keywords

**Fix**:
1. Check GitHub Actions logs
2. Look for lines: `Too old (...)` or `No date, skipping`
3. Check `RSS total candidates: 0` — means RSS feeds are unreachable
4. If ALL results blocked → try changing cutoff to 7 days
5. Check if `feedparser` is installed (should be in `requirements.txt`)

### Problem: Feedback bot not responding

**Cause**: Render free tier sleeping, or wrong token

**Fix**:
1. Visit `https://your-bot.onrender.com/` in browser — should wake it up
2. Wait 10-15 seconds and try the command again
3. Set up keep-alive cronjob (see section 5.5)
4. Check Render logs for errors

### Problem: Buttons not appearing under posts

**Cause**: bridge.py sending via different token than feedback_bot.py listens on

**Fix**:
1. Confirm `TELEGRAM_BOT_TOKEN` is identical in both GitHub Secrets and Render Environment
2. There should be only **one** bot token used everywhere — no `TELEGRAM_FEEDBACK_BOT_TOKEN` needed
3. Redeploy Render after fixing variables

### Problem: Clicking a button does nothing

**Cause**: Render bot is sleeping when callback arrives

**Fix**:
1. Set up keep-alive cronjob (see section 5.5)
2. Or upgrade to Render paid tier ($7/month) for always-on

### Problem: Duplicate posts

**Cause**: Deduplication not working properly

**Fix**:
1. Check Supabase → `posted_news` table for the duplicate URL
2. If not there → the first approval didn't save to posted_news
3. Check Render logs around the time of the duplicate

### Problem: Old news passing through

**Cause**: Article has no date in URL and domain is not in `TRUSTED_NODATELESS_DOMAINS`

**Fix**:
1. Note which domain keeps appearing with old articles
2. Either add it to `BLOCKED_DOMAINS` or check its actual publication date logic

### Problem: cron-job not triggering

**Cause**: Wrong GitHub PAT or expired token

**Fix**:
Test manually with curl:
```bash
curl -X POST \
  -H "Authorization: Bearer YOUR_PAT" \
  -H "Accept: application/vnd.github.v3+json" \
  -d '{"event_type":"news-trigger"}' \
  https://api.github.com/repos/YOURUSERNAME/venture-ai-bot/dispatches
```
Should return `204 No Content`. If `401` → regenerate PAT with `repo` scope.

### Problem: JobQueue warning (weekly digest not sending)

**Cause**: `python-telegram-bot[job-queue]` not installed

**Fix**:
1. Confirm `requirements.txt` contains: `python-telegram-bot[job-queue]>=21.0`
2. Trigger a redeploy on Render (Manual Deploy → Deploy latest commit)

---

## 11. Going Beyond Free Tier

### When to Upgrade

**Groq**: When hitting 1K/day limit
- Unlikely unless running 100+ test runs daily
- Upgrade to Developer plan for higher limits

**Tavily**: When hitting 1K/month limit
- RSS feeds significantly reduce Tavily usage
- Pay $0.01 per search or reduce test runs

**Render**: When instant button responses needed 24/7
- Free tier sleeps after 15 min inactivity (keep-alive solves this)
- $7/month for always-on

**Supabase**: When database >500MB
- Would take 50,000+ posts to reach
- Upgrade only if needed

### Cost Estimate (if scaling)

Running 10x current volume (20 posts/day):

| Service | Monthly Cost |
|---------|--------------|
| Groq | $0 (still under limit) |
| Tavily | $20 (2,000 searches) |
| Render | $7 (always-on) |
| GitHub | $0 (still under limit) |
| Supabase | $0 (still under limit) |
| **Total** | **$27/month** |

---

## 12. Best Practices

### Content Quality

1. **First 20 posts**: Be very selective, reject anything mediocre — these become the few-shot examples the AI learns from
2. **Posts 20-50**: Bot starts copying the style of your approved posts
3. **Posts 50-100**: Quality should be consistently good, few-shot working well
4. **After 100**: Review auto-published posts weekly via `/digest`

### Rejection Discipline

1. Always pick a specific reason from the button menu — it trains faster than vague text
2. "Своя причина" is best for nuanced cases the preset reasons don't cover
3. Check `/rejected` weekly to see patterns in what you're rejecting

### Security

1. **Never commit secrets** to GitHub
2. **Regenerate keys** if accidentally exposed
3. **Use service_role key**, not anon key for Supabase
4. **One bot token** — don't create separate feedback bot tokens

### Monitoring

1. Set up GitHub Actions **email notifications** for failures: repo → Settings → Notifications
2. **Weekly quota check** every Monday
3. Review `/stats` to ensure region balance (not all World, enough Kazakhstan/CentralAsia)
4. Check channel engagement to see what topics resonate

---

## 13. FAQ

**Q: Can I use this for non-VC topics?**
A: Yes — change `SEARCH_QUERIES`, `RSS_FEEDS`, and `VC_KEYWORDS` in bridge.py to match your domain.

**Q: Can I post to multiple channels?**
A: Yes — set multiple chat IDs and loop through them in `send_to_channel()`.

**Q: How do I add my own educational content?**
A: Edit `ACTIVAT_LESSONS` in bridge.py with your transcripts and YouTube URLs.

**Q: Can I use a different AI model?**
A: Yes — change the model name in `groq_client.chat.completions.create(model="...")` to any model available on Groq.

**Q: What if I want posts in English?**
A: Change all prompts in bridge.py from Russian instructions to English. Also update `REGION_HEADER` values.

**Q: Can I self-host instead of Render?**
A: Yes — feedback_bot.py works on any server with Python 3.10+ and a public HTTPS URL for the webhook.

**Q: How does the AI learn from my feedback?**
A: Three ways: (1) rejection reasons become keyword filters, (2) priority feedback boosts certain regions/stages, (3) approved posts become few-shot style examples for future generations.

**Q: How do I backup my data?**
A: Supabase → Database → Backups tab → Download.

**Q: Can I run this more than twice a day?**
A: Yes — add more cron jobs on cron-job.org with different times and `post_type` values.

**Q: Why does the bot sometimes find no news?**
A: On slow news days there may be no fresh VC articles. The bot automatically expands its search window from 5 to 7 days before giving up.

---

## 14. Support & Community

- **Issues**: [GitHub Issues](https://github.com/DiyarZhunussov/venture-ai-bot/issues)
- **Discussions**: [GitHub Discussions](https://github.com/DiyarZhunussov/venture-ai-bot/discussions)
- **Updates**: Watch this repo for new features

---

**You're all set!**

Your bot should now be:
- Reading 14 RSS feeds directly for instant coverage
- Searching via Tavily as a secondary source
- Posting news daily at 08:00 Astana
- Posting education daily at 17:00 Astana
- Sending approval requests with inline buttons
- Learning from every approval and rejection
- Improving post style via few-shot examples
- Sending a weekly digest every Sunday at 18:00 Astana

Enjoy your automated VC news channel!
