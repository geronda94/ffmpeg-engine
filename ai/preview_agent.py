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
        f"You are a viral teaser copywriter. Generate 2-4 words for a video preview overlay.\n"
        f"CHANNEL TOPIC: {topic}\n"
        f"TONE: {tone}\n"
        f"LANGUAGE: {language}\n"
        f"SCRIPT: {script[:1000]}\n"
        f"{hint_instruction}"
        f"RULES:\n"
        f"- 2 to 4 words MAX. Must fit in ~3 seconds of reading.\n"
        f"- One word should be the emotional/impact keyword (capitalize it).\n"
        f"- Make it intriguing, not descriptive. A hook, not a summary.\n"
        f"- In Russian, use natural phrases, not translit.\n"
        f"- Return ONLY JSON: {{\"preview_text\": \"Вавилон — Новая БАШНЯ\", \"highlight_word\": \"БАШНЯ\"}}\n"
        f"- preview_text must contain the highlight_word exactly as it appears (same case).\n"
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
