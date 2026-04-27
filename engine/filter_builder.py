"""Построение строк filter_complex для FFmpeg."""
from __future__ import annotations
import logging

from engine.schema import Action, PipelineStep, Trim
from engine.actions import factory

logger = logging.getLogger(__name__)

def build_action(a: Action, in_label: str, out_label: str, fps: int = 30) -> str:
    """Делегирует построение экшена специализированному билдеру."""
    builder = factory.get_builder(a.type)
    return builder.build(a, in_label, out_label, fps)

def build_pipeline(
    steps: list[PipelineStep],
    resource_map: dict[str, int],
    fps: int = 30
) -> tuple[list[str], dict[str, str]]:
    """Собирает пайплайн из независимых шагов в единый граф фильтров."""
    filters: list[str] = []
    step_labels: dict[str, str] = {}

    for step in steps:
        idx = resource_map[step.input]
        curr = f"{idx}:v"
        
        # 1. Trim и сброс PTS (чтобы эффекты внутри шага работали от 0)
        if step.trim:
            nxt = f"tr_{step.id}"
            filters.append(f"[{curr}]trim=start={step.trim.start}:end={step.trim.end},setpts=PTS-STARTPTS[{nxt}]")
            curr = nxt

        # 2. Последовательное применение экшенов
        for i, action in enumerate(step.actions):
            nxt = f"a_{step.id}_{i}"
            filters.append(build_action(action, curr, nxt, fps))
            curr = nxt

        # 3. Финальный перенос PTS на место для overlay
        out_label = step.id
        if step.trim:
            filters.append(f"[{curr}]setpts=PTS+{step.trim.start}/TB[{out_label}]")
        else:
            # Если не было обрезки, просто помечаем текущий поток именем шага
            filters.append(f"[{curr}]copy[{out_label}]")
            
        step_labels[step.id] = out_label

    return filters, step_labels
