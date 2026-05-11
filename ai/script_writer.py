from ai.llm_client import chat_json
from core.config_loader import get_config
import logging

logger = logging.getLogger(__name__)

_BASE_OUTPUT_RULES = """
### OUTPUT STRUCTURE (return ONLY valid JSON, no markdown):
{
  "title": "Catchy viral title using one of the Hooks (max 70 chars)",
  "script": "The full spoken text. No stage directions, no brackets, only the words to be read.",
  "target_duration": <integer seconds>,
  "language_code": "<ISO 639-1 code>"
}

### АРХИТЕКТУРА УДЕРЖАНИЯ (Retention 61+ сек)
[ПРИНЦИПЫ ЧИСТОГО СМЫСЛА]
1. НИКАКИХ ОБЕЩАНИЙ: Убираем фразы "я расскажу", "досмотри", "ты удивишься", "привет", "сегодня обсудим". Даем только факты.
2. НЕЯВНАЯ ПЕТЛЯ: Создаем ситуацию, требующую объяснения, и идем дальше по сюжету.
3. СМЕРТЬ ПРИЛАГАТЕЛЬНЫМ: Заменяем оценочные прилагательные ("красивый", "чудесный") на активные глаголы (ударил, шептал, замер). Описываем действия и физику.

[МАСТЕР-СТРУКТУРА (Строго 61-65 сек)]
1. Прямой вход (0-7 сек): Озвучивание проблемы или парадокса без вступления.
2. Градиент фактов (7-45 сек): Динамичное развитие. Короткие, рубленые фразы. Каждое предложение — новый этап. Без фраз-связок ("внимательно слушайте").
3. Закон/Развязка (45-55 сек): Главная мысль, закон (духовный/бизнес) как формула. Без морализаторства.
4. Loop (Петля) (55-65 сек): Мягкий CTA. Финальный вывод должен "сшиваться" с первой фразой видео, создавая бесконечный цикл (где это уместно).

[ЭНЦИКЛОПЕДИЯ КРЮЧКОВ (Для первых 3-5 сек)]
Используй один из триггеров:
- Разрыв шаблона: Показ привычного под шокирующим углом ("Почему на иконе...").
- Отрицательный крючок (Страх потери): Бьет в страх ошибки ("Никогда не делайте [X], пока...").
- In Media Res: Начало с кульминации без вступления ("И в этот момент медведь...").
- Секретное знание: Иллюзия эксклюзивной информации ("Об этом молчат в 99%...").
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
                    channel_ctx: dict = None, feedback: str = ""):
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
    if feedback:
        user_prompt += (
            f"\n\n--- CRITICAL REVISION NOTES ---\n"
            f"The previous script was rejected by quality review. "
            f"Here is what MUST be fixed:\n{feedback}\n"
            f"Rewrite the script fixing ALL these issues while keeping the original topic.\n"
            f"DO NOT repeat the same mistakes. Check against the rules above."
        )

    return chat_json(system_prompt=system_prompt, user_prompt=user_prompt)
