import math
import numpy as np
import logging
from PIL import Image as _PILImage
from moviepy import VideoFileClip, ImageClip, ColorClip, CompositeVideoClip, VideoClip
import moviepy.video.fx as vfx
from core.animation_utils import (
    ken_burns_zoom, ease_out_cubic, ease_in_out_cubic,
    lerp, parallax_pan_x, smooth_pulse_lum, clamp
)

logger = logging.getLogger(__name__)

OVERLAY_EFFECTS = {}
CONTENT_EFFECTS = {}


def register(name, category="content"):
    def decorator(fn):
        if category == "overlay":
            OVERLAY_EFFECTS[name] = fn
            logger.debug(f"Registered overlay effect: {name}")
        else:
            CONTENT_EFFECTS[name] = fn
            logger.debug(f"Registered content effect: {name}")
        return fn
    return decorator


# ═══════════════════════════════════════════════
#  ХЕЛПЕРЫ
# ═══════════════════════════════════════════════

def _prepare_params(effect_cfg):
    if isinstance(effect_cfg, str):
        return {}
    return effect_cfg


def _make_kb_frame(src_clip, bw, bh, ow, oh, dur, zf, zt, sf, ef, is_mask=False):
    def _frame(t):
        z = ken_burns_zoom(t, dur, zf, zt, sf, ef)
        new_w = max(1, int(ow * z))
        new_h = max(1, int(oh * z))
        if is_mask:
            raw = src_clip.get_frame(t)
            if raw.ndim == 3:
                raw = raw[..., 0]
            img = _PILImage.fromarray((raw * 255).astype(np.uint8), mode="L")
            scaled = np.array(img.resize((new_w, new_h), _PILImage.BILINEAR)) / 255.0
            canvas = np.zeros((bh, bw), dtype=np.float64)
        else:
            raw = src_clip.get_frame(t)
            img = _PILImage.fromarray(raw.astype(np.uint8))
            scaled = np.array(img.resize((new_w, new_h), _PILImage.BILINEAR))
            canvas = np.zeros((bh, bw, 3), dtype=np.uint8)
        x1 = (bw - new_w) // 2
        y1 = (bh - new_h) // 2
        canvas[y1:y1+new_h, x1:x1+new_w] = scaled[:new_h, :new_w]
        return canvas
    return _frame


def _build_zoom_clip(clip, clip_dur, zoom_from, zoom_to, start_frac, end_frac):
    cw, ch = clip.w, clip.h
    max_z = max(zoom_from, zoom_to)
    big_w, big_h = int(cw * max_z) + 4, int(ch * max_z) + 4

    frame_fn = _make_kb_frame(clip, big_w, big_h, cw, ch, clip_dur, zoom_from, zoom_to, start_frac, end_frac, is_mask=False)
    new_clip = VideoClip(frame_function=frame_fn, duration=clip_dur)
    new_clip.size = (big_w, big_h)

    mask_src = clip.mask if clip.mask else ColorClip(size=(cw, ch), color=1.0, is_mask=True).with_duration(clip_dur)
    mask_fn = _make_kb_frame(mask_src, big_w, big_h, cw, ch, clip_dur, zoom_from, zoom_to, start_frac, end_frac, is_mask=True)
    new_mask = VideoClip(frame_function=mask_fn, duration=clip_dur, is_mask=True)
    new_clip = new_clip.with_mask(new_mask)
    return new_clip


# ═══════════════════════════════════════════════
#  CONTENT EFFECTS
# ═══════════════════════════════════════════════

@register("ken_burns", "content")
def effect_ken_burns(clip, effect_cfg, clip_dur, engine=None):
    p = _prepare_params(effect_cfg)
    zf = p.get("zoom_from", 1.0)
    zt = p.get("zoom_to", 1.15)
    sf = p.get("start_frac", 0.15)
    ef = p.get("end_frac", 0.75)
    return _build_zoom_clip(clip, clip_dur, zf, zt, sf, ef)


@register("ken_burns_fast", "content")
def effect_ken_burns_fast(clip, effect_cfg, clip_dur, engine=None):
    p = _prepare_params(effect_cfg)
    zf = p.get("zoom_from", 1.0)
    zt = p.get("zoom_to", 1.25)
    sf = p.get("start_frac", 0.10)
    ef = p.get("end_frac", 0.50)
    return _build_zoom_clip(clip, clip_dur, zf, zt, sf, ef)


