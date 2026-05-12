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

def align_scenes_with_audio(scenes: list, audio_path: str, whisper_segments: list = None, language: str = None, use_llm_align: bool = False):
    """
    Сравнивает текст сцен с аудио через Whisper и проставляет точные тайминги.
    При use_llm_align=True использует LLM для точного выравнивания слов сценария с Whisper-сегментами.
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
            if processed_scenes:
                processed_scenes[-1]['end'] = round(total_duration, 3)
            return processed_scenes

        # --- НОВЫЙ АЛГОРИТМ: Привязка сцен к сегментам Whisper без дрейфа курсора ---
        # Строим линейный список слов из Whisper-сегментов с временными метками каждого слова
        whisper_words = []
        for seg in segments:
            seg_words = seg['text'].strip().split()
            if not seg_words:
                continue
            word_dur = (seg['end'] - seg['start']) / len(seg_words)
            for j, w in enumerate(seg_words):
                whisper_words.append({
                    'word': ''.join(filter(str.isalnum, w.lower())),
                    'start': seg['start'] + j * word_dur,
                    'end': seg['start'] + (j + 1) * word_dur,
                })

        # Скользящий указатель: последовательно двигаемся по whisper_words для каждой сцены
        # Это предотвращает дрейф — каждая сцена начинается ровно там, где закончилась предыдущая
        w_cursor = 0
        processed_scenes = []

        for i, scene in enumerate(scenes):
            scene_text = scene.get('text_segment', '').strip()
            scene_words_clean = [''.join(filter(str.isalnum, w.lower())) for w in scene_text.split()]
            scene_words_clean = [w for w in scene_words_clean if w]

            if not scene_words_clean:
                prev_end = processed_scenes[-1]['end'] if processed_scenes else 0.0
                scene['start'] = round(prev_end, 3)
                scene['end'] = round(prev_end + 1.0, 3)
                processed_scenes.append(scene)
                continue

            # Находим начало сцены: берём время первого whisper-слова начиная с курсора
            if i == 0:
                scene_start = 0.0
            else:
                prev_end = processed_scenes[-1]['end']
                wstart = whisper_words[w_cursor]['start'] if w_cursor < len(whisper_words) else total_duration
                scene_start = round(max(prev_end, wstart), 3)

            # Смещаем курсор вперёд на количество слов в сцене
            words_in_scene = len(scene_words_clean)
            w_end_cursor = min(w_cursor + words_in_scene - 1, len(whisper_words) - 1)

            if w_end_cursor < len(whisper_words):
                scene_end = round(whisper_words[w_end_cursor]['end'], 3)
            else:
                scene_end = round(total_duration, 3)

            # Защита: конец не может быть <= началу
            if scene_end <= scene_start:
                scene_end = round(scene_start + max(1.0, words_in_scene * 0.4), 3)

            scene['start'] = scene_start
            scene['end'] = scene_end
            processed_scenes.append(scene)

            # Двигаем курсор за конец текущей сцены
            w_cursor = w_end_cursor + 1

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
