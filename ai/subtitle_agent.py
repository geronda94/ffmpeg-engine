import subprocess
import logging
import os

logger = logging.getLogger(__name__)


def generate_srt_from_project(scenes: list, whisper_segments: list, output_path: str) -> str | None:
    """
    Создает .srt файл субтитров с использованием АЛГОРИТМА ПЛАВНОГО РАСПРЕДЕЛЕНИЯ.
    Текст распределяется равномерно по длине сцены пропорционально количеству символов.
    """
    try:
        def format_time(seconds: float) -> str:
            if seconds < 0: seconds = 0
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            s = int(seconds % 60)
            ms = int((seconds % 1) * 1000)
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

        final_srt_segments = []

        for i, scene in enumerate(scenes):
            # Гибкая проверка флага защиты
            allow_fx = scene.get('allow_montage_effects', True)
            
            if not allow_fx:
                logger.info(f"⏭️ SubtitleAgent: Skipping protected scene {i}")
                continue

            logger.info(f"📝 SubtitleAgent: Processing scene {i}")
            scene_start = scene.get('start', 0)
            scene_end = scene.get('end', 0)
            scene_dur = scene_end - scene_start
            original_text = scene.get('text_segment', "").strip()
            
            if not original_text or scene_dur <= 0:
                continue

            # --- АЛГОРИТМ ПЛАВНОГО РАСПРЕДЕЛЕНИЯ (LINEAR SMOOTHING) ---
            
            # 1. Разбиваем текст на слова
            words = original_text.split()
            
            # 2. Группируем слова в сегменты оптимальной длины (30-40 символов)
            # Это позволяет избежать мелькания одиночных коротких слов.
            segments_text = []
            current_seg = []
            current_len = 0
            
            for word in words:
                current_seg.append(word)
                current_len += len(word) + 1
                # Если набрали достаточно символов ИЛИ слово заканчивается знаком препинания
                if current_len >= 30 or word.endswith(('.', '!', '?', ',', ':')):
                    segments_text.append(" ".join(current_seg))
                    current_seg = []
                    current_len = 0
            
            if current_seg:
                segments_text.append(" ".join(current_seg))

            # 3. Распределяем сегменты по времени сцены пропорционально их длине
            total_chars = sum(len(s) for s in segments_text)
            if total_chars == 0: continue
            
            current_time = scene_start
            for i, seg_text in enumerate(segments_text):
                # Доля времени, которую занимает этот сегмент (на основе кол-ва символов)
                weight = len(seg_text) / total_chars
                seg_dur = weight * scene_dur
                
                # Защита от слишком коротких титров (минимум 1.2 секунды, если позволяет сцена)
                # Но не больше остатка времени до конца сцены
                safe_dur = max(1.2, seg_dur)
                seg_end = min(current_time + safe_dur, scene_end)
                
                # Если это последний сегмент в сцене, растягиваем его до конца
                if i == len(segments_text) - 1:
                    seg_end = scene_end

                final_srt_segments.append({
                    'start': current_time,
                    'end': seg_end,
                    'text': seg_text
                })
                current_time = seg_end

        # Генерируем финальный SRT
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

        logger.info(f"SRT generated with Linear Smoothing: {output_path}")
        return output_path

    except Exception as e:
        logger.error(f"Subtitle Agent Error: {e}", exc_info=True)
        return None


def burn_subtitles(video_path: str, srt_path: str, output_path: str) -> str | None:
    """
    Вшивает субтитры в видео с помощью ffmpeg.
    """
    try:
        # Экранируем путь к SRT для ffmpeg фильтра
        clean_srt_path = srt_path.replace("\\", "/").replace(":", "\\:")
        
        # Путь к локальной папке со шрифтами для портативности
        fonts_dir = os.path.join(os.getcwd(), "local_assets", "fonts").replace("\\", "/").replace(":", "\\:")
        
        # Настройка стиля субтитров (Social Media Premium Style):
        # - FontName=DejaVu Sans (Берется из папки fonts/)
        style = "FontName=DejaVu Sans,FontSize=13,PrimaryColour=&H00FFFFFF&,OutlineColour=&H80333333&,BorderStyle=1,Outline=1.0,Shadow=0.5,Alignment=2,MarginV=18,MarginR=100,MarginL=30,Bold=1"
        
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vf", f"subtitles='{clean_srt_path}':fontsdir='{fonts_dir}':force_style='{style}'",
            "-c:a", "copy",
            output_path
        ]
        
        logger.info(f"Burning subtitles (Extreme Safe Zone): {' '.join(cmd)}")
        subprocess.run(cmd, check=True, capture_output=True)
        return output_path
    except Exception as e:
        logger.error(f"Error burning subtitles: {e}")
        return None
