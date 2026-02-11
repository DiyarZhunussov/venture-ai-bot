#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Autonomous Venture Intelligence Analyst
Полностью автономный ИИ-редактор венчурного канала
"""

import os
import requests
import re
import feedparser
import random
from datetime import datetime, timedelta
import google.generativeai as genai
from supabase import create_client
from bs4 import BeautifulSoup
import time

# ============================================
# КОНФИГУРАЦИЯ
# ============================================

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TELEGRAM_ADMIN_ID = os.getenv("TELEGRAM_ADMIN_ID")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY")
GOOGLE_SEARCH_API_KEY = os.getenv("GOOGLE_SEARCH_API_KEY")
GOOGLE_SEARCH_ENGINE_ID = os.getenv("GOOGLE_SEARCH_ENGINE_ID")

# Инициализация
client = genai.Client(api_key=GEMINI_API_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ============================================
# ИСТОЧНИКИ НОВОСТЕЙ
# ============================================

RSS_FEEDS = [
    # Центральная Азия
    "https://kursiv.kz/feed/",
    "https://kursiv.kz/news/StartUp/feed/",
    "https://digitalbusiness.kz/feed/",
    "https://digitalbusiness.kz/category/startups/feed/",
    "https://forbes.kz/rss",
    "https://spot.uz/ru/feed/",
    "https://capital.kz/rss",
    "https://bluescreen.kz/feed/",
    "https://weproject.media/feed/",
    # Tier-1 Global
    "https://techcrunch.com/feed/",
    "https://news.crunchbase.com/feed/",
    "https://www.ycombinator.com/blog/feed",
]

SCRAPE_SITES = [
    {"name": "IT Park Uzbekistan", "url": "https://it-park.uz/ru/news", "selector": "article, .news-item", "region": "UZ"},
    {"name": "Astana Hub", "url": "https://astanahub.com/ru/news/", "selector": "article", "region": "KZ"},
]

KEYWORDS = [
    'инвестиц', 'стартап', 'венчур', 'фонд', 'раунд', 'привлек',
    'запуск', 'млн', 'миллион', 'seed', 'exit', 'выход', 'сделка',
    'финансирование', 'капитал', 'акселератор', 'инкубатор',
    'investment', 'startup', 'venture', 'fund', 'series', 'round',
    'raised', 'million', 'funding', 'capital', 'accelerator', 'exit',
    'MA7', 'Tumar', 'White Hill', 'Big Sky', 'Most Ventures',
    'Axiom Capital', 'Jas Ventures', 'a16z', 'Sequoia', 'YC'
]

TIER_1_ENTITIES = [
    'a16z', 'Andreessen Horowitz', 'Sequoia', 'Y Combinator', 'YC',
    'OpenAI', 'Anthropic', 'Google Ventures', 'Accel'
]

LOCAL_ENTITIES = [
    'MA7 Ventures', 'Tumar Ventures', 'White Hill Capital', 'Big Sky Ventures',
    'Most Ventures', 'Axiom Capital', 'Jas Ventures', 'Astana Hub',
    'Kaspi', 'Chocofamily', 'Kolesa', 'Arbuz.kz'
]

# ============================================
# ОБРАЗОВАТЕЛЬНЫЙ КОНТЕНТ (ACTIVAT VC)
# ============================================

ACTIVAT_VC_TOPICS = [
    {
        "topic": "Параметры инвестиций",
        "content": "Три параметра: доходность (% годовых), надёжность (сохранение ценности), ликвидность (скорость продажи). Депозит: 12%, 100%, 33%. Недвижимость: 15-22%, 70%, 1%. Венчур: неограниченно, 0%, низкая."
    },
    {
        "topic": "Признаки стартапа",
        "content": "5 признаков: юность (3-5 лет), новизна идеи, масштабируемость, технологичность (IT), большой рынок. Uber — не таксопарк, а новая модель через приложение."
    },
    {
        "topic": "Венчурные инвестиции",
        "content": "Venture = рискованный. Высокая смертность, но один успешный окупает 10. Иксы: 5x, 10x, 100x. Правило: 5-10% портфеля. Путь: частный инвестор → бизнес-ангел → супер-ангел → фонд."
    },
    {
        "topic": "Где искать стартапы",
        "content": "4 канала: Google, LinkedIn/Facebook, Demo Days, нетворкинг. Самостоятельно = свобода, но ограничения. В клубе = больше сделок, экспертиза."
    },
    {
        "topic": "Вопросы перед инвестицией",
        "content": "Обсудить: сумму и валюту, сроки, условия траншей (KPI), долю (инвестиция/оценка), вовлечённость. SAFE, конвертируемые займы."
    },
    {
        "topic": "Формы инвестиций",
        "content": "Прямые (cash-in/out), венчурные фонды, частные, корпоративные, краудфандинг (lending/equity)."
    },
    {
        "topic": "Процесс инвестирования",
        "content": "7 этапов: цели, поиск, Due Diligence (финансы, юр., маркетинг), переговоры, Term Sheet, передача, мониторинг."
    },
    {
        "topic": "Стратегии выхода",
        "content": "5 сценариев: следующий раунд, поглощение (M&A), опцион (основатель выкупает), продажа стороннему, банкротство. Обговорить ДО инвестиций!"
    }
]

# ============================================
# ПРОМПТЫ
# ============================================

SYSTEM_NEWS = """Ты — Senior Venture Analyst, редактор элитного канала о венчурном рынке Центральной Азии.

