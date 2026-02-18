# Venture Capital News Bot

An intelligent Telegram bot that automatically curates and posts venture capital news for Central Asia. The bot uses AI to find, filter, deduplicate, and write high-quality posts about startups, funding rounds, and VC deals.

## Features

- **Smart News Discovery**: Searches 9+ sources daily via Tavily API for fresh VC news
- **AI-Powered Content**: Uses Groq (Llama 3.3 70B) to select best articles and write engaging posts
- **Educational Content**: Alternates between news and curated VC education from Activat VC courses
- **Intelligent Deduplication**: 3-layer system (URL, semantic AI, YouTube URL) prevents duplicate posts
- **Human-in-the-loop**: Approval workflow for quality control (auto-publishes after 100 approved posts)
- **Learning System**: Remembers rejection reasons to avoid similar content in future
- **Multi-region Focus**: Prioritizes Kazakhstan → Central Asia → World news

## Architecture

```
cron-job.org (scheduler)
    ↓
GitHub Actions (compute)
    ↓
bridge.py (main bot)
    ↓         ↓         ↓
 Tavily     Groq      Supabase
(search)    (AI)      (database)
    ↓
Telegram Channel + Admin
    ↑
feedback_bot.py (on Render)
```

## Prerequisites

- GitHub account
- Telegram Bot Token ([BotFather](https://t.me/botfather))
- [Supabase](https://supabase.com) account (free tier)
- [Groq](https://console.groq.com) API key (free tier)
- [Tavily](https://tavily.com) API key (free tier)
- [Render](https://render.com) account (free tier, for feedback bot)
- [cron-job.org](https://cron-job.org) account (free, for scheduling)

## Quick Start

### 1. Clone Repository

```bash
git clone https://github.com/yourusername/venture-ai-bot.git
cd venture-ai-bot
```

### 2. Set Up Supabase Database

1. Create a new project at [supabase.com](https://supabase.com)
2. Go to **SQL Editor** → **New query**
3. Run this SQL:

```sql
-- Main news posts table
CREATE TABLE posted_news (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    url_text TEXT NOT NULL,
    title TEXT,
    news_type TEXT NOT NULL,
    shareability_score INT,
    source_type TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Pending approval posts
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

-- Learning from rejections
CREATE TABLE negative_constraints (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    feedback TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Enable Row Level Security
ALTER TABLE posted_news ENABLE ROW LEVEL SECURITY;
ALTER TABLE pending_posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE negative_constraints ENABLE ROW LEVEL SECURITY;

-- Allow service role full access
CREATE POLICY "Allow service role full access" ON posted_news FOR ALL USING (true);
CREATE POLICY "Allow service role full access" ON pending_posts FOR ALL USING (true);
CREATE POLICY "Allow service role full access" ON negative_constraints FOR ALL USING (true);
```

4. Go to **Settings** → **API** and copy:
   - Project URL (`SUPABASE_URL`)
   - `service_role` key (`SUPABASE_KEY`) — **NOT** the anon key

### 3. Get API Keys

| Service | Where to Get | Free Tier Limit |
|---------|--------------|-----------------|
| **Groq** | [console.groq.com](https://console.groq.com) → API Keys | 1,000 req/day |
| **Tavily** | [app.tavily.com](https://app.tavily.com) → API Keys | 1,000 req/month |
| **Telegram** | Message [@BotFather](https://t.me/botfather) → `/newbot` | Unlimited |

For Telegram:
- Create bot via BotFather → get `TELEGRAM_BOT_TOKEN`
- Get your user ID: message [@userinfobot](https://t.me/userinfobot) → get `TELEGRAM_ADMIN_ID`
- Get channel ID: forward any channel message to [@userinfobot](https://t.me/userinfobot) → get `TELEGRAM_CHAT_ID`

### 4. Configure GitHub Secrets

Go to your repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

Add these secrets:

```
GROQ_API_KEY=gsk_...
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
TELEGRAM_CHAT_ID=-100123456789
TELEGRAM_ADMIN_ID=123456789
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
TAVILY_API_KEY=tvly-...
UNSPLASH_ACCESS_KEY=(optional)
TELEGRAM_NEWS_THREAD_ID=(optional - for supergroup topics, often comes on the Telegram Web version as -100123456789_1, -100123456789_2 or -100123456789, etc. The thread ID would be the last number: 1, 2, or 3, etc.)
TELEGRAM_EDUCATION_THREAD_ID=(optional - for supergroup topics)
```

### 5. Deploy Feedback Bot to Render

1. Go to [dashboard.render.com](https://dashboard.render.com)
2. **New** → **Web Service**
3. Connect your GitHub repo
4. Configure:
   - **Name**: `venture-ai-bot`
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements_feedback.txt`
   - **Start Command**: `python feedback_bot.py`
   - **Plan**: Free
5. Add environment variables (same as GitHub secrets above)
6. Click **Create Web Service**
7. Copy the URL (e.g., `https://venture-ai-bot.onrender.com`)

### 6. Set Up Scheduling (cron-job.org)

1. Create account at [cron-job.org](https://cron-job.org)
2. Create **two** cronjobs:

**News Job (08:00 Astana Time = 03:00 UTC)**
- Title: `Venture Bot - News`
- URL: `https://api.github.com/repos/YOURNAME/venture-ai-bot/dispatches`
- Schedule: `0 3 * * *` (daily at 03:00 UTC)
- Request method: `POST`
- Headers:
  ```
  Authorization: Bearer YOUR_GITHUB_PAT
  Accept: application/vnd.github.v3+json
  Content-Type: application/json
  ```
- Request body:
  ```json
  {"event_type": "news-trigger"}
  ```

**Education Job (17:00 Astana Time = 12:00 UTC)**
- Same as above but:
- Schedule: `0 12 * * *`
- Request body: `{"event_type": "education-trigger"}`

**To get GitHub PAT:**
GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic) → Generate new token → Check `repo` scope

### 7. Keep Feedback Bot Awake (Optional, but Recommended. Keep in mind, it will work only on paid subscription.)

Render free tier sleeps after 15 minutes of inactivity. To keep instant responses:

Create a 3rd cronjob on cron-job.org:
- URL: `https://venture-ai-bot.onrender.com/`
- Schedule: `*/10 * * * *` (every 10 minutes)
- Method: `GET`

## 📖 Usage

### Manual Trigger

GitHub → Actions → **Main Bot (triggered)** → **Run workflow** → select `news` or `education`

### Telegram Commands (Admin Only)

Send to your feedback bot:

```
/approve <id>  - Publish pending post
/reject <id> <reason>  - Reject post and learn from reason
/pending  - Show all pending posts
/stats  - View bot statistics
```

### Approval Workflow

1. Bot finds news → writes post → saves to `pending_posts`
2. Admin receives notification with post preview
3. Admin approves/rejects via Telegram
4. After 100 approved posts → bot switches to auto-publish mode

## 🔧 Configuration

### Search Queries (`bridge.py`)

Edit `SEARCH_QUERIES` to customize news sources:

```python
SEARCH_QUERIES = [
    {"query": "Kazakhstan startup funding round February 2026", "region": "Kazakhstan", "priority": 0},
    # Add more queries...
]
```

### Educational Content

- **Activat VC lessons**: Edit `ACTIVAT_LESSONS` array in `bridge.py`
- **Global topics**: Edit `GLOBAL_EDUCATION_TOPICS` array

### Date Filtering

By default, articles older than 3 days are blocked. Change in `tavily_search()`:

```python
cutoff = datetime.utcnow().timestamp() - 86400 * 3  # Change 3 to desired days
```

### Blocked Domains

Add aggregators/databases to skip:

```python
BLOCKED_DOMAINS = [
    "tracxn.com", "crunchbase.com", "instagram.com",
    # Add more...
]
```

## Monitoring

### Check Tavily Usage
[app.tavily.com](https://app.tavily.com) → Dashboard → see requests used

### Check Groq Usage
[console.groq.com](https://console.groq.com) → Usage

### View Database
Supabase → Table Editor → see `posted_news`, `pending_posts`

### GitHub Actions Logs
GitHub → Actions → click any run → see detailed logs

### Render Logs
Render dashboard → your service → Logs tab

## Security

- Supabase RLS enabled
- Service role key (not anon key) in use
- All secrets in GitHub/Render environment variables
- No hardcoded credentials in code

**Weekly Security Check**: Supabase sends security reports every Friday

## Troubleshooting

### "No suitable news found"
- Check Tavily quota: [app.tavily.com](https://app.tavily.com)
- Many results are `Too old` or `No date found, skipping` → date filters working correctly
- Adjust `SEARCH_QUERIES` to be more specific

### Feedback bot not responding
- Check if Render service is live: visit `https://your-bot.onrender.com/`
- Free tier sleeps after 15 min → first command wakes it (slow), second is instant
- Set up keep-alive cronjob (see step 7)

### Duplicate posts appearing
- Check `posted_news` table in Supabase
- AI deduplication works on last 30 posts → if gap >30, duplicates possible
- YouTube URL dedup prevents Activat VC lesson repeats

### Rate limit errors
| Service | Limit | Your Usage | Fix |
|---------|-------|------------|-----|
| Groq | 1K/day | ~5-8/day | Safe |
| Tavily | 1K/month | ~270/month | Don't test too much |
| GitHub Actions | 2K min/month | ~120 min/month | Safe |

### Old news passing through
- Check logs: should see `Too old (YYYY-MM-DD): <url>`
- If seeing `No date found, allowing:` → update to latest `bridge.py`
- Some sites have no date → automatically blocked now

## 📈 Scaling Beyond Free Tier

When you outgrow free limits:

- **Groq**: Upgrade to Developer plan for higher RPM
- **Tavily**: Pay $0.01 per search (1,000 searches = $10)
- **Render**: $7/month for 24/7 uptime without sleep
- **Supabase**: Free tier sufficient unless 500MB+ data

## Contributing

Contributions welcome! Areas for improvement:

- [ ] Add more news sources
- [ ] Support multiple languages
- [ ] Image generation for posts
- [ ] Sentiment analysis
- [ ] Competitor tracking
- [ ] Weekly digest feature

## License

MIT License - feel free to use for your own projects, just do not forget to mention me!

## Acknowledgments

- [Activat VC](https://activat.vc) for educational content transcripts
- Open source LLMs: Llama 3.3 via Groq

## Support

Issues? Create a GitHub issue
---
