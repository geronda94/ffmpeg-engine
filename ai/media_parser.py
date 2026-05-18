import logging
import os
import re
import asyncio
import aiohttp
import time
from pathlib import Path

from aiogram import types

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


async def parse_incoming_media(
    message: types.Message,
    project_id: str,
) -> tuple[str, list[dict]]:
    """
    Извлекает из сообщения:
      1. URL из текста (entities) — скачивает изображения
      2. Прикреплённые фото/видео/документы — копирует
      3. Чистит текст от URL — возвращает для TTS и раскадровки

    Returns:
        clean_script: str  — текст без url-ов
        preloaded: list[dict]  — локальные файлы с метаданными
    """
    text = message.text or message.caption or ""
    preloaded = []
    urls_to_strip: list[tuple[int, int]] = []

    preload_dir = PROJECT_ROOT / "projects" / project_id / "preloaded"
    preload_dir.mkdir(parents=True, exist_ok=True)

    # ── 1. URL из entities ────────────────────────────────────────────
    entities = message.entities or message.caption_entities or []
    for ent in entities:
        if ent.type in ("url", "text_link"):
            url = ent.extract_from(text) if hasattr(ent, "extract_from") else text[ent.offset : ent.offset + ent.length]
            if ent.type == "text_link" and hasattr(ent, "url"):
                url = ent.url
            if not url.startswith(("http://", "https://")):
                continue
            local = await _try_download_url(url, preload_dir)
            if not local:
                local = await _try_scrape_html(url, preload_dir)
            if local:
                preloaded.append({
                    "local_path": str(local),
                    "source_url": url,
                    "type": _guess_type(url),
                    "original_name": url.rsplit("/", 1)[-1][:80],
                })
            urls_to_strip.append((ent.offset, ent.offset + ent.length))

    # ── 2. Прикреплённые фото ─────────────────────────────────────────
    if message.photo:
        largest = message.photo[-1]
        try:
            f = await message.bot.get_file(largest.file_id)
            local = preload_dir / f"attached_photo_{int(time.time())}.jpg"
            await message.bot.download_file(f.file_path, destination=str(local))
            if os.path.exists(local) and os.path.getsize(local) > 0:
                preloaded.append({
                    "local_path": str(local),
                    "source_url": None,
                    "type": "image",
                    "original_name": "attached_photo.jpg",
                })
        except Exception as e:
            logger.warning(f"Failed to download attached photo: {e}")

    # ── 3. Прикреплённые видео ────────────────────────────────────────
    if message.video:
        try:
            f = await message.bot.get_file(message.video.file_id)
            ext = message.video.file_name.rsplit(".", 1)[-1] if message.video.file_name else "mp4"
            local = preload_dir / f"attached_video_{int(time.time())}.{ext}"
            await message.bot.download_file(f.file_path, destination=str(local))
            if os.path.exists(local) and os.path.getsize(local) > 0:
                preloaded.append({
                    "local_path": str(local),
                    "source_url": None,
                    "type": "video",
                    "original_name": message.video.file_name or "attached_video.mp4",
                })
        except Exception as e:
            logger.warning(f"Failed to download attached video: {e}")

    # ── 4. Документы (фото/видео как документ) ───────────────────────
    if message.document:
        doc = message.document
        mime = doc.mime_type or ""
        fname = doc.file_name or "attached_doc"
        if mime.startswith("image/") or mime.startswith("video/"):
            try:
                f = await message.bot.get_file(doc.file_id)
                local = preload_dir / f"attached_doc_{int(time.time())}_{fname}"
                await message.bot.download_file(f.file_path, destination=str(local))
                if os.path.exists(local) and os.path.getsize(local) > 0:
                    preloaded.append({
                        "local_path": str(local),
                        "source_url": None,
                        "type": "video" if mime.startswith("video/") else "image",
                        "original_name": fname,
                    })
            except Exception as e:
                logger.warning(f"Failed to download attached document: {e}")

    # ── 5. Чистим текст от URL ────────────────────────────────────────
    # Удаляем URL-ы из entities (от конца к началу, чтобы не сбить офсеты)
    sorted_urls = sorted(urls_to_strip, key=lambda x: -x[0])
    clean_text = text
    for start, end in sorted_urls:
        # Удаляем URL и предшествующие пробелы/переносы
        prefix = re.sub(r"\s+$", "", clean_text[:start])
        suffix = clean_text[end:].lstrip()
        clean_text = prefix + (" " if prefix and suffix else "") + suffix

    # Удаляем оставшиеся «голые» URL-ы (которые могли не попасть в entities)
    clean_text = re.sub(r"https?://\S+", "", clean_text)
    clean_text = re.sub(r"\n{3,}", "\n\n", clean_text).strip()

    logger.info(
        f"Media parser: {len(preloaded)} files preloaded for {project_id}, "
        f"clean script: {len(clean_text)} chars"
    )
    return clean_text, preloaded


