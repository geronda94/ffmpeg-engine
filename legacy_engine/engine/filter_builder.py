"""Построение строк filter_complex для FFmpeg."""
from __future__ import annotations
import logging

from engine.schema import Action, PipelineStep, Trim
from engine.actions import factory, build_action

logger = logging.getLogger(__name__)

def build_pipeline(
    steps: list[PipelineStep],
    resource_map: dict[str, int],
    resource_types: dict[str, str],
    fps: int = 30,
) -> tuple[list[str], dict[str, str]]:
    filters = []
    step_labels = {}

    for step in steps:
        # Входной ярлык: либо индекс ресурса, либо ярлык другого шага
        curr = f"{resource_map[step.input]}:v" if step.input in resource_map else step.input
        
        # 1. Начальная обрезка источника (если задана)
        st_trim = step.src_trim or step.trim
        if st_trim:
            nxt = f"tr_{step.id}"
            filters.append(f"[{curr}]trim=start={st_trim.start}:end={st_trim.end},setpts=PTS-STARTPTS[{nxt}]")
            curr = nxt

        # 2. Последовательное применение экшенов
        step_dur = 0
        if step.trim:
            step_dur = step.trim.end - step.trim.start

        for i, action in enumerate(step.actions):
            if not action.enabled:
                continue
            nxt = f"a_{step.id}_{i}"
            filters.append(build_action(action, curr, nxt, fps, duration=step_dur))
            curr = nxt

        # 3. Финальный перенос (Сдвиг PTS на место появления)
        out_label = step.id
        if step.trim and step.trim.start > 0:
            delay = step.trim.start
            # setpts сдвигает начало потока, format=rgba сохраняет прозрачность
            filters.append(f"[{curr}]setpts=PTS+{delay}/TB,format=rgba[{out_label}]")
        else:
            filters.append(f"[{curr}]format=rgba[{out_label}]")
            
        step_labels[step.id] = out_label

    return filters, step_labels

def build_compose(
    compose: "ComposeRoot",
    step_labels: dict[str, str],
    resource_map: dict[str, int],
    pipeline: list[PipelineStep],
) -> tuple[list[str], str]:
    """
    Строит цепочку overlay-фильтров для композиции слоёв.
    """
    filters = []
    current = step_labels[compose.base] if compose.base in step_labels else f"{resource_map[compose.base]}:v"
    
    pipeline_map = {s.id: s for s in pipeline}

    for i, layer in enumerate(compose.layers):
        src = layer.source
        top = step_labels[src] if src in step_labels else f"{resource_map[src]}:v"

        out = f"comp_{i}"
        x = str(layer.pos.x).replace(" ", "")
        y = str(layer.pos.y).replace(" ", "")
        
        step = pipeline_map.get(src)
        enable_str = ""
        if step and step.trim:
            enable_str = f":enable='between(t,{step.trim.start},{step.trim.end})'"
        
        # eof_action=pass критически важен для прозрачности и предотвращения замирания
        filters.append(f"[{current}][{top}]overlay=x={x}:y={y}{enable_str}:eof_action=pass[{out}]")
        current = out

    return filters, current
