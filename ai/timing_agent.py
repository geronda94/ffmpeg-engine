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
            
            if aligned_data:
                # Умный маппинг с защитой от сдвига индексов и смены 0-based/1-based логики
                processed_scenes = []
                for i, scene in enumerate(scenes):
                    s_id = scene.get('scene_id')
                    words = []
                    
                    # 1. Сначала ищем по точному совпадению id в aligned_data с scene_id
                    matched = None
                    if s_id is not None:
                        for el in aligned_data:
                            if str(el.get('id', '')) == str(s_id):
                                matched = el
                                break
                    
                    # 2. Если не нашли, ищем по совпадению с 1-based или 0-based индексом
                    if not matched:
                        expected_ids = []
                        if s_id is not None:
                            expected_ids.append(str(s_id))
                            expected_ids.append(str(i + 1))
                        else:
                            expected_ids.append(str(i))
                            
                        for el in aligned_data:
                            if str(el.get('id', '')) in expected_ids:
                                matched = el
                                break
                                
                    # 3. Фолбэк: если длина совпадает, берем строго по порядку в массиве
                    if not matched and len(aligned_data) == len(scenes):
                        matched = aligned_data[i]
                        
                    if matched:
                        words = matched.get('words', [])

                    if words:
                        # Clean words list to guarantee 'start' and 'end' keys exist for every word and are valid floats
                        cleaned_words = []
                        last_start = scene.get('start', 0.0) if scene.get('start') is not None else 0.0
                        last_end = last_start + 1.0

                        for w in words:
                            if not isinstance(w, dict):
                                continue
                            word_text = w.get('word', '')
                            
                            # Safe float parsing with fallbacks
                            try:
                                w_start = float(w['start']) if 'start' in w else last_end
                            except (ValueError, TypeError, KeyError):
                                w_start = last_end
                                
                            try:
                                w_end = float(w['end']) if 'end' in w else w_start + 0.3
                            except (ValueError, TypeError, KeyError):
                                w_end = w_start + 0.3
                                
                            w_start = round(w_start, 3)
                            w_end = round(w_end, 3)
                            
                            cleaned_words.append({
                                'word': word_text,
                                'start': w_start,
                                'end': w_end
                            })
                            last_start = w_start
                            last_end = w_end

                        if cleaned_words:
                            scene['words'] = cleaned_words
                            scene['start'] = cleaned_words[0]['start']
                            scene['end'] = cleaned_words[-1]['end']
                            scene['has_llm_timing'] = True
                        else:
                            scene['words'] = None
                            scene['has_llm_timing'] = False
                    else:
                        scene['words'] = None
                        scene['has_llm_timing'] = False
                    processed_scenes.append(scene)
                
                # --- ЗАПОЛНЕНИЕ ПРОПУСКОВ (GAP FILLING) ДЛЯ СЦЕН БЕЗ LLM-ВЫРАВНИВАНИЯ ---
                n_scenes = len(processed_scenes)
                idx = 0
                while idx < n_scenes:
                    if not processed_scenes[idx].get('has_llm_timing', False):
                        # Нашли начало блока пропущенных сцен
                        start_gap = idx
                        while idx < n_scenes and not processed_scenes[idx].get('has_llm_timing', False):
                            idx += 1
                        end_gap = idx - 1 # индекс последней пропущенной сцены
                        
                        # Определяем левую границу времени T_start
                        T_start = 0.0
                        if start_gap > 0:
                            T_start = processed_scenes[start_gap - 1]['end']
                            
                        # Определяем правую границу времени T_end
                        T_end = total_duration
                        if end_gap + 1 < n_scenes:
                            T_end = processed_scenes[end_gap + 1]['start']
                            
                        # Если T_end почему-то меньше или равно T_start, гарантируем минимальный интервал
                        if T_end <= T_start:
                            T_end = T_start + (end_gap - start_gap + 1) * 3.0
                            
                        gap_duration = T_end - T_start
                        gap_scenes = processed_scenes[start_gap:end_gap + 1]
                        
                        # Считаем сумму символов
                        gap_chars = sum(len(s.get('text_segment', '')) for s in gap_scenes)
                        if gap_chars == 0:
                            gap_chars = len(gap_scenes)
                            
                        current_t = T_start
                        for gs in gap_scenes:
                            text_len = len(gs.get('text_segment', ''))
                            if text_len == 0:
                                text_len = 1
                            ratio = text_len / gap_chars
                            sc_dur = gap_duration * ratio
                            
                            sc_start = round(current_t, 3)
                            sc_end = round(current_t + sc_dur, 3)
                            
                            # Генерируем пословные тайминги
                            gs_text = gs.get('text_segment', '').strip()
                            raw_words = gs_text.split()
                            if not raw_words:
                                raw_words = ["..."]
                                
                            w_dur = (sc_end - sc_start) / len(raw_words)
                            gs_words = []
                            for w_i, r_w in enumerate(raw_words):
                                gs_words.append({
                                    'word': r_w,
                                    'start': round(sc_start + w_i * w_dur, 3),
                                    'end': round(sc_start + (w_i + 1) * w_dur, 3)
                                })
                                
                            gs['start'] = sc_start
                            gs['end'] = sc_end
                            gs['words'] = gs_words
                            gs['has_llm_timing'] = True # теперь у неё есть сгенерированные тайминги
                            
                            current_t += sc_dur
                    else:
                        idx += 1

                # Гарантируем отсутствие разрывов, наложений и инверсии времени
                for i in range(1, len(processed_scenes)):
                    # Стыкуем начало текущей сцены с концом предыдущей
                    processed_scenes[i]['start'] = round(max(processed_scenes[i]['start'], processed_scenes[i-1]['end']), 3)
                    
                    # Защита от нулевой или отрицательной длительности: гарантируем минимум duration
                    min_dur = max(1.0, len(processed_scenes[i].get('text_segment', '').split()) * 0.3)
                    if processed_scenes[i]['end'] <= processed_scenes[i]['start'] + 0.1:
                        processed_scenes[i]['end'] = round(processed_scenes[i]['start'] + min_dur, 3)
                
                if processed_scenes:
                    # Корректируем конец последней сцены под общую длительность аудио
                    last_scene = processed_scenes[-1]
                    last_scene['end'] = round(max(total_duration, last_scene['start'] + 1.0), 3)

                # Пропорционально корректируем тайминги пословных слов, чтобы они укладывались в новые границы сцен
                def adjust_scene_word_timings(sc):
                    wds = sc.get('words', [])
                    if not wds:
                        return
                    s_start = sc['start']
                    s_end = sc['end']
                    
                    w_starts = [float(w['start']) for w in wds if 'start' in w]
                    w_ends = [float(w['end']) for w in wds if 'end' in w]
                    
                    orig_start = min(w_starts) if w_starts else s_start
                    orig_end = max(w_ends) if w_ends else s_end
                    orig_dur = orig_end - orig_start
                    new_dur = s_end - s_start
                    
                    if orig_dur <= 0 or new_dur <= 0:
                        step = new_dur / len(wds)
                        for idx, wd in enumerate(wds):
                            wd['start'] = round(s_start + idx * step, 3)
                            wd['end'] = round(s_start + (idx + 1) * step, 3)
                    else:
                        for wd in wds:
                            rel_start = (float(wd['start']) - orig_start) / orig_dur
                            rel_end = (float(wd['end']) - orig_start) / orig_dur
                            wd['start'] = round(s_start + rel_start * new_dur, 3)
                            wd['end'] = round(s_start + rel_end * new_dur, 3)

                for sc in processed_scenes:
                    adjust_scene_word_timings(sc)
                    
                return processed_scenes
            else:
                logger.warning("LLM Alignment failed completely. Falling back to heuristic alignment.")

        # --- Heuristic Fallback (the current algorithm) ---
        total_chars = sum(len(scene.get('text_segment', '')) for scene in scenes)
        total_whisper_chars = sum(len(seg.get('text', '')) for seg in segments)
        
        if not segments or (total_chars > 0 and total_whisper_chars < total_chars * 0.4):
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
            
            for scene in processed_scenes:
                if not scene.get('words'):
                    s_text = scene.get('text_segment', '').strip()
                    raw_words = s_text.split()
                    if not raw_words:
                        raw_words = ["..."]
                    sc_start = scene['start']
                    sc_end = scene['end']
                    w_dur = (sc_end - sc_start) / len(raw_words)
                    scene['words'] = [
                        {
                            'word': r_w,
                            'start': round(sc_start + w_i * w_dur, 3),
                            'end': round(sc_start + (w_i + 1) * w_dur, 3)
                        }
                        for w_i, r_w in enumerate(raw_words)
                    ]
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
        
        for scene in processed_scenes:
            if not scene.get('words'):
                s_text = scene.get('text_segment', '').strip()
                raw_words = s_text.split()
                if not raw_words:
                    raw_words = ["..."]
                sc_start = scene['start']
                sc_end = scene['end']
                w_dur = (sc_end - sc_start) / len(raw_words)
                scene['words'] = [
                    {
                        'word': r_w,
                        'start': round(sc_start + w_i * w_dur, 3),
                        'end': round(sc_start + (w_i + 1) * w_dur, 3)
                    }
                    for w_i, r_w in enumerate(raw_words)
                ]
        return processed_scenes

    except Exception as e:
        logger.error(f"Timing Agent Error: {e}", exc_info=True)
        for i, s in enumerate(scenes):
        return scenes
