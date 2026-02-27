"""
check_learning.py — полная проверка что ИИ реально учится на фидбэках.

Запусти локально или через GitHub Actions (workflow_dispatch).

Показывает:
  1. Что сохранено в БД (одобренные, отклонённые, анти-кейсы)
  2. Точный промпт который получит ИИ при следующей генерации
  3. Тест-генерацию: пост ДО и ПОСЛЕ фидбэков на одну и ту же тему
  4. Итоговый вердикт — учится или нет

python check_learning.py
"""

import os
import sys
from datetime import datetime, timezone

from supabase import create_client, Client
from groq import Groq

GROQ_API_KEY   = os.getenv("GROQ_API_KEY")
SUPABASE_URL   = os.getenv("SUPABASE_URL")
SUPABASE_KEY   = os.getenv("SUPABASE_KEY")

if not all([GROQ_API_KEY, SUPABASE_URL, SUPABASE_KEY]):
    print("Нужны GROQ_API_KEY, SUPABASE_URL, SUPABASE_KEY")
    sys.exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
groq_client      = Groq(api_key=GROQ_API_KEY)

SEP = "─" * 60

def section(title: str):
    print(f"\n{'═'*60}")
    print(f"  {title}")
    print(f"{'═'*60}")


# ─────────────────────────────────────────────────────
# ШАГ 1: Что сохранено в БД
# ─────────────────────────────────────────────────────
def check_database():
    section("ШАГ 1: ЧТО СОХРАНЕНО В БД")

    # Одобренные bulk
    approved = supabase.table("pending_posts") \
        .select("id, post_text, region, created_at") \
        .in_("status", ["approved", "bulk_approved"]) \
        .order("created_at", desc=True) \
        .limit(5) \
        .execute().data or []

    print(f"\n✅ ОДОБРЕННЫЕ ПОСТЫ (few-shot примеры стиля): {len(approved)} последних\n")
    if approved:
        for i, p in enumerate(approved, 1):
            print(f"  [{i}] [{p['region']}] {p['post_text'][:120]}...")
            print()
    else:
        print("  ❌ НЕТ — ИИ генерирует без примеров стиля")

    # Отклонённые с контентом
    rejected = supabase.table("negative_constraints") \
        .select("feedback, post_content, created_at") \
        .order("created_at", desc=True) \
        .limit(5) \
        .execute().data or []

    with_content    = [r for r in rejected if r.get("post_content")]
    without_content = [r for r in rejected if not r.get("post_content")]

    print(f"{SEP}")
    print(f"\n❌ АНТИ-КЕЙСЫ ВСЕГО: {len(rejected)}")
    print(f"   С контентом поста (антипримеры): {len(with_content)}")
    print(f"   Только текст причины:            {len(without_content)}\n")

    if with_content:
        print("  Антипримеры (причина + контент):")
        for i, r in enumerate(with_content[:3], 1):
            print(f"\n  [{i}] Причина: {r['feedback']}")
            print(f"       Контент: {r['post_content'][:100]}...")
    else:
        print("  ⚠️  Нет антипримеров с контентом.")
        print("  Дай фидбэк через /bulk — выбери ❌ Отклонить → причина")

    if without_content:
        print(f"\n  Причины без контента (только для фильтрации тем):")
        for r in without_content[:3]:
            print(f"  - {r['feedback']}")

    return approved, with_content