async def _try_download_url(url: str, dest_dir: Path) -> Path | None:
    """Пытается скачать изображение по URL. Возвращает локальный путь или None."""
    image_exts = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")
    if not any(url.lower().endswith(ext) or any(ext in url.lower() for ext in image_exts)
               for _ in [1]):
        # Проверяем — может URL заканчивается на расширение картинки
        parsed = url.rsplit("?", 1)[0]
        if not any(parsed.lower().endswith(ext) for ext in image_exts):
            return None  # Не похоже на прямую ссылку на изображение

    fname = url.rsplit("/", -1)[-1].split("?")[0][:100] or f"image_{int(time.time())}"
    if not any(fname.lower().endswith(ext) for ext in image_exts):
        fname += ".jpg"
    local = dest_dir / fname

    if local.exists():
        local = dest_dir / f"{fname.rsplit('.', 1)[0]}_{int(time.time())}.{fname.rsplit('.', 1)[-1]}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.read()
                if not data or len(data) < 1024:
                    return None
                with open(local, "wb") as f:
                    f.write(data)
                from PIL import Image
                with Image.open(local) as img:
                    img.verify()
                with Image.open(local) as img:
                    img.convert("RGB").save(local, "JPEG", quality=92, optimize=True)
                return local
    except Exception as e:
        logger.warning(f"Failed to download {url[:80]}: {e}")
        if local.exists():
            os.remove(local)
        return None


def _guess_type(url: str) -> str:
    if any(url.lower().endswith(ext) for ext in (".mp4", ".webm", ".mov", ".mkv")):
        return "video"
    return "image"


async def _try_scrape_html(url: str, dest_dir: Path) -> Path | None:
    """Парсит HTML-страницу (новостную статью), ищет og:image или первую крупную
    картинку, скачивает её. Возвращает локальный путь или None."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; TelegramBot/1.0)"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    return None
                content_type = resp.headers.get("Content-Type", "")
                if "text/html" not in content_type.lower():
                    return None
                html = await resp.text()
    except Exception as e:
        logger.warning(f"HTML fetch failed for {url[:80]}: {e}")
        return None

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        logger.warning("BeautifulSoup not installed — HTML scraping disabled. Run: pip install beautifulsoup4")
        return None

    soup = BeautifulSoup(html, "html.parser")

    # ── Приоритет 1: og:image ──
    og_img = soup.find("meta", property="og:image")
    if og_img and og_img.get("content"):
        image_url = og_img["content"]
        if image_url.startswith("/"):
            from urllib.parse import urljoin
            image_url = urljoin(url, image_url)
        if image_url.startswith(("http://", "https://")):
            result = await _try_download_url(image_url, dest_dir)
            if result:
                return result

    # ── Приоритет 2: twitter:image ──
    tw_img = soup.find("meta", attrs={"name": "twitter:image"})
    if tw_img and tw_img.get("content"):
        image_url = tw_img["content"]
        if image_url.startswith("/"):
            from urllib.parse import urljoin
            image_url = urljoin(url, image_url)
        if image_url.startswith(("http://", "https://")):
            result = await _try_download_url(image_url, dest_dir)
            if result:
                return result

    # ── Приоритет 3: первое крупное <img> (ширина ≥ 200px) ──
    images = soup.find_all("img")
    for img in images:
        src = img.get("src") or img.get("data-src") or ""
        width = img.get("width", "").strip()
        height = img.get("height", "").strip()
        if not src:
            continue
        if src.startswith("/"):
            from urllib.parse import urljoin
            src = urljoin(url, src)
        if not src.startswith(("http://", "https://")):
            continue
        try:
            w = int(width) if width else 0
            h = int(height) if height else 0
        except (ValueError, TypeError):
            w, h = 0, 0
        if w >= 200 or h >= 200 or (not width and not height):
            result = await _try_download_url(src, dest_dir)
            if result:
                return result

    return None
