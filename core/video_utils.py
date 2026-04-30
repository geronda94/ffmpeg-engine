import subprocess
import os
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

def get_video_info(file_path):
    """Получает информацию о видео (длительность, ширина, высота)."""
    try:
        cmd = [
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration:stream=width,height',
            '-of', 'default=noprint_wrappers=1:nokey=1', str(file_path)
        ]
        output = subprocess.check_output(cmd).decode('utf-8').split()
        if len(output) >= 3:
            return {
                "duration": float(output[2]),
                "width": int(output[0]),
                "height": int(output[1])
            }
    except Exception as e:
        logger.error(f"Error getting video info: {e}")
    return None

def generate_storyboard(video_path, output_path, start_time=0, count=9, interval=5):
    """
    Генерирует сетку кадров 3x3 с учетом длительности видео.
    """
    info = get_video_info(video_path)
    duration = info['duration'] if info else 0
    
    temp_dir = Path("temp/storyboard")
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    frames = []
    for i in range(count):
        t = start_time + (i * interval)
        if duration and t >= duration:
            break
            
        frame_path = temp_dir / f"frame_{i}.jpg"
        
        # Экстракция кадра с наложением таймстемпа на плашке
        timestamp_str = f"{int(t // 60):02d}:{int(t % 60):02d}"
        
        # Сначала масштабируем, потом рисуем текст, потом выравниваем в квадрат
        # box=1 - включает подложку, boxborderw=5 - отступы подложки
        vf = (
            f"scale=400:400:force_original_aspect_ratio=increase,crop=400:400,"
            f"drawtext=text='{timestamp_str}':fontcolor=white:fontsize=36:"
            f"box=1:boxcolor=black@0.6:boxborderw=10:x=20:y=20"
        )
        
        cmd = [
            'ffmpeg', '-y', '-ss', str(t), '-i', str(video_path),
            '-frames:v', '1', '-vf', vf, str(frame_path)
        ]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if frame_path.exists():
                frames.append(str(frame_path))
        except:
            continue

    # Сборка в сетку через фильтр tile
    # Чтобы tile работал корректно с отдельными файлами, мы используем concat или последовательность
    # Но проще всего - использовать фильтр xstack, если мы знаем количество
    num_frames = len(frames)
    if num_frames == 0: return None
    
    # Для стабильности используем метод объединения через 'tile' из видео-потока
    # Создаем временный список файлов для ffmpeg
    list_path = temp_dir / "files.txt"
    with open(list_path, "w") as f:
        for fp in frames:
            f.write(f"file '{os.path.abspath(fp)}'\n")
            
    cmd = [
        'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(list_path),
        '-vf', 'tile=3x3:padding=10:color=white', str(output_path)
    ]
    
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Чистим временные файлы
        if list_path.exists(): os.remove(list_path)
        for f in frames:
            if os.path.exists(f): os.remove(f)
        return str(output_path)
    except Exception as e:
        logger.error(f"Error creating storyboard: {e}")
        return None

def extract_single_frame(video_path, output_path, timestamp):
    """Извлекает один кадр для превью подтверждения."""
    cmd = [
        'ffmpeg', '-y', '-ss', str(timestamp), '-i', str(video_path),
        '-frames:v', '1', '-q:v', '2', str(output_path)
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return str(output_path)
    except Exception as e:
        logger.error(f"Error extracting single frame: {e}")
        return None
