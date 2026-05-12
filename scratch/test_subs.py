import sys
import os

# Добавляем корень проекта в путь
sys.path.append(os.getcwd())

from ai.subtitle_agent import generate_ass_from_project

# Тестовые данные
scenes = [
    {"text_segment": "Hello this is a test of the new animation logic", "start": 0, "end": 5, "allow_montage_effects": True}
]
whisper_segments = [
    {"start": 0, "end": 1, "text": "Hello this"},
    {"start": 1, "end": 2, "text": "is a test"},
    {"start": 2, "end": 3, "text": "of the new"},
    {"start": 3, "end": 4, "text": "animation"},
    {"start": 4, "end": 5, "text": "logic"}
]

output_path = "scratch/test_subtitles.ass"
res = generate_ass_from_project(scenes, whisper_segments, output_path)

if res:
    print(f"ASS generated: {res}")
    with open(res, "r") as f:
        print(f.read())
else:
    print("Failed to generate ASS")
