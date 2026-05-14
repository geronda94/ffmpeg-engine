import os
import re
import logging
import numpy as np
from PIL import Image as _PILImage, ImageDraw
from moviepy import ImageClip, TextClip, ColorClip, CompositeVideoClip
import moviepy.video.fx as vfx
from core.layer_renderer import _resolve_font

logger = logging.getLogger(__name__)


def _split_preview_text(text, highlight_word):
    if not highlight_word:
        return "", text, ""
    pattern = re.escape(highlight_word)
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        start, end = match.start(), match.end()
        before = text[:start]
        hl = text[start:end]
        after = text[end:]
        return before, hl, after
    return "", text, ""


def _balance_lines(text):
    """
    Разбивает текст на 1, 2 или 3 строки для идеального баланса.
    """
    words = text.upper().split()
    count = len(words)
    
    if count <= 1:
        return [text.upper()]
    if count == 3:
        # Для 3 слов — каждое на своей строке (как просил пользователь)
        return [words[0], words[1], words[2]]
    if count == 2:
        return [words[0], words[1]]
    
    # Для 4 и более слов — балансируем по количеству символов на 2 или 3 строки
    num_lines = 3 if count >= 5 else 2
    
    if num_lines == 2:
        best_diff = float('inf')
        best_split = []
        for i in range(1, count):
            l1, l2 = " ".join(words[:i]), " ".join(words[i:])
            diff = abs(len(l1) - len(l2))
            if diff < best_diff:
                best_diff = diff
                best_split = [l1, l2]
        return best_split
    else:
        # Для 3 строк — грубое деление на трети
        t1, t2 = count // 3, 2 * count // 3
        return [" ".join(words[:t1]), " ".join(words[t1:t2]), " ".join(words[t2:])]


def _create_gradient_texture(w, h, color_from, color_to):
    cfrom = tuple(int(color_from[i]) for i in range(3))
    cto = tuple(int(color_to[i]) for i in range(3))
    Y, X = np.meshgrid(np.linspace(0, 1, h), np.linspace(0, 1, w), indexing='ij')
    ratio = (X + Y) / 2
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    for i in range(3):
        arr[:, :, i] = (cfrom[i] * (1 - ratio) + cto[i] * ratio).astype(np.uint8)
    arr[:, :, 3] = 255
    return arr


