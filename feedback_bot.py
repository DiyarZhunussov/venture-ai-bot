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

def add_negative_constraint(feedback: str, post_content: str = None):
    """
    Сохраняет анти-кейс.
    feedback      — причина отклонения (текст)
    post_content  — контент отклонённого поста (чтобы ИИ видел пример что не публиковать)
    """
    try:
        payload = {"feedback": feedback}
        if post_content:
            payload["post_content"] = post_content[:1500]
        res = supabase.table("negative_constraints").insert(payload).execute()
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


# In-memory fallback на случай если bot_state таблица ещё не создана
_STATE_MEMORY: dict = {}


def set_user_state(user_id: int, key: str, value: str):
    """Сохраняет состояние в Supabase + in-memory fallback."""
    state_key = f"{user_id}:{key}"
    # Всегда пишем в память — гарантированный fallback
    _STATE_MEMORY[state_key] = value
    try:
        existing = supabase.table("bot_state").select("id").eq("state_key", state_key).execute()
        if existing.data:
            supabase.table("bot_state").update({"state_value": value}).eq("state_key", state_key).execute()
        else:
            supabase.table("bot_state").insert({"state_key": state_key, "state_value": value}).execute()
    except Exception as e:
        print(f"set_user_state DB error (using memory): {e}")


def get_user_state(user_id: int, key: str) -> str:
    """Читает состояние из Supabase, fallback на in-memory."""
    state_key = f"{user_id}:{key}"
    try:
        res = supabase.table("bot_state").select("state_value").eq("state_key", state_key).execute()
        if res.data:
            val = res.data[0]["state_value"]
            _STATE_MEMORY[state_key] = val  # синхронизируем память
            return val
    except Exception as e:
        print(f"get_user_state DB error (using memory): {e}")
    # Fallback: читаем из памяти
    return _STATE_MEMORY.get(state_key)


def clear_user_state(user_id: int, key: str):
    """Удаляет состояние из Supabase и памяти."""
    state_key = f"{user_id}:{key}"
    _STATE_MEMORY.pop(state_key, None)
    try:
        supabase.table("bot_state").delete().eq("state_key", state_key).execute()
    except Exception as e:
        print(f"clear_user_state DB error: {e}")