@register("ken_burns_pan", "content")
def effect_ken_burns_pan(clip, effect_cfg, clip_dur, engine=None):
    p = _prepare_params(effect_cfg)
    zf = p.get("zoom_from", 1.0)
    zt = p.get("zoom_to", 1.18)
    sf = p.get("start_frac", 0.10)
    ef = p.get("end_frac", 0.80)
    pan_dir = p.get("pan_direction", "left")
    pan_strength = p.get("pan_strength", 0.06)

    zoomed = _build_zoom_clip(clip, clip_dur, zf, zt, sf, ef)

    cw, ch = clip.w, clip.h
    max_z = max(zf, zt)
    big_w = int(cw * max_z) + 4

    def _pan_pos(t):
        p_frac = 0.0
        if clip_dur > 0:
            raw = (t - sf * clip_dur) / ((ef - sf) * clip_dur) if ef != sf else 0
            p_frac = clamp(raw, 0.0, 1.0)
        eased = ease_in_out_cubic(p_frac)
        shift = eased * big_w * pan_strength
        if pan_dir == "right":
            shift = -shift
        return (int(shift), 0)

    return zoomed.with_position(_pan_pos)


@register("snap_zoom", "content")
def effect_snap_zoom(clip, effect_cfg, clip_dur, engine=None):
    p = _prepare_params(effect_cfg)
    zoom_target = p.get("zoom_target", 1.35)
    snap_dur = p.get("snap_duration", 0.15)
    settle_dur = p.get("settle_duration", 0.35)
    total_snap = snap_dur + settle_dur

    if total_snap >= clip_dur:
        return clip

    def _snap_scale(t):
        if t < snap_dur:
            return lerp(1.0, zoom_target, ease_out_cubic(t / snap_dur))
        elif t < total_snap:
            snap_end = t - snap_dur
            return lerp(zoom_target, 1.0, ease_out_cubic(snap_end / settle_dur))
        return 1.0

    return clip.with_effects([vfx.Resize(_snap_scale)])


@register("zoom_out_reveal", "content")
def effect_zoom_out_reveal(clip, effect_cfg, clip_dur, engine=None):
    p = _prepare_params(effect_cfg)
    zf = p.get("zoom_from", 1.25)
    zt = p.get("zoom_to", 1.0)
    sf = p.get("start_frac", 0.05)
    ef = p.get("end_frac", 0.85)
    return _build_zoom_clip(clip, clip_dur, zf, zt, sf, ef)


@register("chromatic_aberration", "content")
def effect_chromatic_aberration(clip, effect_cfg, clip_dur, engine=None):
    p = _prepare_params(effect_cfg)
    strength = p.get("strength", 0.003)
    edge_only = p.get("edge_only", True)

    def _chroma_transform(get_frame, t):
        frame = get_frame(t).astype(np.float32)
        h, w = frame.shape[:2]
        offset = int(w * strength)
        if offset < 1:
            return frame.astype(np.uint8)

        r, g, b = frame[..., 0].copy(), frame[..., 1].copy(), frame[..., 2].copy()

        if edge_only:
            mask_y = np.abs(np.linspace(-1, 1, h)[:, np.newaxis])
            mask_x = np.abs(np.linspace(-1, 1, w)[np.newaxis, :])
            edge_weight = np.maximum(mask_y, mask_x)
            edge_weight = np.clip((edge_weight - 0.5) * 2, 0, 1)[..., np.newaxis]

            r_shifted = np.zeros_like(r)
            b_shifted = np.zeros_like(b)
            if offset < w:
                r_shifted[:, offset:] = r[:, :w-offset]
                b_shifted[:, :w-offset] = b[:, offset:]

            blend_r = (frame[..., 0] * (1 - edge_weight[..., 0]) + r_shifted * edge_weight[..., 0])
            blend_b = (frame[..., 2] * (1 - edge_weight[..., 0]) + b_shifted * edge_weight[..., 0])
            frame[..., 0] = blend_r
            frame[..., 2] = blend_b
        else:
            if offset < w:
                frame[:, offset:, 0] = r[:, :w-offset]
                frame[:, :w-offset, 2] = b[:, offset:]

        return np.clip(frame, 0, 255).astype(np.uint8)

    return clip.transform(_chroma_transform)


@register("drift", "content")
def effect_drift(clip, effect_cfg, clip_dur, engine=None):
    p = _prepare_params(effect_cfg)
    direction = p.get("direction", "left")
    speed = p.get("speed", 0.03)
    start_frac = p.get("start_frac", 0.0)
    end_frac = p.get("end_frac", 1.0)

    pad_factor = 1.0 + speed
    cw = int(clip.w * pad_factor)
    ch = int(clip.h * pad_factor)
    padded = clip.resized(width=cw, height=ch)

    def _drift_pos(t):
        if clip_dur == 0:
            return (0, 0)
        raw_frac = (t - start_frac * clip_dur) / ((end_frac - start_frac) * clip_dur) if end_frac != start_frac else 0
        frac = clamp(raw_frac, 0.0, 1.0)
        px = int(frac * cw * speed * 0.5)
        if direction == "right":
            px = -px
        return (px, 0)

    return padded.with_position(_drift_pos)


