import subprocess
import logging
import os

logger = logging.getLogger(__name__)


def generate_srt_from_project(scenes: list, whisper_segments: list, output_path: str) -> str | None:
    """
    Создает .srt файл субтитров из Whisper-сегментов,
    ПРОПУСКАЯ сцены с allow_montage_effects=False (динамическая графика).
    ДРОБИТ длинные сегменты на короткие части.
    """
    try:
        def format_time(seconds: float) -> str:
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            s = int(seconds % 60)
            ms = int((seconds % 1) * 1000)
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

        # Собираем временные диапазоны сцен, которые нужно СКРЫТЬ
        blocked_ranges = []
        for scene in scenes:
            if not scene.get('allow_montage_effects', True):
                start = scene.get('start', 0)
                end = scene.get('end', 0)
                if end > start:
                    blocked_ranges.append((start, end))

        def is_blocked(seg_start, seg_end):
            for b_start, b_end in blocked_ranges:
                if seg_start < b_end and seg_end > b_start:
                    return True
            return False

        # Дробим сегменты
        fine_segments = []
        for seg in whisper_segments:
            text = seg['text'].strip()
            if not text: continue
            
            words = text.split()
            if len(words) <= 4:
                fine_segments.append(seg)
            else:
                # Дробим на куски по 4 слова
                num_chunks = (len(words) + 3) // 4
                dur = seg['end'] - seg['start']
                chunk_dur = dur / num_chunks
                for i in range(num_chunks):
                    chunk_words = words[i*4 : (i+1)*4]
                    fine_segments.append({
                        'start': seg['start'] + i * chunk_dur,
                        'end': seg['start'] + (i+1) * chunk_dur,
                        'text': " ".join(chunk_words)
                    })

        lines = []
        idx = 1
        for seg in fine_segments:
            if is_blocked(seg['start'], seg['end']):
                continue

            start = format_time(seg['start'])
            end = format_time(seg['end'])
            text = seg['text'].strip()
            if not text: continue

            lines.append(f"{idx}\n{start} --> {end}\n{text}\n")
            idx += 1

        srt_content = "\n".join(lines)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(srt_content)

        logger.info(f"SRT generated: {output_path} ({idx - 1} sub-chunks)")
        return output_path

    except Exception as e:
        logger.error(f"SRT generation error: {e}")
        return None


def burn_subtitles(video_path: str, srt_path: str, output_path: str) -> str | None:
    """
    Вшивает субтитры. Стиль: аккуратный, белый, с тенью, мелкий шрифт.
    """
    try:
        srt_escaped = os.path.abspath(srt_path).replace("\\", "/").replace(":", "\\:")

        subtitle_filter = (
            f"subtitles='{srt_escaped}':"
            f"force_style='"
            f"FontName=Arial,"
            f"FontSize=12,"
            f"Bold=1,"
            f"PrimaryColour=&H00FFFFFF,"
            f"OutlineColour=&H00000000,"
            f"BackColour=&H80000000,"
            f"Outline=1,"
            f"Shadow=1,"
            f"Alignment=2,"
            f"MarginV=60'"
        )

        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vf", subtitle_filter,
            "-c:v", "libx264",
            "-c:a", "copy",
            "-preset", "fast",
            output_path
        ]

        logger.info(f"Burning sub-chunks into: {output_path}")
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        return output_path

    except Exception as e:
        logger.error(f"Subtitle burn error: {e}")
        return None
