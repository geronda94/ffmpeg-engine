import logging
import os
import numpy as np
import math
from PIL import Image as _PILImage, ImageDraw
from moviepy import VideoFileClip, ImageClip, ColorClip, CompositeVideoClip, VideoClip, vfx

logger = logging.getLogger(__name__)

# Порог минимального масштаба переднего плана (доля от размера экрана).
MIN_FG_SCALE_DIVISOR = 2.5


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

    def smart_resize_stable(self, clip, mode="fit", effects_data=None):
        logger.info(f"⚙️ [MediaEngine] smart_resize_stable start: mode={mode}, effects_count={len(effects_data) if effects_data else 0}")
        target_w, target_h = self.width, self.height
        
        if mode == "cover":
            ratio = max(target_w / clip.w, target_h / clip.h)
            new_w = math.ceil(clip.w * ratio) + 2
            new_h = math.ceil(clip.h * ratio) + 2
            
            resized = clip.resized(width=new_w, height=new_h)
            x1 = (new_w - target_w) // 2
            y1 = (new_h - target_h) // 2
            res = resized.cropped(
                x1=x1, y1=y1,
                x2=x1 + target_w, y2=y1 + target_h
            ).with_position((0, 0))

            if effects_data:
                res = self.apply_preset_effects(res, effects_data)
            return res
            
        else:
            # 1. ПОДЛОЖКА (Размытый Cover + Крупное Зерно)
            bg = self.smart_resize_stable(clip, mode="cover")
            bg = bg.resized(self.BLUR_RESIZE_FACTOR)
            over_w = int(target_w * 1.1)
            over_h = int(target_h * 1.1)
            bg = bg.resized(width=over_w, height=over_h)
            bg = bg.cropped(
                x1=(over_w - target_w) // 2,
                y1=(over_h - target_h) // 2,
                x2=(over_w - target_w) // 2 + target_w,
                y2=(over_h - target_h) // 2 + target_h
            ).with_position((0, 0))
            
            bg = bg.with_effects([vfx.LumContrast(lum=self.DEFAULT_LUM)])
            
            # Трендовая крупная зернистость
            def _add_grain(get_frame, t):
                frame = get_frame(t)
                h, w = frame.shape[:2]
                noise_small = np.random.randint(-12, 12, (h//2, w//2, 3), dtype=np.int16)
                noise_img = _PILImage.fromarray((noise_small + 12).astype(np.uint8))
                noise_large = np.array(noise_img.resize((w, h), _PILImage.NEAREST)).astype(np.int16) - 12
                return np.clip(frame.astype(np.int16) + noise_large, 0, 255).astype(np.uint8)
            
            bg = bg.transform(_add_grain)

            # 2. ПЕРЕДНИЙ ПЛАН (FG)
            target_ratio = target_w / target_h
            clip_ratio = clip.w / clip.h
            is_opposed = (target_ratio < 0.8 and clip_ratio > 1.2) or (target_ratio > 1.2 and clip_ratio < 0.8)
            
            if is_opposed:
                new_w = target_w
                new_h = int(target_h / 2.6)
                scale_ratio = max(new_w / clip.w, new_h / clip.h)
                fg_w, fg_h = math.ceil(clip.w * scale_ratio), math.ceil(clip.h * scale_ratio)
                fg = clip.resized(width=fg_w, height=fg_h).cropped(
                    x1=(fg_w - new_w) // 2, y1=(fg_h - new_h) // 2,
                    x2=(fg_w - new_w) // 2 + new_w, y2=(fg_h - new_h) // 2 + new_h
                )
            else:
                max_w, max_h = int(target_w * 0.90), int(target_h * 0.80)
                scale_ratio = min(max_w / clip.w, max_h / clip.h)
                new_w, new_h = math.ceil(clip.w * scale_ratio), math.ceil(clip.h * scale_ratio)
                fg = clip.resized(width=new_w, height=new_h)

            if effects_data:
                fg = self.apply_preset_effects(fg, effects_data)

            # Центрируем
            fg = fg.with_position("center")
            
            # СБОРКА: Только Фон и Кадр (без лишних эффектов)
            res = CompositeVideoClip([bg, fg], size=(target_w, target_h))
            
            if clip.duration:
                res = res.with_duration(clip.duration)
            return res

    def apply_preset_effects(self, clip, effects_data):
        from core.effects import apply_many
        clip_dur = clip.duration
        for effect in effects_data:
            eff_type = effect if isinstance(effect, str) else effect.get("type", "")
            logger.info(f"✨ [MediaEngine] Applying effect: {eff_type} (config: {effect})")
        return apply_many(clip, effects_data, clip_dur, engine=self)

    def process_asset(self, asset_path, duration, mode="fit", offset=0, allow_effects=True, effects=None, mirror=False):
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

            current_mode = mode
            if not allow_effects and current_mode == "fit":
                current_mode = "cover"
            
            effects_to_apply = effects if allow_effects else None
            processed = self.smart_resize_stable(raw, mode=current_mode, effects_data=effects_to_apply)
            processed = processed.with_duration(duration)

            return processed
        except Exception as e:
            logger.error(f"Error processing asset {asset_path}: {e}")
            return ColorClip(size=(self.width, self.height), color=(0,0,0)).with_duration(duration)
