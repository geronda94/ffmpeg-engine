"""Запуск FFmpeg: автодетект GPU-кодека, обработка ошибок."""
from __future__ import annotations
import logging
import shutil
import subprocess

logger = logging.getLogger(__name__)

# Приоритет: Intel QSV → NVIDIA NVENC → AMD AMF → CPU
_HW_CANDIDATES = [
    ("qsv",  "h264_qsv"),
    ("cuda", "h264_nvenc"),
    ("amf",  "h264_amf"),
]


def detect_encoder() -> str:
    """Тестирует доступные энкодеры и возвращает лучший."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg не найден в PATH. Установи ffmpeg.")

    result = subprocess.run(
        ["ffmpeg", "-hwaccels"], capture_output=True, text=True
    )
    hwaccels_output = result.stdout + result.stderr

    for hwaccel, encoder in _HW_CANDIDATES:
        if hwaccel not in hwaccels_output:
            continue
        # Реальный тест: кодируем 1 фрейм
        test = subprocess.run(
            [
                "ffmpeg", "-f", "lavfi", "-i", "nullsrc=s=64x64:d=0.1",
                "-c:v", encoder, "-f", "null", "-",
            ],
            capture_output=True,
        )
        if test.returncode == 0:
            logger.info(f"Аппаратный кодек: {encoder}")
            return encoder

    logger.info("GPU не найден, использую libx264 (CPU)")
    return "libx264"


def run(cmd: list[str], dry_run: bool = False) -> bool:
    """
    Запускает FFmpeg команду.
    dry_run=True — только печатает команду, не выполняет.
    """
    cmd_str = " ".join(cmd)
    logger.debug(f"Команда: {cmd_str}")

    if dry_run:
        print("\n🔍 DRY RUN — команда (не выполняется):")
        print(cmd_str)
        return True

    print(f"\n🎬 Запуск FFmpeg...")
    
    # Запускаем процесс с пробросом stdout/stderr
    with subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True
    ) as process:
        # Читаем вывод построчно и печатаем
        for line in process.stdout:
            print(line, end="")
            
        process.wait()

    if process.returncode != 0:
        logger.error(f"FFmpeg завершился с ошибкой (код {process.returncode})")
        print(f"\n❌ FFmpeg error (код {process.returncode})")
        return False

    print("✅ Готово!")
    return True
