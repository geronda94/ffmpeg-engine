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
    resource_types: dict[str, str],
    fps: int = 30
) -> tuple[list[str], dict[str, str]]:
    """Собирает пайплайн из независимых шагов в единый граф фильтров."""
    filters: list[str] = []
    step_labels: dict[str, str] = {}

    for step in steps:
        idx = resource_map[step.input]
        res_type = resource_types.get(step.input, "video")
        curr = f"{idx}:v"
        
        # Для слоев с прозрачностью или картинок сразу переходим в RGBA
        if res_type in ["image", "lavfi"] or step.id.startswith("overlay"):
            nxt = f"rgba_{step.id}"
            filters.append(f"[{curr}]format=rgba[{nxt}]")
            curr = nxt

        # Зацикливаем статические изображения с исправлением PTS (таймлайна)
        if res_type == "image":
            nxt = f"loop_{step.id}"
            filters.append(f"[{curr}]loop=loop=-1:size=1:start=0,setpts=N/{fps}/TB[{nxt}]")
            curr = nxt
        
        # 1. Trim и сброс PTS (чтобы эффекты внутри шага работали от 0)
        # Используем src_trim для выбора фрагмента источника, или обычный trim если src_trim нет
        st_trim = step.src_trim or step.trim
        if st_trim:
            nxt = f"tr_{step.id}"
            filters.append(f"[{curr}]trim=start={st_trim.start}:end={st_trim.end},setpts=PTS-STARTPTS[{nxt}]")
            curr = nxt

        # 2. Последовательное применение экшенов
        for i, action in enumerate(step.actions):
            nxt = f"a_{step.id}_{i}"
            filters.append(build_action(action, curr, nxt, fps))
            curr = nxt

        # 3. Финальный перенос PTS на место для overlay (через tpad для совместимости)
        out_label = step.id
        if step.trim and step.trim.start > 0:
            delay = step.trim.start
            # color=black@0 гарантирует прозрачность
            filters.append(f"[{curr}]tpad=start_duration={delay}:color=black@0[{out_label}]")
        else:
            # Если задержки нет, просто помечаем текущий поток именем шага
            filters.append(f"[{curr}]copy[{out_label}]")
            
        step_labels[step.id] = out_label

    return filters, step_labels
