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
        f"You are a professional Viral Content Director & Growth Hacker. Your mission is to create a high-impact 'Curiosity Gap' hook for a video preview overlay.\n"
        f"CHANNEL CONTEXT: {topic}\n"
        f"TONE: {tone}\n"
        f"LANGUAGE: {language}\n"
        f"VIDEO SCRIPT: {script[:1500]}\n"
        f"{hint_instruction}\n"
        f"STRICT REQUIREMENTS:\n"
        f"- LENGTH: 3 to 5 words. Must be punchy and readable in 2 seconds.\n"
        f"- HOOK TYPE: Use psychological triggers (loss aversion, forbidden knowledge, unexpected gain, or social proof).\n"
        f"- IMPACT: Avoid descriptive summaries. Create a question or statement that FORCES the user to keep watching to find the answer.\n"
        f"- POWER WORD: Choose the most emotionally charged word and write it in UPPERCASE.\n"
        f"- CONTEXT: Ensure the hook is directly derived from the core 'twist' or 'climax' of the provided script.\n\n"
        f"EXAMPLES:\n"
        f"- ЭТО СКРЫВАЛИ 100 ЛЕТ (Highlight: СКРЫВАЛИ)\n"
        f"- ГЛАВНАЯ ОШИБКА РАЗРАБОТЧИКА (Highlight: ОШИБКА)\n"
        f"- ПОЧЕМУ ТЫ ВСЕ ЕЩЕ БЕДЕН? (Highlight: ПОЧЕМУ)\n\n"
        f"OUTPUT FORMAT (JSON ONLY):\n"
        f"{{\"preview_text\": \"Ваш текст здесь ПРЯМО сейчас\", \"highlight_word\": \"ПРЯМО\"}}\n"
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