# ─────────────────────────────────────────────────────
# ШАГ 2: Точный промпт
# ─────────────────────────────────────────────────────
def build_and_show_prompt(approved: list, rejected_examples: list):
    section("ШАГ 2: ТОЧНЫЙ ПРОМПТ КОТОРЫЙ ПОЛУЧИТ ИИ")

    # Собираем промпт точно как в bridge.py
    region        = "Kazakhstan"
    region_header = "Казахстан"
    test_title    = "Astana Hub привлёк $5 млн от международных инвесторов"
    test_snippet  = "Технопарк Astana Hub объявил о привлечении $5 млн от консорциума инвесторов из США и ОАЭ. Средства пойдут на расширение акселерационных программ и поддержку 200 стартапов в 2026 году."
    test_url      = "https://example.com/astana-hub-funding"

    # Few-shot блок
    examples_block = ""
    examples_used  = []
    for row in approved:
        if row.get("region") == region or len(examples_used) < 3:
            text  = row.get("post_text", "").strip()
            lines = [l for l in text.split("\n") if not l.startswith("http")]
            clean = "\n".join(lines).strip()
            if clean and len(clean) > 80:
                examples_used.append(clean)
            if len(examples_used) >= 3:
                break

    if examples_used:
        examples_block = (
            "\nПРИМЕРЫ ОДОБРЕННЫХ ПОСТОВ — учись СТИЛЮ (длина, тон, структура):\n"
            "Факты для нового поста бери ТОЛЬКО из раздела ИСТОЧНИК ниже.\n"
        )
        for i, ex in enumerate(examples_used, 1):
            examples_block += f"\n[Пример {i}]\n{ex}\n"
        examples_block += "\n"

    # Rejected блок
    rejected_block = ""
    if rejected_examples:
        rejected_block = "\nПРИМЕРЫ ОТКЛОНЁННЫХ ПОСТОВ — НИКОГДА не пиши так:\n"
        for i, ex in enumerate(rejected_examples[:4], 1):
            rejected_block += (
                f"\n[Антипример {i}] Причина: {ex['feedback']}\n"
                f"Контент: {ex['post_content'][:300]}\n"
            )
        rejected_block += "\nЭти посты отклонил редактор. Не повторяй их стиль и причины.\n"

    # Constraint context
    all_constraints = supabase.table("negative_constraints") \
        .select("feedback").execute().data or []
    constraint_context = ""
    if all_constraints:
        constraint_context = "\nПредыдущие причины отклонений (не повторяй подобный контент):\n"
        for c in all_constraints[:8]:
            constraint_context += f"  - {c['feedback']}\n"

    prompt = (
        "Ты редактор Telegram-канала о венчурном капитале в Центральной Азии.\n"
        "Напиши новостной пост на РУССКОМ языке строго по этой статье.\n"
        f"{examples_block}"
        f"{rejected_block}"
        "ИСТОЧНИК (используй ТОЛЬКО эти факты, не добавляй ничего от себя):\n"
        f"Заголовок: {test_title}\n"
        f"Содержание: {test_snippet}\n"
        f"Ссылка: {test_url}\n\n"
        f"{constraint_context}\n"
        f"Начни пост ТОЧНО со слова: {region_header}\n"
        "Затем пустая строка, затем сам пост.\n\n"
        "Структура — ровно 2 предложения:\n"
        "1. Что произошло — кто, что, сколько.\n"
        "2. Конкретный вывод для рынка.\n"
        "Длина 200-350 символов. Без эмодзи, без хэштегов.\n"
    )

    print(f"\n{'─'*60}")
    print(prompt)
    print(f"{'─'*60}")
    print(f"\n📊 В промпте:")
    print(f"  Примеров одобренных постов: {len(examples_used)}")
    print(f"  Антипримеров отклонённых:   {len(rejected_examples[:4])}")
    print(f"  Анти-кейсов (фильтр тем):   {len(all_constraints)}")

    return prompt, test_title, test_snippet


