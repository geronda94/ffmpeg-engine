import os
import logging
import re

logger = logging.getLogger(__name__)

def _clean(word):
    return re.sub(r'[^\w\s]', '', word).lower().strip()

def _hex_to_ass(hex_color):
    hex_color = hex_color.lstrip('#')
    if len(hex_color) == 6:
        r, g, b = hex_color[:2], hex_color[2:4], hex_color[4:6]
        return f"&H00{b}{g}{r}"
    return "&H00FFFFFF"

def _group_words_2line(words, max_chars=18):
    lines = []
    curr_line, curr_len = [], 0
    for w in words:
        if curr_len + len(w) + 1 > max_chars and curr_line:
            lines.append(" ".join(curr_line))
            curr_line, curr_len = [w], len(w)
        else:
            curr_line.append(w)
            curr_len += len(w) + 1
    if curr_line: lines.append(" ".join(curr_line))
    
    groups = []
    for i in range(0, len(lines), 2):
        block = lines[i]
        if i + 1 < len(lines): block += "\\N" + lines[i+1]
        groups.append(block)
    return groups

def generate_ass_from_project(scenes, whisper_segments, output_path, min_start_time=0.0, aligned_words=None, language=""):
    try:
        s_style = {}
        for s in scenes:
            if s.get('subtitle_style'):
                s_style = s['subtitle_style']
                break
        
        # Прямая логика: Primary - это активное слово в караоке, Secondary - неактивный текст
        c_prim = _hex_to_ass(s_style.get('primary_color', '#FF3131'))
        c_sec  = _hex_to_ass(s_style.get('secondary_color', '#FAF9F6'))
        c_outl = _hex_to_ass(s_style.get('outline_color', '#1C1C1C'))
        font_path = str(s_style.get('font_path',''))
        if "Alice" in font_path:
            font_name = "Alice"
        elif "Cormorant" in font_path:
            font_name = "Cormorant Garamond"
        elif "Lora" in font_path:
            font_name = "Lora"
        elif "Inter-Black" in font_path:
            font_name = "Inter Black"
        elif "Inter" in font_path:
            font_name = "Inter Bold"
        elif "Montserrat" in font_path:
            font_name = "Montserrat Bold"
        else:
            font_name = "DejaVu Sans Bold"

        header = [
            "[Script Info]", "ScriptType: v4.00+", "PlayResX: 1080", "PlayResY: 1920", "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            f"Style: Karaoke,{font_name},70,{c_prim},{c_sec},{c_outl},&H00000000,-1,0,0,0,100,100,0,0,1,6,0,2,108,108,420,1",
            "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
        ]

        def fmt(t):
            h, m, s = int(t//3600), int((t%3600)//60), int(t%60)
            ms = int((t%1)*100)
            return f"{h}:{m:02d}:{s:02d}.{ms:02d}"

        all_whisper_words = []
        for s in whisper_segments:
            s_start = float(s['start'])
            if s_start < min_start_time:
                if 'words' in s:
                    for w in s['words']:
                        if float(w['start']) >= min_start_time: all_whisper_words.append(w)
                continue
            
            if 'words' in s and s['words']:
                all_whisper_words.extend(s['words'])
            else:
                words_in_seg = s.get('text', '').strip().split()
                if not words_in_seg: continue
                dur = (float(s['end']) - s_start) / len(words_in_seg)
                for i, w in enumerate(words_in_seg):
                    w_start = s_start + i * dur
                    if w_start >= min_start_time:
                        all_whisper_words.append({'word': w, 'start': w_start, 'end': s_start + (i + 1) * dur})

        if not all_whisper_words: return None

        full_text = " ".join([s.get('text_segment', '') for s in scenes if s.get('allow_montage_effects', True)])
        raw_words = [_clean(w) for w in full_text.split() if _clean(w)]
        
        if len(raw_words) > len(all_whisper_words):
            diff = len(raw_words) - len(all_whisper_words)
            raw_words = raw_words[diff:]

        # Возвращаемся к 18 символам, чтобы текст не раздувался на 3 строки
        groups = _group_words_2line(raw_words, max_chars=18)
        word_groups, aw_cursor = [], 0
        
        for g in groups:
            g_wc = len(g.replace("\\N", " ").split())
            if g_wc == 0: continue
            aw_end = min(aw_cursor + g_wc, len(all_whisper_words))
            if aw_cursor < len(all_whisper_words):
                g_start, g_end = float(all_whisper_words[aw_cursor]["start"]), float(all_whisper_words[max(aw_cursor, aw_end-1)]["end"])
                word_groups.append({'text': g, 'start': g_start, 'end': g_end, 'word_timings': all_whisper_words[aw_cursor:aw_end]})
                aw_cursor = aw_end

        events = []
        for g in word_groups:
            if g['end'] <= g['start']:
                continue
            start, end = g['start'], g['end']
            dur_ms = int((end - start) * 1000)
            anim_ms = min(80, dur_ms // 4)
            tags = f"{{\\fad({anim_ms},{anim_ms})\\pos(540,1500)\\fscx0\\fscy0\\t(0,{anim_ms},\\fscx100\\fscy100)}}"

            k_line, curr_t = "", start
            wt_idx = 0
            parts = g['text'].split("\\N")
            for pi, p in enumerate(parts):
                p_words = p.strip().split()
                for wi, w in enumerate(p_words):
                    if wt_idx < len(g['word_timings']):
                        wd = g['word_timings'][wt_idx]
                        k_dur = int(round((float(wd['end']) - float(wd['start'])) * 100))
                        gap = int(round((float(wd['start']) - curr_t) * 100))
                        if gap > 0: k_line += f"{{\\k{gap}}}"
                        k_line += f"{{\\kf{max(1, k_dur)}}}{w}"
                        curr_t, wt_idx = float(wd['end']), wt_idx + 1
                    else: k_line += w
                    if wi < len(p_words) - 1: k_line += " "
                if pi < len(parts) - 1: k_line += "\\N"

            events.append(f"Dialogue: 0,{fmt(start)},{fmt(end)},Karaoke,,0,0,0,,{tags}{k_line}")

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(header + events))
        return output_path
    except Exception as e:
        logger.error(f"ASS Error: {e}", exc_info=True); return None

def burn_subtitles(video_path, ass_path, output_path):
    try:
        import subprocess
        abs_ass = os.path.abspath(ass_path).replace("\\", "/").replace(":", "\\:")
        cmd = ["ffmpeg", "-y", "-i", video_path, "-vf", f"subtitles='{abs_ass}'", "-c:v", "libx264", "-crf", "23", "-preset", "veryfast", "-c:a", "copy", output_path]
        subprocess.run(cmd, check=True, capture_output=True)
        return output_path
    except Exception as e:
        logger.error(f"Burn error: {e}"); return None
