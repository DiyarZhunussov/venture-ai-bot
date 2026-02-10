import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
from supabase import create_client, Client

# Переменные
TELEGRAM_FEEDBACK_BOT_TOKEN = os.getenv('TELEGRAM_FEEDBACK_BOT_TOKEN')
TELEGRAM_ADMIN_ID = os.getenv('TELEGRAM_ADMIN_ID')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

async def start(update: Update, context):
    await update.message.reply_text("Инструкция: /list, /delete [ID], /stats, или текст для добавления анти-кейса.")

async def add_feedback(update: Update, context):
    if update.message.from_user.id != int(TELEGRAM_ADMIN_ID):
        return
    feedback = update.message.text
    supabase.table('negative_constraints').insert({'feedback': feedback}).execute()
    await update.message.reply_text(f"✅ Анти-кейс добавлен: {feedback}")

async def list_feedbacks(update: Update, context):
    result = supabase.table('negative_constraints').select('*').execute()
    feedbacks = '\n'.join([f"{item['id']}: {item['feedback']}" for item in result.data])
    await update.message.reply_text(feedbacks or "Нет анти-кейсов.")

# ... другие handlers для /delete, /stats

def main():
    application = ApplicationBuilder().token(TELEGRAM_FEEDBACK_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("list", list_feedbacks))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, add_feedback))
    # ... добавьте другие
    application.run_polling()

if __name__ == "__main__":
    main()
