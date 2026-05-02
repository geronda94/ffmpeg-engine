import logging
from ai.llm_client import achat_json
from core.config_loader import get_config

logger = logging.getLogger(__name__)


async def generate_metadata(script, lang="Russian", user_instruction=""):
    """
    Генерирует заголовок, описание и теги для видео на основе сценария и пользовательских предпочтений.
    """
    try:
        context = {
            "channel_topic": "General content",
            "tone_of_voice": "Engaging",
            "avoid_topics": [],
            "target_platform": "YouTube/TikTok/Reels"
        }
        try:
            channel = get_config("channel_context")
            context.update(channel)
        except Exception:
            pass

        style_instruction = f"STYLE INSTRUCTION: {user_instruction}\n" if user_instruction else ""

        lang_critical = (
            f"CRITICAL LANGUAGE RULE: ALL output fields (title, description, hashtags) "
            f"MUST be written in {lang} language. DO NOT output in any other language.\n"
        )
        if lang == "Georgian":
            lang_critical += "Use ONLY Georgian script (ქართული), NEVER Cyrillic or Russian.\n"
        elif lang == "Romanian":
            lang_critical += "Use ONLY Romanian language, NEVER Russian.\n"

        prompt = (
            f"You are a SEO expert for {context['target_platform']}.\n"
            f"CHANNEL CONTEXT: {context['channel_topic']}\n"
            f"TONE OF VOICE: {context['tone_of_voice']}\n"
            f"AVOID: {', '.join(context['avoid_topics'])}\n\n"
            f"{lang_critical}\n"
            f"{style_instruction}"
            f"Based on the script below, generate marketing metadata that is platform-safe and adheres to community guidelines.\n"
            f"SCRIPT: {script}\n"
            f"Language: {lang}\n\n"
            f"Return ONLY a JSON object with these fields:\n"
            f"- 'title': A catchy title in {lang} (max 60 chars).\n"
            f"- 'description': A short engaging description in {lang} (2-3 sentences).\n"
            f"- 'hashtags': 5-7 relevant hashtags as an ARRAY of strings, e.g. ['tag1', 'tag2'].\n"
            f"- 'slug': A URL-friendly version of the title in English.\n"
            f"IMPORTANT: 'hashtags' must be a JSON array, not a single string.\n"
            f"Do not include any other text or markdown blocks."
        )

        result = await achat_json(user_prompt=prompt)
        result = _validate_language(result, lang)
        result = _normalize_hashtags_in_result(result)
        return result

    except Exception as e:
        logger.error(f"Metadata Agent Error: {e}")
        return {
            "title": f"Video about {context.get('channel_topic', 'general')}",
            "description": "Engaging AI generated content.",
            "hashtags": ["ai", "video", "shorts"],
            "slug": "video_result"
        }


def _normalize_hashtags_in_result(result: dict) -> dict:
    hashtags = result.get("hashtags")
    if hashtags is None:
        result["hashtags"] = []
        return result
    if isinstance(hashtags, str):
        result["hashtags"] = [hashtags]
    if isinstance(hashtags, list):
        result["hashtags"] = [str(t).strip().lstrip("#") for t in hashtags if str(t).strip()]
    return result


def _validate_language(result: dict, expected_lang: str) -> dict:
    import re
    title = result.get("title", "")
    if expected_lang == "Georgian":
        if re.search(r"[а-яА-ЯёЁ]", title):
            logger.warning(f"Russian chars detected in Georgian title: {title}")
    elif expected_lang == "Russian":
        if re.search(r"[\u10A0-\u10FF]", title):
            logger.warning(f"Georgian chars detected in Russian title: {title}")
    return result


def normalize_hashtags(hashtags) -> list:
    if isinstance(hashtags, str):
        hashtags = [hashtags]
    if not isinstance(hashtags, list):
        return []
    return [str(t).strip().lstrip("#") for t in hashtags if str(t).strip()]


def format_hashtags(hashtags) -> str:
    tags = normalize_hashtags(hashtags)
    return " ".join(f"#{t}" for t in tags)
