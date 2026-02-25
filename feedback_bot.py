import os
import sys
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from supabase import create_client, Client
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

# ────────────────────────────────────────────────
# ENVIRONMENT VARIABLES
# ────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN          = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_ADMIN_ID           = os.getenv("TELEGRAM_ADMIN_ID")
TELEGRAM_FOUNDER_ID         = os.getenv("TELEGRAM_FOUNDER_ID")
TELEGRAM_CHAT_ID            = os.getenv("TELEGRAM_CHAT_ID")
SUPABASE_URL                = os.getenv("SUPABASE_URL")
SUPABASE_KEY                = os.getenv("SUPABASE_KEY")
NEWS_THREAD_ID              = os.getenv("TELEGRAM_NEWS_THREAD_ID")
EDUCATION_THREAD_ID         = os.getenv("TELEGRAM_EDUCATION_THREAD_ID")

if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_ID, SUPABASE_URL, SUPABASE_KEY, TELEGRAM_CHAT_ID]):
    print("Missing required environment variables for feedback bot.")
    sys.exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
ADMIN_ID         = int(TELEGRAM_ADMIN_ID)
FOUNDER_ID       = int(TELEGRAM_FOUNDER_ID) if TELEGRAM_FOUNDER_ID else None
main_bot         = Bot(token=TELEGRAM_BOT_TOKEN)

AUTHORIZED_IDS = {ADMIN_ID}
if FOUNDER_ID:
    AUTHORIZED_IDS.add(FOUNDER_ID)

def is_authorized(user_id: int) -> bool:
    return user_id in AUTHORIZED_IDS

# ────────────────────────────────────────────────
# SUPABASE HELPERS
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
                "url_text":  url_or_text,
                "news_type": news_type,
                "shareability_score": score,
                "source_type": source_type,
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

def get_post_by_id(pending_id: str):
    try:
        res = supabase.table("pending_posts").select("*").eq("id", pending_id).execute()
        return res.data[0] if res.data else None
    except:
        return None

# ────────────────────────────────────────────────
# PUBLISH TO CHANNEL
# ────────────────────────────────────────────────
async def publish_post(post: dict) -> bool:
    """Publish approved post to the Telegram channel. Returns True on success."""
    post_text = post["post_text"]
    image_url = post.get("image_url", "")
    region    = post.get("region", "Мир")

    if region == "Education":
        thread_id = int(EDUCATION_THREAD_ID) if EDUCATION_THREAD_ID else None
    else:
        thread_id = int(NEWS_THREAD_ID) if NEWS_THREAD_ID else None

    send_kwargs = {"chat_id": TELEGRAM_CHAT_ID}
    if thread_id:
        send_kwargs["message_thread_id"] = thread_id

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
            print(f"Image send failed ({img_err}), falling back to text.")

    if not published:
        await main_bot.send_message(
            text=post_text,
            disable_web_page_preview=False,
            **send_kwargs
        )

    return True