def ensure_bot_state_table():
    """Создаёт таблицу bot_state если не существует. Вызывается при старте."""
    try:
        supabase.table("bot_state").select("id").limit(1).execute()
    except Exception:
        try:
            # Таблица не существует — пробуем создать через прямой запрос
            print("bot_state table missing — please run add_metrics_table.sql in Supabase")
        except Exception as e:
            print(f"ensure_bot_state_table error: {e}")

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
    """Варианты причин отклонения + кнопка Назад."""
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
    # Кнопка Назад — возвращает к исходным кнопкам Одобрить/Отклонить
    buttons.append([InlineKeyboardButton("← Назад", callback_data=f"back_to_approval:{pending_id}")])
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
        "• /metrics — метрики обучения ИИ (5 групп)\n"
        "• /bulk — массовый ревью 100 постов\n"
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
            set_user_state(query.from_user.id, "awaiting_reject_reason", pending_id)
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

    # ── Назад → вернуть кнопки Одобрить/Отклонить ──
    elif data.startswith("back_to_approval:"):
        pending_id = data.split(":", 1)[1]
        post = get_post_by_id(pending_id)
        if not post or post["status"] != "pending":
            await query.edit_message_text("Пост уже обработан.")
            return
        preview = post["post_text"][:800]
        await query.edit_message_text(
            preview,
            reply_markup=make_approval_keyboard(pending_id),
        )

    # ── BULK: одобрить пост (только для обучения, НЕ публикует в канал) ──
    elif data.startswith("bk_approve:"):
        pending_id = data.split(":", 1)[1]
        post = get_post_by_id(pending_id)
        if not post:
            await query.edit_message_text("Пост не найден.")
            return
        # Статус → bulk_approved (НЕ в posted_news — пост в канал не уходит)
        # bulk_approved используется как few-shot примеры в bridge.py (get_approved_examples)
        supabase.table("pending_posts") \
            .update({"status": "bulk_approved"}) \
            .eq("id", pending_id).execute()
        await save_post_metric(pending_id, post.get("post_text",""), post.get("region",""),
                               "approved", source_url=post.get("url"), post_type="bulk")
        remaining = supabase.table("pending_posts").select("id", count="exact").eq("status","bulk_pending").execute()
        total_approved = supabase.table("pending_posts").select("id", count="exact").eq("status","bulk_approved").execute()
        # Сначала просим оценку — после неё придёт следующий пост
        await query.edit_message_text(
            f"✅ Одобрен (#{total_approved.count}, осталось: {remaining.count})\n\n"
            f"Оцени качество поста от 1 до 5:",
            reply_markup=make_bulk_rating_keyboard(pending_id)
        )

    # ── BULK: меню причин отклонения ──
    elif data.startswith("bk_reject_menu:"):
        pending_id = data.split(":", 1)[1]
        post = get_post_by_id(pending_id)
        if not post:
            await query.edit_message_text("Пост не найден.")
            return
        await query.edit_message_text(
            f"Причина отклонения:\n\n{post['post_text'][:200]}...",
            reply_markup=make_bulk_reject_keyboard(pending_id)
        )

    # ── BULK: выбрана причина отклонения ──
    elif data.startswith("bk_reject:"):
        _, pending_id, reason_code = data.split(":", 2)
        post = get_post_by_id(pending_id)
        if not post:
            await query.edit_message_text("Пост не найден.")
            return

        if reason_code == "custom":
            set_user_state(query.from_user.id, "awaiting_bulk_reject", pending_id)
            await query.edit_message_text(
                "Напиши причину отклонения одним сообщением.\n"
                "Она сохранится как анти-кейс."
            )
            return

        reason_labels = {
            "not_vc":      "не про венчур и стартапы",
            "geopolitics": "геополитика, не нужна",
            "old_news":    "старая новость, неактуально",
            "too_generic": "слишком общо, нет конкретных фактов",
            "duplicate":   "дубль уже опубликованной новости",
        }
        reason_text = reason_labels.get(reason_code, reason_code)
        supabase.table("pending_posts").update({"status": "rejected"}).eq("id", pending_id).execute()
        # Сохраняем анти-кейс С контентом — ИИ видит и причину и пример плохого поста
        add_negative_constraint(reason_text, post_content=post.get("post_text",""))
        await save_post_metric(pending_id, post.get("post_text",""), post.get("region",""),
                               "rejected", reject_reason=reason_text,
                               source_url=post.get("url"), post_type="bulk")
        remaining = supabase.table("pending_posts").select("id", count="exact").eq("status","bulk_pending").execute()
        # Сначала просим оценку — после неё придёт следующий пост
        await query.edit_message_text(
            f"❌ Отклонён: «{reason_text}» (осталось: {remaining.count})\n\n"
            f"Оцени качество поста от 1 до 5:",
            reply_markup=make_bulk_rating_keyboard(pending_id)
        )

    # ── BULK: назад к кнопкам поста ──
    elif data.startswith("bk_back:"):
        pending_id = data.split(":", 1)[1]
        post = get_post_by_id(pending_id)
        if not post:
            await query.edit_message_text("Пост не найден.")
            return
        await query.edit_message_text(
            post["post_text"][:700],
            reply_markup=make_bulk_post_keyboard(pending_id)
        )

    # ── BULK: оценка 1-5 → после неё шлём следующий пост ──
    elif data.startswith("bk_rate:"):
        _, pending_id, rating_str = data.split(":", 2)
        rating = int(rating_str)
        post = get_post_by_id(pending_id)
        if not post:
            await query.answer("Пост не найден.", show_alert=True)
            return
        try:
            existing = supabase.table("post_metrics") \
                .select("id").eq("pending_id", pending_id).execute()
            if existing.data:
                supabase.table("post_metrics") \
                    .update({"user_rating": rating}) \
                    .eq("pending_id", pending_id).execute()
            else:
                await save_post_metric(pending_id, post.get("post_text",""), post.get("region",""),
                                       "rated", user_rating=rating,
                                       source_url=post.get("url"), post_type="bulk")
                supabase.table("post_metrics") \
                    .update({"user_rating": rating}) \
                    .eq("pending_id", pending_id).execute()
        except Exception as e:
            print(f"Rating save error: {e}")
        stars = "⭐" * rating
        await query.edit_message_text(f"Оценка {stars} сохранена. Загружаю следующий...")
        # Только теперь шлём следующий пост
        await _send_next_bulk_post(query.message.chat_id, context)


