import os
import logging
from moviepy import VideoFileClip, ImageClip, TextClip, CompositeVideoClip, ColorClip
import moviepy.video.fx as vfx
from core.media_engine import MediaEngine
from core.animation_utils import ease_out_cubic, ease_in_out_cubic, lerp

logger = logging.getLogger(__name__)

FONT_PATH = "assets/fonts/DejaVuSans-Bold.ttf"


def _resolve_font():
    """Находит путь к шрифту для TextClip (Pillow в MoviePy 2.x требует полный путь)."""
    candidates = [
        FONT_PATH,
        # Ubuntu/Debian paths
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        # Arch/Fedora paths
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/liberation-sans/LiberationSans-Bold.ttf"
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    
    # Крайний случай - возвращаем имя, надеясь на ImageMagick (если Pillow не справится)
    logger.warning("No system font path found, falling back to name 'DejaVu-Sans-Bold'")
    return "DejaVu-Sans-Bold"


def _parse_color(hex_color: str) -> tuple:
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 6:
        return (int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16))
    return (255, 255, 255)


def _pos_to_pixels(pos, clip_w, clip_h, screen_w, screen_h):
    if isinstance(pos, (int, float)):
        return (float(pos), float(pos))
    if isinstance(pos, str):
        pos = pos.strip()
        if " " in pos:
            parts = pos.split()
            return (_resolve_axis(parts[0], clip_w, screen_w), _resolve_axis(parts[1], clip_h, screen_h))
        return (_resolve_axis(pos, clip_w, screen_w), _resolve_axis(pos, clip_h, screen_h))
    if isinstance(pos, tuple):
        return (_resolve_axis(pos[0], clip_w, screen_w), _resolve_axis(pos[1], clip_h, screen_h))
    if isinstance(pos, dict):
        x = pos.get('x', 'center')
        y = pos.get('y', 'center')
        return (_resolve_axis(x, clip_w, screen_w), _resolve_axis(y, clip_h, screen_h))
    return ((screen_w - clip_w) / 2, (screen_h - clip_h) / 2)


def _resolve_axis(val, clip_dim, screen_dim):
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        val = val.strip().lower()
        if val == "center":
            return (screen_dim - clip_dim) / 2
        if val == "right" or val == "bottom":
            return screen_dim - clip_dim
        if val == "left" or val == "top":
            return 0
        if val.startswith("h*") or val.startswith("w*") or val.startswith("f*"):
            try:
                return screen_dim * float(val[2:])
            except ValueError:
                pass
        if val.startswith("w-") or val.startswith("h-"):
            try:
                return screen_dim - float(val[2:])
            except ValueError:
                pass
        if val.endswith("%"):
            try:
                return screen_dim * float(val[:-1]) / 100.0
            except ValueError:
                pass
    return (screen_dim - clip_dim) / 2


