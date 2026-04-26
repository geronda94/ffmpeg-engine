"""Построение строк filter_complex для FFmpeg."""
from __future__ import annotations
import logging
from pathlib import Path
from typing import Optional

from engine.schema import Action, PipelineStep, Trim
from engine import resolver

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Шрифт по умолчанию
# ---------------------------------------------------------------------------

# Сначала ищем пользовательский шрифт, потом системные
_DEFAULT_FONTFILE = "local_assets/default.ttf"
_SYSTEM_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/System/Library/Fonts/Helvetica.ttc",   # macOS
]


def _resolve_fontfile(override: Optional[str]) -> str:
    """
    Возвращает путь к шрифту. Порядок приоритетов:
      1. override из action.fontfile
      2. local_assets/default.ttf
      3. Системные шрифты (DejaVu, Liberation и др.)

    Если ничего не найдено — падаем с понятной ошибкой.
    """
    if override:
        try:
            resolved = resolver.resolve(override)
            # Важно: drawtext капризен к путями, используем абсолютный unix-style путь
            font_path = Path(resolved).resolve().as_posix()
            logger.debug(f"Скачанный/найденный шрифт: {font_path}")
            return font_path
        except Exception as e:
            logger.warning(f"Не удалось загрузить шрифт '{override}': {e}. Использую фоллбэк.")

    candidates = []
    candidates.append(_DEFAULT_FONTFILE)
    candidates.extend(_SYSTEM_FONT_CANDIDATES)

    for path in candidates:
        if Path(path).exists():
            font_path = Path(path).resolve().as_posix()
            logger.debug(f"Системный/Локальный шрифт: {font_path}")
            return font_path

    raise RuntimeError(
        "Шрифт для drawtext не найден!\n"
        f"  Положи любой .ttf в: {_DEFAULT_FONTFILE}\n"
        "  Или установи системные шрифты: sudo apt install fonts-dejavu"
    )


# ---------------------------------------------------------------------------
# Санитизация текста для drawtext
# ---------------------------------------------------------------------------

def _sanitize_text(text: str) -> str:
    """
    Экранирует спецсимволы FFmpeg drawtext фильтра.
    Порядок важен: сначала бэкслеш, потом остальные.
    """
    text = text.replace("\\", r"\\")   # \ → \\  (первым!)
    text = text.replace("'",  r"\'")   # ' → \'
    text = text.replace(":",  r"\:")   # : → \:
    text = text.replace(",",  r"\,")   # , → \,
    return text


# ---------------------------------------------------------------------------
# Санитизация FFmpeg-выражений (убираем пробелы)
# ---------------------------------------------------------------------------

def _expr(s: str) -> str:
    """Убирает пробелы из FFmpeg-выражений.
    Пример: '(w-text_w)/2 - 80'  →  '(w-text_w)/2-80'
    """
    return s.replace(" ", "")


# ---------------------------------------------------------------------------
# Одиночный action → строка фильтра
# ---------------------------------------------------------------------------

def build_action(a: Action, fps: int = 30) -> str:
    t = a.type

    if t == "scale_and_crop":
        return (
            f"scale={a.w}:{a.h}:force_original_aspect_ratio=increase,"
            f"crop={a.w}:{a.h}"
        )
    if t == "scale":
        return f"scale={a.w}:{a.h}"

    if t == "blur":
        s = a.sigma or 5
        return f"boxblur={s}:{s}"

    if t == "drawtext":
        text = _sanitize_text(a.text or "")
        fontfile = _resolve_fontfile(a.fontfile)
        x = _expr(a.x or "(w-text_w)/2")
        y = _expr(a.y or "(h-text_h)/2")
        size = a.fontsize or 60
        color = a.fontcolor or "white"
        base = (
            f"drawtext=fontfile='{fontfile}':text='{text}'"
            f":fontsize={size}:fontcolor={color}"
            f":x={x}:y={y}"
        )
        if a.box:
            base += f":box=1:boxcolor={a.boxcolor}:boxborderw={a.boxborderw}"
        return base

    if t == "scale_contain":
        return f"scale={a.w}:{a.h}:force_original_aspect_ratio=decrease"

    if t == "zoom":
        z_val = a.zoom or 1.1
        if a.expr:
            z_expr = a.expr
        else:
            z_expr = f"min(1+on*{(z_val-1)/(fps*10):.5f}, {z_val})"

        if a.smooth:
            # Трюк с апскейлом для устранения дрожания (Ken Burns jitter fix)
            w_hd = (a.w or 540) * 4
            h_hd = (a.h or 960) * 4
            return (
                f"scale={w_hd}:{h_hd}:flags=bicubic,format=yuv420p,"
                f"zoompan=z='{z_expr}':s={w_hd}x{h_hd}"
                f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:fps={fps},"
                f"scale={a.w or 540}:{a.h or 960}:flags=bicubic"
            )
        else:
            # Чистый нативный zoompan
            w_out = a.w or 540
            h_out = a.h or 960
            return (
                f"zoompan=z='{z_expr}':s={w_out}x{h_out}"
                f":x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':d=1:fps={fps}"
            )

    if t == "fade_in":
        st = a.start_time or 0
        if a.alpha:
            return f"format=rgba,fade=t=in:st={st}:d={a.duration or 1}:alpha=1"
        return f"fade=t=in:st={st}:d={a.duration or 1}:color={a.color}"

    if t == "fade_out":
        st = a.start_time or 0
        if a.alpha:
            return f"format=rgba,fade=t=out:st={st}:d={a.duration or 1}:alpha=1"
        return f"fade=t=out:st={st}:d={a.duration or 1}:color={a.color}"

    if t == "custom":
        return a.filter or ""

    if t == "setsar":
        return "setsar=1"

    logger.warning(f"Неизвестный action type: '{t}' — пропускаю")
    return ""



# ---------------------------------------------------------------------------
# Trim → строка фильтра
# ---------------------------------------------------------------------------

def build_trim(trim: Trim) -> str:
    parts = [f"trim=start={trim.start}"]
    if trim.end is not None:
        parts.append(f"end={trim.end}")
    
    trim_filter = ":".join(parts)
    # Сдвигаем PTS вперед на время старта, чтобы overlay поймал слой в нужное время
    return f"{trim_filter},setpts=PTS-STARTPTS+{trim.start}/TB"


# ---------------------------------------------------------------------------
# Весь pipeline → список filter-строк + маппинг id→label
# ---------------------------------------------------------------------------

def build_pipeline(
    steps: list[PipelineStep],
    resource_map: dict[str, int],
    fps: int = 30
) -> tuple[list[str], dict[str, str]]:
    filters: list[str] = []
    step_labels: dict[str, str] = {}

    for step in steps:
        idx = resource_map[step.input]
        in_label = f"{idx}:v"
        chain: list[str] = []

        # 1. Обрезка и сброс PTS в 0 (чтобы эффекты внутри сегмента работали от 0)
        if step.trim:
            chain.append(f"trim=start={step.trim.start}:end={step.trim.end}")
            chain.append("setpts=PTS-STARTPTS")

        # 2. Применяем все действия (уже в пространстве 0..duration)
        for action in step.actions:
            f = build_action(action, fps)
            if f: chain.append(f)

        # 3. Возвращаем PTS на место для overlay
        if step.trim:
            chain.append(f"setpts=PTS+{step.trim.start}/TB")

        out_label = step.id
        step_labels[step.id] = out_label
        body = ",".join(chain) if chain else "copy"
        filters.append(f"[{in_label}]{body}[{out_label}]")

    return filters, step_labels