# ────────────────────────────────────────────────
# BULK: keyboard builders
# ────────────────────────────────────────────────
def make_bulk_post_keyboard(pending_id: str) -> InlineKeyboardMarkup:
    """Кнопки под каждым bulk-постом: одобрить или отклонить."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Одобрить",  callback_data=f"bk_approve:{pending_id}"),
        InlineKeyboardButton("❌ Отклонить", callback_data=f"bk_reject_menu:{pending_id}"),
    ]])


def make_bulk_rating_keyboard(pending_id: str) -> InlineKeyboardMarkup:
    """Кнопки оценки качества — показываются ПОСЛЕ решения одобрить/отклонить."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⭐1", callback_data=f"bk_rate:{pending_id}:1"),
        InlineKeyboardButton("⭐2", callback_data=f"bk_rate:{pending_id}:2"),
        InlineKeyboardButton("⭐3", callback_data=f"bk_rate:{pending_id}:3"),
        InlineKeyboardButton("⭐4", callback_data=f"bk_rate:{pending_id}:4"),
        InlineKeyboardButton("⭐5", callback_data=f"bk_rate:{pending_id}:5"),
    ]])


def make_bulk_reject_keyboard(pending_id: str) -> InlineKeyboardMarkup:
    """Причины отклонения bulk-поста."""
    reasons = [
        ("Не про VC",      "not_vc"),
        ("Геополитика",    "geopolitics"),
        ("Старая новость", "old_news"),
        ("Слишком общо",   "too_generic"),
        ("Дубль",          "duplicate"),
        ("Своя причина",   "custom"),
    ]
    buttons = []
    row = []
    for label, code in reasons:
        row.append(InlineKeyboardButton(label, callback_data=f"bk_reject:{pending_id}:{code}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("← Назад", callback_data=f"bk_back:{pending_id}")])
    return InlineKeyboardMarkup(buttons)


# ────────────────────────────────────────────────
# METRICS HELPERS
# ────────────────────────────────────────────────
async def save_post_metric(pending_id: str, post_text: str, region: str,
                            decision: str, reject_reason: str = None,
                            user_rating: int = None, quality_score: int = None,
                            source_url: str = None, post_type: str = "bulk"):
    """Записывает метрику одного поста в таблицу post_metrics."""
    import re
    char_count  = len(post_text)
    has_numbers = bool(re.search(r'\d+[\s ]*(млн|млрд|тыс|\$|%|M|B|K|\$\d)', post_text))
    vague       = ["аналитики отмечают", "эксперты считают", "по мнению", "как отмечается",
                   "в целом", "в общем", "в перспективе"]
    has_vague   = any(p in post_text.lower() for p in vague)
    try:
        supabase.table("post_metrics").insert({
            "pending_id":    str(pending_id),
            "post_text":     post_text[:2000],
            "region":        region,
            "quality_score": quality_score,
            "user_rating":   user_rating,
            "decision":      decision,
            "reject_reason": reject_reason,
            "char_count":    char_count,
            "has_numbers":   has_numbers,
            "has_vague":     has_vague,
            "source_url":    source_url,
            "post_type":     post_type,
        }).execute()
    except Exception as e:
        print(f"Metrics save error (non-critical): {e}")


# ────────────────────────────────────────────────
# /bulk — запускает сессию: шлёт первый пост
# ────────────────────────────────────────────────
async def _send_next_bulk_post(chat_id: int, context):
    """
    Загружает следующий bulk_pending пост и шлёт его в чат.
    Вызывается после каждого фидбэка автоматически.
    """
    try:
        res = supabase.table("pending_posts") \
            .select("id, post_text, region") \
            .eq("status", "bulk_pending") \
            .order("created_at", desc=False) \
            .limit(1) \
            .execute()
        posts = res.data or []
    except Exception as e:
        print(f"_send_next_bulk_post error: {e}")
        return

    if not posts:
        # Все посты обработаны
        total_res = supabase.table("pending_posts").select("id", count="exact").eq("status","bulk_approved").execute()
        rej_res   = supabase.table("pending_posts").select("id", count="exact").eq("status","rejected").execute()
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"✅ Все посты обработаны!\n\n"
                f"Одобрено для обучения: {total_res.count}\n"
                f"Отклонено: {rej_res.count}\n\n"
                f"ИИ будет использовать одобренные посты как примеры стиля.\n"
                f"Запусти /metrics чтобы посмотреть аналитику."
            )
        )
        return

    post  = posts[0]
    total = supabase.table("pending_posts").select("id", count="exact").eq("status","bulk_pending").execute().count or 0
    done  = supabase.table("pending_posts").select("id", count="exact").in_("status",["bulk_approved","rejected"]).execute().count or 0

    preview = (
        f"[{done + 1}] [{post['region']}] | Осталось: {total}\n"
        f"{'─'*30}\n"
        f"{post['post_text'][:800]}"
    )
    await context.bot.send_message(
        chat_id=chat_id,
        text=preview,
        reply_markup=make_bulk_post_keyboard(post["id"])
    )


