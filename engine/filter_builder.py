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

_DEFAULT_FONTFILE = "local_assets/default.ttf"
_SYSTEM_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/System/Library/Fonts/Helvetica.ttc",   # macOS
]

def _resolve_fontfile(override: Optional[str]) -> str:
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

def _sanitize_text(text: str) -> str:
    return text.replace("\\", r"\\").replace("'",  r"\'").replace(":",  r"\:").replace(",",  r"\,")

def _expr(s: str) -> str:
    return s.replace(" ", "")

# ---------------------------------------------------------------------------
# Продвинутая плашка (Plate / Glassmorphism / Rounding)
# ---------------------------------------------------------------------------

def _build_plate_action(a: Action, in_label: str, out_label: str) -> str:
    """
    Создает сложную плашку с поддержкой Glassmorphism и скруглений.
    Алгоритм:
    1. Split на фон и кусок для обработки.
    2. Crop + Blur + Color + Border для куска.
    3. Применение маски для скругления углов.
    4. Overlay обратно на фон.
    """
    w = a.w or 400
    h = a.h or 100
    x = _expr(a.x or "(W-w)/2")
    y = _expr(a.y or "(H-h)/2")
    
    # Метки для внутреннего графа
    l_orig = f"{out_label}_orig"
    l_blur = f"{out_label}_blur"
    l_mask = f"{out_label}_mask"
    l_final_box = f"{out_label}_box"

    # 1. Разделение и подготовка
    chain = [f"[{in_label}]split[ {l_orig} ][ {l_blur} ]"]

    # 2. Эффект стекла и заливка
    proc = f"[{l_blur}]crop={w}:{h}:{x}:{y}"
    if a.blur:
        proc += f",boxblur={a.blur}:{a.blur}"
    
    # Наложение цвета (плашка)
    color = a.boxcolor or "black@0.5"
    proc += f",drawbox=x=0:y=0:w={w}:h={h}:color={color}:t=fill"
    
    # Рамка
    if a.border_width:
        b_color = a.border_color or "white"
        proc += f",drawbox=x=0:y=0:w={w}:h={h}:color={b_color}:t={a.border_width}"
    
    proc += f"[{l_mask}]"
    chain.append(proc)

    # 3. Скругление углов (если есть radius)
    if a.radius:
        r = a.radius
        # Формула для geq маски
        geq_expr = (
            f"if("
            f" (x<{r} && y<{r} && (pow({r}-x,2)+pow({r}-y,2))>pow({r},2)) || "
            f" (x>{w}-{r} && y<{r} && (pow(x-({w}-{r}),2)+pow({r}-y,2))>pow({r},2)) || "
            f" (x<{r} && y>{h}-{r} && (pow({r}-x,2)+pow(y-({h}-{r}),2))>pow({r},2)) || "
            f" (x>{w}-{r} && y>{h}-{r} && (pow(x-({w}-{r}),2)+pow(y-({h}-{r}),2))>pow({r},2))"
            f", 0, 255)"
        )
        chain.append(f"[{l_mask}]format=rgba,geq=a='{geq_expr}'[{l_final_box}]")
    else:
        chain.append(f"[{l_mask}]copy[{l_final_box}]")

    # 4. Финальный Overlay
    chain.append(f"[{l_orig}][{l_final_box}]overlay={x}:{y}[{out_label}]")
    
    return ";".join(chain)

# ---------------------------------------------------------------------------
# Построение action
# ---------------------------------------------------------------------------

def build_action(a: Action, in_label: str, out_label: str, fps: int = 30) -> str:
    t = a.type
    
    # Простые фильтры (можно объединять через запятую, но для чистоты рефакторинга сделаем единообразно)
    def simple(f_str: str):
        return f"[{in_label}]{f_str}[{out_label}]"

    if t == "plate":
        return _build_plate_action(a, in_label, out_label)

    if t == "scale_and_crop":
        return simple(f"scale={a.w}:{a.h}:force_original_aspect_ratio=increase,crop={a.w}:{a.h}")
    
    if t == "scale":
        return simple(f"scale={a.w}:{a.h}")

    if t == "blur":
        s = a.sigma or 5
        return simple(f"boxblur={s}:{s}")

    if t == "drawtext":
        text = _sanitize_text(a.text or "")
        fontfile = _resolve_fontfile(a.fontfile)
        x = _expr(a.x or "(w-text_w)/2")
        y = _expr(a.y or "(h-text_h)/2")
        size = a.fontsize or 60
        color = a.fontcolor or "white"
        base = f"drawtext=fontfile='{fontfile}':text='{text}':fontsize={size}:fontcolor={color}:x={x}:y={y}"
        if a.box:
            base += f":box=1:boxcolor={a.boxcolor}:boxborderw={a.boxborderw}"
        return simple(base)

    if t == "zoom":
        z_val = a.zoom or 1.1
        z_expr = a.expr or f"min(1+on*{(z_val-1)/(fps*10):.5f}, {z_val})"
        if a.smooth:
            w_hd, h_hd = (a.w or 540) * 4, (a.h or 960) * 4
            return simple(
                f"scale={w_hd}:{h_hd}:flags=bicubic,format=yuv420p,"
                f"zoompan=z='{z_expr}':s={w_hd}x{h_hd}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:fps={fps},"
                f"scale={a.w or 540}:{a.h or 960}:flags=bicubic"
            )
        else:
            w_out, h_out = a.w or 540, a.h or 960
            return simple(f"zoompan=z='{z_expr}':s={w_out}x{h_out}:x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':d=1:fps={fps}")

    if t == "fade_in":
        st = a.start_time or 0
        f = f"fade=t=in:st={st}:d={a.duration or 1}"
        if a.alpha: f = f"format=rgba,{f}:alpha=1"
        else: f += f":color={a.color}"
        return simple(f)

    if t == "fade_out":
        st = a.start_time or 0
        f = f"fade=t=out:st={st}:d={a.duration or 1}"
        if a.alpha: f = f"format=rgba,{f}:alpha=1"
        else: f += f":color={a.color}"
        return simple(f)

    if t == "custom":
        return simple(a.filter or "copy")

    if t == "setsar":
        return simple("setsar=1")

    return simple("copy")

# ---------------------------------------------------------------------------
# Сборка пайплайна
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
        curr = f"{idx}:v"
        
        # 1. Trim
        if step.trim:
            nxt = f"tr_{step.id}"
            filters.append(f"[{curr}]trim=start={step.trim.start}:end={step.trim.end},setpts=PTS-STARTPTS[{nxt}]")
            curr = nxt

        # 2. Actions
        for i, action in enumerate(step.actions):
            nxt = f"a_{step.id}_{i}"
            filters.append(build_action(action, curr, nxt, fps))
            curr = nxt

        # 3. Final PTS restore and output label
        out_label = step.id
        if step.trim:
            filters.append(f"[{curr}]setpts=PTS+{step.trim.start}/TB[{out_label}]")
        else:
            filters.append(f"[{curr}]copy[{out_label}]")
            
        step_labels[step.id] = out_label

    return filters, step_labels
