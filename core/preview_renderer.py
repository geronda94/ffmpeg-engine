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
    from PIL import ImageFilter
    display_dur = duration
    primary_hex = text_color if text_color else "#F5F5DC"
    secondary_hex = secondary_color if secondary_color else "#9B1B30"
    bg_hex = bg_color if bg_color else (color_scheme.get("glass_from", "#2C2C2C") if color_scheme else "#2C2C2C")
    
    # _resolve_font умеет преобразовывать relative → absolute пути
    font = _resolve_font(custom_font_path)
    base_font_size = 110 # База чуть больше
    
    bg_rgb = _hex_to_rgb(bg_hex)
    
    # Вспомогательная функция яркости
    def _get_brightness(rgb):
        return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
        
    p_rgb = _hex_to_rgb(primary_hex)
    s_rgb = _hex_to_rgb(secondary_hex)
    p_bright = _get_brightness(p_rgb)
    s_bright = _get_brightness(s_rgb)
    
    # 1. SMART CONTRAST GUARD: Интеллектуальный выбор темы карты и оптимизация цветов текста
    if p_bright < 130:
        # ТЕМНЫЙ ТЕКСТ -> СВЕТЛАЯ КАРТА (например, для Lifestyle)
        # Принудительно делаем подложку светлой для идеального чтения темного текста
        bg_rgb = (250, 245, 245) if _get_brightness(bg_rgb) < 180 else bg_rgb
        card_alpha = 200 # Высокая плотность (около 80%), чтобы приглушить фоновое видео
        
        # Защита контраста: если вторичный цвет слишком светлый (как #E5A9A9), делаем его темнее и контрастнее (красивый сочный бордово-розовый)
        if s_bright > 130:
            secondary_hex = "#9E4B58" # Благородный глубокий розовый с великолепной читаемостью
    else:
        # СВЕТЛЫЙ ТЕКСТ -> ТЕМНАЯ КАРТА (например, для Православия или IT)
        # Принудительно делаем подложку темной
        bg_rgb = (20, 20, 20) if _get_brightness(bg_rgb) > 100 else bg_rgb
        card_alpha = 145 # Около 57% непрозрачности для мягкого киноэффекта
        
        # Защита контраста: если вторичный цвет слишком темный, переключаем его на читаемый светлый
        if s_bright < 150:
            secondary_hex = "#E5A9A9" # Приятный читаемый пастельно-розовый
            
    # 2. ПОЛУЧЕНИЕ И РАЗМЫТИЕ ПЕРВОГО КАДРА ЗАДНЕГО ПЛАНА
    bg_image = None
    if asset_path and os.path.exists(asset_path):
        try:
            ext = os.path.splitext(asset_path)[1].lower()
            if ext in ['.mp4', '.mov', '.avi', '.mkv']:
                from moviepy import VideoFileClip
                with VideoFileClip(asset_path) as temp_video:
                    frame = temp_video.get_frame(0)
                    bg_image = _PILImage.fromarray(frame)
            else:
                bg_image = _PILImage.open(asset_path).convert("RGBA")
        except Exception as e:
            logger.warning(f"Failed to load backdrop first frame for glass blur: {e}")
            
    if not bg_image:
        # Резервный благородный темный фон, если файл не прочитался
        bg_image = _PILImage.new("RGBA", (frame_width, frame_height), (15, 15, 15, 255))
        
    # Resize and crop to COVER frame_width x frame_height
    iw, ih = bg_image.size
    target_ratio = frame_width / frame_height
    img_ratio = iw / ih
    if img_ratio > target_ratio:
        new_h = frame_height
        new_w = int(iw * (frame_height / ih))
        bg_resized = bg_image.resize((new_w, new_h), _PILImage.Resampling.LANCZOS)
        x_offset = (new_w - frame_width) // 2
        bg_cropped = bg_resized.crop((x_offset, 0, x_offset + frame_width, frame_height))
    else:
        new_w = frame_width
        new_h = int(ih * (frame_width / iw))
        bg_resized = bg_image.resize((new_w, new_h), _PILImage.Resampling.LANCZOS)
        y_offset = (new_h - frame_height) // 2
        bg_cropped = bg_resized.crop((0, y_offset, frame_width, y_offset + frame_height))
        
    # Размываем фоновое изображение
    blurred_bg = bg_cropped.filter(ImageFilter.GaussianBlur(radius=25))
    
    # 3. ПОДГОТОВКА ЛОГОТИПА И СТРОК ТЕКСТА
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
        color = primary_hex if i % 2 == 0 else secondary_hex
        temp = TextClip(text=ln, font_size=base_font_size, color=color, font=font, method="label")
        scale = min(max_scale, target_w / temp.w) if temp.w > 0 else 1.0
        f_size = int(base_font_size * scale)
        line_h = int(f_size * 1.28) # Даем больше воздуха по вертикали внутри контейнера строки
        tc = TextClip(text=ln, font_size=f_size, color=color, font=font, method="caption", size=(frame_width, line_h), text_align="center").with_duration(duration)
        text_clips.append(tc)

    line_spacing = 25  # Щедрый положительный интервал для отличной читаемости и воздуха
    total_text_h = sum(c.h for c in text_clips) + (len(text_clips)-1)*line_spacing
    margin = 45
    total_h = total_text_h
    if logo_clip: total_h += logo_clip.h + margin
    
    start_y = (frame_height - total_h) // 2 - int(frame_height * 0.05)
    if start_y < 110: start_y = 110
    
    # 4. ВЫЧИСЛЕНИЕ ГРАНИЦ И СОЗДАНИЕ СТЕКЛЯННОЙ КАРТОЧКИ
    card_w = int(frame_width * 0.94)
    card_h = total_h + 100
    card_x = (frame_width - card_w) // 2
    card_y = start_y - 50
    radius = 36
    
    # Вырезаем размытую область из подготовленного фона
    sub_img = blurred_bg.crop((card_x, card_y, card_x + card_w, card_y + card_h)).convert("RGBA")
    
    # Накладываем цвет подложки с нужной непрозрачностью
    color_layer = _PILImage.new("RGBA", sub_img.size, bg_rgb + (card_alpha,))
    sub_img = _PILImage.alpha_composite(sub_img, color_layer)
    
    # Скругляем углы с помощью альфа-маски
    mask = _PILImage.new('L', sub_img.size, 0)
    draw_mask = ImageDraw.Draw(mask)
    draw_mask.rounded_rectangle([(0, 0), (card_w - 1, card_h - 1)], radius=radius, fill=255)
    
    rounded_sub = _PILImage.new("RGBA", sub_img.size, (0, 0, 0, 0))
    rounded_sub.paste(sub_img, (0, 0), mask)
    
    # Добавляем благородную тонкую светлую рамку с альфой 60 (эффект грани стекла)
    draw_border = ImageDraw.Draw(rounded_sub)
    draw_border.rounded_rectangle([(0, 0), (card_w - 1, card_h - 1)], radius=radius, outline=(255, 255, 255, 60), width=2)
    
    # Размещаем готовую карточку на полноразмерном прозрачном холсте
    canvas = _PILImage.new("RGBA", (frame_width, frame_height), (0, 0, 0, 0))
    canvas.paste(rounded_sub, (card_x, card_y))
    
    # Создаем ImageClip для стеклянной подложки
    canvas_arr = np.array(canvas)
    card_clip = ImageClip(canvas_arr[:, :, :3]).with_duration(duration)
    card_clip.mask = ImageClip(canvas_arr[:, :, 3] / 255.0, is_mask=True).with_duration(duration)
    card_clip = card_clip.with_position((0, 0))
    
    all_layers = [card_clip]
        
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

    # Пользователь попросил убрать затухание (FadeIn), чтобы превью было с первой миллисекунды (для обложек)
    fade_duration = 0 # Жестко отключаем фейд-ин
    pop_duration, pop_delay = 0.6, 0.2
    for i, tc in enumerate(text_clips):
        tx, tw, th = (frame_width - tc.w) // 2, tc.w, tc.h
        st = i * pop_delay
        
        # Фиксируем текущий Y для конкретной строки (исправление closure bug)
        line_y = curr_y
        
        def make_scale_fn(start_offset):
            def get_scale(t):
                if start_offset <= t <= start_offset + pop_duration:
                    p = (t - start_offset) / pop_duration
                    return 1.0 + 0.08 * np.sin(np.pi * p)
                return 1.0
            return get_scale
            
        def make_pos_fn(start_offset, x, y, w, h, s_fn):
            def get_pos(t):
                s = s_fn(t)
                return (x - (w*s - w)/2, y - (h*s - h)/2)
            return get_pos
            
        line_scale_fn = make_scale_fn(st)
        line_pos_fn = make_pos_fn(st, tx, line_y, tw, th, line_scale_fn)
        
        # Применяем эффекты
        line_clip = tc.with_effects([vfx.Resize(line_scale_fn)]).with_position(line_pos_fn)
        if fade_duration > 0:
            line_clip = line_clip.with_effects([vfx.FadeIn(fade_duration)])
            
        all_layers.append(line_clip)
        curr_y += th + line_spacing

    final_overlay = CompositeVideoClip(all_layers, size=(frame_width, frame_height)).with_duration(duration)
    if fade_duration > 0:
        final_overlay = final_overlay.with_effects([vfx.FadeIn(fade_duration)])
        
    return final_overlay
