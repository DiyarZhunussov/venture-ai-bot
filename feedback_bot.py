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
TELEGRAM_FOUNDER_ID         = os.getenv("TELEGRAM_FOUNDER_ID")      # NEW: Activat founder
TELEGRAM_CHAT_ID            = os.getenv("TELEGRAM_CHAT_ID")         # the channel
SUPABASE_URL                = os.getenv("SUPABASE_URL")
SUPABASE_KEY                = os.getenv("SUPABASE_KEY")
NEWS_THREAD_ID              = os.getenv("TELEGRAM_NEWS_THREAD_ID")
EDUCATION_THREAD_ID         = os.getenv("TELEGRAM_EDUCATION_THREAD_ID")

if not all([TELEGRAM_FEEDBACK_BOT_TOKEN, TELEGRAM_ADMIN_ID, SUPABASE_URL, SUPABASE_KEY,
            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID]):
    print("Missing required environment variables for feedback bot.")
    sys.exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
ADMIN_ID         = int(TELEGRAM_ADMIN_ID)
FOUNDER_ID       = int(TELEGRAM_FOUNDER_ID) if TELEGRAM_FOUNDER_ID else None
main_bot         = Bot(token=TELEGRAM_BOT_TOKEN)  # used to publish to channel

# Collect all authorized user IDs (admin + founder)
AUTHORIZED_IDS = {ADMIN_ID}
if FOUNDER_ID:
    AUTHORIZED_IDS.add(FOUNDER_ID)

def is_authorized(user_id: int) -> bool:
    return user_id in AUTHORIZED_IDS