def _create_rounded_corner_mask(w, h, radius):
    mask = _PILImage.new('L', (w, h), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([(0, 0), (w - 1, h - 1)], radius=radius, fill=255)
    return np.array(mask, dtype=np.float64) / 255.0


def _hex_to_rgb(hex_str):
    h = hex_str.lstrip('#')
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def create_preview_overlay(asset_path, preview_text, highlight_word,
                           display_config, frame_width, frame_height,
                           color_scheme=None, duration=3.0,
                           logo_path=None, bg_color=None, text_color=None,
                           secondary_color=None, custom_font_path=None):
    display_dur = duration
    primary_hex = text_color if text_color else "#F5F5DC"
    secondary_hex = secondary_color if secondary_color else "#9B1B30"
    bg_hex = bg_color if bg_color else (color_scheme.get("glass_from", "#2C2C2C") if color_scheme else "#2C2C2C")
    
    font = custom_font_path if custom_font_path and os.path.exists(custom_font_path) else _resolve_font()
    base_font_size = 110 # База чуть больше
    
    bg_rgb = _hex_to_rgb(bg_hex)
    bg_clip = ColorClip(size=(frame_width, frame_height), color=bg_rgb).with_opacity(0.42).with_duration(duration)
    
    def _add_grain_effect(get_frame, t):
        frame = get_frame(t)
        h, w = frame.shape[:2]
        noise_h, noise_w = h // 3, w // 3
        rng = np.random.RandomState(int(t * 10) % 100)
        noise_small = rng.randint(-14, 14, (noise_h, noise_w, 3), dtype=np.int16)
        from PIL import Image as _PILImage
        noise_img = _PILImage.fromarray((noise_small + 14).astype(np.uint8))
        noise_large = np.array(noise_img.resize((w, h), _PILImage.NEAREST)).astype(np.int16) - 14
        res = frame.copy().astype(np.int16)
        res[..., :3] = np.clip(res[..., :3] + noise_large, 0, 255)
        return res.astype(np.uint8)

    bg_clip = bg_clip.transform(_add_grain_effect)
    all_layers = [bg_clip]

    logo_clip = None
    if logo_path and os.path.exists(logo_path):
        try:
            pil_img = _PILImage.open(logo_path).convert("RGBA")
            img_arr = np.array(pil_img)
            logo_clip = ImageClip(img_arr[:, :, :3]).with_duration(duration)
            mask_arr = img_arr[:, :, 3] / 255.0
            logo_clip.mask = ImageClip(mask_arr, is_mask=True).with_duration(duration)
            max_h = int(frame_height * 0.12)
            if logo_clip.h > max_h: logo_clip = logo_clip.resized(height=max_h)
        except Exception as e: logger.error(f"Logo error: {e}")

    lines = _balance_lines(preview_text)
    text_clips = []
    target_w = int(frame_width * 0.88)
    max_scale = 1.8 # Ограничили, чтобы слова не были гигантскими
    
    for i, ln in enumerate(lines):
        # Чередуем цвета: 1-я слоновая кость, 2-я багряная, 3-я слоновая кость
        color = primary_hex if i % 2 == 0 else secondary_hex
        temp = TextClip(text=ln, font_size=base_font_size, color=color, font=font, method="label")
        scale = min(max_scale, target_w / temp.w) if temp.w > 0 else 1.0
        f_size = int(base_font_size * scale)
        line_h = int(f_size * 1.15)
        tc = TextClip(text=ln, font_size=f_size, color=color, font=font, method="caption", size=(frame_width, line_h), text_align="center").with_duration(duration)
        text_clips.append(tc)

    line_spacing = 5 # Еще плотнее
    total_text_h = sum(c.h for c in text_clips) + (len(text_clips)-1)*line_spacing
    margin = 40
    total_h = total_text_h
    if logo_clip: total_h += logo_clip.h + margin
    
    start_y = (frame_height - total_h) // 2 - int(frame_height * 0.12)
    if start_y < 110: start_y = 110
        
    if logo_clip:
        lx, lw, lh = (frame_width - logo_clip.w) // 2, logo_clip.w, logo_clip.h
        def logo_pulse(t): return 1.0 + 0.03 * np.sin(np.pi * t)
        def logo_pos(t):
            s = logo_pulse(t)
            return (lx - (lw*s - lw)/2, start_y - (lh*s - lh)/2)
        logo_clip = logo_clip.with_effects([vfx.Resize(logo_pulse)])
        all_layers.append(logo_clip.with_position(logo_pos))
        curr_y = start_y + lh + margin
    else: curr_y = start_y

    pop_duration, pop_delay = 0.6, 0.2
    for i, tc in enumerate(text_clips):
        tx, tw, th = (frame_width - tc.w) // 2, tc.w, tc.h
        st = i * pop_delay
        def get_scale(t, st=st):
            if st <= t <= st + pop_duration:
                p = (t - st) / pop_duration
                return 1.0 + 0.08 * np.sin(np.pi * p)
            return 1.0
        def get_pos(t, st=st, x=tx, y=curr_y, w=tw, h=th):
            s = get_scale(t, st)
            return (x - (w*s - w)/2, y - (h*s - h)/2)
        all_layers.append(tc.with_effects([vfx.Resize(get_scale)]).with_position(get_pos))
        curr_y += th + line_spacing

    return CompositeVideoClip(all_layers, size=(frame_width, frame_height)).with_duration(duration)