ФОРМАТ (10-15 предложений):

[Эмодзи] Заголовок

ЧТО ПРОИЗОШЛО (2-3):
Суть, цифры, участники

КТО ВОВЛЕЧЁН (2-3):
О компании/фонде, стадия

ПОЧЕМУ ВАЖНО (3-5):
Контекст рынка, тренды, влияние

ВЫВОДЫ (1-2):
Что это значит

Дата: [дата]
Источник: [название]
Ссылка: [URL]

БЕЗ markdown. Избегай клише. Как эксперт, не ИИ."""

SYSTEM_EDU = """Образовательный пост (5-8 предложений).
Практическая польза. Конкретные примеры. БЕЗ markdown."""

# ============================================
# ФУНКЦИИ
# ============================================

def send_admin(text):
    if not TELEGRAM_ADMIN_ID:
        print(f"⚠️ {text}")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": TELEGRAM_ADMIN_ID, "text": f"🤖 {text}"}, timeout=10)

def google_search(query):
    if not GOOGLE_SEARCH_API_KEY:
        return []
    try:
        url = "https://www.googleapis.com/customsearch/v1"
        params = {"key": GOOGLE_SEARCH_API_KEY, "cx": GOOGLE_SEARCH_ENGINE_ID, "q": query, "num": 3}
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 200:
            return [{"title": i["title"], "link": i["link"]} for i in r.json().get("items", [])]
    except:
        pass
    return []

def find_source(text, url):
    for e in LOCAL_ENTITIES:
        if e.lower() in text.lower():
            results = google_search(f"{e} official website")
            if results:
                site = results[0]['link']
                try:
                    supabase.table("tracked_entities").upsert({
                        "entity_name": e,
                        "entity_type": "fund" if "ventures" in e.lower() else "startup",
                        "website": site
                    }, on_conflict="entity_name").execute()
                except:
                    pass
                return site
    return url

def calc_share(news):
    score = 5
    text = (news.get('title', '') + ' ' + news.get('summary', '')).lower()
    if any(w in text for w in ['млн', 'million', '$', '₸']):
        score += 2
    if any(e.lower() in text for e in TIER_1_ENTITIES + LOCAL_ENTITIES):
        score += 2
    if any(w in text for w in ['seed', 'series', 'раунд']):
        score += 1
    if any(w in text for w in ['может', 'планирует']):
        score -= 2
    if not re.search(r'\d', text):
        score -= 3
    return max(1, min(10, score))

def get_activat():
    topic = random.choice(ACTIVAT_VC_TOPICS)
    return f"""Пост из Activat VC:

Тема: {topic['topic']}
Материал: {topic['content']}