def _animate_position(clip, animation, duration, end_pos_raw, screen_w, screen_h):
    if not animation:
        return clip
    anim_type = animation.get("type", "")
    anim_dur = animation.get("duration", 0.5)
    easing = animation.get("easing", "ease_out_cubic")

    cw = getattr(clip, 'w', screen_w)
    ch = getattr(clip, 'h', screen_h)

    end_x, end_y = _pos_to_pixels(end_pos_raw, cw, ch, screen_w, screen_h)

    if anim_type == "fade_in":
        return clip.with_effects([vfx.FadeIn(anim_dur)])

    elif anim_type == "fade_in_up":
        start_x = end_x
        # ФИКС: не даём start_y уйти ниже экрана, иначе MoviePy 2.x крашится с negative index mask slice
        start_y = min(float(screen_h), end_y + screen_h * 0.12)
        def _fiu_pos(t):
            if t > anim_dur:
                return (int(end_x), int(end_y))
            p = min(t / anim_dur, 1.0)
            e = ease_out_cubic(p)
            return (int(start_x + (end_x - start_x) * e), int(start_y + (end_y - start_y) * e))
        faded = clip.with_effects([vfx.FadeIn(anim_dur)])
        return faded.with_position(_fiu_pos)

    elif anim_type == "reveal_from_top":
        start_scale = animation.get("start_scale", 1.5)
        end_scale = animation.get("end_scale", 1.0)
        start_x, start_y = end_x, -float(ch * start_scale)
        def _rft_pos(t):
            if t > anim_dur:
                return (int(end_x), int(end_y))
            p = min(t / anim_dur, 1.0)
            e = ease_out_cubic(p)
            return (int(start_x + (end_x - start_x) * e), int(start_y + (end_y - start_y) * e))
        def _rft_scale(t):
            if t > anim_dur:
                return end_scale
            p = min(t / anim_dur, 1.0)
            e = ease_out_cubic(p)
            from core.animation_utils import lerp
            return lerp(start_scale, end_scale, e)
        return clip.with_effects([vfx.Resize(_rft_scale)]).with_position(_rft_pos)

    elif anim_type == "scale_in":
        start_scale = animation.get("start_scale", 0.3)
        def _si_scale(t):
            if t > anim_dur:
                return 1.0
            p = min(t / anim_dur, 1.0)
            e = ease_out_cubic(p) if easing == "ease_out_cubic" else ease_in_out_cubic(p)
            from core.animation_utils import lerp
            return lerp(start_scale, 1.0, e)
        return clip.with_effects([vfx.Resize(_si_scale)])

    elif anim_type == "pulse":
        import math
        freq = animation.get("frequency", 2.5)
        strength = animation.get("strength", 0.08)
        decay = animation.get("decay_rate", 0.3)
        def _pulse_func(t):
            d = math.exp(-t * decay)
            return 1.0 + strength * d * math.sin(t * freq)
        return clip.with_effects([vfx.Resize(_pulse_func)])

    elif anim_type == "zoom_in_out":
        zoom_strength = animation.get("zoom_strength", 0.2)
        def _zoom_func(t):
            if t > duration:
                return 1.0
            p = t / duration
            from core.animation_utils import ease_in_out_cubic, lerp
            e = ease_in_out_cubic(p)
            return lerp(1.0 + zoom_strength, 1.0, e)
        
        zoomed = clip.with_effects([vfx.Resize(_zoom_func)])
        # Регулируем позицию, чтобы зум шел в центр
        def _center_pos(t):
            z = _zoom_func(t)
            return (int(end_x - (cw * z - cw) / 2), int(end_y - (ch * z - ch) / 2))
        return zoomed.with_position(_center_pos)

    if anim_type == "slide_up":
        start_x, start_y = end_x, float(screen_h)
    elif anim_type == "slide_down":
        start_x, start_y = end_x, -float(ch)
    elif anim_type == "slide_left":
        start_x, start_y = float(screen_w), end_y
    elif anim_type == "slide_right":
        start_x, start_y = -float(cw), end_y
    else:
        return clip

    def _pos_func(t):
        if t > anim_dur:
            return (int(end_x), int(end_y))
        p = min(t / anim_dur, 1.0)
        e = ease_out_cubic(p) if easing == "ease_out_cubic" else ease_in_out_cubic(p)
        return (
            int(start_x + (end_x - start_x) * e),
            int(start_y + (end_y - start_y) * e)
        )
    return clip.with_position(_pos_func)


def _apply_animations(clip, layers_anim, duration, end_pos_raw, screen_w, screen_h):
    if not layers_anim:
        return clip
    if isinstance(layers_anim, dict):
        layers_anim = [layers_anim]
    for anim in layers_anim:
        clip = _animate_position(clip, anim, duration, end_pos_raw, screen_w, screen_h)
    return clip


