import os
import subprocess
import json
from pathlib import Path

def get_audio_duration(audio_path: str) -> float:
    """Определяет точную длительность аудио через ffprobe."""
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", audio_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return float(result.stdout.strip())

def calculate_scene_timings(scenes: list, total_duration: float):
    """
    Распределяет сцены по времени пропорционально количеству слов в тексте.
    Это дает намного лучшую синхронизацию, чем просто деление на равные части.
    """
    total_words = sum(len(s["text_segment"].split()) for s in scenes)
    current_time = 0.0
    
    for scene in scenes:
        word_count = len(scene["text_segment"].split())
        # Пропорция времени
        scene_duration = (word_count / total_words) * total_duration
        
        scene["start"] = round(current_time, 2)
        scene["end"] = round(current_time + scene_duration, 2)
        current_time += scene_duration
        
    return scenes
