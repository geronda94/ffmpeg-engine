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
        # Константы эстетики
        self.BLUR_RESIZE_FACTOR = 0.02
        self.BLUR_UPSCALER = 50.0
        self.DEFAULT_LUM = -50

    def smart_resize_stable(self, clip, mode="fit"):
        """
        Стабильный ресайз:
        - 'cover': заполнение экрана (обрезка краев)
        - 'fit': вписывание с размытым фоном
        """
        target_w, target_h = self.width, self.height
        
        if mode == "cover":
            # Центрируем и обрезаем под размер (Cover)
            # Сначала ресайзим по меньшей стороне
            ratio = max(target_w / clip.w, target_h / clip.h)
            new_w, new_h = int(clip.w * ratio), int(clip.h * ratio)
            resized = clip.resized(width=new_w, height=new_h)
            # Обрезаем центр
            return resized.cropped(x_center=resized.w/2, y_center=resized.h/2, width=target_w, height=target_h)
            
        else: # mode == "fit"
            # ФОН: Затемненный и сильно размытый (через мягкий ресайз)
            bg = self.smart_resize_stable(clip, mode="cover")
            bg = bg.resized(self.BLUR_RESIZE_FACTOR).resized(self.BLUR_UPSCALER)
            bg = bg.resized(width=target_w, height=target_h)
            bg = bg.with_effects([vfx.LumContrast(lum=self.DEFAULT_LUM)])
            
            # ПЕРЕДНИЙ ПЛАН: Вписываем полностью
            ratio = min(target_w / clip.w, target_h / clip.h)
            new_w, new_h = int(clip.w * ratio), int(clip.h * ratio)
            fg = clip.resized(width=new_w, height=new_h).with_position("center")
            
            return CompositeVideoClip([bg, fg], size=(target_w, target_h))

    def apply_preset_effects(self, clip, effect_list):
        """Наложение эффектов из пресетов монтажа."""
        for effect in effect_list:
            if effect == "ken_burns":
                # Легкий наезд (1.0 -> 1.1) через Resize
                def ken_burns_zoom(t):
                    return 1.0 + 0.1 * (t / clip.duration)
                clip = clip.with_effects([vfx.Resize(ken_burns_zoom)])
            elif effect == "pulse":
                # Пульсация яркости
                clip = clip.with_effects([vfx.LumContrast(lum=lambda t: 10 * (t % 1))])
        return clip

    def process_asset(self, asset_path, duration, mode="fit", offset=0, allow_effects=True, effects=None):
        """
        Полный цикл обработки ассета: загрузка -> подрезка -> ресайз -> эффекты.
        """
        logger.info(f"Processing asset: {asset_path} (dur: {duration}s, offset: {offset}s)")
        ext = os.path.splitext(asset_path)[1].lower()
        
        try:
            if ext in ['.mp4', '.mov', '.avi', '.mkv']:
                raw = VideoFileClip(asset_path).without_audio()
                # Берем фрагмент
                end_time = min(offset + duration, raw.duration)
                raw = raw.subclipped(offset, end_time)
                # Если видео короче сцены - замедляем
                if raw.duration < duration:
                    raw = raw.with_effects([vfx.MultiplySpeed(raw.duration / duration)])
                raw = raw.with_duration(duration)
            else:
                raw = ImageClip(asset_path).with_duration(duration)

            # Базовый слой (черный фон для стабильности)
            base = ColorClip(size=(self.width, self.height), color=(0,0,0)).with_duration(duration)
            
            # Ресайз
            processed = self.smart_resize_stable(raw, mode=mode)
            processed = processed.with_duration(duration)
            
            # Эффекты
            if allow_effects and effects:
                processed = self.apply_preset_effects(processed, effects)
            
            return CompositeVideoClip([base, processed], size=(self.width, self.height)).with_duration(duration)
            
        except Exception as e:
            logger.error(f"Error processing asset {asset_path}: {e}")
            # Откат к пустому черному клипу, чтобы рендер не падал
            return ColorClip(size=(self.width, self.height), color=(0,0,0)).with_duration(duration)
