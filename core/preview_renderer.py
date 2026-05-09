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
                           color_scheme=None, duration=3.0):
    glass_cfg = display_config.get("glass", {})
    grad_cfg = glass_cfg.get("gradient", {})
    pad_x = glass_cfg.get("padding_x", 36)
    pad_y = glass_cfg.get("padding_y", 26)
    x_offset_pct = display_config.get("position", {}).get("x_offset_pct", 0.08)
    width_max_pct = display_config.get("position", {}).get("width_max_pct", 0.72)
    corner_radius = glass_cfg.get("corner_radius", 14)
    grain_strength = glass_cfg.get("grain_strength", 8)
    border_width = glass_cfg.get("border_width", 0)
    border_opacity = glass_cfg.get("border_opacity", 0.15)
    anim_dur = display_config.get("animation", {}).get("duration", 0.6)
    display_dur = display_config.get("display_duration", 3.0)
    font = _resolve_font()
    font_size = display_config.get("font_size", 68)

    if color_scheme:
        primary_hex = color_scheme.get("text_primary", display_config.get("text_colors", {}).get("fallback_primary", "#F5F0E8"))
        accent_hex = color_scheme.get("text_accent", display_config.get("text_colors", {}).get("fallback_accent", "#D4A843"))
        glass_from_hex = color_scheme.get("glass_from", grad_cfg.get("fallback_from", "#2A1F35"))
        glass_to_hex = color_scheme.get("glass_to", grad_cfg.get("fallback_to", "#1A1220"))
        glass_opacity = color_scheme.get("opacity", glass_cfg.get("opacity", 0.30))
    else:
        fallback_colors = display_config.get("text_colors", {})
        primary_hex = fallback_colors.get("fallback_primary", "#F5F0E8")
        accent_hex = fallback_colors.get("fallback_accent", "#D4A843")
        glass_from_hex = grad_cfg.get("fallback_from", "#2A1F35")
        glass_to_hex = grad_cfg.get("fallback_to", "#1A1220")
        glass_opacity = glass_cfg.get("opacity", 0.30)

    before_word, hl_word, after_word = _split_preview_text(preview_text, highlight_word)
    max_text_w = int(frame_width * width_max_pct - 2 * pad_x)
    size_tuple = (max_text_w, None)

    text_segments = []
    if before_word:
        text_segments.append((before_word.strip(), primary_hex))
    if hl_word:
        text_segments.append((hl_word.strip(), accent_hex))
    if after_word:
        text_segments.append((after_word.strip(), primary_hex))

    all_text_clips = []
    total_text_h = 0
    for txt, col in text_segments:
        tc = TextClip(text=txt, font_size=font_size, color=col,
                      font=font, method="caption", size=size_tuple)
        all_text_clips.append(tc)
        total_text_h += getattr(tc, 'h', font_size + 4) + 4

    glass_w = int(frame_width * width_max_pct)
    glass_h = total_text_h + 2 * pad_y
    x_pos = int(frame_width * x_offset_pct)
    y_pos = (frame_height - glass_h) // 2

    glass_from_rgb = _hex_to_rgb(glass_from_hex)
    glass_to_rgb = _hex_to_rgb(glass_to_hex)

    gradient_arr = _create_gradient_texture(glass_w, glass_h, glass_from_rgb, glass_to_rgb)
    gradient_clip = ImageClip(gradient_arr, is_mask=False).with_opacity(glass_opacity).with_duration(display_dur)

    glass = gradient_clip

    if corner_radius > 0:
        mask_arr = _create_rounded_corner_mask(glass_w, glass_h, corner_radius)
        mask_clip = ImageClip(mask_arr, is_mask=True).with_duration(display_dur)
        glass = glass.with_mask(mask_clip)

    if grain_strength > 0:
        np.random.seed(int(os.path.getmtime(asset_path)) if os.path.exists(asset_path) else 42)
        noise = np.random.randint(-grain_strength, grain_strength + 1, (glass_h, glass_w, 3), dtype=np.int16)
        grain_arr = np.clip(np.zeros((glass_h, glass_w, 3), dtype=np.int16) + noise, 0, 255).astype(np.uint8)
        grain_arr_rgba = np.zeros((glass_h, glass_w, 4), dtype=np.uint8)
        grain_arr_rgba[:, :, :3] = grain_arr
        grain_arr_rgba[:, :, 3] = 60
        grain_clip = ImageClip(grain_arr_rgba, is_mask=False).with_duration(display_dur)
        glass = CompositeVideoClip([glass, grain_clip], size=(glass_w, glass_h))

    if border_width > 0:
        border_mask = _PILImage.new('L', (glass_w, glass_h), 0)
        bd = ImageDraw.Draw(border_mask)
        bd.rounded_rectangle([(0, 0), (glass_w - 1, glass_h - 1)],
                              radius=corner_radius, outline=255, width=border_width)
        border_arr = np.zeros((glass_h, glass_w, 4), dtype=np.uint8)
        border_rgb = _hex_to_rgb(accent_hex)
        for i in range(3):
            border_arr[:, :, i] = border_rgb[i]
        border_arr[:, :, 3] = (np.array(border_mask, dtype=np.float64) * border_opacity * 255).astype(np.uint8)
        border_clip = ImageClip(border_arr, is_mask=False).with_duration(display_dur)
        glass = CompositeVideoClip([glass, border_clip], size=(glass_w, glass_h))

    glass = glass.with_position((x_pos, y_pos))

    all_clips = [glass]
    text_y = y_pos + pad_y
    for tc in all_text_clips:
        t_h = getattr(tc, 'h', font_size + 4)
        positioned = tc.with_position((x_pos + pad_x, text_y)).with_duration(display_dur)
        all_clips.append(positioned)
        text_y += t_h + 4

    result = CompositeVideoClip(all_clips, size=(frame_width, frame_height)).with_duration(display_dur)
    result = result.with_effects([vfx.FadeIn(anim_dur)])
    return result