def render_layer(preset_layer: dict, elements: dict, duration: float, width: int, height: int) -> list:
    clips = []
    element_id = preset_layer.get("element")
    layer_type = preset_layer.get("type", "media")

    if layer_type == "media":
        path = elements.get(element_id)
        if path and os.path.exists(path):
            mode = preset_layer.get("mode", "cover")
            effect_list = preset_layer.get("effects", [])
            engine = MediaEngine(width, height)
            clip = engine.process_asset(path, duration, mode=mode, allow_effects=True, effects=effect_list)
        else:
            color_hex = preset_layer.get("fallback_color", "#141419")
            clip = ColorClip(size=(width, height), color=_parse_color(color_hex)).with_duration(duration)

    elif layer_type == "text":
        text_val = elements.get(element_id, preset_layer.get("default", ""))
        if not text_val or str(text_val).strip() == "-":
            return clips  # Пропускаем опциональные пустые элементы
        font_size = preset_layer.get("font_size", 60)
        # ФИКС: MoviePy 2.x принимает color как строку, а не как tuple
        color_str = preset_layer.get("color", "#FFFFFF")
        font = preset_layer.get("font", _resolve_font())
        method = preset_layer.get("method", "caption")
        size_w = int(width * 0.9)
        size_tuple = (size_w, None)

        clip = TextClip(
            text=str(text_val),
            font_size=font_size,
            color=color_str,  # Передаём как hex-строку напрямую
            font=font,
            method=method,
            size=size_tuple
        ).with_duration(duration)

    elif layer_type == "overlay":
        path = elements.get(element_id)
        if path and os.path.exists(path):
            ext = os.path.splitext(path)[1].lower()
            if ext in ['.mp4', '.mov', '.avi', '.mkv']:
                raw = VideoFileClip(path).without_audio().with_duration(duration)
            else:
                raw = ImageClip(path).with_duration(duration)
            if "scale" in preset_layer:
                scale = preset_layer["scale"]
                raw = raw.resized(width=int(raw.w * scale))
            clip = raw
        else:
            return clips

    elif layer_type == "overlay_with_bg":
        path = elements.get(element_id)
        if path and os.path.exists(path):
            ext = os.path.splitext(path)[1].lower()
            if ext in ['.mp4', '.mov', '.avi', '.mkv']:
                raw = VideoFileClip(path).without_audio().with_duration(duration)
            else:
                raw = ImageClip(path).with_duration(duration)
            scale = preset_layer.get("scale", 0.5)
            raw = raw.resized(width=int(width * scale))
            bg_color = _parse_color(preset_layer.get("bg_color", "#000000"))
            bg_opacity = preset_layer.get("bg_opacity", 0.6)
            raw_w, raw_h = raw.w, raw.h
            bg_clip = ColorClip(size=(int(raw_w * 1.15), int(raw_h * 1.15)), color=bg_color).with_opacity(bg_opacity).with_duration(duration)
            comp = CompositeVideoClip([bg_clip, raw.with_position("center")], size=(bg_clip.w, bg_clip.h)).with_duration(duration)
            clip = comp
        else:
            return clips

    elif layer_type == "plate_image":
        path = elements.get(element_id)
        if not path or not os.path.exists(str(path)):
            return clips

        height_pct = preset_layer.get("height_pct", 0.35)
        plate_h = int(height * height_pct)
        raw = ImageClip(str(path)).with_duration(duration)
        clip = raw.resized(width=width, height=plate_h)

    else:
        return clips

    end_pos_raw = preset_layer.get("position", "center")
    animations = preset_layer.get("animations") or preset_layer.get("animation")
    static_pos = preset_layer.get("static", True)

    # ФИКС: проверяем has_slide и для dict, и для list
    SLIDE_TYPES = ("slide_up", "slide_down", "slide_left", "slide_right")
    POSITION_ANIM_TYPES = ("slide_up", "slide_down", "slide_left", "slide_right", "fade_in_up", "reveal_from_top")
    has_slide = False
    has_position_anim = False
    anims_list = animations if isinstance(animations, list) else ([animations] if animations else [])
    for a in anims_list:
        if isinstance(a, dict):
            a_type = a.get("type", "")
            if a_type in SLIDE_TYPES:
                has_slide = True
                has_position_anim = True
            elif a_type in POSITION_ANIM_TYPES:
                has_position_anim = True

    if animations:
        clip = _apply_animations(clip, animations, duration, end_pos_raw, width, height)

    # ФИКС: статическую позицию применяем ТОЛЬКО если нет анимации позиции.
    # Для слайдов и fade_in_up позиция управляется функцией внутри анимации.
    if not has_position_anim and static_pos:
        cw = clip.w if hasattr(clip, 'w') else width
        ch = clip.h if hasattr(clip, 'h') else height
        end_x, end_y = _pos_to_pixels(end_pos_raw, cw, ch, width, height)
        # ФИКС: MoviePy 2.x ломает маску при дробных позициях — всегда целые пиксели
        clip = clip.with_position((int(end_x), int(end_y)))

    clips.append(clip)
    return clips


def render_from_layers(preset: dict, elements: dict, duration: float, output_path: str, video_format: str = "vertical") -> str:
    try:
        if video_format == "horizontal":
            width, height = 1920, 1080
        else:
            width, height = 1080, 1920

        all_clips = []
        layers = preset.get("layers", [])

        for layer_def in layers:
            layer_clips = render_layer(layer_def, elements, duration, width, height)
            all_clips.extend(layer_clips)

        final = CompositeVideoClip(all_clips, size=(width, height))
        final.write_videofile(
            output_path, fps=30, codec="libx264", audio=False,
            threads=4, preset="ultrafast", bitrate="2000k", logger=None
        )
        return output_path

    except Exception as e:
        logger.error(f"Layer Render Error: {e}", exc_info=True)
        return None
