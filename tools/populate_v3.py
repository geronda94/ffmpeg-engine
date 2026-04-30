import os
import subprocess
import json
from pathlib import Path

# Список видео-источников (CC0/No Copyright - Новые стабильные ID)
SOURCES = [
    # SPIRITUAL
    {
        "url": "https://www.youtube.com/watch?v=Xm76w9KzB2U",
        "dest": "assets/audio_library/sfx/spiritual/church_bells_big.ogg",
        "start": "00:00:10", "duration": "10"
    },
    {
        "url": "https://www.youtube.com/watch?v=Fj-y57-a-9Y", # News/Corporate mixed
        "dest": "assets/audio_library/music/news/news_intro.ogg",
        "start": "00:00:00", "duration": "15"
    },
    # INDUSTRIAL
    {
        "url": "https://www.youtube.com/watch?v=Q-IeE7y6X78",
        "dest": "assets/audio_library/sfx/industrial/power_drill.ogg",
        "start": "00:00:02", "duration": "5"
    },
    # SCIENCE
    {
        "url": "https://www.youtube.com/watch?v=Xj3gUReM67E",
        "dest": "assets/audio_library/sfx/science/data_process.ogg",
        "start": "00:00:00", "duration": "5"
    }
]

def download_and_cut(source):
    dest = source['dest']
    url = source['url']
    start = source.get('start', '00:00:00')
    duration = source.get('duration', '10')
    
    print(f"📥 Обработка: {os.path.basename(dest)}...")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    
    cmd = [
        ".venv/bin/yt-dlp",
        "-x", "--audio-format", "vorbis",
        "--postprocessor-args", f"ffmpeg:-ss {start} -t {duration}",
        "-o", dest + ".tmp",
        "--no-check-certificate",
        url
    ]
    
    try:
        # Пытаемся скачать
        subprocess.run(cmd, check=True)
        if os.path.exists(dest + ".tmp"):
            if os.path.exists(dest): os.remove(dest)
            os.rename(dest + ".tmp", dest)
            print(f"✅ Готово: {dest}")
            return True
    except Exception as e:
        print(f"❌ Ошибка для {url}: {e}")
        return False

def main():
    print("\n" + "="*50)
    print("🎵 ULTIMATE AUDIO POPULATOR (yt-dlp Engine v1.2)")
    print("="*50 + "\n")
    
    for s in SOURCES:
        download_and_cut(s)

if __name__ == "__main__":
    main()
