"""
FFmpeg Video Assembly Engine
Точка входа: python main.py --task tasks/demo.json [--dry-run]
"""
from __future__ import annotations
import argparse
import json
import logging
import sys
from pathlib import Path
import shutil

from pydantic import ValidationError

from engine import filter_builder, resolver, runner
from engine.schema import AudioConfig, ComposeRoot, Task

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _resolve_presets(task: Task):
    """
    Для каждого шага пайплайна, если указан preset, 
    добавляет экшены из пресета в начало списка действий шага.
    """
    for step in task.pipeline:
        if step.preset and step.preset in task.presets:
            # Добавляем экшены из пресета ПЕРЕД локальными экшенами
            preset_actions = task.presets[step.preset]
            step.actions = preset_actions + step.actions
        elif step.preset:
            logger.warning(f"Пресет '{step.preset}' не найден в секции presets!")


def _build_inputs(task: Task) -> tuple[list[str], dict[str, int]]:
    """
    Резолвит все ресурсы и строит список аргументов -i для FFmpeg.
    Возвращает (input_args, resource_map: id → input_index).
    """
    inputs: list[str] = []
    resource_map: dict[str, int] = {}

    for idx, res in enumerate(task.resources):
        if res.type == "lavfi":
            # Встроенный генератор FFmpeg — файл не нужен
            inputs.extend(["-f", "lavfi", "-i", res.source])
        elif res.type == "image":
            # -loop 1 — PNG/JPG без этого флага даёт 1 кадр и оверлей не совпадёт по длительности
            path = resolver.resolve(res.source)
            inputs.extend(["-loop", "1", "-framerate", str(task.output.fps), "-i", str(path)])
        else:
            path = resolver.resolve(res.source)
            inputs.extend(["-i", str(path)])

        resource_map[res.id] = idx

    return inputs, resource_map


def _build_compose(
    compose: ComposeRoot,
    step_labels: dict[str, str],
    resource_map: dict[str, int],
    pipeline: list[PipelineStep],
) -> tuple[list[str], str]:
    """
    Строит цепочку overlay-фильтров для композиции слоёв.
    Возвращает (filter_strings, label финального видеопотока).
    """
    filters: list[str] = []
    current = step_labels[compose.base]

    # Карта таймингов слоев (из pipeline)
    timings = {step.id: step.trim for step in pipeline}

    for i, layer in enumerate(compose.layers):
        src = layer.source
        if src in step_labels:
            top = step_labels[src]
        elif src in resource_map:
            top = f"{resource_map[src]}:v"
        else:
            raise ValueError(
                f"Источник слоя '{src}' не найден ни в pipeline, ни в resources."
            )

        out = f"comp_{i}"
        x = layer.pos.x.replace(" ", "")
        y = layer.pos.y.replace(" ", "")
        
        # Оптимизация: отключаем отработавшие слои через enable
        enable_str = ""
        if src in timings and timings[src]:
            trim = timings[src]
            if trim.end:
                enable_str = f":enable='between(t\\,{trim.start}\\,{trim.end})'"
            else:
                enable_str = f":enable='gte(t\\,{trim.start})'"

        filters.append(f"[{current}][{top}]overlay={x}:{y}{enable_str}[{out}]")
        current = out

    return filters, current


def _add_format(filters: list[str], video_label: str) -> tuple[list[str], str]:
    """
    Добавляет format=yuv420p после всей цепочки compose.
    Это гарантирует совместимость с кодеком и правильную цветовую модель
    при любом количестве слоёв (в т.ч. при пустом compose.layers).
    """
    out_label = "vout"
    filters.append(f"[{video_label}]format=yuv420p[{out_label}]")
    return filters, out_label


def _build_audio_filter(
    audio: AudioConfig,
    resource_map: dict[str, int],
    duration: float | None = None,
) -> tuple[list[str], str | None]:
    """
    Строит аудио-фильтры.
    source может быть resource типа 'audio' ИЛИ 'video' (вытаскиваем аудиодорожку).
    Если фильтров нет — возвращает ([], None) и используется прямой маппинг.
    """
    needs_filter = audio.volume != 1.0 or audio.fade_in > 0 or audio.fade_out > 0
    if not needs_filter:
        return [], None

    idx = resource_map[audio.source]
    chain: list[str] = []

    if audio.volume != 1.0:
        chain.append(f"volume={audio.volume}")
    if audio.fade_in > 0:
        chain.append(f"afade=t=in:st=0:d={audio.fade_in}")
    if audio.fade_out > 0 and duration:
        # st = длительность - время затухания
        st = max(0, duration - audio.fade_out)
        chain.append(f"afade=t=out:st={st}:d={audio.fade_out}")

    label = "audio_out"
    return [f"[{idx}:a]{','.join(chain)}[{label}]"], label


