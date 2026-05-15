import os
import logging
import re

logger = logging.getLogger(__name__)

def _clean(word):
    return re.sub(r'[^\w\s]', '', word).lower().strip()

def _clean_display(word):
    """Очищает слово от знаков препинания, но сохраняет регистр (CAPS)."""
    # Убираем только явный пунктуационный шум, не трогая буквы и цифры
    return re.sub(r'[",.«»"\'\(\)\[\]!?;:]', '', word).strip()

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

        # Собираем ВСЕ слова, включая те что до min_start_time.
        # Ранние слова помечаем флагом invisible=True, чтобы не сдвигать курсор по тексту.
        all_whisper_words = []
        for s in whisper_segments:
            s_start = float(s['start'])
            if 'words' in s and s['words']:
                for w in s['words']:
                    word = dict(w)
                    word['invisible'] = float(word['end']) <= min_start_time
                    all_whisper_words.append(word)
            else:
                words_in_seg = s.get('text', '').strip().split()
                if not words_in_seg: continue
                dur = (float(s['end']) - s_start) / len(words_in_seg)
                for i, w in enumerate(words_in_seg):
                    w_start = s_start + i * dur
                    w_end = s_start + (i + 1) * dur
                    all_whisper_words.append({
                        'word': w, 'start': w_start, 'end': w_end,
                        'invisible': w_end <= min_start_time
                    })

        if not all_whisper_words: return None

        word_groups = []
        for scene in scenes:
            if not scene.get('allow_montage_effects', True):
                continue
            
            s_text = scene.get('text_segment', '').strip()
            if not s_text: continue
            
            s_start = float(scene.get('start', 0.0))
            s_end = float(scene.get('end', 0.0))
            
            # Используем слова, предварительно выровненные через LLM (в timing_agent)
            if 'words' in scene and scene['words']:
                scene_whisper_words = scene['words']
            else:
                # Берем слова Whisper, которые попадают в интервал этой сцены.
                scene_whisper_words = [
                    w for w in all_whisper_words 
                    if w['start'] >= s_start - 0.1 and w['start'] < s_end + 0.1
                ]
            
            if not scene_whisper_words:
                # Если Whisper ничего не нашел для этой сцены (тишина?), создаем пустую заглушку
                # или просто пропускаем, но лучше распределить пропорционально если текст есть.
                raw_words = s_text.split()
                dur = (s_end - s_start) / len(raw_words) if raw_words else 1.0
                for i, rw in enumerate(raw_words):
                    scene_whisper_words.append({
                        'word': rw, 'start': s_start + i * dur, 'end': s_start + (i + 1) * dur,
                        'invisible': s_start + (i+1)*dur <= min_start_time
                    })

            # Разбиваем текст конкретной сцены на группы (обычно 1-2 группы на сцену)
            raw_scene_words = s_text.split()
            groups = _group_words_2line(raw_scene_words, max_chars=18)
            
            sw_cursor = 0
            for g in groups:
                g_words = g.replace("\\N", " ").split()
                g_wc = len(g_words)
                if g_wc == 0: continue
                
                # Мапим слова группы на доступные слова Whisper в этой сцене.
                # ФИКС: Если слова в Whisper закончились, но группы еще есть — интерполируем по времени сцены.
                if sw_cursor < len(scene_whisper_words):
                    sw_end = min(sw_cursor + g_wc, len(scene_whisper_words))
                    g_start_t = float(scene_whisper_words[sw_cursor]["start"])
                    g_end_t = float(scene_whisper_words[max(sw_cursor, sw_end-1)]["end"])
                    g_timings = scene_whisper_words[sw_cursor:sw_end]
                    sw_cursor = sw_end
                else:
                    # Интерполяция для "лишних" слов сценария, которых нет в Whisper
                    g_start_t = s_end - 0.2
                    g_end_t = s_end
                    g_timings = [] # Будут отображаться как статический текст в конце
                    
                word_groups.append({
                    'text': g, 'start': g_start_t, 'end': g_end_t,
                    'word_timings': g_timings
                })

        if not word_groups: return None

        # --- АЛГОРИТМ ШЛИФОВКИ ТАЙМИНГОВ ---
        # Устраняем наслоения и добавляем зазор для анимации (0.08с)
        GAP = 0.08
        for i in range(len(word_groups) - 1):
            curr, nxt = word_groups[i], word_groups[i+1]
            if curr['end'] > nxt['start'] - GAP:
                # Сжимаем текущий, чтобы дать место следующему
                new_end = nxt['start'] - GAP
                if new_end > curr['start'] + 0.1:
                    curr['end'] = new_end
                else:
                    # Если места совсем нет, чуть-чуть двигаем начало следующего
                    curr['end'] = curr['start'] + 0.1
                    nxt['start'] = curr['end'] + GAP

        events = []
        for g in word_groups:
            if g['end'] <= g['start']:
                continue
            start, end = g['start'], g['end']
            dur_ms = int((end - start) * 1000)
            anim_ms = min(80, dur_ms // 4)

            # Высчитываем, сколько миллисекунд от начала группы длится превью
            reveal_ms = int((min_start_time - start) * 1000)

            if reveal_ms >= dur_ms:
                # Вся группа попадает под превью — держим размер нулевым
                tags = f"{{\\pos(540,1500)\\fscx0\\fscy0}}"
            elif reveal_ms > 0:
                # Группа начинается под превью, а заканчивается после.
                # Ждём reveal_ms с нулевым размером, потом делаем pop-анимацию!
                # Используем fade-out (0, anim_ms) чтобы в конце субтитр плавно исчез.
                tags = f"{{\\fad(0,{anim_ms})\\pos(540,1500)\\fscx0\\fscy0\\t({reveal_ms},{reveal_ms+anim_ms},\\fscx100\\fscy100)}}"
            else:
                # Обычная группа после превью
                tags = f"{{\\fad({anim_ms},{anim_ms})\\pos(540,1500)\\fscx0\\fscy0\\t(0,{anim_ms},\\fscx100\\fscy100)}}"

            k_line, curr_t = "", start
            wt_idx = 0
            parts = g['text'].split("\\N")
            for pi, p in enumerate(parts):
                p_words = p.strip().split()
                for wi, w in enumerate(p_words):
                    if wt_idx < len(g['word_timings']):
                        wd = g['word_timings'][wt_idx]
                        # Используем очищенное слово, сохраняя регистр
                        display_word = _clean_display(wd.get('word', w))
                        k_dur = int(round((float(wd['end']) - float(wd['start'])) * 100))
                        gap = int(round((float(wd['start']) - curr_t) * 100))
                        if gap > 0: k_line += f"{{\\k{gap}}}"
                        k_line += f"{{\\kf{max(1, k_dur)}}}{display_word}"
                        curr_t, wt_idx = float(wd['end']), wt_idx + 1
                    else:
                        k_line += _clean_display(w)
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
