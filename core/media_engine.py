import logging
import os
from moviepy import VideoFileClip, ImageClip, ColorClip, CompositeVideoClip, vfx

logger = logging.getLogger(__name__)

class MediaEngine:
    """
    Унифицированный движок для обработки медиа-контента.
    Содержит общую логику ресайза, блюра и наложения эффектов.
    """
    
    def __init__(self, width: int = 1080, height: int = 1920, fps: int = 30):
        self.width = width
        self.height = height
        self.fps = fps
        self.BLUR_RESIZE_FACTOR = 0.02
        self.BLUR_UPSCALER = 50.0
        self.DEFAULT_LUM = -50

    def smart_resize_stable(self, clip, mode="fit"):
        import math
        target_w, target_h = self.width, self.height
        
        if mode == "cover":
            # ceil() вместо int() — никогда не усекаем вниз, всегда перекрываем
            ratio = max(target_w / clip.w, target_h / clip.h)
            new_w = math.ceil(clip.w * ratio) + 2  # +2px запас на субпиксельные ошибки
            new_h = math.ceil(clip.h * ratio) + 2
            
            resized = clip.resized(width=new_w, height=new_h)
            
            # Точный кроп через x1/y1/x2/y2 — нет плавающих центров
            x1 = (new_w - target_w) // 2
            y1 = (new_h - target_h) // 2
            return resized.cropped(
                x1=x1, y1=y1,
                x2=x1 + target_w, y2=y1 + target_h
            ).with_position((0, 0))
            
        else:
            # 1. Получаем основу cover (гарантированно target_w x target_h)
            bg = self.smart_resize_stable(clip, mode="cover")
            
            # 2. Размываем: сжать до крошечного → растянуть с запасом
            bg = bg.resized(self.BLUR_RESIZE_FACTOR)
            
            # Растягиваем чуть больше target, кропаем через точные координаты
            over_w = target_w + 60
            over_h = target_h + 60
            bg = bg.resized(width=over_w, height=over_h)
            x1 = (over_w - target_w) // 2
            y1 = (over_h - target_h) // 2
            bg = bg.cropped(
                x1=x1, y1=y1,
                x2=x1 + target_w, y2=y1 + target_h
            ).with_position((0, 0))
            
            bg = bg.with_effects([vfx.LumContrast(lum=self.DEFAULT_LUM)])
            
            # 3. Передний план (fit — вписываем без обрезки)
            ratio = min(target_w / clip.w, target_h / clip.h)
            new_w = math.ceil(clip.w * ratio)
            new_h = math.ceil(clip.h * ratio)
            fg = clip.resized(width=new_w, height=new_h).with_position("center")
            
            return CompositeVideoClip([bg, fg], size=(target_w, target_h))

    def apply_preset_effects(self, clip, effects_data):
        from core.animation_utils import (
            ken_burns_zoom, smooth_pulse_lum, parallax_pan_x, ease_in_out_cubic, lerp
        )
        clip_dur = clip.duration

        for effect in effects_data:
            eff_type = effect if isinstance(effect, str) else effect.get("type", "")

            if eff_type in ("ken_burns", "ken_burns_fast"):
                zoom_from = 1.0
                zoom_to = 1.25 if eff_type == "ken_burns_fast" else 1.15
                start_frac = 0.10 if eff_type == "ken_burns_fast" else 0.15
                end_frac = 0.50 if eff_type == "ken_burns_fast" else 0.75
                if isinstance(effect, dict):
                    zoom_from = effect.get("zoom_from", zoom_from)
                    zoom_to = effect.get("zoom_to", zoom_to)
                    start_frac = effect.get("start_frac", start_frac)
                    end_frac = effect.get("end_frac", end_frac)

                pad_factor = zoom_to * 1.05
                padded = clip.resized(width=int(clip.w * pad_factor), height=int(clip.h * pad_factor))

                def make_zoom_func(zf, zt, sf, ef):
                    def _z(t):
                        return ken_burns_zoom(t, clip_dur, zf, zt, sf, ef)
                    return _z
                zoom_func = make_zoom_func(zoom_from, zoom_to, start_frac, end_frac)
                padded = padded.with_effects([vfx.Resize(zoom_func)])

                base_w, base_h = clip.w, clip.h
                def make_center_pos(bw, bh, pf, zf, zt, sf, ef):
                    def _p(t):
                        z = ken_burns_zoom(t, clip_dur, zf, zt, sf, ef)
                        cw = bw * pf * z
                        ch = bh * pf * z
                        return ((self.width - cw) / 2, (self.height - ch) / 2)
                    return _p
                center_func = make_center_pos(base_w, base_h, pad_factor, zoom_from, zoom_to, start_frac, end_frac)
                clip = padded.with_position(center_func)

            elif eff_type == "pulse":
                frequency = 1.5
                amplitude = 5.0
                if isinstance(effect, dict):
                    frequency = effect.get("frequency", frequency)
                    amplitude = effect.get("amplitude", amplitude)

                def _pulse_func(t):
                    return smooth_pulse_lum(t, frequency, amplitude)
                clip = clip.with_effects([vfx.LumContrast(lum=_pulse_func)])

            elif eff_type == "parallax":
                direction = effect.get("direction", "left") if isinstance(effect, dict) else "left"
                strength = effect.get("strength", 0.08) if isinstance(effect, dict) else 0.08
                start_frac = effect.get("start_frac", 0.10) if isinstance(effect, dict) else 0.10
                end_frac = effect.get("end_frac", 0.80) if isinstance(effect, dict) else 0.80

                pad_factor = 1.25
                pan_clip = clip.resized(width=int(clip.w * pad_factor), height=int(clip.h * pad_factor))
                center_x = (self.width - pan_clip.w) / 2
                center_y = (self.height - pan_clip.h) / 2

                def _parallax_func(t):
                    px = parallax_pan_x(t, pan_clip.w, clip_dur, direction, strength, start_frac, end_frac)
                    return (center_x + px, center_y)
                clip = pan_clip.with_position(_parallax_func)

        return clip

    def process_asset(self, asset_path, duration, mode="fit", offset=0, allow_effects=True, effects=None):
        logger.info(f"Processing asset: {asset_path} (dur: {duration}s, offset: {offset}s)")
        ext = os.path.splitext(asset_path)[1].lower()
        
        try:
            if ext in ['.mp4', '.mov', '.avi', '.mkv']:
                raw = VideoFileClip(asset_path).without_audio()
                end_time = min(offset + duration, raw.duration)
                raw = raw.subclipped(offset, end_time)
                if raw.duration < duration:
                    raw = raw.with_effects([vfx.MultiplySpeed(raw.duration / duration)])
                raw = raw.with_duration(duration)
            else:
                raw = ImageClip(asset_path).with_duration(duration)

            # ФИКС: убираем двойную обёртку в черный ColorClip.
            # smart_resize_stable уже возвращает клип точного размера экрана.
            # Лишний CompositeVideoClip([base, processed]) создаёт пиксельные зазоры.
            # Если эффекты отключены, принудительно используем cover (чтобы не было размытия фона)
            # или можно было бы добавить режим 'fit_black'
            current_mode = mode
            if not allow_effects and current_mode == "fit":
                current_mode = "cover" # Для "своих сцен" cover обычно лучше, чем блюр
            
            processed = self.smart_resize_stable(raw, mode=current_mode)
            processed = processed.with_duration(duration)
            
            if allow_effects and effects:
                processed = self.apply_preset_effects(processed, effects)
            
            return processed
            
        except Exception as e:
            logger.error(f"Error processing asset {asset_path}: {e}")
            return ColorClip(size=(self.width, self.height), color=(0,0,0)).with_duration(duration)

