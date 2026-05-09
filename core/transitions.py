import math
import logging
import numpy as np
from moviepy import VideoClip, ColorClip
import moviepy.video.fx as vfx
from core.animation_utils import ease_out_cubic, ease_in_out_cubic, lerp

logger = logging.getLogger(__name__)

TRANSITIONS = {}


def register(name):
    def decorator(fn):
        TRANSITIONS[name] = fn
        logger.debug(f"Registered transition: {name}")
        return fn
    return decorator


def apply(clip, trans_cfg, is_first, engine_w, engine_h):
    if is_first:
        return clip
    trans_type = trans_cfg.get("type", "crossfade") if isinstance(trans_cfg, dict) else "crossfade"
    trans_fn = TRANSITIONS.get(trans_type)
    if trans_fn:
        try:
            return trans_fn(clip, trans_cfg, engine_w, engine_h)
        except Exception as e:
            logger.error(f"Transition '{trans_type}' failed: {e}", exc_info=True)
            return clip
    logger.warning(f"Unknown transition: {trans_type}. Skipping.")
    return clip


@register("crossfade")
def trans_crossfade(clip, trans_cfg, engine_w, engine_h):
    duration = trans_cfg.get("duration", 0.5)
    if duration <= 0:
        return clip
    return clip.with_effects([vfx.CrossFadeIn(duration)])


@register("fade_black")
def trans_fade_black(clip, trans_cfg, engine_w, engine_h):
    duration = trans_cfg.get("duration", 0.5)
    if duration <= 0:
        return clip
    return clip.with_effects([vfx.FadeIn(duration)])


@register("blur_dissolve")
def trans_blur_dissolve(clip, trans_cfg, engine_w, engine_h):
    duration = trans_cfg.get("duration", 0.6)
    iterations = trans_cfg.get("blur_iterations", 3)
    if duration <= 0:
        return clip

    def _blur_tfm(get_frame, t):
        frame = get_frame(t)
        if t > duration:
            return frame
        progress = t / duration
        blur_radius = int(progress * iterations * 2)
        if blur_radius < 1:
            return frame
        from PIL import Image, ImageFilter
        img = Image.fromarray(frame)
        blurred = img.filter(ImageFilter.GaussianBlur(radius=blur_radius))
        return np.array(blurred, dtype=np.uint8)

    return clip.transform(_blur_tfm).with_effects([vfx.FadeIn(duration)])


@register("slide_left")
def trans_slide_left(clip, trans_cfg, engine_w, engine_h):
    duration = trans_cfg.get("duration", 0.4)
    if duration <= 0:
        return clip
    cx = (engine_w - clip.w) / 2
    cy = (engine_h - clip.h) / 2

    def _pos(t):
        if t > duration:
            return (cx, cy)
        frac = 1 - t / duration
        eased = ease_out_cubic(1 - frac)
        return (lerp(engine_w, cx, eased), cy)

    return clip.with_position(_pos)


@register("slide_right")
def trans_slide_right(clip, trans_cfg, engine_w, engine_h):
    duration = trans_cfg.get("duration", 0.4)
    if duration <= 0:
        return clip
    cx = (engine_w - clip.w) / 2
    cy = (engine_h - clip.h) / 2

    def _pos(t):
        if t > duration:
            return (cx, cy)
        frac = 1 - t / duration
        eased = ease_out_cubic(1 - frac)
        return (lerp(-clip.w, cx, eased), cy)

    return clip.with_position(_pos)


@register("slide_up")
def trans_slide_up(clip, trans_cfg, engine_w, engine_h):
    duration = trans_cfg.get("duration", 0.4)
    if duration <= 0:
        return clip
    cx = (engine_w - clip.w) / 2
    cy = (engine_h - clip.h) / 2

    def _pos(t):
        if t > duration:
            return (cx, cy)
        frac = 1 - t / duration
        eased = ease_out_cubic(1 - frac)
        return (cx, lerp(engine_h, cy, eased))

    return clip.with_position(_pos)


@register("slide_down")
def trans_slide_down(clip, trans_cfg, engine_w, engine_h):
    duration = trans_cfg.get("duration", 0.4)
    if duration <= 0:
        return clip
    cx = (engine_w - clip.w) / 2
    cy = (engine_h - clip.h) / 2

    def _pos(t):
        if t > duration:
            return (cx, cy)
        frac = 1 - t / duration
        eased = ease_out_cubic(1 - frac)
        return (cx, lerp(-clip.h, cy, eased))

    return clip.with_position(_pos)


@register("zoom_in_out")
def trans_zoom_in_out(clip, trans_cfg, engine_w, engine_h):
    duration = trans_cfg.get("duration", 0.5)
    zoom_strength = trans_cfg.get("zoom_strength", 0.4)
    if duration <= 0:
        return clip
    orig_w, orig_h = clip.w, clip.h

    def _zoom_func(t):
        if t > duration:
            return 1.0
        frac = t / duration
        eased = ease_in_out_cubic(frac)
        return lerp(1.0 + zoom_strength, 1.0, eased)

    zoomed = clip.with_effects([vfx.Resize(_zoom_func)])

    def _center_pos(t):
        z = _zoom_func(t)
        return (-orig_w * (z - 1.0) / 2, -orig_h * (z - 1.0) / 2)

    return zoomed.with_position(_center_pos)


@register("glitch_transition")
def trans_glitch(clip, trans_cfg, engine_w, engine_h):
    duration = trans_cfg.get("duration", 0.35)
    intensity = trans_cfg.get("intensity", 0.6)
    if duration <= 0:
        return clip

    def _glitch_tfm(get_frame, t):
        frame = get_frame(t)
        if t > duration:
            return frame
        h, w = frame.shape[:2]
        progress = t / duration
        amp = intensity * (1 - progress) * 10
        offset = max(1, int(amp))
        if offset >= w:
            return frame

        result = frame.astype(np.float32)
        r, g, b = result[..., 0].copy(), result[..., 1].copy(), result[..., 2].copy()
        result[:, offset:, 0] = r[:, :w-offset]
        result[:, :w-offset, 2] = b[:, offset:]
        return np.clip(result, 0, 255).astype(np.uint8)

    return clip.transform(_glitch_tfm).with_effects([vfx.FadeIn(duration * 0.5)])


@register("whip_pan")
def trans_whip_pan(clip, trans_cfg, engine_w, engine_h):
    duration = trans_cfg.get("duration", 0.3)
    direction = trans_cfg.get("direction", "left")
    blur_intensity = trans_cfg.get("blur_intensity", 20)
    if duration <= 0:
        return clip

    cx = (engine_w - clip.w) / 2
    cy = (engine_h - clip.h) / 2
    sign = -1 if direction == "left" else 1

    def _whip_pos(t):
        if t > duration:
            return (cx, cy)
        frac = t / duration
        eased = ease_out_cubic(frac)
        offset = sign * engine_w * (1 - eased)
        return (cx + int(offset), cy)

    def _whip_blur(get_frame, t):
        frame = get_frame(t)
        if t > duration * 0.7:
            return frame
        progress = t / duration
        b = int(blur_intensity * (1 - progress * 1.4) / 4)
        if b < 1:
            return frame
        from PIL import Image, ImageFilter
        img = Image.fromarray(frame)
        blurred = img.filter(ImageFilter.GaussianBlur(radius=b))
        return np.array(blurred, dtype=np.uint8)

    return clip.transform(_whip_blur).with_position(_whip_pos)
