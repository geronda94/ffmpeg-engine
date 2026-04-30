import os
import requests
import json
import time
from pathlib import Path

# Список ресурсов с OpenGameArt и других стабильных CC0 площадок
AUDIO_SOURCES = [
    # MUSIC
    {
        "url": "https://archive.org/download/K_M_L_E_D/Kevin%20MacLeod%20-%20Epic%20Dramatic.mp3",
        "dest": "assets/audio_library/music/cinematic_epic.mp3"
    },
    {
        "url": "https://archive.org/download/LofiHiphop_201901/Lofi%20Hiphop.mp3",
        "dest": "assets/audio_library/music/lofi_relax.mp3"
    },
    
    # SFX NATURE (OpenGameArt / Stable Wikimedia)
    {
        "url": "https://opengameart.org/sites/default/files/wind_loop.wav",
        "dest": "assets/audio_library/sfx/nature/wind_mountains.wav"
    },
    {
        "url": "https://opengameart.org/sites/default/files/forest_ambience.wav",
        "dest": "assets/audio_library/sfx/nature/forest_birds.wav"
    },
    {
        "url": "https://opengameart.org/sites/default/files/sea_waves_0.mp3",
        "dest": "assets/audio_library/sfx/nature/ocean_waves.mp3"
    },
    
    # SFX TRANSITIONS & UI
    {
        "url": "https://opengameart.org/sites/default/files/whoosh.wav",
        "dest": "assets/audio_library/sfx/transitions/whoosh_clean.wav"
    },
    {
        "url": "https://opengameart.org/sites/default/files/collision_glitch.wav",
        "dest": "assets/audio_library/sfx/transitions/glitch_short.wav"
    },
    {
        "url": "https://opengameart.org/sites/default/files/ui_pop.wav",
        "dest": "assets/audio_library/sfx/ui/pop_clean.wav"
    },
    {
        "url": "https://opengameart.org/sites/default/files/cash_register.wav",
        "dest": "assets/audio_library/sfx/ui/cash_register.wav"
    },
    {
        "url": "https://opengameart.org/sites/default/files/ding.wav",
        "dest": "assets/audio_library/sfx/ui/ding_success.wav"
    }
]

def download_file(url, dest):
    print(f"📥 Скачиваю: {os.path.basename(dest)}...")
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        headers = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        response = requests.get(url, headers=headers, stream=True, timeout=60)
        
        if response.status_code == 200:
            with open(dest, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            print(f"✅ Готово: {dest}")
            return True
        else:
            print(f"⚠️ Ошибка {response.status_code} для {url}")
            return False
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return False

def main():
    print("\n" + "="*50)
    print("🎵 AUDIO POPULATOR 3.0 (Permissive Sources)")
    print("="*50 + "\n")
    
    success_count = 0
    for source in AUDIO_SOURCES:
        if download_file(source['url'], source['dest']):
            success_count += 1
            
    print(f"\n🚀 Итог: Скачано {success_count}/{len(AUDIO_SOURCES)} файлов.")

if __name__ == "__main__":
    main()
