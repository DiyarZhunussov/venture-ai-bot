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

**Your Channel ID:**
1. Create a Telegram channel (or use existing)
2. Add your bot as administrator with "Post messages" permission
3. Forward any message from the channel to [@userinfobot](https://t.me/userinfobot)
4. Look for "Forwarded from chat" → copy that ID (will be negative, like `-1001234567890`)
5. This is your `TELEGRAM_CHAT_ID`

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

-- Add indexes for performance
CREATE INDEX idx_posted_news_created ON posted_news(created_at DESC);
CREATE INDEX idx_posted_news_url ON posted_news(url_text);
CREATE INDEX idx_pending_status ON pending_posts(status);

-- Enable Row Level Security
ALTER TABLE posted_news ENABLE ROW LEVEL SECURITY;
ALTER TABLE pending_posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE negative_constraints ENABLE ROW LEVEL SECURITY;

-- Policies: allow service role full access
CREATE POLICY "Service role full access" ON posted_news 
    FOR ALL USING (true);

CREATE POLICY "Service role full access" ON pending_posts 
    FOR ALL USING (true);

CREATE POLICY "Service role full access" ON negative_constraints 
    FOR ALL USING (true);
```

4. Click **Run** (green button, top right)
5. Should see "Success. No rows returned"
6. Verify: Click **Table Editor** → should see 3 tables

### 2.2 Security Check

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
2. Clone this project
3. Push to your repo

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
| `SUPABASE_URL` | `https://xxx.supabase.co` | Supabase Settings → API |
| `SUPABASE_KEY` | `eyJhbGci...` | Supabase Settings → API (service_role) |
| `TAVILY_API_KEY` | `tvly-...` | Tavily dashboard |

**Optional secrets** (can add later):
- `UNSPLASH_ACCESS_KEY` - for post images
- `TELEGRAM_NEWS_THREAD_ID` - if using supergroup topics
- `TELEGRAM_EDUCATION_THREAD_ID` - if using supergroup topics

### 3.3 Verify Workflows

1. In your repo, check `.github/workflows/` folder exists
2. Should have:
   - `main.yml` - manual trigger
   - `triggered-main.yml` - cron trigger

---

## 4. Feedback Bot Deployment

The feedback bot runs 24/7 on Render to handle `/approve` and `/reject` commands.

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
   - **Build Command**: `pip install -r requirements_feedback.txt`
   - **Start Command**: `python feedback_bot.py`
5. Click **Advanced**
6. Add **Environment Variables** (same as GitHub secrets):

```
GROQ_API_KEY=gsk_...
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=-1001234...
TELEGRAM_ADMIN_ID=123456789
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=eyJhbGci...
TAVILY_API_KEY=tvly-...
```

7. **Instance Type**: `Free`
8. Click **Create Web Service**
9. Wait 3-5 minutes for deployment
10. **Copy the URL** (e.g., `https://venture-ai-bot.onrender.com`)

### 4.3 Test Feedback Bot

1. Send `/start` to your bot on Telegram
2. Should reply instantly (or after ~10 sec if sleeping)
3. Send `/stats` → should show `Posts: 0 | Approved: 0`

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
   - Time: `03:00` (UTC = 08:00 Astana)
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
3. Same URL
4. **Schedule**: `12:00` UTC (= 17:00 Astana)
5. Same headers
6. **Request body**:
   ```json
   {"event_type": "education-trigger"}
   ```

### 5.5 Create Keep-Alive Job (Optional)

Keeps Render bot awake for instant responses:

1. **Title**: `Keep Bot Awake`
2. **URL**: `https://venture-ai-bot.onrender.com/` (your Render URL)
3. **Schedule**: `Every 10 minutes`
4. **Method**: `GET`
5. No headers/body needed

---

## 6. Testing & Validation

### 6.1 Manual Test Run

1. GitHub → your repo → **Actions**
2. **Main Bot (triggered)** → **Run workflow**
3. Select branch: `main`
4. Select `post_type`: `news`
5. Click **Run workflow**
6. Wait 1-2 minutes
7. Click the running workflow → view logs

**Expected log output:**
```
STARTING | 2026-02-18 | TYPE: NEWS
MODE: NEWS (08:00)
Searching via Tavily...
Blocked aggregator: ...
Too old (...): ...
Candidates after filter: 3
Selected [Kazakhstan]: ...
Post ready (452 chars)
Sent for approval. ID: abc-123-def
```

### 6.2 Check Telegram

Within 1 minute, you should receive a message:

```
NEWS POST FOR APPROVAL (#1/100)
--------------------
Kazakhstan

[News headline]
• Fact 1
• Fact 2
...

https://source.com
--------------------
Approve: /approve abc-123-def
Reject: /reject abc-123-def reason
```

### 6.3 Test Approval

1. Copy the approve command: `/approve abc-123-def`
2. Send to bot
3. Bot should reply: "✅ Пост опубликован!"
4. Check your Telegram channel → post should appear

### 6.4 Test Education

1. GitHub Actions → **Run workflow**
2. Select `post_type`: `education`
3. Should get educational post about VC concepts
4. Approve same way

---

## 7. Going Live

### 7.1 Verify Everything Works

Checklist:
- [ ] Manual news post works
- [ ] Manual education post works
- [ ] `/approve` publishes to channel
- [ ] `/reject` saves reason
- [ ] cron-job.org shows both jobs enabled
- [ ] Render bot responds to commands

### 7.2 Set Posting Schedule

Your current schedule:
- **08:00 Astana** (03:00 UTC) → News post
- **17:00 Astana** (12:00 UTC) → Education post

To change:
1. cron-job.org → edit cronjob
2. Adjust time (remember UTC conversion)
3. Save

### 7.3 Monitor First Week

Days 1-3:
- Check each post for quality
- Reject poor posts with clear reasons
- Bot learns from rejections

Days 4-7:
- Quality should improve
- Duplicates should be rare
- Date filtering working (no old news)

After 100 approved posts:
- Bot switches to auto-publish mode
- You'll only get notifications, no approval needed

---

## 8. Daily Operations

### 8.1 Approving Posts

**Good posts have:**
- Fresh news (within 3 days)
- Specific numbers and facts
- Clear headline
- Relevant to VC/startups

**Reject if:**
- Old news (>3 days)
- Duplicate story
- Not about VC/startups
- Too generic or vague

### 8.2 Rejection Examples

When rejecting, be specific:

```
Bad: /reject abc-123 bad
Good: /reject abc-123 This is about consumer banking, not venture capital

Bad: /reject abc-123 duplicate
Good: /reject abc-123 We already posted about this Anthropic funding round

Bad: /reject abc-123 old
Good: /reject abc-123 Article is from January 15, older than 3 days
```

Bot learns from these reasons to avoid similar content.

### 8.3 Useful Commands

```bash
/pending          # See all posts waiting for approval
/stats           # View bot statistics
/approve <id>    # Publish post
/reject <id> <reason>  # Reject and learn
```

### 8.4 Check Quotas Weekly

Every Monday, check:

**Tavily**: [app.tavily.com](https://app.tavily.com)
- Should use ~60/1000 per month
- If approaching limit, reduce test runs

**Groq**: [console.groq.com](https://console.groq.com) → Usage
- Should use ~200/1000 per month
- Free tier is generous

**GitHub Actions**: Repo → Settings → Billing
- Should use ~120/2000 minutes per month
- No concern

**Supabase**: Project → Settings → Billing
- Database size should be <10MB
- Free tier: 500MB limit

### 8.5 Weekly Maintenance

**Monday:**
- Check quota usage
- Review rejected posts → look for patterns
- Adjust search queries if news quality drops

**Friday:**
- Review week's posts
- Check Supabase security report email
- Clean up old pending posts if any stuck

---

## 9. Customization Guide

### 9.1 Change Search Focus

Edit `bridge.py` → `SEARCH_QUERIES`:

```python
# Example: Focus more on AI startups
SEARCH_QUERIES = [
    {"query": "Kazakhstan AI startup funding February 2026", 
     "region": "Kazakhstan", "priority": 0},
    {"query": "Central Asia machine learning investment 2026",
     "region": "CentralAsia", "priority": 1},
    # ... add more
]
```

### 9.2 Add More Educational Topics

Edit `bridge.py` → `GLOBAL_EDUCATION_TOPICS`:

```python
GLOBAL_EDUCATION_TOPICS = [
    "Как работает венчурный капитал",
    "Your new topic here",
    # ... add more
]
```

### 9.3 Change Post Format

Edit `bridge.py` → find the news prompt (~line 530):

```python
prompt = (
    "You are the editor..."
    "Post structure:\n"
    "1. Your custom structure\n"
    "2. Your requirements\n"
    # ...
)
```

### 9.4 Adjust Date Filter

Edit `bridge.py` → `tavily_search()`:

```python
cutoff = datetime.utcnow().timestamp() - 86400 * 3  # Change 3 to 5 for 5 days
```

---

## 10. Troubleshooting

### Problem: "No suitable news found"

**Cause**: Date filters blocking everything

**Fix**:
1. Check GitHub Actions logs
2. Look for lines: `Too old (...)` or `No date found, skipping`
3. If ALL results blocked → date filter too strict
4. Temporarily change cutoff to 7 days for testing

### Problem: Feedback bot not responding

**Cause**: Render free tier sleeping

**Fix**:
1. Visit bot URL in browser: `https://your-bot.onrender.com/`
2. Should see "OK" or bot info
3. Wait 10 seconds, try command again
4. Set up keep-alive cronjob (see 5.5)

### Problem: Duplicate posts

**Cause**: Deduplication not working

**Fix**:
1. Check Supabase → `posted_news` table
2. Look for the duplicate URL
3. If not there → approval didn't save properly
4. Check feedback_bot logs on Render

### Problem: Old news passing through

**Cause**: Using old version of bridge.py

**Fix**:
1. Pull latest code from this repo
2. Confirm `tavily_search()` has:
   ```python
   if not pub_date:
       print(f"No date found, skipping: {url}")
       continue  # Must be 'continue', not pass through
   ```

### Problem: cron-job not triggering

**Cause**: Wrong GitHub PAT or permissions

**Fix**:
1. Test manually: Send POST request via Postman/curl:
   ```bash
   curl -X POST \
     -H "Authorization: Bearer YOUR_PAT" \
     -H "Accept: application/vnd.github.v3+json" \
     -d '{"event_type":"news-trigger"}' \
     https://api.github.com/repos/USER/REPO/dispatches
   ```
2. Should return 204 No Content
3. Check GitHub Actions → should see workflow triggered
4. If 401/403 → regenerate PAT with correct scopes

---

## 11. Going Beyond Free Tier

### When to Upgrade

**Groq**: When hitting 1K/day limit
- Unlikely unless running 100+ tests daily
- Upgrade to Developer plan: higher limits

**Tavily**: When hitting 1K/month limit
- Happens if testing excessively
- Pay $0.01 per search or reduce tests

**Render**: When instant responses needed 24/7
- Free tier sleeps after 15 min inactivity
- $7/month for always-on

**Supabase**: When database >500MB
- Would take 50,000+ posts to reach
- Upgrade if needed

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

1. **First 20 posts**: Be very selective, reject anything mediocre
2. **Posts 20-50**: Bot starts learning your preferences
3. **Posts 50-100**: Quality should be consistently good
4. **After 100**: Review auto-published posts weekly

### Security

1. **Never commit secrets** to GitHub
2. **Regenerate keys** if accidentally exposed
3. **Check Supabase security reports** every Friday
4. **Use service_role key**, not anon key

### Monitoring

1. **Set up Slack/email alerts** for GitHub Actions failures
2. **Weekly quota check** every Monday
3. **Review rejection patterns** to improve search queries
4. **Check channel engagement** to see what topics resonate

### Optimization

1. **Start with broad queries**, narrow based on results
2. **Adjust priorities** if one region dominates
3. **Add negative keywords** to blocked domains as needed
4. **Update Activat VC transcripts** as new lessons released

---

## 13. FAQ

**Q: Can I use this for non-VC topics?**
A: Yes! Just change `SEARCH_QUERIES` and `VC_KEYWORDS` in bridge.py

**Q: Can I post to multiple channels?**
A: Yes, set multiple `TELEGRAM_CHAT_ID` and loop through in send_to_channel()

**Q: How do I add my own educational content?**
A: Edit `ACTIVAT_LESSONS` array with your transcripts and YouTube URLs

**Q: Can I use a different AI model?**
A: Yes! Change `groq_client.chat.completions.create(model="...")` to any Groq model

**Q: What if I want posts in English, not Russian?**
A: Change all prompts in bridge.py from "Write in RUSSIAN" to "Write in ENGLISH"

**Q: Can I self-host instead of Render?**
A: Yes, feedback_bot.py works on any server with Python 3.10+

**Q: How do I backup my data?**
A: Supabase → Database → Backups tab → Download

**Q: Can I run this on a schedule other than daily?**
A: Yes, edit cron-job.org schedule (e.g., twice daily, weekly)

---

## 14. Support & Community

- **Issues**: [GitHub Issues](https://github.com/DiyarZhunussov/venture-ai-bot/issues)
- **Discussions**: [GitHub Discussions](https://github.com/DiyarZhunussov/venture-ai-bot/discussions)
- **Updates**: Watch this repo for new features

---

**You're all set!**

Your bot should now be:
- Posting news daily at 08:00
- Posting education daily at 17:00
- Learning from your feedback
- Deduplicating intelligently
- Filtering old content

Enjoy your automated VC news channel!