# ────────────────────────────────────────────────
# INLINE KEYBOARD BUILDERS
# ────────────────────────────────────────────────
def make_approval_keyboard(pending_id: str) -> InlineKeyboardMarkup:
    """Кнопки Одобрить / Отклонить под каждым постом."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Одобрить", callback_data=f"approve:{pending_id}"),
            InlineKeyboardButton("Отклонить", callback_data=f"reject_menu:{pending_id}"),
        ]
    ])

def make_reject_reason_keyboard(pending_id: str) -> InlineKeyboardMarkup:
    """Варианты причин отклонения."""
    reasons = [
        ("Не про VC",        "not_vc"),
        ("Геополитика",      "geopolitics"),
        ("Старая новость",   "old_news"),
        ("Слишком общо",     "too_generic"),
        ("Дубль",            "duplicate"),
        ("Своя причина",     "custom"),
    ]
    buttons = []
    row = []
    for label, code in reasons:
        row.append(InlineKeyboardButton(label, callback_data=f"reject_reason:{pending_id}:{code}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)

# ────────────────────────────────────────────────
# SEND POST FOR APPROVAL (called from bridge.py via main_bot)
# This function is not called directly here — it's a reference implementation.
# bridge.py uses notify_recipients() which sends the preview text.
# The inline keyboard is added by feedback_bot when it sees the approval message.
# ────────────────────────────────────────────────

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
        "ОДОБРЕНИЕ ПОСТОВ:\n"
        "Кнопки приходят автоматически под каждым постом.\n"
        "Или вручную: /approve <id> / /reject <id> <причина>\n\n"
        "ПРОСМОТР:\n"
        "• /pending — посты на одобрении\n"
        "• /rejected — последние отклонённые посты\n\n"
        "АНТИ-КЕЙСЫ:\n"
        "• Просто напиши текст — добавит анти-кейс\n"
        "• /list — все анти-кейсы\n"
        "• /delete <id> — удалить анти-кейс\n\n"
        "СТАТИСТИКА:\n"
        "• /stats — статистика по регионам и режиму\n"
        "• /digest — сводка за последние 7 дней\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )
    await update.message.reply_text(text)

# ────────────────────────────────────────────────
# INLINE BUTTON HANDLER
# ────────────────────────────────────────────────
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_authorized(query.from_user.id):
        await query.answer("Доступ запрещён.")
        return

    await query.answer()
    data = query.data

    # ── Одобрить ──
    if data.startswith("approve:"):
        pending_id    = data.split(":", 1)[1]
        approver_name = query.from_user.first_name or "Пользователь"

        post = get_post_by_id(pending_id)
        if not post:
            await query.edit_message_text("Пост не найден.")
            return
        if post["status"] != "pending":
            await query.edit_message_text(f"Пост уже обработан (статус: {post['status']}).")
            return

        try:
            await publish_post(post)
            supabase.table("pending_posts").update({"status": "approved"}).eq("id", pending_id).execute()
            news_type = "EDUCATION" if post.get("region") == "Education" else "NEWS"
            url_key   = post.get("url") or post["post_text"][:100]
            add_to_posted(url_key, news_type, 8, post.get("region", ""), title=post.get("title", ""))

            await query.edit_message_text(
                f"Одобрено и опубликовано ({approver_name}).\n\n{post['post_text'][:300]}..."
            )
            # Уведомить второго пользователя
            await _cross_notify(query.from_user.id, f"Пост одобрен {approver_name}:\n{post['post_text'][:200]}...")
        except Exception as e:
            await query.edit_message_text(f"Ошибка публикации: {e}")

    # ── Показать меню причин отклонения ──
    elif data.startswith("reject_menu:"):
        pending_id = data.split(":", 1)[1]
        post = get_post_by_id(pending_id)
        if not post or post["status"] != "pending":
            await query.edit_message_text("Пост не найден или уже обработан.")
            return
        await query.edit_message_text(
            f"Выбери причину отклонения:\n\n{post['post_text'][:200]}...",
            reply_markup=make_reject_reason_keyboard(pending_id)
        )

    # ── Выбрана причина отклонения ──
    elif data.startswith("reject_reason:"):
        _, pending_id, reason_code = data.split(":", 2)
        rejecter_name = query.from_user.first_name or "Пользователь"

        post = get_post_by_id(pending_id)
        if not post or post["status"] != "pending":
            await query.edit_message_text("Пост не найден или уже обработан.")
            return

        if reason_code == "custom":
            # Просим написать причину текстом
            context.user_data["awaiting_reject_reason"] = pending_id
            await query.edit_message_text(
                "Напиши причину отклонения одним сообщением.\n"
                "Бот запомнит её как анти-кейс."
            )
            return

        # Предустановленные причины → сохраняем как анти-кейс
        reason_labels = {
            "not_vc":      "не про венчур и стартапы",
            "geopolitics": "геополитика, не нужна",
            "old_news":    "старая новость, неактуально",
            "too_generic": "слишком общо, нет конкретных фактов",
            "duplicate":   "дубль уже опубликованной новости",
        }
        reason_text = reason_labels.get(reason_code, reason_code)

        supabase.table("pending_posts").update({"status": "rejected"}).eq("id", pending_id).execute()
        constraint_id = add_negative_constraint(reason_text)

        await query.edit_message_text(
            f"Отклонено ({rejecter_name}).\n"
            f"Причина сохранена: «{reason_text}»\n"
            f"ID анти-кейса: {constraint_id}"
        )
        await _cross_notify(
            query.from_user.id,
            f"Пост отклонён {rejecter_name}. Причина: {reason_text}"
        )

    # ── Подтверждение удаления анти-кейса ──
    elif data.startswith("confirm_delete:"):
        feedback_id = data.split(":", 1)[1]
        try:
            supabase.table("negative_constraints").delete().eq("id", feedback_id).execute()
            await query.edit_message_text("Анти-кейс удалён.")
        except Exception as e:
            await query.edit_message_text(f"Ошибка: {e}")

    elif data == "cancel_delete":
        await query.edit_message_text("Удаление отменено.")


async def _cross_notify(sender_id: int, message: str):
    """Уведомить второго пользователя (фаундер ↔ админ)."""
    if FOUNDER_ID and sender_id == FOUNDER_ID and ADMIN_ID != FOUNDER_ID:
        try:
            await main_bot.send_message(ADMIN_ID, message)
        except Exception:
            pass
    elif sender_id == ADMIN_ID and FOUNDER_ID and ADMIN_ID != FOUNDER_ID:
        try:
            await main_bot.send_message(FOUNDER_ID, message)
        except Exception:
            pass

# ────────────────────────────────────────────────
# /approve <id>  — ручное одобрение (если вдруг нужно)
# ────────────────────────────────────────────────
async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Использование: /approve <id>")
        return

    pending_id    = context.args[0].strip()
    approver_name = update.effective_user.first_name or "Пользователь"

    post = get_post_by_id(pending_id)
    if not post:
        await update.message.reply_text("Пост не найден.")
        return
    if post["status"] != "pending":
        await update.message.reply_text(f"Пост уже обработан (статус: {post['status']}).")
        return

    try:
        await publish_post(post)
        supabase.table("pending_posts").update({"status": "approved"}).eq("id", pending_id).execute()
        news_type = "EDUCATION" if post.get("region") == "Education" else "NEWS"
        url_key   = post.get("url") or post["post_text"][:100]
        add_to_posted(url_key, news_type, 8, post.get("region", ""), title=post.get("title", ""))
        await update.message.reply_text(f"Опубликовано ({approver_name}).\n\n{post['post_text'][:300]}...")
        await _cross_notify(update.effective_user.id, f"Пост одобрен {approver_name}:\n{post['post_text'][:200]}...")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

# ────────────────────────────────────────────────
# /reject <id> <reason>
# ────────────────────────────────────────────────
async def reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Использование: /reject <id> <причина>")
        return

    pending_id    = context.args[0].strip()
    reason        = " ".join(context.args[1:]).strip() if len(context.args) > 1 else ""
    rejecter_name = update.effective_user.first_name or "Пользователь"

    post = get_post_by_id(pending_id)
    if not post:
        await update.message.reply_text("Пост не найден.")
        return
    if post["status"] != "pending":
        await update.message.reply_text(f"Пост уже обработан (статус: {post['status']}).")
        return

    supabase.table("pending_posts").update({"status": "rejected"}).eq("id", pending_id).execute()

    lines = [f"Отклонено ({rejecter_name})."]
    if reason:
        cid = add_negative_constraint(reason)
        lines.append(f"Причина сохранена: «{reason}»")
        lines.append(f"ID анти-кейса: {cid}")
    else:
        lines.append("Совет: добавь причину — бот запомнит её.")
        lines.append("Пример: /reject <id> геополитика не нужна")

    await update.message.reply_text("\n".join(lines))
    await _cross_notify(update.effective_user.id, f"Пост отклонён {rejecter_name}. Причина: {reason or 'не указана'}")

# ────────────────────────────────────────────────
# Ожидание текстовой причины после нажатия "Своя причина"
# ────────────────────────────────────────────────
async def handle_custom_reject_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return

    pending_id = context.user_data.get("awaiting_reject_reason")
    if not pending_id:
        # Это обычный анти-кейс (не привязан к посту)
        await add_feedback(update, context)
        return

    reason        = update.message.text.strip()
    rejecter_name = update.effective_user.first_name or "Пользователь"

    del context.user_data["awaiting_reject_reason"]

    post = get_post_by_id(pending_id)
    if post and post["status"] == "pending":
        supabase.table("pending_posts").update({"status": "rejected"}).eq("id", pending_id).execute()

    cid = add_negative_constraint(reason)
    await update.message.reply_text(
        f"Отклонено ({rejecter_name}).\n"
        f"Причина сохранена: «{reason}»\n"
        f"ID анти-кейса: {cid}"
    )
    await _cross_notify(update.effective_user.id, f"Пост отклонён {rejecter_name}. Причина: {reason}")

# ────────────────────────────────────────────────
# /pending
# ────────────────────────────────────────────────
async def pending_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return

    try:
        res = supabase.table("pending_posts").select("id, title, region, created_at") \
            .eq("status", "pending").order("created_at", desc=True).execute()

        if not res.data:
            await update.message.reply_text("Нет постов на одобрении.")
            return

        lines = [f"Постов на одобрении: {len(res.data)}\n"]
        for row in res.data:
            dt = row["created_at"].split("T")[0]
            lines.append(
                f"[{row['region']}] {row['title'][:55]}...\n"
                f"  Дата: {dt}\n"
                f"  /approve {row['id']}\n"
            )
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

# ────────────────────────────────────────────────
# /rejected  — показать последние отклонённые посты (НОВАЯ КОМАНДА)
# ────────────────────────────────────────────────
async def rejected_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return

    try:
        res = supabase.table("pending_posts") \
            .select("id, title, region, created_at") \
            .eq("status", "rejected") \
            .order("created_at", desc=True) \
            .limit(15) \
            .execute()

        if not res.data:
            await update.message.reply_text("Отклонённых постов нет.")
            return

        lines = [f"Последние отклонённые посты ({len(res.data)}):\n"]
        for row in res.data:
            dt = row["created_at"].split("T")[0]
            lines.append(f"[{row['region']}] {row['title'][:60]}\n  Дата: {dt}\n")

        # Также показать сохранённые анти-кейсы
        nc_res = supabase.table("negative_constraints") \
            .select("feedback, created_at") \
            .order("created_at", desc=True) \
            .limit(8) \
            .execute()

        if nc_res.data:
            lines.append("\nСохранённые причины отклонений:")
            for row in nc_res.data:
                dt = row["created_at"].split("T")[0]
                lines.append(f"  {dt}: {row['feedback'][:70]}")

        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

# ────────────────────────────────────────────────
# /list
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

        lines = [f"Анти-кейсы ({len(res.data)}):\n"]
        for row in res.data:
            dt = row["created_at"].split("T")[0]
            lines.append(f"{dt} | {row['feedback'][:80]}\n  ID: {row['id']}")

        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

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

    # Запросить подтверждение через inline-кнопки
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Да, удалить", callback_data=f"confirm_delete:{feedback_id}"),
            InlineKeyboardButton("Отмена",      callback_data="cancel_delete"),
        ]
    ])
    await update.message.reply_text(
        f"Удалить анти-кейс {feedback_id}?",
        reply_markup=keyboard
    )

# ────────────────────────────────────────────────
# /stats  — статистика с разбивкой по регионам (ОБНОВЛЕНО)
# ────────────────────────────────────────────────
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return

    try:
        # Общие счётчики
        total     = supabase.table("posted_news").select("count", count="exact").execute()
        negatives = supabase.table("negative_constraints").select("count", count="exact").execute()
        pend      = supabase.table("pending_posts").select("count", count="exact").eq("status", "pending").execute()
        approved  = supabase.table("pending_posts").select("count", count="exact").eq("status", "approved").execute()
        rejected  = supabase.table("pending_posts").select("count", count="exact").eq("status", "rejected").execute()

        # Разбивка по регионам (только NEWS)
        kz_count  = supabase.table("posted_news").select("count", count="exact") \
            .eq("news_type", "NEWS").eq("source_type", "Kazakhstan").execute()
        ca_count  = supabase.table("posted_news").select("count", count="exact") \
            .eq("news_type", "NEWS").eq("source_type", "CentralAsia").execute()
        world_count = supabase.table("posted_news").select("count", count="exact") \
            .eq("news_type", "NEWS").eq("source_type", "World").execute()
        edu_count = supabase.table("posted_news").select("count", count="exact") \
            .eq("news_type", "EDUCATION").execute()

        mode = "Одобрение (первые 100)" if (total.count or 0) < 100 else "Авто"

        text = (
            f"Статистика\n\n"
            f"Режим: {mode}\n"
            f"Всего опубликовано: {total.count}\n\n"
            f"По регионам (новости):\n"
            f"  Казахстан:        {kz_count.count or 0}\n"
            f"  Центральная Азия: {ca_count.count or 0}\n"
            f"  Мир:              {world_count.count or 0}\n"
            f"  Обучение:         {edu_count.count or 0}\n\n"
            f"Очередь:\n"
            f"  На одобрении:  {pend.count}\n"
            f"  Одобрено:      {approved.count}\n"
            f"  Отклонено:     {rejected.count}\n\n"
            f"Анти-кейсов: {negatives.count}"
        )
        await update.message.reply_text(text)
    except Exception as e:
        await update.message.reply_text(f"Ошибка статистики: {e}")

# ────────────────────────────────────────────────
# /digest  — сводка за последние 7 дней (НОВАЯ КОМАНДА)
# ────────────────────────────────────────────────
async def digest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return

    try:
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

        # Опубликованные за неделю
        published = supabase.table("posted_news") \
            .select("title, news_type, source_type, created_at") \
            .gte("created_at", week_ago) \
            .order("created_at", desc=True) \
            .execute()

        # Отклонённые за неделю
        rej = supabase.table("pending_posts") \
            .select("title, region, created_at") \
            .eq("status", "rejected") \
            .gte("created_at", week_ago) \
            .execute()

        # Анти-кейсы добавленные за неделю
        new_constraints = supabase.table("negative_constraints") \
            .select("feedback, created_at") \
            .gte("created_at", week_ago) \
            .execute()

        pub_data  = published.data or []
        rej_data  = rej.data or []
        nc_data   = new_constraints.data or []

        news_pub  = [p for p in pub_data if p.get("news_type") == "NEWS"]
        edu_pub   = [p for p in pub_data if p.get("news_type") == "EDUCATION"]

        lines = [
            f"Сводка за последние 7 дней\n",
            f"Опубликовано: {len(pub_data)} постов",
            f"  Новости:   {len(news_pub)}",
            f"  Обучение:  {len(edu_pub)}",
            f"Отклонено:   {len(rej_data)}",
            f"Новых анти-кейсов: {len(nc_data)}\n",
        ]

        if news_pub:
            lines.append("Опубликованные новости:")
            for p in news_pub[:8]:
                dt = p["created_at"].split("T")[0]
                region = p.get("source_type", "")
                lines.append(f"  {dt} [{region}] {(p.get('title') or '')[:55]}")

        if rej_data:
            lines.append("\nОтклонённые:")
            for r in rej_data[:5]:
                dt = r["created_at"].split("T")[0]
                lines.append(f"  {dt} [{r.get('region','')}] {(r.get('title') or '')[:55]}")

        if nc_data:
            lines.append("\nНовые анти-кейсы:")
            for nc in nc_data:
                lines.append(f"  - {nc['feedback'][:70]}")

        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

# ────────────────────────────────────────────────
# WEEKLY DIGEST JOB  — автоматическая рассылка каждое воскресенье
# ────────────────────────────────────────────────
async def send_weekly_digest(context: ContextTypes.DEFAULT_TYPE):
    """Автоматически отправляет еженедельную сводку каждое воскресенье в 18:00 Астана (13:00 UTC)."""
    try:
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

        published = supabase.table("posted_news") \
            .select("title, news_type, source_type, created_at") \
            .gte("created_at", week_ago).execute()
        rej = supabase.table("pending_posts") \
            .select("title, region", count="exact") \
            .eq("status", "rejected").gte("created_at", week_ago).execute()
        nc = supabase.table("negative_constraints") \
            .select("feedback", count="exact") \
            .gte("created_at", week_ago).execute()

        pub_data = published.data or []
        news_pub = [p for p in pub_data if p.get("news_type") == "NEWS"]
        edu_pub  = [p for p in pub_data if p.get("news_type") == "EDUCATION"]

        kz  = [p for p in news_pub if p.get("source_type") == "Kazakhstan"]
        ca  = [p for p in news_pub if p.get("source_type") == "CentralAsia"]
        w   = [p for p in news_pub if p.get("source_type") == "World"]

        text = (
            f"Еженедельная сводка — {datetime.now(timezone.utc).strftime('%d.%m.%Y')}\n\n"
            f"Опубликовано за неделю: {len(pub_data)}\n"
            f"  Казахстан:        {len(kz)}\n"
            f"  Центральная Азия: {len(ca)}\n"
            f"  Мир:              {len(w)}\n"
            f"  Обучение:         {len(edu_pub)}\n\n"
            f"Отклонено: {rej.count or 0}\n"
            f"Новых анти-кейсов: {nc.count or 0}\n\n"
            f"Для подробностей: /digest"
        )

        for uid in AUTHORIZED_IDS:
            try:
                await context.bot.send_message(uid, text)
            except Exception as e:
                print(f"Failed to send weekly digest to {uid}: {e}")

    except Exception as e:
        print(f"Weekly digest error: {e}")

# ────────────────────────────────────────────────
# SEND APPROVAL MESSAGE WITH INLINE BUTTONS
# This is called by the main bridge.py via notify_recipients.
# But feedback_bot also needs to intercept incoming approval texts
# and attach buttons — handled here via a special message handler.
# ────────────────────────────────────────────────
async def intercept_approval_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Когда bridge.py присылает сообщение вида 'НОВОСТЬ НА ОДОБРЕНИЕ ... /approve <id>',
    feedback_bot добавляет к нему inline-кнопки чтобы не нужно было копировать ID.
    """
    if not is_authorized(update.effective_user.id):
        return

    text = update.message.text or ""

    # Проверяем — это сообщение от bridge.py с постом на одобрение
    if ("НА ОДОБРЕНИЕ" in text or "FOR APPROVAL" in text) and "/approve " in text:
        import re
        match = re.search(r"/approve ([a-f0-9\-]{36})", text)
        if match:
            pending_id = match.group(1)
            await update.message.reply_text(
                "Используй кнопки для быстрого одобрения:",
                reply_markup=make_approval_keyboard(pending_id)
            )
            return

    # Иначе — это обычный анти-кейс
    await add_feedback(update, context)

