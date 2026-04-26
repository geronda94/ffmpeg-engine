"""Загрузка ресурсов: URL, YouTube, локальные файлы."""
from __future__ import annotations
import hashlib
import logging
from pathlib import Path
from urllib.parse import urlparse

import requests
from tqdm import tqdm

import shutil

logger = logging.getLogger(__name__)

# По умолчанию, но может быть переопределено через init_session
TEMP_DIR = Path("temp_session")
LOCAL_DIR = Path("local_assets")

def init_session(path: Path):
    global TEMP_DIR
    TEMP_DIR = path
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    logger.debug(f"Сессионный резолвер инициализирован: {TEMP_DIR}")


def _url_hash(url: str) -> str:
    """MD5-хеш URL → уникальное имя файла без коллизий."""
    h = hashlib.md5(url.encode()).hexdigest()[:10]
    ext = Path(urlparse(url).path).suffix or ".bin"
    return f"{h}{ext}"


def resolve(source: str) -> Path:
    """Вернуть локальный Path к ресурсу (скачать если нужно)."""
    parsed = urlparse(source)

    if parsed.scheme in ("http", "https"):
        netloc = parsed.netloc.lower()
        if "youtube.com" in netloc or "youtu.be" in netloc:
            return _download_youtube(source)
        return _download_http(source)

    # Локальный путь
    p = Path(source)
    if not p.exists():
        # Попробовать относительно local_assets/
        p = LOCAL_DIR / source

    if p.exists():
        # Копируем локальный файл в temp для изоляции и последующей очистки
        dest = TEMP_DIR / p.name
        if not dest.exists():
            logger.debug(f"Копирую локальный ресурс: {p.name} -> {TEMP_DIR}")
            shutil.copy2(p, dest)
        return dest

    raise FileNotFoundError(
        f"Ресурс не найден: '{source}'\n"
        f"  Проверь путь, URL или положи файл в local_assets/"
    )


def _download_http(url: str) -> Path:
    local_path = TEMP_DIR / _url_hash(url)
    if local_path.exists():
        logger.info(f"Кэш: {local_path.name}")
        return local_path

    logger.info(f"Скачиваю {url}")
    try:
        r = requests.get(url, stream=True, timeout=30)
        r.raise_for_status()
    except requests.RequestException as e:
        raise RuntimeError(f"Ошибка загрузки {url}: {e}") from e

    total = int(r.headers.get("content-length", 0))
    with open(local_path, "wb") as f, tqdm(
        total=total, unit="B", unit_scale=True, desc=local_path.name
    ) as bar:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)
            bar.update(len(chunk))

    return local_path


def _download_youtube(url: str) -> Path:
    try:
        import yt_dlp
    except ImportError:
        raise RuntimeError("yt-dlp не установлен: pip install yt-dlp")

    out_tmpl = str(TEMP_DIR / _url_hash(url).replace(".bin", ""))
    # yt-dlp добавит расширение сам
    final = Path(out_tmpl + ".mp4")
    if final.exists():
        return final

    logger.info(f"YouTube: {url}")
    ydl_opts = {
        "outtmpl": out_tmpl,
        "format": "bestvideo[height<=1080]+bestaudio/best",
        "merge_output_format": "mp4",
        "quiet": False,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    return final