5-8 предложений, примеры.
В конце: "Источник: Курс Activat VC"
"""

def parse_rss():
    print("📡 RSS...")
    fresh = []
    day_ago = datetime.now() - timedelta(days=1)
    
    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:20]:
                title = entry.get('title', '')
                summary = entry.get('summary', '')
                link = entry.get('link', '')
                
                pub = entry.get('published_parsed') or entry.get('updated_parsed')
                if pub:
                    pub_date = datetime(*pub[:6])
                    if pub_date < day_ago:
                        continue
                else:
                    pub_date = datetime.now()
                
                text = (title + ' ' + summary).lower()
                if any(kw.lower() in text for kw in KEYWORDS):
                    item = {
                        'title': title,
                        'summary': BeautifulSoup(summary, 'html.parser').get_text()[:800],
                        'link': link,
                        'date': pub_date.strftime('%d.%m.%Y'),
                        'source': feed_url.split('/')[2],
                        'is_tier1': any(t.lower() in text for t in TIER_1_ENTITIES)
                    }
                    item['shareability'] = calc_share(item)
                    fresh.append(item)
        except:
            pass
        time.sleep(0.5)
    
    if fresh:
        fresh.sort(key=lambda x: (x['shareability'], datetime.strptime(x['date'], '%d.%m.%Y')), reverse=True)
    
    print(f"📊 Найдено: {len(fresh)}")
    return fresh

def scrape_site(site):
    try:
        r = requests.get(site['url'], headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        if r.status_code != 200:
            return []
        soup = BeautifulSoup(r.content, 'html.parser')
        articles = soup.select(site['selector'])[:10]
        news = []
        for a in articles:
            try:
                title_tag = a.find(['h1', 'h2', 'h3', 'a'])
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)
                link_tag = a.find('a')
                href = link_tag.get('href', '') if link_tag else ''
                if href and not href.startswith('http'):
                    href = site['url'].rstrip('/') + '/' + href.lstrip('/')
                if any(kw.lower() in title.lower() for kw in KEYWORDS):
                    item = {
                        'title': title, 'summary': '', 'link': href,
                        'date': datetime.now().strftime('%d.%m.%Y'),
                        'source': site['name'],
                        'is_tier1': site.get('region') == 'GLOBAL'
                    }
                    item['shareability'] = calc_share(item)
                    news.append(item)
            except:
                continue
        return news
    except:
        return []

def extract_img(url):
    if not url or not url.startswith('http'):
        return None
    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.content, 'html.parser')
        
        for prop in ['og:image', 'twitter:image']:
            meta = soup.find('meta', property=prop) or soup.find('meta', attrs={'name': prop})
            if meta and meta.get('content'):
                img = meta['content']
                if img.startswith('http'):
                    return img
        return None
    except:
        return None

def unsplash(kw="startup"):
    if not UNSPLASH_ACCESS_KEY:
        return None
    try:
        url = f"https://api.unsplash.com/photos/random?query={kw}&client_id={UNSPLASH_ACCESS_KEY}&orientation=landscape"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            return r.json()['urls']['regular']
    except:
        pass
    return None

# ============================================
# MAIN
# ============================================

def main():
    try:
        print("="*60)
        print("🚀 ЗАПУСК")
        print("="*60)
        send_admin("🚀 Запуск")
        
        # Анти-кейсы
        try:
            neg = supabase.table("negative_constraints").select("feedback").execute()
            neg_ctx = "\n".join([f["feedback"] for f in neg.data]) if neg.data else ""
        except:
            neg_ctx = ""
        
        # Режим
        hour = datetime.now().hour
        print(f"🕐 UTC: {datetime.now().strftime('%H:%M')}")
        
        if hour == 3:
            mode = "НОВОСТЬ"
        elif hour == 12:
            mode = "ОБУЧЕНИЕ"
        else:
            mode = "НОВОСТЬ" if hour < 12 else "ОБУЧЕНИЕ"
        
        print(f"📋 Режим: {mode}")
        
        img = None
        fresh = []
        
        if mode == "НОВОСТЬ":
            fresh = parse_rss()
            
            if len(fresh) < 5:
                print("🕷️ Скрейпинг...")
                for site in SCRAPE_SITES:
                    fresh.extend(scrape_site(site))
                    time.sleep(1)
            
            fresh = [n for n in fresh if n.get('shareability', 0) >= 6]
            print(f"🎯 После фильтра: {len(fresh)}")
            
            if fresh:
                news = fresh[0]
                print(f"\n✅ ВЫБРАНА:\n   {news['title']}")
                
                orig = find_source(news['title'] + ' ' + news['summary'], news['link'])
                
                prompt = f"""Аналитический пост (10-15 предложений):

