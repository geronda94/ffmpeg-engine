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
from engine.schema import AudioTrack, ComposeRoot, Task

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
            # Принудительно задаем формат rgba для поддержки прозрачности в lavfi
            source = res.source
            if "format=" not in source:
                source = f"{source},format=rgba"
            inputs.extend(["-f", "lavfi", "-i", source])
        elif res.type == "image":
            path = resolver.resolve(res.source)
            inputs.extend(["-loop", "1", "-framerate", str(task.output.fps), "-i", str(path)])
        elif res.type == "loop_video":
            # Бесконечное зацикливание для GIF и анимированных плашек (WebM)
            path = resolver.resolve(res.source)
            inputs.extend(["-stream_loop", "-1", "-i", str(path)])
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
        
        # eof_action=pass предотвращает остановку рендера при окончании коротких клипов
        filters.append(f"[{current}][{top}]overlay={x}:{y}:eof_action=pass[{out}]")
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
    tracks: list[AudioTrack],
    steps: list[PipelineStep],
    resource_map: dict[str, int],
    resource_types: dict[str, str],
    duration: float | None = None,
) -> tuple[list[str], str | None]:
    """
    Строит аудио-фильтры для микширования:
    - Явных аудио-дорожек из Task.audio
    - Звука из слоев PipelineStep (если volume > 0)
    """
    filters: list[str] = []
    track_labels: list[str] = []

    # 1. Звук из слоев видео (PipelineSteps)
    for i, step in enumerate(steps):
        # Пропускаем, если громкость 0 или ресурс не поддерживает звук
        res_type = resource_types.get(step.input, "video")
        if step.volume <= 0 or res_type in ["image", "lavfi"]:
            continue
            
        idx = resource_map[step.input]
        l_in = f"{idx}:a"
        l_out = f"a_step_{i}"
        
        chain: list[str] = []
        
        # Обрезка звука синхронно с видео
        st_trim = step.src_trim or step.trim
        if st_trim:
            chain.append(f"atrim=start={st_trim.start}:end={st_trim.end},asetpts=PTS-STARTPTS")
        
        # Громкость слоя
        if step.volume != 1.0:
            chain.append(f"volume={step.volume}")
            
        # Задержка звука (чтобы совпадало с появлением слоя в Compose)
        if step.trim and step.trim.start > 0:
            ms = int(step.trim.start * 1000)
            chain.append(f"adelay={ms}|{ms}")
            
        label = l_out
        track_labels.append(label)
        body = ",".join(chain) if chain else "anull"
        filters.append(f"[{l_in}]{body}[{label}]")

    # 2. Явные аудио-дорожки (Music, SFX)
    for i, track in enumerate(tracks):
        idx = resource_map[track.source]
        l_in = f"{idx}:a"
        l_out = f"a_track_{i}"
        
        chain: list[str] = []

        if track.volume != 1.0:
            chain.append(f"volume={track.volume}")
        
        if track.fade_in > 0:
            chain.append(f"afade=t=in:st=0:d={track.fade_in}")
        
        if track.fade_out > 0 and duration:
            st = max(0, duration - track.fade_out)
            chain.append(f"afade=t=out:st={st}:d={track.fade_out}")

        if track.start > 0:
            ms = int(track.start * 1000)
            chain.append(f"adelay={ms}|{ms}")

        label = l_out
        track_labels.append(label)
        body = ",".join(chain) if chain else "anull"
        filters.append(f"[{l_in}]{body}[{label}]")

    if not track_labels:
        return [], None

    # 3. Смешивание (Mix)
    final_label = "audio_out"
    inputs_str = "".join(f"[{l}]" for l in track_labels)
    # normalize=0 отключает автоматическое понижение громкости
    filters.append(f"{inputs_str}amix=inputs={len(track_labels)}:duration=first:dropout_transition=0:normalize=0[{final_label}]")

    return filters, final_label


# ---------------------------------------------------------------------------
# Главная сборка
# ---------------------------------------------------------------------------

def assemble(task: Task, dry_run: bool = False) -> bool:
    # 0. Подготовка временной папки
    ok = False
    _resolve_presets(task)
    temp_dir = Path("temp_render")
    resolver.init_session(temp_dir)
    Path("output").mkdir(exist_ok=True)

    try:
        # 1. Входы
        inputs, resource_map = _build_inputs(task)
        resource_types = {r.id: r.type for r in task.resources}

        # 2. Pipeline (обработка каждого слоя)
        pipeline_filters, step_labels = filter_builder.build_pipeline(
            task.pipeline, resource_map, resource_types, task.output.fps
        )

        # 3. Compose (наложение слоёв)
        compose_filters, final_video = filter_builder.build_compose(
            task.compose, step_labels, resource_map, task.pipeline
        )

        # 3.1 format=yuv420p — финализация цветового пространства
        final_video_out = "final_video_stream"
        compose_filters.append(f"[{final_video}]format=yuv420p[{final_video_out}]")
        final_video = final_video_out

        # 4. Audio
        audio_filters: list[str] = []
        final_audio: str | None = None
        if task.audio or any(s.volume > 0 for s in task.pipeline):
            audio_filters, final_audio = _build_audio_filter(
                task.audio, task.pipeline, resource_map, resource_types, task.output.duration
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
        
        logger.info("--- FULL FFMPEG COMMAND ---")
        logger.info(" ".join(cmd))
        
        cmd += ["-map", f"[{final_video}]"]

        if final_audio:
            cmd += ["-map", f"[{final_audio}]"]

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

        ok = runner.run(cmd, dry_run=dry_run)
        return ok
    finally:
        if not dry_run and ok and temp_dir.exists():
            logger.info(f"Очистка временных файлов: {temp_dir}")
            shutil.rmtree(temp_dir)
        elif not ok:
            logger.warning(f"Рендер не удался. Временные файлы сохранены в: {temp_dir}")


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