@register("parallax", "content")
def effect_parallax(clip, effect_cfg, clip_dur, engine=None):
    p = _prepare_params(effect_cfg)
    direction = p.get("direction", "left") if isinstance(p, dict) else "left"
    strength = p.get("strength", 0.08) if isinstance(p, dict) else 0.08
    sf = p.get("start_frac", 0.10) if isinstance(p, dict) else 0.10
    ef = p.get("end_frac", 0.80) if isinstance(p, dict) else 0.80

    pad_factor = 1.0 + strength * 2.5
    cw, ch = clip.w, clip.h
    pan_clip = clip.resized(width=int(cw * pad_factor), height=int(ch * pad_factor))
    cx = (cw - pan_clip.w) / 2
    cy = (ch - pan_clip.h) / 2

    def _par_pos(t):
        px = parallax_pan_x(t, pan_clip.w, clip_dur, direction, strength, sf, ef)
        return (int(cx + px), int(cy))

    positioned = pan_clip.with_position(_par_pos)
    return CompositeVideoClip([positioned], size=(cw, pan_clip.h)).with_duration(clip_dur)


@register("pulse", "content")
def effect_pulse(clip, effect_cfg, clip_dur, engine=None):
    p = _prepare_params(effect_cfg)
    frequency = p.get("frequency", 1.5)
    amplitude = p.get("amplitude", 6.0)

    def _pulse_tfm(get_frame, t):
        frame = get_frame(t)
        lum = smooth_pulse_lum(t, frequency, amplitude)
        return np.clip(frame.astype(np.float32) + lum, 0, 255).astype(np.uint8)

    return clip.transform(_pulse_tfm)


@register("shake_decay", "content")
def effect_shake_decay(clip, effect_cfg, clip_dur, engine=None):
    p = _prepare_params(effect_cfg)
    intensity = p.get("intensity", 12.0)
    decay = p.get("decay", 6.0)
    duration = p.get("duration", 0.4)
    rng = np.random.RandomState(42)

    def _shake_pos(t):
        if t > duration:
            return (0, 0)
        d = math.exp(-t * decay)
        sx = rng.randint(-int(intensity * d), int(intensity * d) + 1)
        sy = rng.randint(-int(intensity * d * 0.6), int(intensity * d * 0.6) + 1)
        return (sx, sy)

    return clip.with_position(_shake_pos)


@register("glitch_rgb_split", "content")
def effect_glitch_rgb_split(clip, effect_cfg, clip_dur, engine=None):
    p = _prepare_params(effect_cfg)
    max_offset = p.get("max_offset", 4.0)
    pulse_freq = p.get("pulse_frequency", 0.0)
    decay = p.get("decay", 0.0)

    def _rgb_glitch(get_frame, t):
        frame = get_frame(t).astype(np.float32)
        h, w = frame.shape[:2]

        offset = max_offset
        if pulse_freq > 0:
            offset *= 0.5 + 0.5 * math.sin(t * pulse_freq * math.pi * 2)
        if decay > 0:
            offset *= math.exp(-t * decay)

        offset = max(1, int(abs(offset)))
        if offset >= w:
            return frame.astype(np.uint8)

        r, g, b = frame[..., 0].copy(), frame[..., 1].copy(), frame[..., 2].copy()
        frame[:, offset:, 0] = r[:, :w-offset]
        frame[:, :w-offset, 2] = b[:, offset:]
        return np.clip(frame, 0, 255).astype(np.uint8)

    return clip.transform(_rgb_glitch)


@register("glitch_block_shift", "content")
def effect_glitch_block_shift(clip, effect_cfg, clip_dur, engine=None):
    p = _prepare_params(effect_cfg)
    blocks = p.get("blocks", 7)
    max_shift = p.get("max_shift", 8.0)
    effect_dur = p.get("duration", 0.25)
    decay = p.get("decay", 5.0)
    rng = np.random.RandomState(seed=1)
    pre_shifts = [rng.randint(-int(max_shift), int(max_shift) + 1) for _ in range(blocks)]

    def _block_glitch(get_frame, t):
        frame = get_frame(t).astype(np.float32)
        h, w = frame.shape[:2]

        if t > effect_dur:
            return frame.astype(np.uint8)

        amp = math.exp(-t * decay)
        block_h = h // blocks
        result = frame.copy()

        for i in range(blocks):
            shift = int(pre_shifts[i] * amp)
            if shift == 0:
                continue
            y0 = i * block_h
            y1 = (i + 1) * block_h if i < blocks - 1 else h
            if shift > 0 and shift < w:
                result[y0:y1, shift:] = frame[y0:y1, :w-shift]
                result[y0:y1, :shift] = frame[y0:y1, -shift:]
            elif shift < 0 and -shift < w:
                shift = -shift
                result[y0:y1, :w-shift] = frame[y0:y1, shift:]
                result[y0:y1, w-shift:] = frame[y0:y1, :shift]

        return np.clip(result, 0, 255).astype(np.uint8)

    return clip.transform(_block_glitch)


