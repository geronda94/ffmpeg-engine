import logging
from ai.llm_client import achat_json
from core.config_loader import get_channel_profile

logger = logging.getLogger(__name__)


async def generate_preview_text(script: str, language: str = "Russian",
                                 channel_profile: str = None, style_id: str = "narrative",
                                 user_hint: str = ""):
    channel_ctx = get_channel_profile(channel_profile) if channel_profile else {}
    topic = channel_ctx.get("channel_topic", "general")
    tone = channel_ctx.get("tone_of_voice", "engaging")

    hint_instruction = f"\nUSER WISH: {user_hint}\n" if user_hint else ""

    prompt = (
        f"You are a professional Content Director & Graphic Designer specializing in high-impact video previews.\n"
        f"Your mission is to create a deeply meaningful, context-driven, and high-impact title hook for a video preview overlay.\n\n"
        f"CHANNEL CONTEXT: {topic}\n"
        f"TONE: {tone}\n"
        f"LANGUAGE: {language}\n"
        f"VIDEO SCRIPT:\n\"\"\"\n{script[:1800]}\n\"\"\"\n"
        f"{hint_instruction}\n"
        f"CRITICAL REQUIREMENTS:\n"
        f"1. DEEP MEANING & CONTEXT: Avoid generic, cheap clickbait phrases (such as 'ЭТО СКРЫВАЛИ 100 ЛЕТ', 'ВЫ БУДЕТЕ В ШОКЕ', 'СЕКРЕТ КОТОРЫЙ...', etc.). The preview MUST be deeply meaningful and directly summarize the core wisdom, main message, or holy figure discussed in the actual script!\n"
        f"2. SACRED ICON RESPECT RULE (ORTHODOX ONLY):\n"
        f"  - The preview text will be displayed directly over sacred painted icons. Therefore, it is STRICTLY FORBIDDEN to use negative, dark, or sinful words (such as 'бес', 'демон', 'блуд', 'грех', 'дьявол', 'сатана', 'ад', 'страсть', 'смерть', 'искушение') in the preview text or as the highlight word!\n"
        f"  - Instead, ALWAYS focus on the positive, light, and spiritual side of the solution. Transform negative script topics into positive/pure preview titles:\n"
        f"    * 'How to fight fornication (блуд)' -> 'Как сохранить ЧИСТОТУ души' (Highlight: ЧИСТОТУ)\n"
        f"    * 'How to defeat a demon (бес)' -> 'Духовная СИЛА против искушений' (Highlight: СИЛА)\n"
        f"    * 'Sins (грехи) of man' -> 'Путь к СПАСЕНИЮ души' (Highlight: СПАСЕНИЮ)\n"
        f"3. LENGTH: 3 to 7 words. Must be punchy, extremely readable, but grammatically complete and clear.\n"
        f"4. EMOTIONAL / INTELLECTUAL IMPACT: Choose a phrase that evokes respect, reflection, spiritual warmth (for Orthodox channels) or professional interest (for Tech/Business channels).\n"
        f"5. HIGH-VOLTAGE HIGHLIGHT: Choose exactly ONE key word from your generated phrase to be in UPPERCASE. This word must represent the main emotional or logical highlight of the message (e.g. 'ЛЮБИТЕ', 'МУДРОСТЬ', 'ПУТЬ', 'ОШИБКА').\n\n"
        f"EXAMPLES FOR ORTHODOX TOPICS:\n"
        f"- ЛЮБИТЕ друг друга всем сердцем (Highlight: ЛЮБИТЕ)\n"
        f"- Великая МУДРОСТЬ старца Серафима (Highlight: МУДРОСТЬ)\n"
        f"- Как обрести МИР в душе? (Highlight: МИР)\n\n"
        f"EXAMPLES FOR TECH/BUSINESS TOPICS:\n"
        f"- Как Vue.js УСКОРЯЕТ разработку сайтов (Highlight: УСКОРЯЕТ)\n"
        f"- Главная ОШИБКА веб-дизайнера (Highlight: ОШИБКА)\n"
        f"- ПУТЬ от джуна до архитектора (Highlight: ПУТЬ)\n\n"
        f"OUTPUT FORMAT (JSON ONLY):\n"
        f"{{\"preview_text\": \"Ваш осмысленный текст здесь\", \"highlight_word\": \"СЛОВО\"}}\n"
    )

    try:
        result = await achat_json(user_prompt=prompt)
        text = result.get("preview_text", "").strip()
        hl = result.get("highlight_word", "").strip()
        if not text or not hl:
            logger.warning("Preview agent returned empty text")
            return _fallback_preview(script)
        return {"preview_text": text, "highlight_word": hl}
    except Exception as e:
        logger.error(f"Preview Agent Error: {e}")
        return _fallback_preview(script)


def _fallback_preview(script):
    words = script.split()[:4]
    return {
        "preview_text": " ".join(words) if words else "New Video",
        "highlight_word": words[-1] if words else "Video"
    }
