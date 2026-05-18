import os
import random
import logging
from PIL import Image as _PILImage, ImageChops, ImageEnhance

logger = logging.getLogger(__name__)


def auto_crop_borders(img: _PILImage.Image) -> _PILImage.Image:
    """Удаляет сплошные черные или белые рамки (паспарту) вокруг изображения.
    Поддерживает JPEG-артефакты (допуск ±18 на угловые пиксели)."""
    try:
        w, h = img.size
        if w < 10 or h < 10:
            return img

        corners = [img.getpixel((0, 0)), img.getpixel((w-1, 0)),
                   img.getpixel((0, h-1)), img.getpixel((w-1, h-1))]

        def _close(c1, c2, tol=18) -> bool:
            return all(abs(int(a) - int(b)) <= tol for a, b in zip(c1[:3], c2[:3]))

        ref = corners[0]
        if not all(_close(ref, c) for c in corners[1:]):
            return img

        avg_r = sum(c[0] for c in corners) // 4
        avg_g = sum(c[1] for c in corners) // 4
        avg_b = sum(c[2] for c in corners) // 4

        is_black = avg_r < 35 and avg_g < 35 and avg_b < 35
        is_white = avg_r > 200 and avg_g > 200 and avg_b > 200
        if not (is_black or is_white):
            return img

        # Строим однородный фон по средним угловым пикселям и ищем bbox отличий
        bg_color = (avg_r, avg_g, avg_b)
        bg = _PILImage.new("RGB", img.size, bg_color)
        diff = ImageChops.difference(img.convert("RGB"), bg)
        # Binarize diff with threshold=22 to ignore JPEG noise
        diff_gray = diff.convert("L").point(lambda x: 255 if x > 22 else 0)
        bbox = diff_gray.getbbox()

        if bbox:
            bx1, by1, bx2, by2 = bbox
            if bx1 > w * 0.03 or by1 > h * 0.03 or (w - bx2) > w * 0.03 or (h - by2) > h * 0.03:
                cropped = img.crop(bbox)
                logger.info(f"✨ Auto-cropped borders {img.size} → {cropped.size} (bg≈{bg_color})")
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
