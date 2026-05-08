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

            # Берем ИДЕАЛЬНЫЙ текст из скрипта, а не из распознавания
            text = scene.get('text_segment', '').strip()
            if not text: continue

            # Находим сегменты Whisper, которые хотя бы частично попадают в эту сцену
            scene_whisper = [
                s for s in whisper_segments 
                if (s['start'] < scene['end'] and s['end'] > scene['start'])
            ]

            if not scene_whisper:
                # Если Whisper почему-то не нашел речь, используем границы сцены
                speech_start = scene['start']
                speech_end = scene['end']
            else:
                speech_start = min(s['start'] for s in scene_whisper)
                speech_end = max(s['end'] for s in scene_whisper)
            
            # Добавляем небольшой отступ от краев сцены для красоты
            speech_start = max(speech_start, scene['start'])
            speech_end = min(speech_end, scene['end'])
            
            duration = speech_end - speech_start
            if duration <= 0: continue

            # Разбиваем текст скрипта на кусочки по 3-4 слова
            words = text.split()
            chunks = []
            temp_chunk = []
            for w in words:
                temp_chunk.append(w)
                if len(temp_chunk) >= 4 or len(" ".join(temp_chunk)) > 25:
                    chunks.append(" ".join(temp_chunk))
                    temp_chunk = []
            if temp_chunk:
                chunks.append(" ".join(temp_chunk))

            # Равномерно распределяем кусочки текста ВНУТРИ интервала речи
            if not chunks: continue
            chunk_dur = duration / len(chunks)
            for i, chunk_text in enumerate(chunks):
                final_srt_segments.append({
                    'start': speech_start + (i * chunk_dur),
                    'end': speech_start + ((i + 1) * chunk_dur),
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

def generate_ass_from_project(scenes: list, whisper_segments: list, output_path: str) -> str | None:
    """
    Создает .ass файл с анимациями (выезд с боков).
    Использует ту же логику защиты сцен и синхронизации с Whisper.
    """
    try:
        import random
        
        def format_ass_time(seconds: float) -> str:
            if seconds < 0: seconds = 0
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            s = int(seconds % 60)
            ms = int((seconds % 1) * 100) # В ASS сотые доли, а не тысячные
            return f"{h}:{m:02d}:{s:02d}.{ms:02d}"

        if not whisper_segments:
            logger.warning("⚠️ SubtitleAgent: No whisper segments provided!")
            return None

        # 1. Заголовок ASS (разрешение 1080x1920)
        # Цвета: Primary (Желтый - подсветка), Secondary (Белый - база)
        header = [
            "[Script Info]",
            "Title: Animated AI Karaoke Subtitles",
            "ScriptType: v4.00+",
            "PlayResX: 1080",
            "PlayResY: 1920",
            "ScaledBorderAndShadow: yes",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            "Style: Default,DejaVu Sans Bold,62,&H0000FFFF,&H00FFFFFF,&H80333333,&H00000000,-1,0,0,0,100,100,0,0,1,3,1.5,2,120,120,520,1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
        ]

        final_segments = []
        for scene in scenes:
            if not scene.get('allow_montage_effects', True):
                continue

            text = scene.get('text_segment', '').strip()
            if not text: continue

            scene_whisper = [
                s for s in whisper_segments 
                if (s['start'] < scene['end'] and s['end'] > scene['start'])
            ]

            if not scene_whisper:
                speech_start, speech_end = scene['start'], scene['end']
            else:
                speech_start = min(s['start'] for s in scene_whisper)
                speech_end = max(s['end'] for s in scene_whisper)
            
            speech_start = max(speech_start, scene['start'])
            speech_end = min(speech_end, scene['end'])
            
            duration = speech_end - speech_start
            if duration <= 0: continue

            # Разбиваем на чанки
            words = text.split()
            chunks = []
            temp_chunk = []
            for w in words:
                temp_chunk.append(w)
                if len(temp_chunk) >= 4 or len(" ".join(temp_chunk)) > 25:
                    chunks.append(" ".join(temp_chunk).upper()) # В Shorts часто используют капс
                    temp_chunk = []
            if temp_chunk:
                chunks.append(" ".join(temp_chunk).upper())

            if not chunks: continue
            chunk_dur = duration / len(chunks)
            for i, chunk_text in enumerate(chunks):
                final_segments.append({
                    'start': speech_start + (i * chunk_dur),
                    'end': speech_start + ((i + 1) * chunk_dur),
                    'text': chunk_text
                })

        # Генерация строк событий с анимацией и караоке
        events = []
        for seg in final_segments:
            start_str = format_ass_time(seg['start'])
            end_str = format_ass_time(seg['end'])
            
            # Динамически рассчитываем Y на основе MarginV (520)
            # 1920 - 520 = 1400
            margin_v = 520
            target_x, target_y = 540, 1920 - margin_v
            move_dur = 120
            
            side = random.choice(['left', 'right', 'bottom'])
            if side == 'left':
                start_x, start_y = -400, target_y
            elif side == 'right':
                start_x, start_y = 1480, target_y
            else: # bottom
                start_x, start_y = target_x, 1920 + 200

            anim_tag = f"{{\\move({start_x}, {target_y}, {target_x}, {target_y}, 0, {move_dur})}}"
            
            # Караоке-логика: делим текст на слова и ставим \k
            words = seg['text'].split()
            if not words: continue
            
            total_dur_ms = (seg['end'] - seg['start']) * 1000
            # Длительность одного слова в центисекундах (1/100 сек)
            k_word = int((total_dur_ms / len(words)) / 10)
            
            karaoke_text = ""
            for word in words:
                karaoke_text += f"{{\\k{k_word}}}{word} "
            
            events.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{anim_tag}{karaoke_text.strip()}")

        ass_content = "\n".join(header + events)
        with open(output_path, "w", encoding="utf-8-sig") as f: # ASS лучше с BOM
            f.write(ass_content)

        logger.info(f"✅ ASS generated (Animated): {output_path}")
        return output_path

    except Exception as e:
        logger.error(f"❌ Subtitle Agent ASS Error: {e}", exc_info=True)
        return None

def burn_subtitles(video_path: str, srt_path: str, output_path: str) -> str | None:
    """Вшивает субтитры в видео. Поддерживает SRT и ASS."""
    try:
        is_ass = srt_path.lower().endswith('.ass')
        clean_srt_path = srt_path.replace("\\", "/").replace(":", "\\:")
        fonts_dir = os.path.join(os.getcwd(), "local_assets", "fonts").replace("\\", "/").replace(":", "\\:")
        
        # Если это ASS, стили уже внутри файла, force_style не нужен
        if is_ass:
            vf = f"subtitles='{clean_srt_path}':fontsdir='{fonts_dir}'"
        else:
            style = "FontName=DejaVu Sans Bold,FontSize=16,PrimaryColour=&H00FFFFFF&,OutlineColour=&H80333333&,BorderStyle=1,Outline=0.8,Shadow=0.5,Alignment=2,MarginV=520,MarginR=120,MarginL=120"
            vf = f"subtitles='{clean_srt_path}':fontsdir='{fonts_dir}':force_style='{style}'"
        
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vf", vf,
            "-af", "dynaudnorm", # Динамическая нормализация звука (делает голос громким и плотным)
            "-c:a", "aac", "-b:a", "192k",
            output_path
        ]
        
        subprocess.run(cmd, check=True, capture_output=True)
        return output_path
    except Exception as e:
        logger.error(f"Error burning subtitles: {e}")
        return None