# ---------------------------------------------------------------------------
# Главная сборка
# ---------------------------------------------------------------------------

def assemble(task: Task, dry_run: bool = False) -> bool:
    # 0. Подготовка временной папки
    _resolve_presets(task)
    temp_dir = Path("temp_render")
    resolver.init_session(temp_dir)
    Path("output").mkdir(exist_ok=True)

    try:
        # 1. Входы
        inputs, resource_map = _build_inputs(task)

        # 2. Pipeline (обработка каждого слоя)
        pipeline_filters, step_labels = filter_builder.build_pipeline(
            task.pipeline, resource_map, task.output.fps
        )

        # 3. Compose (наложение слоёв)
        compose_filters, final_video = _build_compose(
            task.compose, step_labels, resource_map, task.pipeline
        )

        # 3.1 format=yuv420p — финализация цветового пространства
        compose_filters, final_video = _add_format(compose_filters, final_video)

        # 4. Audio
        audio_filters: list[str] = []
        final_audio: str | None = None
        if task.audio:
            audio_filters, final_audio = _build_audio_filter(
                task.audio, resource_map, task.output.duration
            )

        # 5. Собираем filter_complex
        all_filters = pipeline_filters + compose_filters + audio_filters
        filter_complex = ";".join(all_filters)

        if dry_run:
            logger.info("--- DRY RUN: Сгенерированный filter_complex ---")
            logger.info(filter_complex)

        # 6. Кодек
        codec = (
            runner.detect_encoder()
            if task.output.codec == "auto"
            else task.output.codec
        )

        # 7. Финальная команда
        cmd = ["ffmpeg", "-y"]
        cmd.extend(inputs)
        cmd += ["-filter_complex", filter_complex]
        cmd += ["-map", f"[{final_video}]"]

        if final_audio:
            cmd += ["-map", f"[{final_audio}]"]
        elif task.audio:
            audio_idx = resource_map[task.audio.source]
            # Используем :a:0 — работает как для audio-ресурсов, так и для video
            # (видеофайл может содержать аудиодорожку, берём первую)
            cmd += ["-map", f"{audio_idx}:a:0"]

        cmd += ["-c:v", codec]
        if codec == "libx264":
            cmd += ["-preset", task.output.preset, "-crf", str(task.output.crf)]

        if task.audio:
            cmd += ["-c:a", "aac", "-b:a", "192k"]

        cmd += ["-r", str(task.output.fps)]

        # Логика ограничения длительности
        if task.output.duration:
            # Принудительная длительность секвенции
            cmd += ["-t", str(task.output.duration)]
        else:
            # Авто-обрезка по самому короткому потоку
            cmd += ["-shortest"]

        cmd.append(task.output.path)

        return runner.run(cmd, dry_run=dry_run)
    finally:
        if not dry_run and temp_dir.exists():
            logger.info(f"Очистка временных файлов: {temp_dir}")
            shutil.rmtree(temp_dir)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="FFmpeg Video Assembly Engine — собирает видео по JSON-заданию"
    )
    parser.add_argument(
        "--task", required=True,
        help="Путь к JSON-файлу задания (например: tasks/demo.json)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Только вывести команду FFmpeg, не запускать"
    )
    parser.add_argument(
        "--output", default=None,
        help="Переопределить путь к выходному файлу"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Подробный лог (DEBUG)"
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Загрузка и валидация задания
    task_path = Path(args.task)
    if not task_path.exists():
        print(f"❌ Файл задания не найден: {task_path}")
        sys.exit(1)

    try:
        raw = json.loads(task_path.read_text(encoding="utf-8"))
        task = Task.model_validate(raw)
    except ValidationError as e:
        print(f"❌ Ошибка валидации JSON:\n{e}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"❌ Невалидный JSON: {e}")
        sys.exit(1)

    if args.output:
        task.output.path = args.output

    logger.info(f"Задание загружено: {task_path.name}")
    logger.info(f"Выход: {task.output.path}")

    ok = assemble(task, dry_run=args.dry_run)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
