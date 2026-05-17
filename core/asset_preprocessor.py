import os
import random
import logging
from PIL import Image as _PILImage, ImageChops, ImageEnhance

logger = logging.getLogger(__name__)


def auto_crop_borders(img: _PILImage.Image) -> _PILImage.Image:
    """Удаляет сплошные черные или белые рамки (паспарту) вокруг изображения."""
    try:
        w, h = img.size
        # Берем угловые пиксели для определения цвета фона
        corners = [img.getpixel((0, 0)), img.getpixel((w-1, 0)), img.getpixel((0, h-1)), img.getpixel((w-1, h-1))]
        
        # Если углы не одинаковые, значит сплошной рамки нет
        if not all(corners[0] == c for c in corners[1:]):
            return img

        bg_color = corners[0]
        # Проверяем, что фон действительно черный (r,g,b < 25) или белый (r,g,b > 230)
        is_black = all(val < 25 for val in bg_color[:3])
        is_white = all(val > 230 for val in bg_color[:3])
        
        if not (is_black or is_white):
            return img

        bg = _PILImage.new(img.mode, img.size, bg_color)
        diff = ImageChops.difference(img, bg)
        bbox = diff.getbbox()
        
        if bbox:
            bx1, by1, bx2, by2 = bbox
            # Обрезаем только если рамка занимает больше 3% от размера
            if bx1 > w*0.03 or by1 > h*0.03 or (w - bx2) > w*0.03 or (h - by2) > h*0.03:
                cropped = img.crop(bbox)
                logger.info(f"✨ Auto-cropped borders from size {img.size} to {cropped.size} (bg: {bg_color})")
                return cropped
    except Exception as e:
        logger.warning(f"Auto-crop borders failed: {e}")
    return img


def apply_base_enhancement(img: _PILImage.Image) -> _PILImage.Image:
    """Применяет легкий микро-зум 1.5% и мягкую цветокоррекцию для уникализации стоковых исходников по умолчанию."""
    try:
        w, h = img.size
        cw, ch = int(w * 0.015), int(h * 0.015)
        if cw > 0 and ch > 0:
            img = img.crop((cw, ch, w - cw, h - ch)).resize((w, h), _PILImage.Resampling.LANCZOS)
        
        img = ImageEnhance.Contrast(img).enhance(random.uniform(1.01, 1.04))
        img = ImageEnhance.Color(img).enhance(random.uniform(1.01, 1.05))
        img = ImageEnhance.Sharpness(img).enhance(random.uniform(1.05, 1.15))
        logger.info("✨ Applied base 1.5% micro-zoom & enhancement to stock asset")
        return img
    except Exception as e:
        logger.warning(f"Base enhancement failed: {e}")
        return img


def apply_unique_mirror(img: _PILImage.Image, channel_profile: str) -> _PILImage.Image:
    """Уникализирует изображение для клонированных проектов (отзеркаливание + цветокоррекция + зум)."""
    try:
        # 1. Горизонтальное отзеркаливание (не делаем для икон в православном канале, чтобы не нарушать каноны и надписи)
        if channel_profile != "orthodox":
            img = img.transpose(_PILImage.FLIP_LEFT_RIGHT)
            logger.info("🪞 Applied horizontal flip for asset mirroring")

        # 2. Мягкая уникализация цвета и контраста
        contrast = random.uniform(1.02, 1.08)
        img = ImageEnhance.Contrast(img).enhance(contrast)

        sat = random.uniform(1.02, 1.10)
        img = ImageEnhance.Color(img).enhance(sat)

        sharp = random.uniform(1.1, 1.3)
        img = ImageEnhance.Sharpness(img).enhance(sharp)

        # 3. Микро-зум 2% (срезаем края по 2% и растягиваем обратно)
        w, h = img.size
        crop_w, crop_h = int(w * 0.02), int(h * 0.02)
        bbox = (crop_w, crop_h, w - crop_w, h - crop_h)
        img = img.crop(bbox).resize((w, h), _PILImage.Resampling.LANCZOS)
        logger.info("✨ Applied micro-zoom 2% and color adjustment for uniqueness")
        
        return img
    except Exception as e:
        logger.warning(f"Mirror uniqueness processing failed: {e}")
        return img


def preprocess_project_assets(project_id: str, is_mirror: bool = False, channel_profile: str = ""):
    """Главный входной метод предобработки: проходит по всем ассетам проекта перед рендером."""
    from core.project_manager import ProjectManager
    pm = ProjectManager()
    proj_path = pm.get_project_path(project_id)
    assets_dir = proj_path / "assets"
    
    if not assets_dir.exists():
        return

    logger.info(f"🛠️ Starting Asset Preprocess Engine for project {project_id} (is_mirror={is_mirror})...")
    
    count = 0
    for root, _, files in os.walk(assets_dir):
        for file in files:
            ext = os.path.splitext(file)[1].lower()
            if ext in [".jpg", ".jpeg", ".png"]:
                fpath = os.path.join(root, file)
                try:
                    with _PILImage.open(fpath) as pil_img:
                        img_rgb = pil_img.convert("RGB")
                        
                        # 1. Всегда делаем авто-кроп рамок
                        processed = auto_crop_borders(img_rgb)
                        
                        # 2. Если это перевод / клон, делаем глубокую уникализацию и зеркало
                        if is_mirror:
                            processed = apply_unique_mirror(processed, channel_profile)
                        else:
                            # Для основного проекта делаем базовую уникализацию (микро-зум 1.5% и фильтры)
                            processed = apply_base_enhancement(processed)
                            
                        processed.save(fpath, quality=95)
                        count += 1
                except Exception as ex:
                    logger.warning(f"Failed to preprocess asset {file}: {ex}")

    logger.info(f"✅ Asset Preprocess Engine completed successfully ({count} assets processed).")