# ────────────────────────────────────────────────
# HELPERS
# ────────────────────────────────────────────────
def add_to_posted(url_or_text: str, news_type: str, score: int, source_type: str, title: str = ""):
    try:
        supabase.table("posted_news").insert({
            "url_text":           url_or_text,
            "news_type":          news_type,
            "shareability_score": score,
            "source_type":        source_type,
            "title":              title,
        }).execute()
    except Exception as e:
        try:
            supabase.table("posted_news").insert({
                "url_text":           url_or_text,
                "news_type":          news_type,
                "shareability_score": score,
                "source_type":        source_type,
            }).execute()
        except Exception as e2:
            print(f"Failed to save to posted_news: {e2}")

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
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("Доступ запрещён.")
        return

    text = (
        "Бот управления постами\n\n"
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
    if not is_authorized(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text("Использование: /approve <id>")
        return

    pending_id = context.args[0].strip()
    approver_name = update.effective_user.first_name or "Пользователь"

    try:
        res = supabase.table("pending_posts").select("*").eq("id", pending_id).execute()
        if not res.data:
            await update.message.reply_text("Пост не найден.")
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
        published = False
        if image_url:
            try:
                await main_bot.send_photo(
                    photo=image_url,
                    caption=post_text,
                    parse_mode="HTML" if "<" in post_text else None,
                    **send_kwargs
                )
                published = True
            except Exception as img_err:
                print(f"Image send failed ({img_err}), falling back to text-only.")

        if not published:
            await main_bot.send_message(
                text=post_text,
                disable_web_page_preview=False,
                **send_kwargs
            )

        # Mark as approved in pending_posts
        supabase.table("pending_posts").update({"status": "approved"}).eq("id", pending_id).execute()

        # Record in posted_news (for dedup + count)
        news_type  = "EDUCATION" if region == "Education" else "NEWS"
        post_title = post.get("title", "")
        add_to_posted(url_key, news_type, 8, region, title=post_title)

        reply = f"Пост опубликован ({approver_name}).\n\n{post_text[:200]}..."
        await update.message.reply_text(reply)

        # If founder approved, notify admin too (and vice versa)
        user_id = update.effective_user.id
        if FOUNDER_ID and user_id == FOUNDER_ID and ADMIN_ID != FOUNDER_ID:
            try:
                await main_bot.send_message(
                    ADMIN_ID,
                    f"Пост одобрен фаундером ({approver_name}):\n{post_text[:200]}..."
                )
            except Exception:
                pass
        elif user_id == ADMIN_ID and FOUNDER_ID and ADMIN_ID != FOUNDER_ID:
            try:
                await main_bot.send_message(
                    FOUNDER_ID,
                    f"Пост одобрен администратором ({approver_name}):\n{post_text[:200]}..."
                )
            except Exception:
                pass

    except Exception as e:
        await update.message.reply_text(f"Ошибка публикации: {str(e)}")

# ────────────────────────────────────────────────
# /reject <pending_id> <reason>  — skip + learn
# ────────────────────────────────────────────────
async def reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text("Использование: /reject <id> <причина>")
        return

    pending_id = context.args[0].strip()
    reason     = " ".join(context.args[1:]).strip() if len(context.args) > 1 else ""
    rejecter_name = update.effective_user.first_name or "Пользователь"

    try:
        res = supabase.table("pending_posts").select("*").eq("id", pending_id).execute()
        if not res.data:
            await update.message.reply_text("Пост не найден.")
            return

        post = res.data[0]
        if post["status"] != "pending":
            await update.message.reply_text(f"Пост уже обработан (статус: {post['status']}).")
            return

        # Mark as rejected
        supabase.table("pending_posts").update({"status": "rejected"}).eq("id", pending_id).execute()

        reply_lines = [f"Пост отклонён ({rejecter_name})."]
        if reason:
            constraint_id = add_negative_constraint(reason)
            reply_lines.append(f"Причина сохранена как анти-кейс: «{reason}»")
            reply_lines.append(f"ID анти-кейса: {constraint_id}")
        else:
            reply_lines.append("Совет: укажи причину после ID, чтобы бот запомнил её.")
            reply_lines.append("Пример: /reject <id> новости о крипте не нужны")

        await update.message.reply_text("\n".join(reply_lines))

        # Cross-notify the other person
        user_id = update.effective_user.id
        cross_msg = f"Пост отклонён {rejecter_name}. Причина: {reason or 'не указана'}"
        if FOUNDER_ID and user_id == FOUNDER_ID and ADMIN_ID != FOUNDER_ID:
            try:
                await main_bot.send_message(ADMIN_ID, cross_msg)
            except Exception:
                pass
        elif user_id == ADMIN_ID and FOUNDER_ID and ADMIN_ID != FOUNDER_ID:
            try:
                await main_bot.send_message(FOUNDER_ID, cross_msg)
            except Exception:
                pass

    except Exception as e:
        await update.message.reply_text(f"Ошибка: {str(e)}")

# ────────────────────────────────────────────────
# /pending  — list posts awaiting approval
# ────────────────────────────────────────────────
async def pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return

    try:
        res = supabase.table("pending_posts").select("id, title, region, created_at, status") \
            .eq("status", "pending").order("created_at", desc=True).execute()

        if not res.data:
            await update.message.reply_text("Нет постов, ожидающих одобрения.")
            return

        lines = ["Посты на одобрении:\n"]
        for row in res.data:
            dt     = row["created_at"].split("T")[0]
            lines.append(
                f"[{row['region']}] {row['title'][:60]}...\n"
                f"  Дата: {dt}\n"
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
    if not is_authorized(update.effective_user.id):
        return

    try:
        res = supabase.table("negative_constraints").select("id, feedback, created_at") \
            .order("created_at", desc=True).execute()
        if not res.data:
            await update.message.reply_text("Анти-кейсов пока нет.")
            return

        lines = ["Анти-кейсы:\n"]
        for row in res.data:
            dt = row["created_at"].split("T")[0]
            lines.append(f"{dt} | {row['feedback'][:80]}\n  ID: {row['id']}")

        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {str(e)}")

# ────────────────────────────────────────────────
# /delete <id>
# ────────────────────────────────────────────────
async def delete_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text("Использование: /delete <id>")
        return

    feedback_id = context.args[0].strip()
    try:
        res = supabase.table("negative_constraints").delete().eq("id", feedback_id).execute()
        if res.data:
            await update.message.reply_text("Анти-кейс удалён.")
        else:
            await update.message.reply_text("Не найден анти-кейс с таким ID.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка удаления: {str(e)}")

# ────────────────────────────────────────────────
# /stats
# ────────────────────────────────────────────────
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return

    try:
        posted    = supabase.table("posted_news").select("count", count="exact").execute()
        negatives = supabase.table("negative_constraints").select("count", count="exact").execute()
        pending_r = supabase.table("pending_posts").select("count", count="exact").eq("status", "pending").execute()
        approved  = supabase.table("pending_posts").select("count", count="exact").eq("status", "approved").execute()
        rejected  = supabase.table("pending_posts").select("count", count="exact").eq("status", "rejected").execute()

        mode = "Одобрение (первые 100)" if (posted.count or 0) < 100 else "Авто"

        text = (
            f"Статистика:\n\n"
            f"Режим: {mode}\n"
            f"Опубликовано постов: {posted.count}\n\n"
            f"На одобрении: {pending_r.count}\n"
            f"Одобрено вручную: {approved.count}\n"
            f"Отклонено: {rejected.count}\n\n"
            f"Анти-кейсов: {negatives.count}"
        )
        await update.message.reply_text(text)
    except Exception as e:
        await update.message.reply_text(f"Ошибка статистики: {str(e)}")

# ────────────────────────────────────────────────
# Plain text → add as anti-case manually
# ────────────────────────────────────────────────
async def add_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return

    feedback = update.message.text.strip()
    if not feedback:
        return

    try:
        res    = supabase.table("negative_constraints").insert({"feedback": feedback}).execute()
        new_id = res.data[0]["id"]
        await update.message.reply_text(
            f"Анти-кейс добавлен (ID: {new_id}):\n{feedback}"
        )
    except Exception as e:
        await update.message.reply_text(f"Ошибка добавления: {str(e)}")

# ────────────────────────────────────────────────
# MAIN
# ────────────────────────────────────────────────
if __name__ == "__main__":
    import logging
    import asyncio

    logging.basicConfig(level=logging.INFO)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    port        = int(os.getenv("PORT", 10000))
    base_url    = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
    webhook_url = f"{base_url}/{TELEGRAM_FEEDBACK_BOT_TOKEN}"

    print(f"ЗАПУСК FEEDBACK BOT (webhook mode)")
    print(f"Webhook URL: {webhook_url}")
    print(f"Port: {port}")
    if FOUNDER_ID:
        print(f"Founder ID подключён: {FOUNDER_ID}")

    app = ApplicationBuilder().token(TELEGRAM_FEEDBACK_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",   start))
    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("reject",  reject))
    app.add_handler(CommandHandler("pending", pending))
    app.add_handler(CommandHandler("list",    list_feedbacks))
    app.add_handler(CommandHandler("delete",  delete_feedback))
    app.add_handler(CommandHandler("stats",   stats))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, add_feedback))

    url_path = TELEGRAM_FEEDBACK_BOT_TOKEN

    print("Bot is running in webhook mode.")
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=url_path,
        key=None,
        cert=None,
        webhook_url=webhook_url,
        drop_pending_updates=True,
    )