async def bulk_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /bulk — начинает сессию bulk-ревью.
    Шлёт ОДИН пост. После фидбэка бот автоматически шлёт следующий.
    Так продолжается пока не закончатся все посты.
    """
    if not is_authorized(update.effective_user.id):
        return

    total = supabase.table("pending_posts").select("id", count="exact").eq("status","bulk_pending").execute().count or 0
    done  = supabase.table("pending_posts").select("id", count="exact").in_("status",["bulk_approved","rejected"]).execute().count or 0

    if total == 0:
        if done > 0:
            await update.message.reply_text(
                f"✅ Bulk-ревью уже завершён ({done} постов обработано).\n"
                f"Запусти /metrics для аналитики."
            )
        else:
            await update.message.reply_text(
                "Нет постов для bulk-ревью.\n\n"
                "Сначала запусти bulk_seed.py через GitHub Actions:\n"
                "Actions → Run workflow → bulk_seed"
            )
        return

    await update.message.reply_text(
        f"📋 Bulk ревью — {total} постов осталось (обработано: {done})\n\n"
        f"Как давать фидбэк:\n"
        f"• ✅ Одобрить — станет примером стиля для ИИ (в канал НЕ публикуется)\n"
        f"• ❌ Отклонить → причина → сохранится как анти-кейс\n"
        f"• ⭐1–5 — оценка для метрик\n\n"
        f"После каждого ответа автоматически придёт следующий пост. Поехали!"
    )
    await _send_next_bulk_post(update.effective_chat.id, context)


# ────────────────────────────────────────────────
# Обработка текстовой причины при bulk отклонении ("Своя причина")
# ────────────────────────────────────────────────
async def handle_bulk_custom_reject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Вызывается из handle_custom_reject_reason.
    Возвращает True если обработал, False если это не bulk отклонение.
    """
    user_id    = update.effective_user.id
    pending_id = get_user_state(user_id, "awaiting_bulk_reject")
    if not pending_id:
        return False

    reason = update.message.text.strip()
    clear_user_state(user_id, "awaiting_bulk_reject")

    post = get_post_by_id(pending_id)
    if not post:
        await update.message.reply_text("Пост не найден.")
        # Всё равно шлём следующий пост чтобы не застрять
        await _send_next_bulk_post(update.effective_chat.id, context)
        return True

    supabase.table("pending_posts").update({"status": "rejected"}).eq("id", pending_id).execute()
    # Сохраняем анти-кейс С контентом поста
    add_negative_constraint(reason, post_content=post.get("post_text", ""))
    await save_post_metric(pending_id, post.get("post_text", ""), post.get("region", ""),
                           "rejected", reject_reason=reason,
                           source_url=post.get("url"), post_type="bulk")
    remaining = supabase.table("pending_posts").select("id", count="exact").eq("status", "bulk_pending").execute()

    # Подтверждаем и СРАЗУ шлём следующий пост — без ожидания оценки
    # (оценка через "Своя причина" пропускается, чтобы не было разрывов в цепочке)
    await update.message.reply_text(
        f"❌ Отклонён. Причина сохранена как анти-кейс:\n«{reason}»\n"
        f"Осталось постов: {remaining.count}"
    )
    await _send_next_bulk_post(update.effective_chat.id, context)
    return True


