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

def align_scenes_with_audio(scenes: list, audio_path: str, whisper_segments: list = None, language: str = None):
    """
    Сравнивает текст сцен с аудио через Whisper и проставляет точные тайминги.
    """
    try:
        if whisper_segments is not None:
            segments = whisper_segments
            # Получаем общую длительность из сегментов (или из аудио, если сегменты пустые)
            total_duration = segments[-1]['end'] if segments else 0.0
            logger.info(f"Using provided Whisper segments for timing ({len(segments)} segments)")
        else:
            model = get_model()
            logger.info(f"Transcribing audio for timing: {audio_path} (lang={language})")
            
            # Если язык указан, помогаем Whisper-у
            transcribe_kwargs = {"verbose": False}
            if language:
                transcribe_kwargs["language"] = language
                
            result = model.transcribe(audio_path, **transcribe_kwargs)
            segments = result.get('segments', [])
            total_duration = segments[-1]['end'] if segments else 0.0
        
        # Подсчет длины оригинального текста и текста от Whisper
        total_chars = sum(len(scene.get('text_segment', '')) for scene in scenes)
        total_whisper_chars = sum(len(seg.get('text', '')) for seg in segments)
        
        # Если Whisper выдал мусор (текст слишком короткий), используем пропорциональное распределение
        if not segments or (total_chars > 0 and total_whisper_chars < total_chars * 0.4):
            logger.warning(f"Whisper output seems inaccurate ({total_whisper_chars} vs {total_chars} chars). Using proportional timing fallback.")
            if total_duration == 0.0:
                # Если даже длины нет, пытаемся оценить по 3 секунды на сцену
                total_duration = len(scenes) * 3.0
            
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
            
            # Корректируем конец последней сцены
            if processed_scenes:
                processed_scenes[-1]['end'] = round(total_duration, 3)
            return processed_scenes

        # 1. Создаем карту соответствия каждого символа Whisper-текста временной метке
        char_to_time = []
        for seg in segments:
            seg_text = "".join(filter(str.isalnum, seg['text'].lower()))
            if not seg_text:
                continue
            
            start_t = seg['start']
            end_t = seg['end']
            duration = end_t - start_t
            
            # Распределяем время сегмента между его символами
            char_dur = duration / len(seg_text)
            for i in range(len(seg_text)):
                char_to_time.append(start_t + (i * char_dur))

        # 2. Проходим по сценам и находим их границы в этой карте
        current_char_idx = 0
        processed_scenes = []
        
        for i, scene in enumerate(scenes):
            scene_text = "".join(filter(str.isalnum, scene.get('text_segment', "").lower()))
            
            if not scene_text:
                # Если текста нет, берем 1 секунду от текущего момента
                start_t = char_to_time[current_char_idx] if current_char_idx < len(char_to_time) else total_duration
                scene['start'] = round(start_t, 3)
                scene['end'] = round(start_t + 1.0, 3)
                processed_scenes.append(scene)
                continue

            # Находим начало и конец сцены в массиве таймингов
            start_idx = current_char_idx
            end_idx = min(len(char_to_time) - 1, current_char_idx + len(scene_text))
            
            # Первая сцена всегда от 0
            if i == 0:
                scene['start'] = 0.0
            else:
                # Начинаем там, где кончилась предыдущая, или где реально начался текст
                real_start = char_to_time[start_idx] if start_idx < len(char_to_time) else total_duration
                prev_end = processed_scenes[-1]['end']
                scene['start'] = round(max(prev_end, real_start), 3)

            scene['end'] = round(char_to_time[end_idx] if end_idx < len(char_to_time) else total_duration, 3)
            
            processed_scenes.append(scene)
            current_char_idx = end_idx + 1 # Сдвигаемся на следующий текст
            
        # Гарантируем, что последняя сцена идет до конца аудио
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
