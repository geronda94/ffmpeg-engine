import asyncio
import whisper
import logging
import os

logger = logging.getLogger(__name__)

# Загружаем модель один раз при импорте
_model = None

def get_model():
    global _model
    if _model is None:
        logger.info("Loading Whisper model (base)...")
        _model = whisper.load_model("base")
    return _model

async def align_scenes_with_audio(scenes: list, audio_path: str, whisper_segments: list = None, language: str = None, use_llm_align: bool = False):
    """
    Сравнивает текст сцен с аудио через Whisper и проставляет точные тайминги.
    При use_llm_align=True использует LLM для точного выравнивания слов сценария с Whisper-сегментами.
    """
    try:
        if whisper_segments is not None:
            segments = whisper_segments
            total_duration = segments[-1]['end'] if segments else 0.0
            logger.info(f"Using provided Whisper segments for timing ({len(segments)} segments)")
        else:
            model = get_model()
            logger.info(f"Transcribing audio for timing: {audio_path} (lang={language})")
            
            # Включаем пословные тайминги
            transcribe_kwargs = {"verbose": False, "word_timestamps": True}
            if language:
                transcribe_kwargs["language"] = language
                
            result = await asyncio.to_thread(model.transcribe, audio_path, **transcribe_kwargs)
            segments = result.get('segments', [])
            total_duration = segments[-1]['end'] if segments else 0.0
        
        if use_llm_align:
            from ai.llm_aligner import align_words_with_whisper
            logger.info("Using LLM Aligner for precision timing...")
            aligned_data = await align_words_with_whisper(scenes, segments, target_lang=language or "Russian")
            
            if aligned_data and len(aligned_data) >= len(scenes) * 0.8:
                # Мапим данные из LLM обратно в сцены. Приводим ID к строке для надежности.
                aligned_dict = {str(s.get('id', '')): s for s in aligned_data}
                processed_scenes = []
                for i, scene in enumerate(scenes):
                    s_id = str(scene.get('scene_id', ''))
                    words = []
                    
                    if s_id in aligned_dict:
                        words = aligned_dict[s_id].get('words', [])
                    elif len(aligned_data) == len(scenes):
                        # Фолбэк: если ИИ вернул индексы 0,1,2 вместо 1,2,3, мапим по порядку
                        words = aligned_data[i].get('words', [])
                        
                    if words:
                        scene['words'] = words
                        scene['start'] = round(float(words[0]['start']), 3)
                        scene['end'] = round(float(words[-1]['end']), 3)
                    else:
                        # Если слов нет, оставляем старые или примерные
                        scene.setdefault('start', 0.0)
                        scene.setdefault('end', scene['start'] + 3.0)
                    processed_scenes.append(scene)
                
                # Гарантируем отсутствие разрывов и наложений
                for i in range(1, len(processed_scenes)):
                    processed_scenes[i]['start'] = max(processed_scenes[i]['start'], processed_scenes[i-1]['end'])
                
                if processed_scenes:
                    processed_scenes[-1]['end'] = round(total_duration, 3)
                return processed_scenes
            else:
                logger.warning(f"LLM Alignment failed or incomplete ({len(aligned_data) if aligned_data else 0}/{len(scenes)}). Falling back to heuristic alignment.")

        # --- Heuristic Fallback (the current algorithm) ---
        total_chars = sum(len(scene.get('text_segment', '')) for scene in scenes)
        total_whisper_chars = sum(len(seg.get('text', '')) for seg in segments)
        
        if not segments or (total_chars > 0 and total_whisper_chars < total_chars * 0.4):
            # ... (proportional logic omitted for brevity in thought, but I'll keep it in code)
            current_time = 0.0
            processed_scenes = []
            for scene in scenes:
                text_len = len(scene.get('text_segment', ''))
                ratio = text_len / total_chars if total_chars > 0 else 1.0 / len(scenes)
                duration = total_duration * ratio
                scene['start'] = round(current_time, 3)
                scene['end'] = round(current_time + duration, 3)
                current_time += duration
                processed_scenes.append(scene)
            if processed_scenes: processed_scenes[-1]['end'] = round(total_duration, 3)
            return processed_scenes

        whisper_words = []
        for seg in segments:
            if 'words' in seg and seg['words']:
                for w in seg['words']:
                    whisper_words.append({'word': ''.join(filter(str.isalnum, w['word'].lower())), 'start': float(w['start']), 'end': float(w['end'])})
            else:
                seg_words = seg['text'].strip().split()
                if not seg_words: continue
                word_dur = (seg['end'] - seg['start']) / len(seg_words)
                for j, w in enumerate(seg_words):
                    whisper_words.append({'word': ''.join(filter(str.isalnum, w.lower())), 'start': seg['start'] + j * word_dur, 'end': seg['start'] + (j + 1) * word_dur})

        w_cursor = 0
        processed_scenes = []
        for i, scene in enumerate(scenes):
            scene_text = scene.get('text_segment', '').strip()
            scene_words_clean = [w for w in [''.join(filter(str.isalnum, w.lower())) for w in scene_text.split()] if w]

            if not scene_words_clean:
                prev_end = processed_scenes[-1]['end'] if processed_scenes else 0.0
                scene['start'], scene['end'] = round(prev_end, 3), round(prev_end + 1.0, 3)
                processed_scenes.append(scene); continue

            scene_start = 0.0 if i == 0 else round(max(processed_scenes[-1]['end'], whisper_words[w_cursor]['start'] if w_cursor < len(whisper_words) else total_duration), 3)
            words_in_scene = len(scene_words_clean)
            w_end_idx = min(w_cursor + words_in_scene - 1, len(whisper_words) - 1)
            
            if w_end_idx >= 0 and w_end_idx < len(whisper_words):
                scene_end = round(whisper_words[w_end_idx]['end'], 3)
                w_cursor = w_end_idx + 1
            else: scene_end = round(total_duration, 3)

            if scene_end <= scene_start: scene_end = round(scene_start + max(1.0, words_in_scene * 0.3), 3)
            scene['start'], scene['end'] = scene_start, scene_end
            processed_scenes.append(scene)

        if processed_scenes: processed_scenes[-1]['end'] = round(total_duration, 3)
        return processed_scenes

    except Exception as e:
        logger.error(f"Timing Agent Error: {e}", exc_info=True)
        for i, s in enumerate(scenes):
            if 'start' not in s: s['start'], s['end'] = round(i * 3.0, 3), round((i + 1) * 3.0, 3)
        return scenes
