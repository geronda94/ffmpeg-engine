import sys
import os

# Add project root to path
sys.path.append("/home/goga/Рабочий стол/Projects/ffmpeg")

from ai.subtitle_agent import generate_ass_from_project

scenes = [
    {
        'start': 0,
        'end': 5,
        'text_segment': 'Покаяние это не просто слова.',
        'allow_montage_effects': True,
        'subtitle_style': {
            'primary_color': '#f7ec20',
            'secondary_color': '#FFFFFF',
            'outline_color': '#141416',
            'shadow_color': '#000000',
            'outline_width': 2.5,
            'shadow_width': 0
        }
    }
]

# Mock Whisper segments
whisper_segments = [{'start': 0.0, 'end': 5.0}]

# Mock Aligned words (with a pause after the first word)
aligned_words = [
    {
        "words": [
            {"word": "Покаяние", "start": 1.0, "end": 1.8},
            {"word": "это", "start": 2.5, "end": 2.8}, # Pause here
            {"word": "не", "start": 2.9, "end": 3.1},
            {"word": "просто", "start": 3.2, "end": 3.6},
            {"word": "слова", "start": 3.7, "end": 4.5}
        ]
    }
]

output_path = "/home/goga/Рабочий стол/Projects/ffmpeg/scratch/test_sync.ass"
res = generate_ass_from_project(scenes, whisper_segments, output_path, aligned_words=aligned_words)

if res:
    print(f"ASS generated at: {res}")
    with open(res, 'r', encoding='utf-8-sig') as f:
        print(f.read())
else:
    print("Failed to generate ASS")