# ────────────────────────────────────────────────
# /metrics — все 5 групп метрик из переписки
# ────────────────────────────────────────────────
async def metrics_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /metrics — полная аналитика:
    1. Качество постов
    2. Галлюцинации
    3. Обучение ИИ-агента
    4. Память и обучаемость
    5. Системные метрики
    """
    if not is_authorized(update.effective_user.id):
        return

    try:
        # Загружаем все метрики
        all_m = supabase.table("post_metrics").select("*").execute().data or []
        total = len(all_m)

        if total == 0:
            await update.message.reply_text(
                "Метрик пока нет.\n"
                "Запусти /bulk и дай фидбэк на посты — тогда здесь появится аналитика."
            )
            return

        approved = [m for m in all_m if m.get("decision") == "approved"]
        rejected = [m for m in all_m if m.get("decision") == "rejected"]
        rated    = [m for m in all_m if m.get("user_rating")]

        # ── 1. МЕТРИКИ КАЧЕСТВА ──────────────────────────
        approval_rate = round(len(approved) / total * 100) if total else 0
        reject_rate   = round(len(rejected) / total * 100) if total else 0

        avg_len = round(sum(m.get("char_count", 0) for m in all_m) / total) if total else 0
        with_numbers = sum(1 for m in all_m if m.get("has_numbers"))
        pct_numbers  = round(with_numbers / total * 100) if total else 0

        generic_rejections = [m for m in rejected if m.get("reject_reason") and "общо" in (m.get("reject_reason") or "")]
        pct_generic = round(len(generic_rejections) / total * 100) if total else 0

        avg_rating = round(sum(m.get("user_rating", 0) for m in rated) / len(rated), 1) if rated else "—"

        # ── 2. МЕТРИКИ ГАЛЛЮЦИНАЦИЙ ──────────────────────
        with_vague = sum(1 for m in all_m if m.get("has_vague"))
        pct_vague  = round(with_vague / total * 100) if total else 0

        # Посты с оценкой 1-2 считаем вероятными галлюцинациями
        low_rated = [m for m in rated if (m.get("user_rating") or 0) <= 2]
        pct_low   = round(len(low_rated) / total * 100) if total else 0

        # ── 3. МЕТРИКИ ОБУЧЕНИЯ ──────────────────────────
        # Повторяющиеся причины отклонений
        from collections import Counter
        reject_reasons = [m.get("reject_reason","") for m in rejected if m.get("reject_reason")]
        reason_counts  = Counter(reject_reasons).most_common(3)

        # Запрещённые конструкции из negative_constraints
        nc_total = supabase.table("negative_constraints").select("id", count="exact").execute().count or 0

        # Тренд качества: сравниваем первые 25% и последние 25% постов
        quarter = max(1, total // 4)
        early_approved = sum(1 for m in all_m[:quarter] if m.get("decision") == "approved")
        late_approved  = sum(1 for m in all_m[-quarter:] if m.get("decision") == "approved")
        early_rate = round(early_approved / quarter * 100)
        late_rate  = round(late_approved  / quarter * 100)
        trend      = "↑ растёт" if late_rate > early_rate else ("↓ падает" if late_rate < early_rate else "→ стабильно")

        # ── 4. ПАМЯТЬ И ОБУЧАЕМОСТЬ ──────────────────────
        # Насколько накопленные запреты применяются: смотрим есть ли rejected с теми же причинами
        # что уже были в начале (значит ИИ не усвоил)
        if len(rejected) >= 4:
            first_half_reasons = set(m.get("reject_reason","") for m in rejected[:len(rejected)//2])
            second_half_reasons = Counter(m.get("reject_reason","") for m in rejected[len(rejected)//2:])
            repeat_count = sum(v for k,v in second_half_reasons.items() if k in first_half_reasons)
            repeat_rate  = round(repeat_count / max(1, len(rejected)//2) * 100)
        else:
            repeat_rate = 0

        # Процент постов без нарушений запретов (approved + has_numbers + not has_vague)
        clean = sum(1 for m in all_m if m.get("decision")=="approved" and m.get("has_numbers") and not m.get("has_vague"))
        pct_clean = round(clean / total * 100) if total else 0

        # ── 5. СИСТЕМНЫЕ МЕТРИКИ ──────────────────────────
        bulk_remaining = supabase.table("pending_posts").select("id", count="exact").eq("status","bulk_pending").execute().count or 0
        posted_total   = supabase.table("posted_news").select("id", count="exact").execute().count or 0
        mode = "Одобрение" if posted_total < 100 else "Авто ✅"

        # ── ФОРМАТИРОВАНИЕ с объяснением каждой метрики ──
        lines = [
            "📊 МЕТРИКИ ОБУЧЕНИЯ ИИ",
            "━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            "1️⃣ КАЧЕСТВО ПОСТОВ",
            f"  Одобрено: {approval_rate}%",
            "  ↳ Сколько постов прошло с первого раза без правок.",
            f"  Отклонено: {reject_rate}%",
            f"  Из-за «общих фраз»: {pct_generic}%",
            "  ↳ Посты без конкретных фактов — «эксперты отмечают» и т.п.",
            f"  Средняя длина: {avg_len} симв.",
            "  ↳ Норма 200–350. Если меньше — пост слишком короткий.",
            f"  С конкретными числами: {pct_numbers}%",
            "  ↳ Хороший пост содержит цифры ($, млн, %). Чем выше — тем лучше.",
            f"  Средняя оценка: {avg_rating}/5",
            "  ↳ Твоя личная оценка качества по шкале 1–5.",
            "",
            "2️⃣ ГАЛЛЮЦИНАЦИИ",
            f"  С общими фразами: {pct_vague}%",
            "  ↳ % постов с фразами типа «по мнению аналитиков» — признак выдумки.",
            f"  С низкой оценкой ≤2⭐: {pct_low}%",
            "  ↳ Посты которые ты оценил 1–2 — вероятно содержат ошибки или выдумку.",
            "",
            "3️⃣ ОБУЧЕНИЕ ИИ-АГЕНТА",
            f"  Тренд одобрений: {trend}",
            "  ↳ Сравнение первых и последних постов — растёт ли качество.",
            f"  Ранние посты одобрено: {early_rate}%",
            f"  Поздние посты одобрено: {late_rate}%",
            "  ↳ Если поздние > ранних — ИИ реально учится на твоих фидбэках.",
            f"  Анти-кейсов накоплено: {nc_total}",
            "  ↳ Сколько правил «не публиковать» ИИ уже усвоил.",
        ]

        if reason_counts:
            lines.append("  Топ причин отклонений:")
            for reason, count in reason_counts:
                lines.append(f"    • {reason[:40]}: {count}x")

        lines += [
            "",
            "4️⃣ ПАМЯТЬ И ОБУЧАЕМОСТЬ",
            f"  Повторяющиеся ошибки: {repeat_rate}%",
            "  ↳ Как часто ИИ повторяет уже запрещённые типы контента. Норма <20%.",
            f"  Посты без нарушений: {pct_clean}%",
            "  ↳ Одобренные + с цифрами + без общих фраз. Норма >60%.",
            f"  Обработано постов: {total}",
            "",
            "5️⃣ СИСТЕМНЫЕ",
            f"  Режим: {mode}",
            "  ↳ До 100 одобренных — запрашивает ревью. После — публикует сам.",
            f"  Опубликовано: {posted_total}/100",
            f"  Осталось bulk-постов: {bulk_remaining}",
            f"  Метрик в БД: {total}",
            "",
            "━━━━━━━━━━━━━━━━━━━━━━━━",
            "ℹ️ Сброс данных для нового тестирования:",
            "Запусти reset_for_demo.sql в Supabase → SQL Editor",
        ]

        await update.message.reply_text("\n".join(lines))

    except Exception as e:
        await update.message.reply_text(f"Ошибка метрик: {e}")


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

    # Сначала проверяем bulk отклонение
    if await handle_bulk_custom_reject(update, context):
        return

    user_id    = update.effective_user.id
    pending_id = get_user_state(user_id, "awaiting_reject_reason")
    if not pending_id:
        # Это обычный анти-кейс (не привязан к посту)
        await add_feedback(update, context)
        return

    reason        = update.message.text.strip()
    rejecter_name = update.effective_user.first_name or "Пользователь"

    clear_user_state(user_id, "awaiting_reject_reason")

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
# /stats  — расширенная статистика + краткие метрики качества
# ────────────────────────────────────────────────
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return

    try:
        # ── Базовые счётчики ──
        total       = supabase.table("posted_news").select("count", count="exact").execute()
        negatives   = supabase.table("negative_constraints").select("count", count="exact").execute()
        pend        = supabase.table("pending_posts").select("count", count="exact").eq("status", "pending").execute()
        bulk_left   = supabase.table("pending_posts").select("count", count="exact").eq("status", "bulk_pending").execute()
        approved    = supabase.table("pending_posts").select("count", count="exact").eq("status", "approved").execute()
        rejected_c  = supabase.table("pending_posts").select("count", count="exact").eq("status", "rejected").execute()

        # ── По регионам ──
        kz_count    = supabase.table("posted_news").select("count", count="exact").eq("news_type", "NEWS").eq("source_type", "Kazakhstan").execute()
        ca_count    = supabase.table("posted_news").select("count", count="exact").eq("news_type", "NEWS").eq("source_type", "CentralAsia").execute()
        world_count = supabase.table("posted_news").select("count", count="exact").eq("news_type", "NEWS").eq("source_type", "World").execute()
        edu_count   = supabase.table("posted_news").select("count", count="exact").eq("news_type", "EDUCATION").execute()

        mode = "🟡 Одобрение (первые 100)" if (total.count or 0) < 100 else "🟢 Авто-режим"

        # ── Краткие метрики качества из post_metrics ──
        all_m    = supabase.table("post_metrics").select("decision, has_numbers, has_vague, user_rating, char_count").execute().data or []
        m_total  = len(all_m)
        if m_total > 0:
            m_approved   = sum(1 for m in all_m if m.get("decision") == "approved")
            m_rejected   = sum(1 for m in all_m if m.get("decision") == "rejected")
            m_numbers    = sum(1 for m in all_m if m.get("has_numbers"))
            m_vague      = sum(1 for m in all_m if m.get("has_vague"))
            rated        = [m for m in all_m if m.get("user_rating")]
            avg_rating   = round(sum(m["user_rating"] for m in rated) / len(rated), 1) if rated else None
            avg_len      = round(sum(m.get("char_count",0) for m in all_m) / m_total)
            approval_pct = round(m_approved / m_total * 100)
            numbers_pct  = round(m_numbers  / m_total * 100)
            vague_pct    = round(m_vague    / m_total * 100)
            metrics_block = (
                f"\nМетрики качества (bulk, {m_total} постов):\n"
                f"  Одобрено:        {approval_pct}% ({m_approved}/{m_total})\n"
                f"  С цифрами:       {numbers_pct}%\n"
                f"  Общие фразы:     {vague_pct}%\n"
                f"  Средняя длина:   {avg_len} симв.\n"
                + (f"  Средняя оценка: {avg_rating}/5\n" if avg_rating else "")
                + f"  → /metrics для полной аналитики"
            )
        else:
            metrics_block = "\nМетрики: нет данных (запусти /bulk)"

        text = (
            f"Статистика\n\n"
            f"Режим: {mode}\n"
            f"Опубликовано: {total.count}/100\n\n"
            f"По регионам:\n"
            f"  Казахстан:        {kz_count.count or 0}\n"
            f"  Центральная Азия: {ca_count.count or 0}\n"
            f"  Мир:              {world_count.count or 0}\n"
            f"  Обучение:         {edu_count.count or 0}\n\n"
            f"Очередь:\n"
            f"  На одобрении:    {pend.count}\n"
            f"  Bulk (осталось): {bulk_left.count}\n"
            f"  Одобрено:        {approved.count}\n"
            f"  Отклонено:       {rejected_c.count}\n\n"
            f"Анти-кейсов: {negatives.count}"
            f"{metrics_block}"
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
# /bulk — массовый ревью: каждый пост отдельно с полным фидбэком
# ────────────────────────────────────────────────

def _make_bulk_post_keyboard(pending_id: str) -> InlineKeyboardMarkup:
    """Кнопки фидбэка для каждого bulk-поста."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Одобрить",  callback_data=f"bk_approve:{pending_id}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"bk_reject_menu:{pending_id}"),
        ],
        [
            InlineKeyboardButton("⭐1", callback_data=f"bk_rate:{pending_id}:1"),
            InlineKeyboardButton("⭐2", callback_data=f"bk_rate:{pending_id}:2"),
            InlineKeyboardButton("⭐3", callback_data=f"bk_rate:{pending_id}:3"),
            InlineKeyboardButton("⭐4", callback_data=f"bk_rate:{pending_id}:4"),
            InlineKeyboardButton("⭐5", callback_data=f"bk_rate:{pending_id}:5"),
        ],
    ])


