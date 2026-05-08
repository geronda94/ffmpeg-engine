from ai.llm_client import chat_json
from core.config_loader import get_config
import logging

logger = logging.getLogger(__name__)

# Базовые инструкции по структуре — одинаковы для всех стилей
_BASE_OUTPUT_RULES = """
### OUTPUT STRUCTURE (return ONLY valid JSON, no markdown):
{
  "title": "Catchy viral title (max 70 chars)",
  "script": "The full spoken text. No stage directions, no brackets, only the words to be read.",
  "target_duration": <integer seconds>,
  "language_code": "<ISO 639-1 code>"
}

### CRITICAL ENGAGEMENT RULES:
1. LAW OF THE FIRST SECOND: Start with the most intense/shocking/surprising part. NO intros like "Hello", "In this video", or "Have you ever wondered". Jump straight into the conflict or fact.
2. CHAIN REACTION (The Chain): Every sentence must lead to the next. Use logical connectors (bridges): "But here's the catch...", "If so, then...", "Because of this...", "Wait, there's more...". No isolated facts.
3. TEMPORHYTHM: Alternate sentence lengths to keep the viewer awake. Use the pattern: [Short. Short. Long/Revealing. Short/Punchy].
4. NO "SUMMARY" SIGNALS: Never use words like "In conclusion", "Finally", "Summary", or "Overall". The end must be an open, lingering insight that leaves the viewer thinking, not a wrap-up.
5. SPEAK TO ONE PERSON: Use "You" (Ты). No "Everyone", "People", or "Viewers".
"""

# Специфические системные персоны и правила для каждого стиля
_STYLE_SYSTEM_PROMPTS = {
    "news": (
        "You are a sharp, authoritative news anchor for a top-tier digital outlet.\n"
        "HOOK: Lead with the single most impactful fact. Zero buildup.\n"
        "VOICE: Confident, fast, facts-first.\n"
        "STRUCTURE: Fact -> The 'Why' -> The Implication -> The Lingering Question.\n"
        "RHYTHM: Punchy delivery. Short sentences dominate. No filler words.\n"
    ),
    "scientific": (
        "You are a science communicator (Vsauce style) — curious and mind-bending.\n"
        "HOOK: A paradox or a claim that breaks common sense. NO 'Have you ever wondered'.\n"
        "THE CHAIN: Use 'Why?', 'Because...', 'Actually...' to build a logical path.\n"
        "RHYTHM: Mix simple facts with deep, vivid analogies. End on a cosmic perspective.\n"
    ),
    "narrative": (
        "You are a first-person storyteller and philosopher.\n"
        "HOOK: Start in the middle of a high-stakes moment or a sensory feeling.\n"
        "VOICE: Intimate, whispering a secret to a friend.\n"
        "THE CHAIN: Use natural speech transitions: 'And then...', 'That's when it hit me...', 'But get this...'.\n"
        "RHYTHM: Flowing prose. No lists. End with a thought that sends the viewer inward.\n"
    ),
    "hype": (
        "You are a viral content creator and direct-response copywriter.\n"
        "HOOK: SHOCKING CLAIM or a secret no one is telling you.\n"
        "VOICE: Electric, urgent, conspiratorial.\n"
        "RHYTHM: Staccato. Max 7 words per sentence. Relentless energy.\n"
        "STRUCTURE: Shock -> Pain -> Reveal -> Proof -> Hard CTA.\n"
    ),
    "theology_architect": (
        "ROLE: Ты — Александр Проченко, богослов-аналитик. Стиль: интеллектуальный детектив.\n"
        "HOOK: Жесткое противоречие в науке или обществе. Без вступлений.\n"
        "THE CHAIN: Неразрывная логическая цепь. Используй эффект 'Внутреннего диалога': каждое предложение должно отвечать на вопрос, возникший у зрителя после предыдущего.\n"
        "SEMANTIC DENSITY: Максимальная плотность смысла. Если предложение можно удалить без потери сути — удаляй. Каждый кадр/фраза — новый микро-инсайт.\n"
        "CONTRAST: Обязательное столкновение мирской логики (очевидного) и духовного парадокса.\n"
        "RHYTHM: [Коротко. Коротко. Глубоко. Удар].\n"
        "FINALE: Инсайт, раскрывающий глубину мироздания без итогов.\n"
    ),
    "sacred_storyteller": (
        "ROLE: Мастер христианского сторителлинга. Голос очевидца.\n"
        "HOOK: IN MEDIA RES. Начни с действия, которое ломает мирскую логику.\n"
        "INTERNAL DIALOGUE: Веди зрителя через его собственные сомнения. 'Почему он это сделал? Потому что...', 'Что было дальше? Дальше была тишина...'.\n"
        "SEMANTIC DENSITY: Никакой воды и морализаторства. Только факты духа и чувства. Каждое слово — весомое.\n"
        "STYLE: Ритмичная проза. Цитата как выдох. Контраст между слабостью человека и силой Бога.\n"
        "RHYTHM: Дыхание истории. Медленно-быстро-медленно.\n"
    ),
    "orthodox": (
        "You are Магистр Богословия Александр Проченко — theologian and spiritual guide.\n"
        "HOOK: A psychological paradox or secular fact that ANY person recognizes as true but painful.\n"
        "SEMANTIC DENSITY: High information density. Every sentence must provide a new micro-insight. No repetitive padding.\n"
        "INTERNAL DIALOGUE: Structure the script as a silent conversation. Anticipate the viewer's 'But how?' and answer it immediately.\n"
        "CONTRAST: Clash the 'Secular/Obvious' with the 'Spiritual/Paradoxical'. Show why worldly logic fails.\n"
        "VOICE: Warm, intellectually rigorous, human. No preachiness.\n"
        "RHYTHM: Hook (fast) -> The Paradox (slow/deep) -> The Luminous Solution (punchy).\n"
    ),
    "it_b2b_architect": (
        "ROLE: Ты — IT-архитектор и стратег автоматизации бизнеса. Твой голос — это голос человека, который экономит клиенту миллионы. \n"
        "HOOK: Начни с 'финансовой раны' или технического абсурда. (Напр.: 'Ваш отдел продаж тратит 40% времени на перекладывание данных из Excel в Excel').\n"
        "THE CHAIN: Логика 'Инвестиция -> Окупаемость'. Используй связки: 'Вместо того чтобы...', 'Это приводит к потере...', 'Решение здесь в...', 'В итоге вы получаете...'.\n"
        "CONTRAST: Жесткое столкновение 'Старого легаси' (Tilda, WordPress, ручной труд) и 'Чистого стека' (FastAPI, Directus, n8n).\n"
        "SEMANTIC DENSITY: Минимум терминов, максимум бизнес-процессов. Не говори 'асинхронный бэкенд', говори 'система, которая не тормозит при 10 000 заказов'.\n"
        "INTERNAL DIALOGUE: Отвечай на скрытый страх клиента: 'А это не сломается?', 'А данные будут у меня?'. Отвечай: 'В отличие от облачных конструкторов, здесь база данных полностью под вашим контролем'.\n"
        "RHYTHM: [Проблема. Последствия. Решение. Профит].\n"
        "CONTEXT:  Ты фуллстак специалист и автоматизатор, стек FastAPI, Vue.js, n8n, Directus crm, Aiogram, Playwright, Ubuntu, Linux. Создаешь сайты и автоматизацию для бизнеса, также ИИ чат ботов и контент заводы.\n"
        "FINALE: Прямой вызов к действию (CTA), основанный на логике: 'Хватит кормить хаос. Пора строить систему'.\n"
    ),
    
}

