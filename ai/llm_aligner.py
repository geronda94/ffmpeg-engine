import json
import logging
import re
from ai.llm_client import achat_json

logger = logging.getLogger(__name__)


async def align_words_with_whisper(scenes, whisper_segments, target_lang="Russian"):
    if not whisper_segments:
        return None

    scenes_summary = []
    for s in scenes:
        scenes_summary.append({
            "id": s.get("scene_id", len(scenes_summary)),
            "text": s.get("text_segment", "")
        })

    whisper_clean = []
    for seg in whisper_segments:
        whisper_clean.append({
            "start": round(seg.get("start", 0), 2),
            "end": round(seg.get("end", 0), 2),
            "text": seg.get("text", "")
        })

        output_example = (
            '{ "scenes": [ {"id": 0, "words": [ {"word": "...", "start": 0.0, "end": 0.5} ]} ] }'
        )
        prompt = (
            f"You are a precise audio-to-text alignment engineer. "
            f"Match each word from the script scenes to the correct Whisper timestamp segment.\n\n"
            f"LANGUAGE: {target_lang}\n\n"
            f"WHISPER SEGMENTS (with timestamps and raw recognized text):\n"
            f"{json.dumps(whisper_clean, ensure_ascii=False)}\n\n"
            f"SCRIPT SCENES (exact text from the video script):\n"
            f"{json.dumps(scenes_summary, ensure_ascii=False)}\n\n"
            f"RULES:\n"
            f"1. For each scene, assign each WORD its correct start and end time.\n"
            f"2. A word's start must be >= the whisper segment start it belongs to.\n"
            f"3. A word's end must be <= the whisper segment end it belongs to.\n"
            f"4. Distribute each Whisper segment's time evenly among the words it contains.\n"
            f"5. Use ONLY words from the SCRIPT SCENES text_segment, not from Whisper text (which may be inaccurate).\n"
            f"6. Keep word order as it appears in the scene text.\n"
            f"7. If Whisper has gaps or overlaps, distribute proportionally.\n\n"
            f"Return ONLY valid JSON:\n{output_example}\n"
    )

    try:
        result = await achat_json(user_prompt=prompt)
        aligned = result.get("scenes", [])
        logger.info(f"Align complete for {len(aligned)} scenes")
        return aligned
    except Exception as e:
        logger.error(f"LLM aligner error: {e}", exc_info=True)
        return None