# ═══════════════════════════════════════════════
#  OVERLAY EFFECTS
# ═══════════════════════════════════════════════

@register("vignette_breathe", "overlay")
def overlay_vignette_breathe(width, height, duration, effect_cfg):
    p = _prepare_params(effect_cfg)
    max_opacity = p.get("max_opacity", 0.35)
    frequency = p.get("frequency", 0.5)
    feather = p.get("feather", 0.4)

    Y, X = np.meshgrid(np.linspace(-1, 1, height), np.linspace(-1, 1, width), indexing='ij')
    radius = np.sqrt(X**2 + Y**2)
    vignette_mask = np.clip((radius - feather) / (1.0 - feather), 0, 1)

    def _make_vignette_frame(t):
        breathe = 0.5 + 0.5 * math.sin(t * frequency * math.pi * 2)
        opacity = max_opacity * breathe
        overlay = np.zeros((height, width, 4), dtype=np.uint8)
        alpha = (vignette_mask * opacity * 255).astype(np.uint8)
        overlay[..., 3] = alpha
        return overlay

    return VideoClip(frame_function=lambda t: _make_vignette_frame(t), duration=duration)


@register("light_leak", "overlay")
def overlay_light_leak(width, height, duration, effect_cfg):
    p = _prepare_params(effect_cfg)
    side = p.get("side", "top_left")
    color = p.get("color", [255, 215, 179])
    opacity = p.get("opacity", 0.12)
    falloff = p.get("falloff", 1.5)

    Y, X = np.meshgrid(np.linspace(0, 1, height), np.linspace(0, 1, width), indexing='ij')

    if side == "top_left":
        dist = np.sqrt(X**2 + Y**2)
    elif side == "top_right":
        dist = np.sqrt((1-X)**2 + Y**2)
    elif side == "bottom_left":
        dist = np.sqrt(X**2 + (1-Y)**2)
    elif side == "bottom_right":
        dist = np.sqrt((1-X)**2 + (1-Y)**2)
    else:
        dist = np.sqrt(X**2 + Y**2)

    intensity = np.exp(-dist * falloff)
    r = np.clip(color[0] * intensity * opacity, 0, 255).astype(np.uint8)
    g = np.clip(color[1] * intensity * opacity, 0, 255).astype(np.uint8)
    b = np.clip(color[2] * intensity * opacity, 0, 255).astype(np.uint8)
    alpha = np.clip(intensity * opacity * 255, 0, 255).astype(np.uint8)

    overlay = np.zeros((height, width, 4), dtype=np.uint8)
    overlay[..., 0] = r
    overlay[..., 1] = g
    overlay[..., 2] = b
    overlay[..., 3] = alpha

    return ImageClip(overlay, is_mask=False).with_duration(duration)


# ═══════════════════════════════════════════════
#  ОСНОВНЫЕ ДИСПЕТЧЕРЫ
# ═══════════════════════════════════════════════

def apply(clip, effect_cfg, clip_dur, engine=None):
    etype = effect_cfg if isinstance(effect_cfg, str) else effect_cfg.get("type", "")
    if etype in CONTENT_EFFECTS:
        try:
            return CONTENT_EFFECTS[etype](clip, effect_cfg, clip_dur, engine)
        except Exception as e:
            logger.error(f"Effect '{etype}' failed: {e}", exc_info=True)
            return clip
    if etype in OVERLAY_EFFECTS:
        return clip
    logger.warning(f"Unknown content effect: {etype}. Skipping.")
    return clip


def apply_many(clip, effects_data, clip_dur, engine=None):
    for effect in effects_data:
        clip = apply(clip, effect, clip_dur, engine)
    return clip


def collect_overlays(effects_data, width, height, duration):
    overlays = []
    if not effects_data:
        return overlays
    for effect in effects_data:
        etype = effect if isinstance(effect, str) else effect.get("type", "")
        if etype in OVERLAY_EFFECTS:
            try:
                overlay = OVERLAY_EFFECTS[etype](width, height, duration, effect)
                if overlay is not None:
                    overlays.append(overlay)
            except Exception as e:
                logger.error(f"Overlay effect '{etype}' failed: {e}", exc_info=True)
    return overlays


def list_content_effects():
    return dict(CONTENT_EFFECTS)


def list_overlay_effects():
    return dict(OVERLAY_EFFECTS)
