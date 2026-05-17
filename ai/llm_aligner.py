import json
import logging
import asyncio
import random
from ai.llm_client import achat_json

logger = logging.getLogger(__name__)


async def align_chunk(chunk_scenes, whisper_clean, target_lang, chunk_idx):
    scenes_summary = []
    for i, s in enumerate(chunk_scenes):
        scenes_summary.append({
            "id": s.get("scene_id") if s.get("scene_id") is not None else s.get("scene_idx", i),
            "text": s.get("text_segment", "")
        })

    output_example = (
        '{ "scenes": [ {"id": 1, "words": [ {"word": "...", "start": 0.0, "end": 0.5} ]} ] }'
    )
    prompt = (
        f"You are a precise audio-to-text alignment engineer. "
        f"Match each word from the script scenes to the correct Whisper timestamp segment.\n\n"
        f"LANGUAGE: {target_lang}\n\n"
        f"WHISPER SEGMENTS (with timestamps and raw recognized text):\n"
        f"{json.dumps(whisper_clean, ensure_ascii=False)}\n\n"
        f"SCRIPT SCENES CHUNK (exact text from the video script for alignment):\n"
        f"{json.dumps(scenes_summary, ensure_ascii=False)}\n\n"
        f"RULES:\n"
        f"1. For each scene in SCRIPT SCENES CHUNK, assign each WORD its correct start and end time based on Whisper segments.\n"
        f"2. MANDATORY: You MUST return the EXACT words found in the 'text' field of the SCRIPT SCENES CHUNK. DO NOT replace them with words from Whisper. Even if Whisper says 'seventy' but script says '7-10', you MUST return '7-10' and assign it the timestamp of 'seventy'.\n"
        f"3. NO OMISSION: Do not omit any words from the script. Every single word in the script chunk must be present in your output.\n"
        f"4. CLEANING: Remove quotes, commas, and dots at the end of sentences, but DO NOT remove dots inside URLs or domain names.\n"
        f"5. CASE PRESERVATION: KEEP THE CASE EXACTLY as in the script.\n"
        f"6. CONTINUITY: Ensure that word timestamps are continuous and don't have massive gaps unless there is silence in Whisper.\n"
        f"7. IMPORTANT: You MUST preserve the exact 'id' value from the SCRIPT SCENES CHUNK for each matched scene in your output JSON.\n\n"
        f"Return ONLY valid JSON in this format:\n{output_example}\n"
    )

    max_retries = 4
    for attempt in range(max_retries):
        try:
            logger.info(f"Aligning chunk {chunk_idx} ({len(chunk_scenes)} scenes), attempt {attempt + 1}...")
            result = await achat_json(user_prompt=prompt)
            aligned = result.get("scenes", [])
            logger.info(f"Chunk {chunk_idx} alignment complete: got {len(aligned)} scenes")
            return aligned
        except Exception as e:
            logger.warning(f"Attempt {attempt + 1} failed for chunk {chunk_idx} alignment: {e}")
            if attempt < max_retries - 1:
                # Exponential backoff with random jitter
                sleep_time = (2 ** attempt) + random.uniform(1.0, 3.0)
                logger.info(f"Retrying chunk {chunk_idx} in {sleep_time:.2f} seconds...")
                await asyncio.sleep(sleep_time)
            else:
                logger.error(f"Error in LLM alignment chunk {chunk_idx} after {max_retries} attempts: {e}", exc_info=True)
                return []


async def align_words_with_whisper(scenes, whisper_segments, target_lang="Russian"):
    if not whisper_segments:
        return None

    whisper_clean = []
    for seg in whisper_segments:
        whisper_clean.append({
            "start": round(seg.get("start", 0), 2),
            "end": round(seg.get("end", 0), 2),
            "text": seg.get("text", "")
        })

    # Chunk size of 10 to fit strictly into token limits and speed up
    chunk_size = 10
    chunks = [scenes[i:i + chunk_size] for i in range(0, len(scenes), chunk_size)]
    
    logger.info(f"Aligning {len(scenes)} scenes in {len(chunks)} spaced chunks...")
    
    tasks = []
    for idx, chunk in enumerate(chunks):
        if idx > 0:
            # 500ms pacing delay to prevent simultaneous request burst / API 429
            await asyncio.sleep(0.5)
        tasks.append(align_chunk(chunk, whisper_clean, target_lang, idx + 1))
        
    results = await asyncio.gather(*tasks)
    
    # Merge results
    merged_aligned = []
    for chunk_res in results:
        if chunk_res:
            merged_aligned.extend(chunk_res)
            
    logger.info(f"LLM Aligner merged: {len(merged_aligned)} / {len(scenes)} scenes successfully aligned.")
    return merged_aligned if merged_aligned else None
