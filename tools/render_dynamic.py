import os
import sys
import json
from pathlib import Path

# Добавляем корень проекта в путь
sys.path.append(str(Path(__file__).resolve().parent.parent))

from ai.dynamic_scene_agent import render_dynamic_scene

def load_config():
    config_path = Path(__file__).resolve().parent.parent / "config" / "dynamic_scenes.json"
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)

def main():
    print("\n" + "="*50)
    print("🎭 CONTENT FACTORY: DYNAMIC SCENE BUILDER (CLI)")
    print("="*50)

    try:
        config = load_config()
    except Exception as e:
        print(f"❌ Ошибка загрузки конфига: {e}")
        return

    # 1. Выбор пресета по цифре
    print("\nВыберите пресет для рендеринга:")
    for i, p in enumerate(config['presets'], 1):
        print(f"{i}. {p['name']} — {p['description']}")
    
    try:
        choice = int(input("\nВведите номер: ")) - 1
        if choice < 0 or choice >= len(config['presets']):
            raise ValueError
    except ValueError:
        print("❌ Неверный номер пресета.")
        return

    preset = config['presets'][choice]
    print(f"\n✅ Выбран пресет: {preset['name']}")
    print("-" * 30)

    # 2. Пошаговый сбор данных на основе элементов пресета
    elements = {}
    for elem in preset['elements']:
        prompt = f"👉 Введите {elem['name']}"
        if elem['type'] in ['media', 'photo', 'video']:
            prompt += " (путь к файлу): "
        else:
            prompt += " (текст): "
        
        val = input(prompt).strip()
        
        # Минимальная проверка файлов
        if elem['type'] in ['media', 'photo', 'video']:
            if not os.path.exists(val):
                print(f"⚠️  Предупреждение: Файл не найден по пути '{val}'")
                confirm = input("Продолжить всё равно? (y/n): ")
                if confirm.lower() != 'y':
                    print("Отмена.")
                    return
        
        elements[elem['id']] = val

    # 3. Доп. параметры
    print("-" * 30)
    duration = float(input("⏱ Длительность сцены в секундах [5.0]: ") or 5.0)
    output_name = input("💾 Имя выходного файла [dynamic_result.mp4]: ") or "dynamic_result.mp4"
    
    # 4. Рендеринг
    print("\n🚀 Запускаю рендеринг... Пожалуйста, подождите.")
    
    res = render_dynamic_scene(preset['id'], elements, duration, output_name)
    
    if res:
        print("\n" + "!"*50)
        print(f"🎉 СЦЕНА ГОТОВА!")
        print(f"Путь: {os.path.abspath(output_name)}")
        print("!"*50 + "\n")
    else:
        print("\n❌ Упс! Что-то пошло не так при сборке видео.")

if __name__ == "__main__":
    main()