# ────────────────────────────────────────────────
# Plain text → anti-case
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
        await update.message.reply_text(f"Анти-кейс добавлен (ID: {new_id}):\n{feedback}")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

# ────────────────────────────────────────────────
# MAIN
# ────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    port        = int(os.getenv("PORT", 10000))
    base_url    = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
    webhook_url = f"{base_url}/webhook"

    print(f"ЗАПУСК FEEDBACK BOT (webhook mode)")
    print(f"Webhook URL: {webhook_url}")
    print(f"Port: {port}")
    if FOUNDER_ID:
        print(f"Founder ID: {FOUNDER_ID}")

    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    # Commands
    app.add_handler(CommandHandler("start",    start))
    app.add_handler(CommandHandler("approve",  approve))
    app.add_handler(CommandHandler("reject",   reject))
    app.add_handler(CommandHandler("pending",  pending_cmd))
    app.add_handler(CommandHandler("rejected", rejected_cmd))
    app.add_handler(CommandHandler("list",     list_feedbacks))
    app.add_handler(CommandHandler("delete",   delete_feedback))
    app.add_handler(CommandHandler("stats",    stats))
    app.add_handler(CommandHandler("digest",   digest))

    # Inline button callbacks
    app.add_handler(CallbackQueryHandler(button_handler))

    # Text messages — check if approval message or plain anti-case
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_custom_reject_reason
    ))

    # Weekly digest — every Sunday at 13:00 UTC (18:00 Astana)
    job_queue = app.job_queue
    if job_queue:
        # Run weekly on Sunday (weekday=6) at 13:00 UTC
        from datetime import time as dt_time
        job_queue.run_daily(
            send_weekly_digest,
            time=dt_time(hour=13, minute=0, tzinfo=timezone.utc),
            days=(6,),  # Sunday
            name="weekly_digest",
        )
        print("Weekly digest scheduled: Sundays at 13:00 UTC (18:00 Astana)")

    print("Bot is running in webhook mode.")
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path="webhook",
        webhook_url=webhook_url,
        drop_pending_updates=True,
    )
