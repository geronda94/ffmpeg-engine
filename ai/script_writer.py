from ai.llm_client import chat_json
from core.config_loader import get_config

SYSTEM_PROMPT = """
You are a Professional Scriptwriter for Short-form video (Reels/TikTok).
Your task is to write a script for a video based on a topic and language.

### OUTPUT STRUCTURE
JSON with:
1. "title": Catchy title.
2. "script": The full text to be spoken.
3. "target_duration": Estimated duration in seconds (aim for ~60s unless specified).
4. "language_code": ISO code of the language used.

### RULES
- Calculate word count to match duration (~140 words per minute for RU/EN).
- Use natural, engaging tone.
- If topic is 'Mars', write about Mars.
"""


def generate_script(topic: str, language: str = "Russian", duration: int = 60):
    context = {
        "channel_topic": "General",
        "tone_of_voice": "Engaging",
        "target_platform": "Short-form (Reels/TikTok)"
    }
    try:
        channel = get_config("channel_context")
        context.update(channel)
    except Exception:
        pass

    dynamic_system_prompt = (
        f"You are a Professional Scriptwriter for {context['target_platform']}.\n"
        f"CHANNEL THEME: {context['channel_topic']}\n"
        f"TONE: {context['tone_of_voice']}\n\n"
        "### OUTPUT STRUCTURE (JSON ONLY):\n"
        "1. 'title': Catchy viral title.\n"
        "2. 'script': The full text to be spoken. Use HOOK, CONTEXT, SURPRISING FACT, OUTRO structure.\n"
        f"3. 'target_duration': {duration} seconds.\n"
        "4. 'language_code': ISO code.\n\n"
        "### RULES:\n"
        "- NO dry encyclopedic style. Be vivid and emotional.\n"
        "- Aim for high retention. First 3 seconds MUST be a hook.\n"
        f"- Language: {language}."
    )

    return chat_json(
        system_prompt=dynamic_system_prompt,
        user_prompt=f"Topic: {topic}. Target Duration: {duration} seconds."
    )
