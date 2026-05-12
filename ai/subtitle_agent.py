import subprocess
import logging
import os

logger = logging.getLogger(__name__)


def _group_words(words, max_chars=14):
    groups = []
    current = []
    for w in words:
        if not current:
            current.append(w)
        elif len(w) <= 3 and len(" ".join(current + [w])) <= max_chars:
            current.append(w)
        else:
            groups.append(" ".join(current))
            current = [w]
    if current:
        groups.append(" ".join(current))
    return groups


def generate_srt_from_project(scenes: list, whisper_segments: list, output_path: str) -> str | None:
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
        for scene in scenes:
            if not scene.get('allow_montage_effects', True):
                continue
            text = scene.get('text_segment', '').strip()
            if not text: continue

            scene_whisper = [s for s in whisper_segments if (s['start'] < scene['end'] and s['end'] > scene['start'])]

            if scene_whisper:
                speech_start = min(s['start'] for s in scene_whisper)
                speech_end = max(s['end'] for s in scene_whisper)
            else:
                speech_start, speech_end = scene['start'], scene['end']

            speech_start = max(speech_start, scene['start'])
            speech_end = min(speech_end, scene['end'])
            duration = speech_end - speech_start
            if duration <= 0: continue

            words = text.split()
            chunks = _group_words(words)
            chunk_dur = duration / len(chunks)

            for i, chunk_text in enumerate(chunks):
                seg_start = speech_start + i * chunk_dur
                seg_end = speech_start + (i + 1) * chunk_dur
                if is_time_allowed(seg_start):
                    final_srt_segments.append({
                        'start': seg_start, 'end': seg_end, 'text': chunk_text
                    })

        if not final_srt_segments:
            logger.warning("⚠️ SubtitleAgent: No segments after filtering!")
            return None

        with open(output_path, "w", encoding="utf-8") as f:
            for i, seg in enumerate(final_srt_segments, 1):
                f.write(f"{i}\n")
                f.write(f"{format_time(seg['start'])} --> {format_time(seg['end'])}\n")
                f.write(f"{seg['text']}\n\n")

        logger.info(f"✅ SRT generated ({len(final_srt_segments)} segs): {output_path}")
        return output_path

    except Exception as e:
        logger.error(f"SRT generation error: {e}", exc_info=True)
        return None


def generate_ass_from_project(scenes: list, whisper_segments: list, output_path: str) -> str | None:
    try:
        def fmt(seconds):
            if seconds < 0: seconds = 0
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            s = int(seconds % 60)
            ms = int((seconds % 1) * 100)
            return f"{h}:{m:02d}:{s:02d}.{ms:02d}"

        if not whisper_segments:
            logger.warning("⚠️ No whisper segments!")
            return None

        header = [
            "[Script Info]",
            "Title: Slot Machine Subtitles",
            "ScriptType: v4.00+",
            "PlayResX: 1080",
            "PlayResY: 1920",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            "Style: CenterLine,DejaVu Sans Bold,94,&H0033CCFF,&H00FFFFFF,&H002C2C2C,&H00000000,-1,0,0,0,100,100,0,0,1,10,0,5,30,30,0,1",
            "Style: SideLine,DejaVu Sans Bold,94,&H00FFFFFF,&H00FFFFFF,&H002C2C2C,&H00000000,-1,0,0,0,100,100,0,0,1,1.5,0,5,30,30,0,1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
        ]

        word_groups = []
        for scene in scenes:
            if not scene.get('allow_montage_effects', True):
                continue
            text = scene.get('text_segment', '').strip()
            if not text:
                continue

            scene_whisper = [s for s in whisper_segments if (s['start'] < scene['end'] and s['end'] > scene['start'])]
            if scene_whisper:
                speech_start = min(s['start'] for s in scene_whisper)
                speech_end = max(s['end'] for s in scene_whisper)
            else:
                speech_start, speech_end = scene['start'], scene['end']
            speech_start = max(speech_start, scene['start'])
            speech_end = min(speech_end, scene['end'])
            duration = speech_end - speech_start
            if duration <= 0:
                continue

            groups = _group_words(text.split())
            if not groups:
                continue
            grp_dur = duration / len(groups)
            for i, g in enumerate(groups):
                word_groups.append({
                    'text': g,
                    'start': speech_start + i * grp_dur,
                    'end': speech_start + (i + 1) * grp_dur,
                })

        cx = 540
        y_curr = 1440
        y_offset = 80
        y_prev = y_curr - y_offset
        y_next = y_curr + y_offset
        y_below = y_next + y_offset
        anim_ms = 300
        
        c_hl = "&H0033CCFF&"
        c_white = "&H00FFFFFF&"
        c_ant = "&H002C2C2C&"

        events = []
        for i, g in enumerate(word_groups):
            s, e = fmt(g['start']), fmt(g['end'])

            prev_txt = word_groups[i - 1]['text'] if i > 0 else ""
            next_txt = word_groups[i + 1]['text'] if i < len(word_groups) - 1 else ""
            curr_txt = g['text']

            # Верхний ряд: становится меньше и исчезает вверх
            events.append(
                f"Dialogue: 0,{s},{e},SideLine,,0,0,0,,"
                f"{{\\pos({cx},{y_curr})\\fscx100\\fscy100\\bord10\\1c{c_hl}\\3c{c_ant}"
                f"\\t(0,{anim_ms},\\pos({cx},{y_prev})\\fscx65\\fscy65\\bord1.5\\1c{c_white}\\3c{c_ant})}}"
                f"{{\\fad(0,150)}}{prev_txt}"
            )
            # Центральный ряд: вырастает и становится активным
            events.append(
                f"Dialogue: 0,{s},{e},CenterLine,,0,0,0,,"
                f"{{\\pos({cx},{y_next})\\fscx65\\fscy65\\bord1.5\\1c{c_white}\\3c{c_ant}"
                f"\\t(0,{anim_ms},\\pos({cx},{y_curr})\\fscx100\\fscy100\\bord10\\1c{c_hl}\\3c{c_ant})}}"
                f"{{\\fad(150,0)}}{curr_txt}"
            )
            # Нижний ряд: поднимается на место ожидания
            events.append(
                f"Dialogue: 0,{s},{e},SideLine,,0,0,0,,"
                f"{{\\pos({cx},{y_below})\\fscx65\\fscy65\\bord1.5\\1c{c_white}\\3c{c_ant}"
                f"\\t(0,{anim_ms},\\pos({cx},{y_next})\\fscx65\\fscy65\\bord1.5\\1c{c_white}\\3c{c_ant})}}"
                f"{{\\fad(150,0)}}{next_txt}"
            )

        with open(output_path, "w", encoding="utf-8-sig") as f:
            f.write("\n".join(header) + "\n")
            for line in events:
                f.write(line + "\n")

        logger.info(f"✅ ASS slot-machine ({len(word_groups)} groups): {output_path}")
        return output_path

    except Exception as e:
        logger.error(f"ASS error: {e}", exc_info=True)
        return None


def burn_subtitles(video_path: str, subtitle_path: str, output_path: str):
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", f"subtitles={subtitle_path}",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "192k",
        "-af", "dynaudnorm",
        output_path
    ]
    logger.info(f"🔥 Burning subtitles with FFmpeg...")
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        logger.info(f"🔥 Subtitles burned: {output_path}")
        return output_path
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg subtitle burn error: {e}")
        logger.error(f"FFmpeg stderr: {e.stderr[:500]}")
        return None
