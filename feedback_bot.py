import os
import sys
import asyncio
import requests as http_requests
from supabase import create_client, Client
from telegram import Update, Bot
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ────────────────────────────────────────────────
# ENVIRONMENT VARIABLES
# ────────────────────────────────────────────────
TELEGRAM_FEEDBACK_BOT_TOKEN = os.getenv("TELEGRAM_FEEDBACK_BOT_TOKEN")
TELEGRAM_BOT_TOKEN          = os.getenv("TELEGRAM_BOT_TOKEN")       # main bot — for publishing
TELEGRAM_ADMIN_ID           = os.getenv("TELEGRAM_ADMIN_ID")
TELEGRAM_CHAT_ID            = os.getenv("TELEGRAM_CHAT_ID")         # the channel
SUPABASE_URL                = os.getenv("SUPABASE_URL")
SUPABASE_KEY                = os.getenv("SUPABASE_KEY")
NEWS_THREAD_ID              = os.getenv("TELEGRAM_NEWS_THREAD_ID")
EDUCATION_THREAD_ID         = os.getenv("TELEGRAM_EDUCATION_THREAD_ID")

if not all([TELEGRAM_FEEDBACK_BOT_TOKEN, TELEGRAM_ADMIN_ID, SUPABASE_URL, SUPABASE_KEY,
            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID]):
    print("❌ Missing required environment variables for feedback bot.")
    sys.exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
ADMIN_ID         = int(TELEGRAM_ADMIN_ID)
main_bot         = Bot(token=TELEGRAM_BOT_TOKEN)  # used to publish to channel

# ────────────────────────────────────────────────
# HELPERS
# ────────────────────────────────────────────────
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

def add_negative_constraint(feedback: str):
    try:
        res = supabase.table("negative_constraints").insert({"feedback": feedback}).execute()
        return res.data[0]["id"]
    except Exception as e:
        print(f"Failed to add negative constraint: {e}")
        return None

