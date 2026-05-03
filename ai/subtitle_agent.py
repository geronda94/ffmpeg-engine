import subprocess
import logging
import os

logger = logging.getLogger(__name__)


def generate_srt_from_project(scenes: list, whisper_segments: list, output_path: str) -> str | None:
    """
    Создает .srt файл субтитров, используя ОРИГИНАЛЬНЫЙ ТЕКСТ из сцен,
    но ТАЙМИНГИ из Whisper для синхронизации.
    """
    try:
        def format_time(seconds: float) -> str:
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            s = int(seconds % 60)
            ms = int((seconds % 1) * 1000)
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

        final_srt_segments = []

        for scene in scenes:
            if not scene.get('allow_montage_effects', True):
                continue

            scene_start = scene.get('start', 0)
            scene_end = scene.get('end', 0)
            original_text = scene.get('text_segment', "").strip()
            
            if not original_text:
                continue

            # Ищем whisper-сегменты, которые попадают в эту сцену
            scene_whisper_segs = [
                s for s in whisper_segments 
                if s['start'] >= scene_start - 0.5 and s['end'] <= scene_end + 0.5
            ]

            if not scene_whisper_segs:
                # Если whisper ничего не нашел для этой сцены, просто бьем текст сцены на куски
                # Дробим текст на куски примерно по 2-3 слова
                words = original_text.split()
                num_chunks = max(1, int(round(len(words) / 2.5)))
                dur = scene_end - scene_start
                chunk_dur = dur / num_chunks if num_chunks > 0 else dur
                for i in range(num_chunks):
                    chunk = words[int(i * (len(words)/num_chunks)) : int((i+1) * (len(words)/num_chunks))]
                    final_srt_segments.append({
                        'start': scene_start + i * chunk_dur,
                        'end': scene_start + (i+1) * chunk_dur,
                        'text': " ".join(chunk)
                    })
            else:
                # У нас есть и оригинальный текст, и тайминги whisper
                # Распределяем оригинальные слова по whisper-сегментам
                orig_words = original_text.split()
                words_per_seg = len(orig_words) / len(scene_whisper_segs)
                
                for i, wseg in enumerate(scene_whisper_segs):
                    w_start_idx = i * words_per_seg
                    w_end_idx = (i + 1) * words_per_seg
                    seg_words = orig_words[int(w_start_idx) : int(w_end_idx)]
                    
                    if not seg_words:
                        continue
                        
                    # ДРОБИМ САМ СЕГМЕНТ НА КУСКИ ПО 2-3 СЛОВА
                    num_subchunks = max(1, int(round(len(seg_words) / 2.5)))
                    w_dur = wseg['end'] - wseg['start']
                    subchunk_dur = w_dur / num_subchunks if num_subchunks > 0 else w_dur
                    
                    for j in range(num_subchunks):
                        sub_start_idx = int(j * (len(seg_words)/num_subchunks))
                        sub_end_idx = int((j+1) * (len(seg_words)/num_subchunks))
                        subchunk = seg_words[sub_start_idx:sub_end_idx]
                        
                        if subchunk:
                            final_srt_segments.append({
                                'start': wseg['start'] + j * subchunk_dur,
                                'end': wseg['start'] + (j+1) * subchunk_dur,
                                'text': " ".join(subchunk)
                            })

        # Генерируем финальный SRT
        lines = []
        for idx, seg in enumerate(final_srt_segments, 1):
            start = format_time(seg['start'])
            end = format_time(seg['end'])
            text = seg['text'].strip()
            if not text: continue
            lines.append(f"{idx}\n{start} --> {end}\n{text}\n")

        srt_content = "\n".join(lines)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(srt_content)

        logger.info(f"SRT generated with original text: {output_path}")
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
            f"FontName=DejaVu Sans,"
            f"FontSize=14,"
            f"Bold=1,"
            f"PrimaryColour=&H00FFFFFF,"
            f"OutlineColour=&H00000000,"
            f"BackColour=&H80000000,"
            f"Outline=1,"
            f"Shadow=1,"
            f"Alignment=1,"
            f"MarginL=20,"
            f"MarginV=45'"
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
