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
        
        total_chars = sum(len(scene.get('text_segment', '')) for scene in scenes)
        whisper_words = []
        for seg in segments:
            if 'words' in seg and seg['words']:
                for w in seg['words']:
                    w_text = w.get('word', '').strip()
                    w_clean = ''.join(filter(str.isalnum, w_text.lower()))
                    if w_clean:
                        whisper_words.append({
                            'raw': w_text,
                            'clean': w_clean,
                            'start': float(w['start']),
                            'end': float(w['end'])
                        })
            else:
                seg_words = seg['text'].strip().split()
                if not seg_words: continue
                word_dur = (seg['end'] - seg['start']) / len(seg_words)
                for j, w in enumerate(seg_words):
                    w_clean = ''.join(filter(str.isalnum, w.lower()))
                    if w_clean:
                        whisper_words.append({
                            'raw': w,
                            'clean': w_clean,
                            'start': round(seg['start'] + j * word_dur, 3),
                            'end': round(seg['start'] + (j + 1) * word_dur, 3)
                        })

        if not whisper_words or (total_chars > 0 and len(whisper_words) < len(scenes) * 0.4):
            logger.warning("Whisper words insufficient. Falling back to proportional heuristic timing.")
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
                    scene['has_llm_timing'] = False
            return processed_scenes

        logger.info(f"Using Needleman-Wunsch DP Sequence Alignment engine for flawless word-level timing ({len(whisper_words)} audio words)...")

        total_scene_words = []
        for s_i, scene in enumerate(scenes):
            s_text = scene.get('text_segment', '').strip()
            s_words = s_text.split()
            if not s_words:
                s_words = ["..."]
            for w in s_words:
                w_clean = ''.join(filter(str.isalnum, w.lower()))
                if not w_clean:
                    w_clean = w.lower() # Fallback for punctuation-only words like "—"
                total_scene_words.append({
                    'scene_idx': s_i,
                    'raw': w,
                    'clean': w_clean
                })

        n = len(total_scene_words)
        m = len(whisper_words)

        dp = [[0.0] * (m + 1) for _ in range(n + 1)]
        parent = [[None] * (m + 1) for _ in range(n + 1)]

        for i in range(n + 1):
            dp[i][0] = i * 2.0
        for j in range(m + 1):
            dp[0][j] = j * 2.0

        # ── CRITICAL FIX: Initialize boundary parents so traceback never hits None ──
        # Without this, when the path reaches the grid edge, parent[i][0] or parent[0][j]
        # is None, causing "cannot unpack non-iterable NoneType" crash → subtitles desync
        for i in range(1, n + 1):
            parent[i][0] = (i - 1, 0)
        for j in range(1, m + 1):
            parent[0][j] = (0, j - 1)

        for i in range(1, n + 1):
            sw_clean = total_scene_words[i - 1]['clean']
            for j in range(1, m + 1):
                ww_clean = whisper_words[j - 1]['clean']
                
                if sw_clean == ww_clean:
                    cost = -3.0
                elif sw_clean in ww_clean or ww_clean in sw_clean:
                    cost = -1.0
                else:
                    cost = 2.0
                    
                match_cost = dp[i - 1][j - 1] + cost
                del_cost = dp[i - 1][j] + 2.0
                ins_cost = dp[i][j - 1] + 2.0
                
                best = min(match_cost, del_cost, ins_cost)
                dp[i][j] = best
                
                if best == match_cost:
                    parent[i][j] = (i - 1, j - 1)
                elif best == ins_cost:
                    parent[i][j] = (i, j - 1)
                else:
                    parent[i][j] = (i - 1, j)

        curr_i, curr_j = n, m
        alignment = []
        while curr_i > 0 or curr_j > 0:
            p = parent[curr_i][curr_j]
            if p == (curr_i - 1, curr_j - 1):
                alignment.append((curr_i - 1, curr_j - 1))
                curr_i, curr_j = p
            elif p == (curr_i, curr_j - 1):
                curr_i, curr_j = p
            else:
                alignment.append((curr_i - 1, None))
                curr_i, curr_j = p

        alignment.reverse()

        mapped_scene_words = [[] for _ in range(len(scenes))]
        last_valid_end = 0.0
        for s_w_idx, w_w_idx in alignment:
            sw = total_scene_words[s_w_idx]
            s_i = sw['scene_idx']
            if w_w_idx is not None:
                ww = whisper_words[w_w_idx]
                w_start = round(float(ww['start']), 3)
                w_end = round(float(ww['end']), 3)
                last_valid_end = w_end
            else:
                w_start = round(last_valid_end, 3)
                w_end = round(last_valid_end + 0.3, 3)
                last_valid_end = w_end
            
            if w_end < w_start:
                w_end = round(w_start + 0.3, 3)
                
            mapped_scene_words[s_i].append({
                'word': sw['raw'],
                'start': w_start,
                'end': w_end
            })

        def adjust_scene_word_timings(sc):
            wds = sc.get('words', [])
            if not wds: return
            s_start, s_end = sc['start'], sc['end']
            orig_start = wds[0]['start']
            orig_end = wds[-1]['end']
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

        processed_scenes = []
        for s_i, scene in enumerate(scenes):
            m_words = mapped_scene_words[s_i]
            if m_words:
                curr_t = m_words[0]['start']
                for w in m_words:
                    w['start'] = round(max(curr_t, w['start']), 3)
                    w['end'] = round(max(w['start'] + 0.1, w['end']), 3)
                    curr_t = w['end']
                    
                scene['words'] = m_words
                scene['start'] = round(m_words[0]['start'], 3)
                scene['end'] = round(m_words[-1]['end'], 3)
                scene['has_llm_timing'] = True
            else:
                prev_end = processed_scenes[-1]['end'] if processed_scenes else 0.0
                scene['words'] = [{'word': '...', 'start': round(prev_end, 3), 'end': round(prev_end + 1.0, 3)}]
                scene['start'] = round(prev_end, 3)
                scene['end'] = round(prev_end + 1.0, 3)
                scene['has_llm_timing'] = True
            processed_scenes.append(scene)

        for i in range(1, len(processed_scenes)):
            processed_scenes[i]['start'] = round(max(processed_scenes[i]['start'], processed_scenes[i-1]['end']), 3)
            if processed_scenes[i]['end'] < processed_scenes[i]['start'] + 0.1:
                min_dur = max(1.0, len(processed_scenes[i]['words']) * 0.3)
                processed_scenes[i]['end'] = round(processed_scenes[i]['start'] + min_dur, 3)
            adjust_scene_word_timings(processed_scenes[i])

        if processed_scenes:
            processed_scenes[0]['start'] = round(max(0.0, processed_scenes[0]['start']), 3)
            adjust_scene_word_timings(processed_scenes[0])
            processed_scenes[-1]['end'] = round(max(total_duration, processed_scenes[-1]['start'] + 1.0), 3)
            adjust_scene_word_timings(processed_scenes[-1])

        logger.info(f"DP Alignment successfully mapped {len(processed_scenes)} scenes. Audio duration: {total_duration:.2f}s")
        return processed_scenes

    except Exception as e:
        logger.error(f"Timing Agent Error: {e}", exc_info=True)
        for i, s in enumerate(scenes):
            if 'start' not in s: 
                s['start'] = round(i * 3.0, 3)
                s['end'] = round((i + 1) * 3.0, 3)
            if not s.get('words'):
                s_text = s.get('text_segment', '').strip()
                raw_words = s_text.split()
                if not raw_words:
                    raw_words = ["..."]
                sc_start = s['start']
                sc_end = s['end']
                w_dur = (sc_end - sc_start) / len(raw_words)
                s['words'] = [
                    {
                        'word': r_w,
                        'start': round(sc_start + w_i * w_dur, 3),
                        'end': round(sc_start + (w_i + 1) * w_dur, 3)
                    }
                    for w_i, r_w in enumerate(raw_words)
                ]
        return scenes
