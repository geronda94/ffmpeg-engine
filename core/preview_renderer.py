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
    """
    Создает оверлей превью на весь экран.
    """
    display_dur = duration
    
    # 1. ЦВЕТОВАЯ СХЕМА
    primary_hex = text_color if text_color else "#FFFFFF"
    secondary_hex = secondary_color if secondary_color else "#FFD700"
    bg_hex = bg_color if bg_color else (color_scheme.get("glass_from", "#2C2C2C") if color_scheme else "#2C2C2C")
    
    # Шрифт из конфига или дефолт
    font = custom_font_path if custom_font_path and os.path.exists(custom_font_path) else _resolve_font()
    base_font_size = display_config.get("font_size", 84)
    
    opacity = 0.85
    bg_rgb = _hex_to_rgb(bg_hex)
    
    # 2. ФОН
    bg_clip = ColorClip(size=(frame_width, frame_height), color=bg_rgb)
    bg_clip = bg_clip.with_opacity(opacity).with_duration(duration)
    
    # Добавляем эффект ЗЕРНИСТОСТИ (среднее зерно)
    def _add_grain_effect(get_frame, t):
        frame = get_frame(t)
        h, w = frame.shape[:2]
        # Создаем шум меньшего разрешения для "среднего" зерна
        # h//3 и w//3 дадут зерна размером примерно 3x3 пикселя
        noise_h, noise_w = h // 3, w // 3
        
        # Генерируем шум (диапазон -12..12 для мягкости)
        # Используем фиксированный сид для каждого кадра превью, чтобы зерно было статичным (или менялось медленно)
        rng = np.random.RandomState(int(t * 10) % 100) # Меняем зерно 10 раз в секунду
        noise_small = rng.randint(-14, 14, (noise_h, noise_w, 3), dtype=np.int16)
        
        # Масштабируем шум до размеров кадра через PIL (ближайший сосед даст четкое зерно)
        from PIL import Image as _PILImage
        noise_img = _PILImage.fromarray((noise_small + 14).astype(np.uint8))
        noise_large = np.array(noise_img.resize((w, h), _PILImage.NEAREST)).astype(np.int16) - 14
        
        # Накладываем шум на RGB каналы
        res = frame.copy().astype(np.int16)
        res[..., :3] = np.clip(res[..., :3] + noise_large, 0, 255)
        return res.astype(np.uint8)

    bg_clip = bg_clip.transform(_add_grain_effect)
    all_layers = [bg_clip]

    # 3. ЛОГОТИП
    logo_clip = None
    if logo_path and os.path.exists(logo_path):
        try:
            from PIL import Image as _PILImage
            pil_img = _PILImage.open(logo_path).convert("RGBA")
            img_arr = np.array(pil_img)
            logo_clip = ImageClip(img_arr[:, :, :3]).with_duration(duration)
            mask_arr = img_arr[:, :, 3] / 255.0
            logo_clip.mask = ImageClip(mask_arr, is_mask=True).with_duration(duration)
            
            max_h = int(frame_height * 0.12)
            if logo_clip.h > max_h:
                logo_clip = logo_clip.resized(height=max_h)
        except Exception as e:
            logger.error(f"Logo error: {e}")

    # 4. ТЕКСТ (АЛГОРИТМ ВЕСОВЫХ СТРОК)
    words = preview_text.upper().split()
    lines = []
    curr_line = []
    for w in words:
        if not curr_line:
            curr_line.append(w)
        # Если слово длинное (>8 симв) - в отдельную строку
        elif len(w) > 8:
            lines.append(" ".join(curr_line))
            curr_line = [w]
        # Если в текущей строке уже есть слова и новое слово не супер короткое
        elif len(curr_line) >= 2 or (len(curr_line) == 1 and len(" ".join(curr_line + [w])) > 12):
            lines.append(" ".join(curr_line))
            curr_line = [w]
        else:
            curr_line.append(w)
    if curr_line:
        lines.append(" ".join(curr_line))

    text_clips = []
    target_w = int(frame_width * 0.82)
    max_scale = 1.6
    
    for i, ln in enumerate(lines):
        color = primary_hex if i % 2 == 0 else secondary_hex
        
        # Пробный замер ширины
        temp = TextClip(text=ln, font_size=base_font_size, color=color, font=font, method="label")
        
        # Динамическое масштабирование (max 1.6x)
        scale = min(max_scale, target_w / temp.w) if temp.w > 0 else 1.0
        f_size = int(base_font_size * scale)
        
        # Используем CAPTION с запасом по высоте (1.5x), чтобы буквы не обрезались снизу
        line_h = int(f_size * 1.5)
        tc = TextClip(
            text=ln,
            font_size=f_size,
            color=color,
            font=font,
            method="caption",
            size=(frame_width, line_h),
            text_align="center"
        ).with_duration(duration)
        text_clips.append(tc)

    # 5. КОМПОНОВКА (ПОДНЯТИЕ НА 15%)
    line_spacing = 30 # Уменьшили на 0.75 (было 40)
    total_text_h = sum(c.h for c in text_clips) + (len(text_clips)-1)*line_spacing
    total_text_h += 40
    
    margin = 70
    total_h = total_text_h
    if logo_clip:
        total_h += logo_clip.h + margin
    
    start_y = (frame_height - total_h) // 2
    start_y -= int(frame_height * 0.15)
    
    if start_y < 110: start_y = 110
        
    if logo_clip:
        lx = (frame_width - logo_clip.w) // 2
        lw, lh = logo_clip.w, logo_clip.h
        
        # Анимация пульсации логотипа ОТ ЦЕНТРА
        def logo_pulse(t):
            return 1.0 + 0.03 * np.sin(np.pi * t)
            
        def logo_pos(t):
            s = logo_pulse(t)
            return (lx - (lw*s - lw)/2, start_y - (lh*s - lh)/2)
            
        logo_clip = logo_clip.with_effects([vfx.Resize(logo_pulse)])
        all_layers.append(logo_clip.with_position(logo_pos))
        curr_y = start_y + lh + margin
    else:
        curr_y = start_y

    # Анимация строк текста (поочередный "всплеск" ОТ ЦЕНТРА)
    pop_duration = 0.6
    pop_delay = 0.3
    
    for i, tc in enumerate(text_clips):
        tx = (frame_width - tc.w) // 2
        tw, th = tc.w, tc.h
        start_pop = i * pop_delay
        
        def get_scale(t, st=start_pop):
            if st <= t <= st + pop_duration:
                progress = (t - st) / pop_duration
                return 1.0 + 0.08 * np.sin(np.pi * progress)
            return 1.0
            
        def get_pos(t, st=start_pop, x=tx, y=curr_y, w=tw, h=th):
            s = get_scale(t, st)
            return (x - (w*s - w)/2, y - (h*s - h)/2)
            
        tc_animated = tc.with_effects([vfx.Resize(get_scale)])
        all_layers.append(tc_animated.with_position(get_pos))
        curr_y += th + line_spacing

    # Сборка
    result = CompositeVideoClip(all_layers, size=(frame_width, frame_height)).with_duration(duration)
    return result
    return result
