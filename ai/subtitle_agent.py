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
        
        # 2. Обрабатываем сегменты Whisper напрямую
        for seg in whisper_segments:
            start_t = seg['start']
            end_t = seg['end']
            text = seg['text'].strip()
            
            if not text:
                continue
            
            # Проверяем, разрешены ли субтитры в этот момент времени (защита динамических сцен)
            if not is_time_allowed(start_t):
                continue
            
            # Разбиваем длинные сегменты Whisper на части, если в них больше 5 слов
            words = text.split()
            if len(words) > 5:
                mid = len(words) // 2
                dur = end_t - start_t
                final_srt_segments.append({
                    'start': start_t,
                    'end': start_t + (dur / 2),
                    'text': " ".join(words[:mid])
                })
                final_srt_segments.append({
                    'start': start_t + (dur / 2),
                    'end': end_t,
                    'text': " ".join(words[mid:])
                })
            else:
                final_srt_segments.append({
                    'start': start_t,
                    'end': end_t,
                    'text': text
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
