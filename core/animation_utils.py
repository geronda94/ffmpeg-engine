import math

def ease_in_out_cubic(t: float) -> float:
    if t < 0.5:
        return 4 * t * t * t
    return 1 - pow(-2 * t + 2, 3) / 2


def ease_out_cubic(t: float) -> float:
    return 1 - pow(1 - t, 3)


def ease_in_cubic(t: float) -> float:
    return t * t * t


def ease_in_out_quad(t: float) -> float:
    if t < 0.5:
        return 2 * t * t
    return 1 - pow(-2 * t + 2, 2) / 2


def ease_out_quad(t: float) -> float:
    return 1 - (1 - t) * (1 - t)


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def clamp(t: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, t))


def _effect_progress(t: float, clip_duration: float, start_frac: float = 0.15, end_frac: float = 0.75) -> float:
    effect_start = clip_duration * start_frac
    effect_end = clip_duration * end_frac
    if t < effect_start:
        return 0.0
    if t > effect_end:
        return 1.0
    return (t - effect_start) / (effect_end - effect_start)


def ken_burns_zoom(t: float, clip_duration: float, zoom_from: float = 1.0, zoom_to: float = 1.15,
                    start_frac: float = 0.15, end_frac: float = 0.75) -> float:
    p = _effect_progress(t, clip_duration, start_frac, end_frac)
    eased = ease_in_out_cubic(p)
    return lerp(zoom_from, zoom_to, eased)


def parallax_pan_x(t: float, clip_w: float, clip_duration: float, direction: str = "left",
                   strength: float = 0.08, start_frac: float = 0.10, end_frac: float = 0.80) -> int:
    p = _effect_progress(t, clip_duration, start_frac, end_frac)
    eased = ease_in_out_cubic(p)
    px_shift = int(clip_w * strength * eased)
    if direction == "left":
        return -px_shift
    return px_shift


def smooth_pulse_lum(t: float, frequency: float = 1.5, amplitude: float = 5.0) -> float:
    return amplitude * math.sin(t * math.pi * frequency)


def logo_pulse_zoom(t: float, clip_duration: float, base_zoom: float = 1.0,
                    pulse_strength: float = 0.08, pulse_frequency: float = 2.5,
                    decay_rate: float = 0.3) -> float:
    decay = math.exp(-t * decay_rate)
    return base_zoom + pulse_strength * decay * math.sin(t * pulse_frequency)


def slide_in_position(t: float, duration: float, start_pos: tuple, end_pos: tuple) -> tuple:
    if t > duration:
        return end_pos
    p = t / duration
    eased = ease_out_cubic(p)
    return (
        start_pos[0] + (end_pos[0] - start_pos[0]) * eased,
        start_pos[1] + (end_pos[1] - start_pos[1]) * eased
    )
