import logging
from pathlib import Path
from typing import Optional
from engine import resolver

logger = logging.getLogger(__name__)

_DEFAULT_FONTFILE = "local_assets/default.ttf"
_SYSTEM_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/System/Library/Fonts/Helvetica.ttc",   # macOS
]

def resolve_fontfile(override: Optional[str]) -> str:
    if override:
        try:
            resolved = resolver.resolve(override)
            return Path(resolved).resolve().as_posix()
        except Exception as e:
            logger.warning(f"Не удалось загрузить шрифт '{override}': {e}. Использую фоллбэк.")

    for path in [_DEFAULT_FONTFILE] + _SYSTEM_FONT_CANDIDATES:
        if Path(path).exists():
            return Path(path).resolve().as_posix()

    raise RuntimeError("Шрифт для drawtext не найден!")

def sanitize_text(text: str) -> str:
    return text.replace("\\", r"\\").replace("'",  r"\'").replace(":",  r"\:").replace(",",  r"\,")

def expr(s: str) -> str:
    return s.replace(" ", "")
