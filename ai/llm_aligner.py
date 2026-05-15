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
            f"1. For each scene, assign each WORD its correct start and end time based on Whisper segments.\n"
            f"2. MANDATORY: You MUST return the EXACT words found in the 'text' field of the SCRIPT SCENES. DO NOT replace them with words from Whisper. Even if Whisper says 'seventy' but script says '7-10', you MUST return '7-10' and assign it the timestamp of 'seventy'.\n"
            f"3. NO OMISSION: Do not omit any words from the script. Every single word in the script must be present in your output.\n"
            f"4. CLEANING: Remove quotes, commas, dots, and other punctuation from the 'word' field in your JSON output.\n"
            f"5. CASE PRESERVATION: KEEP THE CASE EXACTLY as in the script (names, ALL CAPS emphasis).\n"
            f"6. CONTINUITY: Ensure that word timestamps are continuous and don't have massive gaps unless there is silence in Whisper.\n\n"
            f"Return ONLY valid JSON in this format:\n{output_example}\n"
    )

    try:
        result = await achat_json(user_prompt=prompt)
        aligned = result.get("scenes", [])
        logger.info(f"Align complete for {len(aligned)} scenes")
        return aligned
    except Exception as e:
        logger.error(f"LLM aligner error: {e}", exc_info=True)
        return None
