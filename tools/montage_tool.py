import json
import argparse
from ai.montage_agent import run_montage

def main():
    parser = argparse.ArgumentParser(description="Локальный инструмент для тестирования MoviePy монтажа")
    parser.add_argument("--audio", required=True, help="Путь к аудио-файлу")
    parser.add_argument("--images", nargs="+", required=True, help="Список изображений для сцен")
    parser.add_argument("--preset", default="smooth_story", help="ID пресета из montage_presets.json")
    parser.add_argument("--output", default="test_output.mp4", help="Путь к результату")
    
    args = parser.parse_args()

    # Загружаем пресет
    with open("config/montage_presets.json", "r", encoding="utf-8") as f:
        config = json.load(f)
    
    preset = next((s for s in config['styles'] if s['id'] == args.preset), config['styles'][0])
    
    # Формируем простые сцены для теста (равномерно распределяем время аудио)
    from ai.syncer import get_audio_duration
    total_dur = get_audio_duration(args.audio)
    scene_dur = total_dur / len(args.images)
    
    scenes = []
    for i, img in enumerate(args.images):
        scenes.append({
            "asset_path": img,
            "start": i * scene_dur,
            "end": (i + 1) * scene_dur,
            "text_segment": f"Тестовая сцена {i+1}"
        })
    
    print(f"🎬 Начинаю тестовый монтаж...")
    print(f"Пресет: {preset['name']}")
    
    success = run_montage(scenes, args.audio, args.output, preset)
    
    if success:
        print(f"✅ Готово! Результат: {args.output}")
    else:
        print(f"❌ Ошибка монтажа.")

if __name__ == "__main__":
    main()
