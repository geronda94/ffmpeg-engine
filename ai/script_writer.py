from ai.llm_client import chat_json
from core.config_loader import get_config
import logging

logger = logging.getLogger(__name__)

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

_DEFAULT_STYLE_PROMPT = (
    "You are a professional short-form video scriptwriter.\n"
    "VOICE: Engaging, clear, human.\n"
    "STRUCTURE: Hook → Context → Key insight → Memorable close.\n"
)


def _get_style_prompt(style_id: str) -> str:
    presets = get_config("script_presets", ttl=0)
    style_config = next((s for s in presets.get('styles', []) if s['id'] == style_id), None)

    if style_config and 'system_prompt' in style_config:
        logger.info(f"📝 [ScriptWriter] Using prompt from JSON for style: {style_id}")
        return style_config['system_prompt']

    logger.info(f"❓ [ScriptWriter] Style {style_id} not found, using default prompt.")
    return _DEFAULT_STYLE_PROMPT


def generate_script(topic: str, language: str = "Russian",
                    duration: int = 60, style_id: str = "narrative",
                    channel_ctx: dict = None):
    if channel_ctx:
        channel_context = channel_ctx
    else:
        from core.config_loader import get_channel_profile
        channel_context = get_channel_profile()

    style_system = _get_style_prompt(style_id)

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
