import json
import logging
from ai.llm_client import achat_json

logger = logging.getLogger(__name__)


async def translate_project_content(script: str, scenes: list, metadata: dict, target_lang: str):
    """
    Переводит сценарий, сегменты сцен и SEO-метаданные на целевой язык.
    """
    try:
        scenes_data = [{"id": i, "text": s["text_segment"]} for i, s in enumerate(scenes)]
        meta_data = {
            "title": metadata.get("title", ""),
            "description": metadata.get("description", ""),
            "hashtags": metadata.get("hashtags", [])
        }

        lang_critical = (
            f"CRITICAL: ALL output MUST be in {target_lang} language. "
        )
        if target_lang == "Georgian":
            lang_critical += "Use ONLY Georgian script (ქართული), NEVER Russian or Cyrillic. "

        prompt = (
            f"You are a professional marketing localizer and copywriter specializing in short-form viral video content.\n"
            f"Task: Localize (not just literally translate) the following script, scene segments, and SEO metadata into {target_lang}.\n"
            f"{lang_critical}\n"
            f"Requirements:\n"
            f"1. CULTURAL ADAPTATION: Adapt idioms, psychological triggers, and emotional impact to sound native, persuasive, and natural to a {target_lang} speaker.\n"
            f"2. HOOKS & ENGAGEMENT: Maximize the impact of the opening hook. Ensure that tension and engagement are fully preserved in {target_lang}.\n"
            f"3. CALL TO ACTION (CTA): Localize the CTA so it is compelling and drives action, using the strongest marketing verbs native to {target_lang}.\n"
            f"4. Keep the segments short enough for a video scene and preserve the exact same structure.\n"
            f"5. Localize hashtags to reflect actual popular search terms in the {target_lang} segment.\n"
            f"6. 'hashtags' MUST be an ARRAY of strings, e.g. ['tag1', 'tag2'].\n\n"
            f"ORIGINAL SCRIPT: {script}\n"
            f"SCENE SEGMENTS: {json.dumps(scenes_data, ensure_ascii=False)}\n"
            f"METADATA: {json.dumps(meta_data, ensure_ascii=False)}\n\n"
            f"Return ONLY a JSON object with these fields:\n"
            f"- 'translated_script': The full script.\n"
            f"- 'translated_scenes': A list of objects with 'id' and 'text'.\n"
            f"- 'translated_metadata': Object with 'title', 'description', 'hashtags' (array of strings).\n"
            f"Do not include any other text or markdown blocks."
        )

        result = await achat_json(user_prompt=prompt)

        new_scenes = [s.copy() for s in scenes]
        for item in result.get("translated_scenes", []):
            idx = item.get("id")
            if idx is not None and idx < len(new_scenes):
                new_text = item.get("text", "")
                new_scenes[idx]["text_segment"] = new_text
                # FIX #4: Пересчитываем estimated_duration по длине нового текста
                new_scenes[idx]["estimated_duration"] = max(2.5, round(len(new_text) / 13.0 + 0.5, 1))

        # FIX #3: Безусловно очищаем тайминги у ВСЕХ сцен (защита от пропущенных LLM-ом сцен).
        # Это критично: если хотя бы одна сцена сохранит start/end от родителя,
        # pipeline_manager пропустит Whisper и использует чужие тайминги.
        for s in new_scenes:
            s.pop('start', None)
            s.pop('end', None)
            s.pop('effects', None)
            s.pop('transition', None)
            s.pop('words', None)
            s.pop('subtitle_style', None) # Сбрасываем стиль, если он был привязан к старой сцене

        return {
            "script": result.get("translated_script"),
            "scenes": new_scenes,
            "metadata": result.get("translated_metadata")
        }

    except Exception as e:
        logger.error(f"Localization Agent Error: {e}")
        return None
