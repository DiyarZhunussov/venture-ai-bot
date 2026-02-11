import os
import sys
from supabase import create_client, Client
from telegram import Update
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
TELEGRAM_ADMIN_ID = os.getenv("TELEGRAM_ADMIN_ID")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not all([TELEGRAM_FEEDBACK_BOT_TOKEN, TELEGRAM_ADMIN_ID, SUPABASE_URL, SUPABASE_KEY]):
    print("❌ Missing required environment variables for feedback bot.")
    sys.exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
ADMIN_ID = int(TELEGRAM_ADMIN_ID)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Доступ запрещён.")
        return

    text = (
        "👋 Добро пожаловать в бота управления анти-кейсами\n\n"
        "Команды:\n"
        "• Просто напиши текст — добавит новый анти-кейс\n"
        "• /list — показать все анти-кейсы\n"
        "• /delete <id> — удалить анти-кейс по ID\n"
        "• /stats — статистика\n\n"
        "Отправляй анти-кейсы в свободной форме."
    )
    await update.message.reply_text(text)

async def add_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    feedback = update.message.text.strip()
    if not feedback:
        return

    try:
        res = supabase.table("negative_constraints").insert({"feedback": feedback}).execute()
        new_id = res.data[0]["id"]
        await update.message.reply_text(
            f"✅ Анти-кейс добавлен (ID: {new_id}):\n{feedback}"
        )
    except Exception as e:
        await update.message.reply_text(f"Ошибка добавления: {str(e)}")

async def list_feedbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    try:
        res = supabase.table("negative_constraints").select("id, feedback, created_at").order("created_at", desc=True).execute()
        if not res.data:
            await update.message.reply_text("Анти-кейсов пока нет.")
            return

        lines = []
        for row in res.data:
            dt = row["created_at"].split("T")[0]
            lines.append(f"ID: {row['id'][:8]}… | {dt} | {row['feedback'][:80]}")

        text = "Список анти-кейсов:\n\n" + "\n".join(lines)
        await update.message.reply_text(text)
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {str(e)}")

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
            await update.message.reply_text(f"🗑️ Анти-кейс удалён (ID: {feedback_id})")
        else:
            await update.message.reply_text("Не найден анти-кейс с таким ID.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка удаления: {str(e)}")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    try:
        posted = supabase.table("posted_news").select("count", count="exact").execute()
        negatives = supabase.table("negative_constraints").select("count", count="exact").execute()
        entities = supabase.table("tracked_entities").select("count", count="exact").execute()

        text = (
            "📊 Статистика:\n\n"
            f"Опубликовано постов: {posted.count}\n"
            f"Анти-кейсов: {negatives.count}\n"
            f"Отслеживаемых компаний/фондов: {entities.count}"
        )
        await update.message.reply_text(text)
    except Exception as e:
        await update.message.reply_text(f"Ошибка статистики: {str(e)}")

def main():
    print("🚀 ЗАПУСК FEEDBACK BOT")

    app = ApplicationBuilder().token(TELEGRAM_FEEDBACK_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("list", list_feedbacks))
    app.add_handler(CommandHandler("delete", delete_feedback))
    app.add_handler(CommandHandler("stats", stats))

    # Any non-command text → add as new anti-case
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, add_feedback))

    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Feedback bot краш: {e}")
        sys.exit(1)