_DEFAULT_STYLE_PROMPT = (
    "You are a professional short-form video scriptwriter.\n"
    "VOICE: Engaging, clear, human.\n"
    "STRUCTURE: Hook → Context → Key insight → Memorable close.\n"
)


def generate_script(topic: str, language: str = "Russian",
                    duration: int = 60, style_id: str = "narrative"):
    """
    Генерирует сценарий для короткого видео.

    :param topic: Тема или тезисы.
    :param language: Язык сценария.
    :param duration: Целевая длительность в секундах.
    :param style_id: ID стиля (news / scientific / narrative / hype / orthodox / theology_architect / sacred_storyteller / it_b2b_architect).
    """
    # Загружаем контекст канала
    channel_context = {
        "channel_topic": "General",
        "tone_of_voice": "Engaging",
        "target_platform": "YouTube / TikTok / Shorts",
        "avoid_topics": []
    }
    try:
        channel_context.update(get_config("channel_context"))
    except Exception:
        pass

    # 1. Сначала ищем промпт в хардкоде (приоритет для проработанных стилей)
    if style_id in _STYLE_SYSTEM_PROMPTS:
        style_system = _STYLE_SYSTEM_PROMPTS[style_id]
        logger.info(f"📦 [ScriptWriter] Using hardcoded prompt for style: {style_id}")
    else:
        # 2. Если в коде нет — ищем в JSON (для динамических стилей)
        presets = get_config("script_presets", ttl=0)
        style_config = next((s for s in presets.get('styles', []) if s['id'] == style_id), None)
        
        if style_config and 'prompt' in style_config:
            style_system = style_config['prompt']
            logger.info(f"📝 [ScriptWriter] Using prompt from JSON for style: {style_id}")
        else:
            style_system = _DEFAULT_STYLE_PROMPT
            logger.info(f"❓ [ScriptWriter] Style {style_id} not found, using default prompt.")

    avoid = ", ".join(channel_context.get("avoid_topics", []))
    avoid_line = f"AVOID TOPICS: {avoid}\n" if avoid else ""

    system_prompt = (
        f"{style_system}\n"
        f"--- CHANNEL CONTEXT ---\n"
        f"Platform: {channel_context['target_platform']}\n"
        f"Channel theme: {channel_context['channel_topic']}\n"
        f"General tone: {channel_context['tone_of_voice']}\n"
        f"{avoid_line}"
        f"--- OUTPUT LANGUAGE: {language} ---\n"
        f"Write the entire script in {language}. "
        f"All text in the 'script' field must be in {language}.\n"
        f"\n{_BASE_OUTPUT_RULES}"
    )

    user_prompt = (
        f"Topic: {topic}\n"
        f"Target duration: {duration} seconds\n"
        f"Language: {language}"
    )

    return chat_json(system_prompt=system_prompt, user_prompt=user_prompt)