# ────────────────────────────────────────────────
# /start
# ────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Доступ запрещён.")
        return

    text = (
        "👋 Бот управления постами\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "ОДОБРЕНИЕ ПОСТОВ (первые 100):\n"
        "• /approve <id> — опубликовать пост\n"
        "• /reject <id> <причина> — отклонить и запомнить причину\n\n"
        "АНТИ-КЕЙСЫ:\n"
        "• Просто напиши текст — добавит новый анти-кейс\n"
        "• /list — все анти-кейсы\n"
        "• /delete <id> — удалить анти-кейс\n\n"
        "СТАТИСТИКА:\n"
        "• /stats — статистика системы\n"
        "• /pending — посмотреть посты, ожидающие одобрения\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )
    await update.message.reply_text(text)

# ────────────────────────────────────────────────
# /approve <pending_id>  — publish the post
# ────────────────────────────────────────────────
async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        await update.message.reply_text("Использование: /approve <id>")
        return

    pending_id = context.args[0].strip()

    try:
        res = supabase.table("pending_posts").select("*").eq("id", pending_id).execute()
        if not res.data:
            await update.message.reply_text("❌ Пост не найден.")
            return

        post = res.data[0]
        if post["status"] != "pending":
            await update.message.reply_text(f"Пост уже обработан (статус: {post['status']}).")
            return

        post_text = post["post_text"]
        image_url = post.get("image_url", "")
        url_key   = post.get("url") or post_text[:100]
        region    = post.get("region", "Мир")

        # Determine thread ID based on region
        if region == "Education":
            thread_id = int(EDUCATION_THREAD_ID) if EDUCATION_THREAD_ID else None
        else:
            thread_id = int(NEWS_THREAD_ID) if NEWS_THREAD_ID else None

        print(f"DEBUG: region={region}, NEWS_THREAD_ID={NEWS_THREAD_ID}, EDUCATION_THREAD_ID={EDUCATION_THREAD_ID}, thread_id={thread_id}, chat_id={TELEGRAM_CHAT_ID}")

        # Build kwargs for send
        send_kwargs = {"chat_id": TELEGRAM_CHAT_ID}
        if thread_id:
            send_kwargs["message_thread_id"] = thread_id

        # Publish to channel using the main bot
        if image_url:
            await main_bot.send_photo(
                photo=image_url,
                caption=post_text,
                parse_mode="HTML" if "<" in post_text else None,
                **send_kwargs
            )
        else:
            await main_bot.send_message(
                text=post_text,
                disable_web_page_preview=False,
                **send_kwargs
            )

        # Mark as approved in pending_posts
        supabase.table("pending_posts").update({"status": "approved"}).eq("id", pending_id).execute()

        # Record in posted_news (for dedup + count)
        add_to_posted(url_key, "НОВОСТЬ", 8, region)

        await update.message.reply_text(f"✅ Пост опубликован!\n\n{post_text[:200]}...")

    except Exception as e:
        await update.message.reply_text(f"Ошибка публикации: {str(e)}")

# ────────────────────────────────────────────────
# /reject <pending_id> <reason>  — skip + learn
# ────────────────────────────────────────────────
async def reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        await update.message.reply_text("Использование: /reject <id> <причина>")
        return

    pending_id = context.args[0].strip()
    reason     = " ".join(context.args[1:]).strip() if len(context.args) > 1 else ""

    try:
        res = supabase.table("pending_posts").select("*").eq("id", pending_id).execute()
        if not res.data:
            await update.message.reply_text("❌ Пост не найден.")
            return

        post = res.data[0]
        if post["status"] != "pending":
            await update.message.reply_text(f"Пост уже обработан (статус: {post['status']}).")
            return

        # Mark as rejected
        supabase.table("pending_posts").update({"status": "rejected"}).eq("id", pending_id).execute()

        # Auto-learn: if a reason was given, save it as an anti-case
        reply_lines = [f"❌ Пост отклонён."]
        if reason:
            constraint_id = add_negative_constraint(reason)
            reply_lines.append(f"📚 Причина сохранена как анти-кейс: «{reason}»")
            reply_lines.append(f"(ID анти-кейса: {constraint_id})")
        else:
            reply_lines.append("💡 Совет: укажи причину после ID, чтобы бот запомнил её.")
            reply_lines.append("Пример: /reject <id> новости о крипте не нужны")

        await update.message.reply_text("\n".join(reply_lines))

    except Exception as e:
        await update.message.reply_text(f"Ошибка: {str(e)}")

# ────────────────────────────────────────────────
# /pending  — list posts awaiting approval
# ────────────────────────────────────────────────
async def pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    try:
        res = supabase.table("pending_posts").select("id, title, region, created_at, status") \
            .eq("status", "pending").order("created_at", desc=True).execute()

        if not res.data:
            await update.message.reply_text("Нет постов, ожидающих одобрения. ✅")
            return

        lines = ["📋 Посты на одобрении:\n"]
        for row in res.data:
            dt     = row["created_at"].split("T")[0]
            lines.append(
                f"• [{row['region']}] {row['title'][:60]}…\n"
                f"  {dt}\n"
                f"  /approve {row['id']}\n"
                f"  /reject {row['id']} <причина>\n"
            )

        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {str(e)}")

# ────────────────────────────────────────────────
# /list — show all anti-cases
# ────────────────────────────────────────────────
async def list_feedbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    try:
        res = supabase.table("negative_constraints").select("id, feedback, created_at") \
            .order("created_at", desc=True).execute()
        if not res.data:
            await update.message.reply_text("Анти-кейсов пока нет.")
            return

        lines = ["📋 Анти-кейсы:\n"]
        for row in res.data:
            dt = row["created_at"].split("T")[0]
            lines.append(f"• {dt} | {row['feedback'][:80]}\n  ID: {row['id']}")

        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {str(e)}")

# ────────────────────────────────────────────────
# /delete <id>
# ────────────────────────────────────────────────
async def delete_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        await update.message.reply_text("Использование: /delete <id>")
        return

    feedback_id = context.args[0].strip()
    try:
        res = supabase.table("negative_constraints").delete().eq("id", feedback_id).execute()
        if res.data:
            await update.message.reply_text(f"🗑️ Анти-кейс удалён.")
        else:
            await update.message.reply_text("Не найден анти-кейс с таким ID.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка удаления: {str(e)}")

# ────────────────────────────────────────────────
# /stats
# ────────────────────────────────────────────────
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    try:
        posted    = supabase.table("posted_news").select("count", count="exact").execute()
        negatives = supabase.table("negative_constraints").select("count", count="exact").execute()
        pending_r = supabase.table("pending_posts").select("count", count="exact").eq("status", "pending").execute()
        approved  = supabase.table("pending_posts").select("count", count="exact").eq("status", "approved").execute()
        rejected  = supabase.table("pending_posts").select("count", count="exact").eq("status", "rejected").execute()

        mode = "ОДОБРЕНИЕ (первые 100)" if (posted.count or 0) < 100 else "АВТОМАТ"

        text = (
            f"📊 Статистика:\n\n"
            f"Режим: {mode}\n"
            f"Опубликовано постов: {posted.count}\n\n"
            f"Посты на одобрении: {pending_r.count}\n"
            f"Одобрено вручную: {approved.count}\n"
            f"Отклонено: {rejected.count}\n\n"
            f"Анти-кейсов (выученных): {negatives.count}"
        )
        await update.message.reply_text(text)
    except Exception as e:
        await update.message.reply_text(f"Ошибка статистики: {str(e)}")

# ────────────────────────────────────────────────
# Plain text → add as anti-case manually
# ────────────────────────────────────────────────
async def add_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    feedback = update.message.text.strip()
    if not feedback:
        return

    try:
        res    = supabase.table("negative_constraints").insert({"feedback": feedback}).execute()
        new_id = res.data[0]["id"]
        await update.message.reply_text(
            f"✅ Анти-кейс добавлен (ID: {new_id}):\n{feedback}"
        )
    except Exception as e:
        await update.message.reply_text(f"Ошибка добавления: {str(e)}")

# ────────────────────────────────────────────────
# HEALTH CHECK SERVER (required for Render Web Service)
# ────────────────────────────────────────────────
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, format, *args):
        pass  # Silence request logs

def run_health_server():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"Health check server running on port {port}")
    server.serve_forever()

# ────────────────────────────────────────────────
# MAIN
# ────────────────────────────────────────────────
def main():
    print("🚀 ЗАПУСК FEEDBACK BOT")

    # Start health check server in background thread (for Render)
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()

    app = ApplicationBuilder().token(TELEGRAM_FEEDBACK_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",   start))
    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("reject",  reject))
    app.add_handler(CommandHandler("pending", pending))
    app.add_handler(CommandHandler("list",    list_feedbacks))
    app.add_handler(CommandHandler("delete",  delete_feedback))
    app.add_handler(CommandHandler("stats",   stats))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, add_feedback))

    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Feedback bot краш: {e}")
        sys.exit(1)
