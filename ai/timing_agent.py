import whisper
import logging
import os

logger = logging.getLogger(__name__)

# Загружаем модель один раз при импорте (base - баланс скорости и качества)
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
        
        # Транскрибируем с детальными таймингами
        result = model.transcribe(audio_path, verbose=False)
        segments = result['segments'] # Список сегментов с 'start', 'end', 'text'
        
        # Логика сопоставления: 
        # Мы идем по сегментам Whisper и пытаемся понять, к какой сцене они относятся.
        # Самый простой и надежный способ - распределить сегменты по сценам на основе накопленного текста.
        
        current_time = 0.0
        total_duration = segments[-1]['end'] if segments else 0.0
        
        # Если Whisper ничего не нашел (тишина), возвращаем как есть
        if not segments:
            return scenes

        processed_scenes = []
        seg_idx = 0
        
        for i, scene in enumerate(scenes):
            scene_text = scene['text_segment'].lower().strip()
            scene_start = segments[seg_idx]['start'] if seg_idx < len(segments) else current_time
            
            # Находим, где заканчивается текст этой сцены в сегментах Whisper
            accumulated_text = ""
            while seg_idx < len(segments):
                accumulated_text += segments[seg_idx]['text'].lower()
                current_time = segments[seg_idx]['end']
                seg_idx += 1
                
                # Если мы набрали достаточно текста (или это последняя сцена) - стоп
                # Мы используем мягкое сравнение длины, так как ИИ может чуть менять слова
                if len(accumulated_text) >= len(scene_text) * 0.8:
                    break
            
            scene['start'] = scene_start
            scene['end'] = current_time
            processed_scenes.append(scene)
            
        # Гарантируем, что последняя сцена идет до конца аудио
        if processed_scenes:
            processed_scenes[-1]['end'] = total_duration
            
        return processed_scenes

    except Exception as e:
        logger.error(f"Timing Agent Error: {e}")
        return scenes # В случае ошибки возвращаем исходные (аппроксимированные) сцены