def _make_bulk_reject_keyboard(pending_id: str) -> InlineKeyboardMarkup:
    """Причины отклонения bulk-поста."""
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
        row.append(InlineKeyboardButton(label, callback_data=f"bk_reject:{pending_id}:{code}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("← Назад", callback_data=f"bk_back:{pending_id}")])
    return InlineKeyboardMarkup(buttons)


async def _save_post_metric(pending_id: str, post_text: str, region: str,
                             decision: str, reject_reason: str = None,
                             user_rating: int = None, quality_score: int = None,
                             source_url: str = None, post_type: str = "bulk"):
    """Записывает метрику в post_metrics."""
    import re
    char_count  = len(post_text)
    has_numbers = bool(re.search(r"\d+[\s\u00a0]*(млн|млрд|тыс|\$|%|M|B|K)", post_text))
    vague_phrases = ["аналитики отмечают", "эксперты считают", "по мнению", "как отмечается"]
    has_vague = any(p in post_text.lower() for p in vague_phrases)
    try:
        supabase.table("post_metrics").insert({
            "pending_id":    str(pending_id),
            "post_text":     post_text[:2000],
            "region":        region,
            "quality_score": quality_score,
            "user_rating":   user_rating,
            "decision":      decision,
            "reject_reason": reject_reason,
            "char_count":    char_count,
            "has_numbers":   has_numbers,
            "has_vague":     has_vague,
            "source_url":    source_url,
            "post_type":     post_type,
        }).execute()
    except Exception as e:
        print(f"Metrics save error: {e}")


async def _bulk_do_approve(pending_id: str) -> bool:
    """Одобряет bulk-пост и добавляет в posted_news."""
    try:
        res = supabase.table("pending_posts").select("*").eq("id", pending_id).single().execute()
        post = res.data
        if not post:
            return False
        supabase.table("pending_posts").update({"status": "approved"}).eq("id", pending_id).execute()
        supabase.table("posted_news").insert({
            "url_text":           post.get("url", pending_id),
            "title":              post.get("title", ""),
            "news_type":          "NEWS",
            "shareability_score": 7,
            "source_type":        post.get("region", "Kazakhstan"),
        }).execute()
        await _save_post_metric(
            pending_id=pending_id,
            post_text=post.get("post_text", ""),
            region=post.get("region", ""),
            decision="approved",
            source_url=post.get("url"),
        )
        return True
    except Exception as e:
        print(f"bulk_approve error: {e}")
        return False


async def _bulk_do_reject(pending_id: str, reason: str) -> bool:
    """Отклоняет bulk-пост и сохраняет причину в negative_constraints."""
    try:
        res = supabase.table("pending_posts").select("*").eq("id", pending_id).single().execute()
        post = res.data
        if not post:
            return False
        supabase.table("pending_posts").update({"status": "rejected"}).eq("id", pending_id).execute()
        # Сохраняем причину как анти-кейс если это не "custom" (custom добавится отдельно)
        reason_labels = {
            "not_vc":      "не про венчурный капитал и стартапы",
            "geopolitics": "геополитика и международные конфликты",
            "old_news":    "старая новость, уже не актуально",
            "too_generic": "слишком общо, нет конкретных фактов и цифр",
            "duplicate":   "дубль — такая новость уже публиковалась",
        }
        if reason in reason_labels:
            supabase.table("negative_constraints").insert({
                "feedback": reason_labels[reason]
            }).execute()
        await _save_post_metric(
            pending_id=pending_id,
            post_text=post.get("post_text", ""),
            region=post.get("region", ""),
            decision="rejected",
            reject_reason=reason,
            source_url=post.get("url"),
        )
        return True
    except Exception as e:
        print(f"bulk_reject error: {e}")
        return False





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
    ensure_bot_state_table()
    print("bot_state table: OK")

    # Пробуем включить JobQueue (нужен APScheduler)
    try:
        from telegram.ext import JobQueue
        builder = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).job_queue(JobQueue())
        print("JobQueue: включён")
    except Exception as e:
        builder = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN)
        print(f"JobQueue: недоступен ({e})")

    app = builder.build()

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
    app.add_handler(CommandHandler("bulk",     bulk_cmd))
    app.add_handler(CommandHandler("metrics",  metrics_cmd))

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