Заголовок: {news['title']}
Содержание: {news['summary']}
Ссылка: {orig}
Дата: {news['date']}
Источник: {news['source']}

Анти-кейсы: {neg_ctx if neg_ctx else "Нет"}

СТРУКТУРА:
ЧТО ПРОИЗОШЛО (2-3)
КТО ВОВЛЕЧЁН (2-3)
ПОЧЕМУ ВАЖНО (3-5)
ВЫВОДЫ (1-2)

Дата: {news['date']}
Источник: {news['source']}
Ссылка: {orig}
"""
                img = extract_img(news['link']) or unsplash("venture capital")
            else:
                mode = "ОБУЧЕНИЕ"
        
        if mode == "ОБУЧЕНИЕ":
            use_act = random.choice([True, False])
            if use_act:
                prompt = get_activat()
            else:
                prompt = "Образовательный пост (5-8 предложений): Стадии инвестиций / Метрики / Unit Economics / Term Sheet / Due Diligence. С примерами."
            img = unsplash("business education")
        
        # Gemini
        print("🤖 Gemini...")
        sys = SYSTEM_NEWS if mode == "НОВОСТЬ" else SYSTEM_EDU
        
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            config={"system_instruction": sys, "temperature": 0.7},
            contents=prompt
        )
        
        if not resp or not resp.text:
            raise Exception("Gemini пусто")
        
        text = resp.text.strip().replace('**', '').replace('__', '').replace('*', '').replace('_', '')
        
        forbidden = ["симуляци", "я ищу", "Visual Prompt"]
        if any(w.lower() in text.lower() for w in forbidden):
            send_admin("⚠️ Запрещённое слово")
            return
        
        while "---" in text:
            text = text.split("---", 1)[0].strip()
        
        print(f"✅ Готово ({len(text)} символов)")
        
        # Дедупликация
        if mode == "НОВОСТЬ" and fresh:
            dedup = fresh[0]['link']
            share = fresh[0].get('shareability', 0)
            src_type = "tier1" if fresh[0].get('is_tier1') else "local"
        else:
            dedup = text[:100].strip().replace('\n', ' ')
            share = 0
            src_type = "education"
        
        check = supabase.table("posted_news").select("url_text").eq("url_text", dedup).execute()
        if check.data:
            print("❌ Дубликат")
            send_admin("⚠️ Дубликат")
            return
        
        # Публикация
        print("📤 Публикация...")
        msg = text if len(text) <= 4000 else text[:3997] + "..."
        
        if img:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
            payload = {"chat_id": TELEGRAM_CHAT_ID, "photo": img, "caption": msg}
        else:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg}
        
        r = requests.post(url, data=payload, timeout=30)
        
        if r.status_code == 200:
            supabase.table("posted_news").insert({
                "url_text": dedup,
                "news_type": mode,
                "shareability_score": share,
                "source_type": src_type
            }).execute()
            
            print("🎉 ОПУБЛИКОВАНО!")
            
            preview = text[:100] + "..."
            img_st = "✅ картинка" if (img and "unsplash" not in str(img).lower()) else "🎨 Unsplash" if img else "без"
            send_admin(f"✅ {mode}, {img_st}:\n\n{preview}")
        else:
            raise Exception(f"Telegram {r.status_code}")
    
    except Exception as e:
        print(f"\n💥 {e}")
        send_admin(f"💥 {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
