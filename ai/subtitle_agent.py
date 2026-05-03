import subprocess
import logging
import os

logger = logging.getLogger(__name__)

def generate_srt_from_project(scenes: list, whisper_segments: list, output_path: str) -> str | None:
    """
    Создает .srt файл на основе РЕАЛЬНЫХ таймингов Whisper, 
    но С УЧЕТОМ защиты динамических сцен.
    """
    try:
        def format_time(seconds: float) -> str:
            if seconds < 0: seconds = 0
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            s = int(seconds % 60)
            ms = int((seconds % 1) * 1000)
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

        if not whisper_segments:
            logger.warning("⚠️ SubtitleAgent: No whisper segments provided!")
            return None

        # 1. Создаем карту разрешенных интервалов времени
        allowed_intervals = []
        for scene in scenes:
            if scene.get('allow_montage_effects', True):
                allowed_intervals.append((scene.get('start', 0), scene.get('end', 0)))
        
        def is_time_allowed(t):
            for start, end in allowed_intervals:
                if start <= t <= end:
                    return True
            return False

        final_srt_segments = []
        
        # 2. Обрабатываем каждую сцену отдельно
        for scene in scenes:
            # Проверка: разрешены ли субтитры в этой сцене (защита динамических сцен)
            if not scene.get('allow_montage_effects', True):
                continue

            text = scene.get('text_segment', '').strip()
            if not text: continue

            # Находим временной диапазон речи в этой сцене по данным Whisper
            # Берем сегменты, которые попадают в границы сцены (с небольшим запасом)
            scene_whisper = [
                s for s in whisper_segments 
                if s['start'] >= scene['start'] - 0.3 
                and s['end'] <= scene['end'] + 0.3
            ]

            if not scene_whisper:
                speech_start = scene['start']
                speech_end = scene['end']
            else:
                speech_start = min(s['start'] for s in scene_whisper)
                speech_end = max(s['end'] for s in scene_whisper)
            
            duration = speech_end - speech_start
            if duration <= 0: continue

            # Разбиваем текст на небольшие группы (по 3-4 слова)
            words = text.split()
            chunks = []
            temp_chunk = []
            temp_len = 0
            
            for w in words:
                # Ограничение: 4 слова или 30 символов на субтитр
                if (len(temp_chunk) >= 4 or temp_len + len(w) > 30) and temp_chunk:
                    chunks.append(" ".join(temp_chunk))
                    temp_chunk = [w]
                    temp_len = len(w)
                else:
                    temp_chunk.append(w)
                    temp_len += len(w) + 1
            if temp_chunk:
                chunks.append(" ".join(temp_chunk))

            # Равномерно распределяем группы слов по времени речи
            chunk_dur = duration / len(chunks)
            for i, chunk_text in enumerate(chunks):
                final_srt_segments.append({
                    'start': speech_start + i * chunk_dur,
                    'end': speech_start + (i + 1) * chunk_dur,
                    'text': chunk_text
                })

        # Генерируем SRT
        lines = []
        for idx, seg in enumerate(final_srt_segments, 1):
            start_str = format_time(seg['start'])
            end_str = format_time(seg['end'])
            text = seg['text'].strip()
            if not text: continue
            lines.append(f"{idx}\n{start_str} --> {end_str}\n{text}\n")

        srt_content = "\n".join(lines)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(srt_content)

        logger.info(f"✅ SRT generated (Script-driven + Whisper sync): {output_path}")
        return output_path

    except Exception as e:
        logger.error(f"❌ Subtitle Agent Error: {e}", exc_info=True)
        return None

def burn_subtitles(video_path: str, srt_path: str, output_path: str) -> str | None:
    """Вшивает субтитры в видео."""
    try:
        clean_srt_path = srt_path.replace("\\", "/").replace(":", "\\:")
        fonts_dir = os.path.join(os.getcwd(), "local_assets", "fonts").replace("\\", "/").replace(":", "\\:")
        style = "FontName=DejaVu Sans Bold,FontSize=18,PrimaryColour=&H00FFFFFF&,OutlineColour=&H80333333&,BorderStyle=1,Outline=0.8,Shadow=0.5,Alignment=2,MarginV=25,MarginR=30,MarginL=30"
        
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vf", f"subtitles='{clean_srt_path}':fontsdir='{fonts_dir}':force_style='{style}'",
            "-c:a", "copy",
            output_path
        ]
        
        subprocess.run(cmd, check=True, capture_output=True)
        return output_path
    except Exception as e:
        logger.error(f"Error burning subtitles: {e}")
        return None
