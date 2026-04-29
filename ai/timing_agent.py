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

def align_scenes_with_audio(scenes: list, audio_path: str):
    """
    Сравнивает текст сцен с аудио через Whisper и проставляет точные тайминги.
    """
    try:
        model = get_model()
        logger.info(f"Transcribing audio for timing: {audio_path}")
        
        result = model.transcribe(audio_path, verbose=False)
        segments = result.get('segments', [])
        
        total_duration = segments[-1]['end'] if segments else 0.0
        current_time = 0.0
        processed_scenes = []
        
        if not segments:
            # Если аудио пустое, распределяем время равномерно (заглушка)
            avg_dur = 2.0
            for i, scene in enumerate(scenes):
                scene['start'] = round(i * avg_dur, 3)
                scene['end'] = round((i + 1) * avg_dur, 3)
                processed_scenes.append(scene)
            return processed_scenes

        seg_ptr = 0
        for i, scene in enumerate(scenes):
            scene_text = scene.get('text_segment', "").lower().strip()
            clean_scene_text = "".join(filter(str.isalnum, scene_text))
            
            scene_start = segments[seg_ptr]['start'] if seg_ptr < len(segments) else current_time
            
            if not clean_scene_text:
                scene['start'] = round(scene_start, 3)
                scene['end'] = round(scene_start + 1.0, 3)
                processed_scenes.append(scene)
                continue

            accumulated_clean = ""
            while seg_ptr < len(segments):
                seg_text = "".join(filter(str.isalnum, segments[seg_ptr]['text'].lower()))
                accumulated_clean += seg_text
                current_time = segments[seg_ptr]['end']
                seg_ptr += 1
                
                # Поиск вхождения текста (с допуском на ошибки распознавания)
                if len(accumulated_clean) >= len(clean_scene_text) - 2:
                    break
            
            scene['start'] = round(scene_start, 3)
            scene['end'] = round(current_time, 3)
            processed_scenes.append(scene)
            
        if processed_scenes:
            processed_scenes[-1]['end'] = round(total_duration, 3)
            
        return processed_scenes

    except Exception as e:
        logger.error(f"Timing Agent Error: {e}")
        # В случае ошибки гарантируем наличие ключей start/end, чтобы не ломать продакшн
        for i, s in enumerate(scenes):
            if 'start' not in s: s['start'] = round(i * 3.0, 3)
            if 'end' not in s: s['end'] = round((i + 1) * 3.0, 3)
        return scenes
