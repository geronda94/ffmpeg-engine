import subprocess
import logging
import os

logger = logging.getLogger(__name__)


def _group_words(words, max_chars=16, max_lines=2):
    """
    Groups words into blocks. Each block can have multiple lines (max_lines).
    Each line has a maximum of max_chars.
    """
    lines = []
    current_line = []
    current_len = 0
    
    for w in words:
        # If word itself exceeds max_chars, it will be its own line
        new_len = current_len + (1 if current_line else 0) + len(w)
        if new_len <= max_chars:
            current_line.append(w)
            current_len = new_len
        else:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [w]
            current_len = len(w)
            
    if current_line:
        lines.append(" ".join(current_line))
        
    # Group lines into blocks (events)
    blocks = []
    for i in range(0, len(lines), max_lines):
        blocks.append("\\N".join(lines[i:i + max_lines]))
        
    return blocks


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


def generate_ass_from_project(scenes: list, whisper_segments: list, output_path: str,
                                min_start_time: float = 0.0, aligned_words: list = None,
                                language: str = "") -> str | None:
    def _hex_to_ass(hex_str):
        if not hex_str or not isinstance(hex_str, str): return "&H00FFFFFF&"
        h = hex_str.lstrip('#')
        if len(h) != 6: return "&H00FFFFFF&"
        return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}&"

    def _clean(w):
        return w.strip('.,!?;:""''«»—-()[]{}…\' ').strip()

    try:
        def fmt(seconds):
            if seconds < 0: seconds = 0
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            s = int(seconds % 60)
            ms = int((seconds % 1) * 100)
            return f"{h}:{m:02d}:{s:02d}.{ms:02d}"

        first_scene = scenes[0] if scenes else {}
        s_style = first_scene.get('subtitle_style', {})
        c_prim = _hex_to_ass(s_style.get('primary_color', '#f7ec20')) # Active (Yellow)
        c_sec  = _hex_to_ass(s_style.get('secondary_color', '#FFFFFF')) # Passive (White)
        c_outl = _hex_to_ass(s_style.get('outline_color', '#141416')) # Outline (Anthracite)
        c_shad = _hex_to_ass(s_style.get('shadow_color', '#000000'))
        out_w = s_style.get('outline_width', 2.5) # Thin outline
        sha_w = s_style.get('shadow_width', 0)
        font_name = "Montserrat Bold" if "Montserrat" in str(first_scene.get('preview_font_path', '')) else "DejaVu Sans Bold"

        if not whisper_segments:
            logger.warning("⚠️ No whisper segments!")
            return None

        header = [
            "[Script Info]", "Title: Karaoke Subtitles",
            "ScriptType: v4.00+", "PlayResX: 1080", "PlayResY: 1920", "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            f"Style: Karaoke,{font_name},85,{c_prim},{c_sec},{c_outl},{c_shad},-1,0,0,0,100,100,0,0,1,{out_w},{sha_w},5,80,80,150,1",
            "", "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
        ]

        word_groups = []
        for scene_idx, scene in enumerate(scenes):
            if not scene.get('allow_montage_effects', True):
                continue
            text = scene.get('text_segment', '').strip()
            if not text:
                continue

            scene_whisper = [s for s in whisper_segments if (float(s['start']) < float(scene['end']) and float(s['end']) > float(scene['start']))]
            if not scene_whisper:
                continue
            speech_start = max(min(s['start'] for s in scene_whisper), scene['start'])
            speech_end = min(max(s['end'] for s in scene_whisper), scene['end'])
            duration = speech_end - speech_start
            if duration <= 0:
                continue

            raw_words = [_clean(w) for w in text.split()]
            raw_words = [w for w in raw_words if w]
            if not raw_words:
                continue

            groups = _group_words(raw_words)

            if aligned_words and scene_idx < len(aligned_words):
                aw = aligned_words[scene_idx].get("words", [])
                if aw:
                    aw_words = [_clean(w.get("word", "")) for w in aw]
                    aw_words = [w for w in aw_words if w]
                    
                    for g in groups:
                        # Split by space OR \N to get actual words
                        g_words_clean = [_clean(w) for w in g.replace("\\N", " ").split()]
                        g_words_clean = [w for w in g_words_clean if w]
                        
                        if not g_words_clean: continue
                        
                        fw = g_words_clean[0]
                        lw = g_words_clean[-1]
                        
                        fi = next((j for j, w in enumerate(aw_words) if w == fw), None)
                        li = next((j for j, w in enumerate(reversed(aw_words)) if w == lw), None)
                        
                        if li is not None:
                            li = len(aw_words) - 1 - li
                            
                        if fi is not None and li is not None:
                            # Use actual word timings from aligned_words
                            g_start = float(aw[fi]["start"])
                            g_end = float(aw[li]["end"])
                            # Extract word timings for karaoke
                            g_word_timings = []
                            for j in range(fi, li + 1):
                                g_word_timings.append({
                                    'word': aw[j]['word'],
                                    'start': float(aw[j]['start']),
                                    'end': float(aw[j]['end'])
                                })
                        else:
                            g_start = speech_start
                            g_end = speech_end
                            g_word_timings = None
                            
                        word_groups.append({
                            'text': g, 
                            'start': g_start, 
                            'end': g_end,
                            'word_timings': g_word_timings
                        })
                else:
                    grp_dur = duration / len(groups)
                    for i, g in enumerate(groups):
                        word_groups.append({
                            'text': g, 
                            'start': speech_start + i * grp_dur, 
                            'end': speech_start + (i + 1) * grp_dur,
                            'word_timings': None
                        })
            else:
                grp_dur = duration / len(groups)
                for i, g in enumerate(groups):
                    word_groups.append({
                        'text': g, 
                        'start': speech_start + i * grp_dur, 
                        'end': speech_start + (i + 1) * grp_dur,
                        'word_timings': None
                    })

        cx = 540
        y_curr = 1650 # Positioned lower with padding
        
        events = []
        for i, g in enumerate(word_groups):
            if g['start'] < min_start_time:
                continue

            s_fmt, e_fmt = fmt(g['start']), fmt(g['end'])
            curr_txt = g['text']
            parts = curr_txt.split("\\N")
            
            wt = g.get('word_timings')
            k_line = ""
            
            if wt:
                # Accurate karaoke timing from Whisper
                current_time = g['start']
                word_idx = 0
                for pi, p in enumerate(parts):
                    p_words = p.strip().split()
                    for wi, w in enumerate(p_words):
                        if word_idx < len(wt):
                            w_data = wt[word_idx]
                            # Gap before word (in centiseconds)
                            gap = int(max(0, w_data['start'] - current_time) * 100)
                            if gap > 0:
                                k_line += f"{{\\k{gap}}}"
                            # Word duration
                            w_dur = int(max(0, w_data['end'] - w_data['start']) * 100)
                            # Ensure some duration if zero
                            if w_dur == 0 and gap == 0: w_dur = 1
                            k_line += f"{{\\k{w_dur}}}{w}"
                            current_time = w_data['end']
                            word_idx += 1
                        else:
                            k_line += f"{{\\k0}}{w}"
                            
                        if wi < len(p_words) - 1:
                            k_line += " "
                    if pi < len(parts) - 1:
                        k_line += "\\N"
            else:
                # Fallback to linear distribution within the block
                dur_ms = (g['end'] - g['start']) * 1000
                all_words = []
                for p in parts:
                    all_words.extend(p.strip().split())
                
                if all_words:
                    k_total = max(1, int(dur_ms / 10))
                    k_each = k_total // len(all_words)
                    for pi, p in enumerate(parts):
                        p_words = p.strip().split()
                        for wi, w in enumerate(p_words):
                            k_line += f"{{\\k{k_each}}}{w}"
                            if wi < len(p_words) - 1:
                                k_line += " "
                        if pi < len(parts) - 1:
                            k_line += "\\N"

            anim = "{\\fad(100,100)\\fscx0\\fscy0\\t(0,200,\\fscx100\\fscy100)}"
            pos = f"{{\\pos({cx},{y_curr})}}"

            events.append(
                f"Dialogue: 0,{s_fmt},{e_fmt},Karaoke,,0,0,0,,"
                f"{anim}{pos}{k_line.strip()}"
            )

        with open(output_path, "w", encoding="utf-8-sig") as f:
            f.write("\n".join(header) + "\n")
            for line in events:
                f.write(line + "\n")

        logger.info(f"✅ KARAOKE ASS ({len(word_groups)} groups): {output_path}")
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
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logger.info(f"🔥 Subtitles burned: {output_path}")
        return output_path
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg subtitle burn error: {e}")
        logger.error(f"FFmpeg stderr: {e.stderr[:500]}")
        return None