# ─────────────────────────────────────────────────────
# ШАГ 3: Генерация ДО и ПОСЛЕ фидбэков
# ─────────────────────────────────────────────────────
def test_generation(full_prompt: str, test_title: str, test_snippet: str):
    section("ШАГ 3: ГЕНЕРАЦИЯ С ФИДБЭКАМИ (реальный результат)")

    print("\n🤖 Генерирую пост с учётом всех фидбэков...\n")
    try:
        resp = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": full_prompt}],
            max_tokens=512,
            temperature=0.6,
        )
        post_with = resp.choices[0].message.content.strip()
    except Exception as e:
        post_with = f"ОШИБКА: {e}"

    print("Пост С фидбэками:")
    print(f"{'─'*60}")
    print(post_with)
    print(f"{'─'*60}")

    # Для сравнения — без фидбэков
    bare_prompt = (
        "Ты редактор Telegram-канала о венчурном капитале в Центральной Азии.\n"
        "Напиши новостной пост на РУССКОМ языке строго по этой статье.\n\n"
        "ИСТОЧНИК:\n"
        f"Заголовок: {test_title}\n"
        f"Содержание: {test_snippet}\n\n"
        "Начни со слова: Казахстан\n"
        "Структура — ровно 2 предложения. Длина 200-350 символов.\n"
    )

    print("\n🤖 Генерирую пост БЕЗ фидбэков (для сравнения)...\n")
    try:
        resp2 = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": bare_prompt}],
            max_tokens=512,
            temperature=0.6,
        )
        post_without = resp2.choices[0].message.content.strip()
    except Exception as e:
        post_without = f"ОШИБКА: {e}"

    print("Пост БЕЗ фидбэков:")
    print(f"{'─'*60}")
    print(post_without)
    print(f"{'─'*60}")

    return post_with, post_without


# ─────────────────────────────────────────────────────
# ШАГ 4: Вердикт
# ─────────────────────────────────────────────────────
def verdict(approved: list, rejected_with_content: list, post_with: str, post_without: str):
    section("ШАГ 4: ВЕРДИКТ — УЧИТСЯ ЛИ ИИ?")

    checks = []

    # Проверка 1: есть одобренные примеры
    ok1 = len(approved) > 0
    checks.append((ok1,
        f"Одобренные посты как примеры стиля: {len(approved)} шт.",
        "Нет одобренных постов → запусти /bulk и одобри хотя бы 5"))

    # Проверка 2: есть антипримеры с контентом
    ok2 = len(rejected_with_content) > 0
    checks.append((ok2,
        f"Антипримеры с контентом: {len(rejected_with_content)} шт.",
        "Нет антипримеров → при отклонении выбирай причину из меню или пиши свою"))

    # Проверка 3: пост с фидбэками отличается от поста без
    ok3 = post_with != post_without and "ОШИБКА" not in post_with
    checks.append((ok3,
        "Промпт с фидбэками генерирует другой результат",
        "Посты идентичны — возможно фидбэков слишком мало"))

    # Проверка 4: пост с фидбэками не содержит запрещённых фраз
    all_constraints = supabase.table("negative_constraints").select("feedback").execute().data or []
    forbidden       = [c["feedback"].lower() for c in all_constraints]
    violations      = [f for f in forbidden if any(w in post_with.lower() for w in f.split()[:3])]
    ok4 = len(violations) == 0
    checks.append((ok4,
        "Пост не нарушает анти-кейсы",
        f"Нарушены правила: {violations[:2]}"))

    print()
    all_ok = True
    for ok, good_msg, bad_msg in checks:
        icon = "✅" if ok else "❌"
        msg  = good_msg if ok else bad_msg
        print(f"  {icon} {msg}")
        if not ok:
            all_ok = False

    print()
    if all_ok:
        print("🎓 ИТОГ: ИИ УЧИТСЯ. Фидбэки попадают в промпт и влияют на генерацию.")
        print("   Чем больше фидбэков — тем точнее будут посты.")
    else:
        print("⚠️  ИТОГ: Есть пробелы в обучении. Исправь отмеченные пункты.")

    print()
    print("Дальнейшие шаги для улучшения качества:")
    print("  1. Дай фидбэк на 50+ постов через /bulk")
    print("  2. При отклонении всегда выбирай причину (попадёт в антипримеры)")
    print("  3. Ставь оценку ⭐ — метрики покажут тренд улучшения")
    print("  4. Запускай /metrics раз в неделю — смотри растёт ли % одобрений")


# ─────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"\n{'═'*60}")
    print(f"  ПРОВЕРКА ОБУЧЕНИЯ ИИ")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'═'*60}")

    approved, rejected_with_content = check_database()
    prompt, test_title, test_snippet = build_and_show_prompt(approved, rejected_with_content)
    post_with, post_without          = test_generation(prompt, test_title, test_snippet)
    verdict(approved, rejected_with_content, post_with, post_without)
