import logging
import os
import numpy as np
from PIL import Image as _PILImage
from moviepy import VideoFileClip, ImageClip, ColorClip, CompositeVideoClip, VideoClip, vfx

logger = logging.getLogger(__name__)

# Порог минимального масштаба переднего плана (доля от размера экрана).
# Изменяйте для подстройки масштаба узких/мелких медиа. Работает для обеих ориентаций кадра.
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
            res = resized.cropped(
                x1=x1, y1=y1,
                x2=x1 + target_w, y2=y1 + target_h
            ).with_position((0, 0))

            if effects_data:
                res = self.apply_preset_effects(res, effects_data)
            return res
            
        else:
            # 1. ПОДЛОЖКА (Размытый Cover)
            # Используем рекурсию для получения базы фона
            bg = self.smart_resize_stable(clip, mode="cover")
            
            # Размываем: сжать → растянуть с запасом
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
            
            # Затемняем фон
            bg = bg.with_effects([vfx.LumContrast(lum=self.DEFAULT_LUM)])
            
            # 2. ПЕРЕДНИЙ ПЛАН (с новой логикой отступов)
            target_ratio = target_w / target_h
            clip_ratio = clip.w / clip.h
            
            # Определяем, является ли пропорция "противоположной" (например, горизонтальное фото в вертикальном видео)
            is_opposed = (target_ratio < 0.8 and clip_ratio > 1.2) or (target_ratio > 1.2 and clip_ratio < 0.8)
            
            if is_opposed:
                # СЛУЧАЙ B: Горизонтальное в вертикальном (или наоборот)
                # По бокам без отступов (ширина = канвас)
                # По высоте занимаем фиксированную долю (1/2.6 от экрана)
                new_w = target_w
                new_h = int(target_h / 2.6)
                
                # Масштабируем фото по принципу COVER внутри этого окна
                scale_ratio = max(new_w / clip.w, new_h / clip.h)
                fg_w = math.ceil(clip.w * scale_ratio)
                fg_h = math.ceil(clip.h * scale_ratio)
                fg = clip.resized(width=fg_w, height=fg_h)
                
                # Кропаем лишнее, чтобы вписаться точно в окно (new_w, new_h)
                fg = fg.cropped(
                    x1=(fg_w - new_w) // 2,
                    y1=(fg_h - new_h) // 2,
                    x2=(fg_w - new_w) // 2 + new_w,
                    y2=(fg_h - new_h) // 2 + new_h
                )
            else:
                # СЛУЧАЙ A: Похожие пропорции
                # Принудительные отступы: ширина 90% (по 5% сбоку), высота 80% (по 10% сверху/снизу)
                max_w = int(target_w * 0.90)
                max_h = int(target_h * 0.80)
                
                scale_ratio = min(max_w / clip.w, max_h / clip.h)
                new_w = math.ceil(clip.w * scale_ratio)
                new_h = math.ceil(clip.h * scale_ratio)
                fg = clip.resized(width=new_w, height=new_h)

            # ПРИМЕНЯЕМ ЭФФЕКТЫ
            if effects_data:
                fg = self.apply_preset_effects(fg, effects_data)

            # Центрируем
            fg = fg.with_position("center")
            
            return CompositeVideoClip([bg, fg], size=(target_w, target_h))

    def apply_preset_effects(self, clip, effects_data):
        from core.animation_utils import (
            ken_burns_zoom, smooth_pulse_lum, parallax_pan_x, ease_in_out_cubic, lerp
        )
        clip_dur = clip.duration

        for effect in effects_data:
            eff_type = effect if isinstance(effect, str) else effect.get("type", "")
            logger.info(f"✨ [MediaEngine] Applying effect: {eff_type} (config: {effect})")

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

                # Идеальный Ken Burns: клип РАСТЁТ на экране из центра.
                # Canvas фиксируется по максимальному размеру зума.
                cw, ch = clip.w, clip.h
                max_z = max(zoom_from, zoom_to)
                big_w = int(cw * max_z) + 4  # +4px запас
                big_h = int(ch * max_z) + 4
                _dur = clip_dur
                _src = clip

                def _make_kb_frame(src, bw, bh, ow, oh, d, zf, zt, sf, ef, is_mask=False):
                    def _frame(t):
                        z = ken_burns_zoom(t, d, zf, zt, sf, ef)
                        new_w = max(1, int(ow * z))
                        new_h = max(1, int(oh * z))
                        
                        if is_mask:
                            if src is not None:
                                raw = src.get_frame(t)
                                img = _PILImage.fromarray((raw * 255).astype(np.uint8), mode="L")
                                scaled = np.array(img.resize((new_w, new_h), _PILImage.BILINEAR)) / 255.0
                            else:
                                scaled = np.ones((new_h, new_w), dtype=np.float64)
                            canvas = np.zeros((bh, bw), dtype=np.float64)
                        else:
                            raw = src.get_frame(t)
                            img = _PILImage.fromarray(raw.astype(np.uint8))
                            scaled = np.array(img.resize((new_w, new_h), _PILImage.BILINEAR))
                            canvas = np.zeros((bh, bw, 3), dtype=np.uint8)
                            
                        x1 = (bw - new_w) // 2
                        y1 = (bh - new_h) // 2
                        x2 = x1 + new_w
                        y2 = y1 + new_h
                        
                        if x2 > bw or y2 > bh:
                            trim_w = min(new_w, bw - x1)
                            trim_h = min(new_h, bh - y1)
                            canvas[y1:y1+trim_h, x1:x1+trim_w] = scaled[:trim_h, :trim_w]
                        else:
                            canvas[y1:y2, x1:x2] = scaled
                            
                        return canvas
                    return _frame

                kb_fn = _make_kb_frame(_src, big_w, big_h, cw, ch, _dur, zoom_from, zoom_to, start_frac, end_frac)
                new_clip = VideoClip(frame_function=kb_fn, duration=_dur)
                new_clip.size = (big_w, big_h)
                
                # Добавляем маску, чтобы края были прозрачными при зуме
                mask_src = _src.mask if _src.mask else ColorClip(size=(cw, ch), color=1.0, is_mask=True).with_duration(_dur)
                mask_fn = _make_kb_frame(mask_src, big_w, big_h, cw, ch, _dur, zoom_from, zoom_to, start_frac, end_frac, is_mask=True)
                new_mask = VideoClip(frame_function=mask_fn, duration=_dur, is_mask=True)
                new_mask.size = (big_w, big_h)
                new_clip = new_clip.with_mask(new_mask)
                
                clip = new_clip



            elif eff_type == "pulse":
                frequency = 1.5
                amplitude = 6.0 # Немного усилили по умолчанию
                if isinstance(effect, dict):
                    frequency = effect.get("frequency", frequency)
                    amplitude = effect.get("amplitude", amplitude)

                def _pulse_transform(get_frame, t):
                    frame = get_frame(t)
                    lum_shift = smooth_pulse_lum(t, frequency, amplitude)
                    # Применяем изменение яркости напрямую к массиву кадра
                    return np.clip(frame.astype(np.float32) + lum_shift, 0, 255).astype(np.uint8)

                clip = clip.transform(_pulse_transform)

            elif eff_type == "parallax":
                direction = effect.get("direction", "left") if isinstance(effect, dict) else "left"
                strength = effect.get("strength", 0.08) if isinstance(effect, dict) else 0.08
                start_frac = effect.get("start_frac", 0.10) if isinstance(effect, dict) else 0.10
                end_frac = effect.get("end_frac", 0.80) if isinstance(effect, dict) else 0.80

                # Параллакс: расширяем клип горизонтально, сдвигаем по x.
                pad_factor = 1.0 + strength * 2.5
                pan_clip = clip.resized(
                    width=int(clip.w * pad_factor),
                    height=int(clip.h * pad_factor)
                )
                _cx = (clip.w - pan_clip.w) / 2
                _cy = (clip.h - pan_clip.h) / 2
                _pw = pan_clip.w
                _dir = direction
                _str = strength
                _sf = start_frac
                _ef = end_frac
                _pdur = clip_dur

                def _make_par_pos(cx, cy, pw, dire, stre, sf, ef, dur):
                    def _pos(t):
                        px = parallax_pan_x(t, pw, dur, dire, stre, sf, ef)
                        return (int(cx + px), int(cy))
                    return _pos

                positioned_pan = pan_clip.with_position(
                    _make_par_pos(_cx, _cy, _pw, _dir, _str, _sf, _ef, _pdur)
                )
                # Оборачиваем в CompositeVideoClip для фиксации ШИРИНЫ (отсекает выезжающие края),
                # но высоту оставляем от pan_clip, чтобы не обрезать верх и низ контента.
                clip = CompositeVideoClip([positioned_pan], size=(clip.w, pan_clip.h)).with_duration(_pdur)

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

            current_mode = mode
            if not allow_effects and current_mode == "fit":
                current_mode = "cover" # Для "своих сцен" cover обычно лучше
            
            effects_to_apply = effects if allow_effects else None
            processed = self.smart_resize_stable(raw, mode=current_mode, effects_data=effects_to_apply)
            processed = processed.with_duration(duration)
            
            return processed
            
        except Exception as e:
            logger.error(f"Error processing asset {asset_path}: {e}")
            return ColorClip(size=(self.width, self.height), color=(0,0,0)).with_duration(duration)

