import asyncio
import sys
import logging
import json
import os

# Добавляем корневую папку в путь поиска модулей
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.pipeline_manager import render_project_video, pm

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def load_montage_presets(): 
    with open("config/rendering_presets.json", "r", encoding="utf-8") as f:
        return json.load(f)

async def main():
    if len(sys.argv) < 2:
        print("Usage: python3 tools/render_only.py {project_id}")
        return

    project_id = sys.argv[1]
    data = pm.load_project(project_id)
    if not data:
        print(f"❌ Project {project_id} not found!")
        return

    # 1. Выбор формата
    print("\n📐 ВЫБЕРИТЕ ФОРМАТ ВИДЕО:")
    print("1. Vertical (9:16) - для Reels/Shorts/TikTok")
    print("2. Horizontal (16:9) - для YouTube/TV")
    
    try:
        fmt_choice = int(input("\nВаш выбор (1-2): "))
        video_format = "vertical" if fmt_choice == 1 else "horizontal"
    except ValueError:
        print("❌ Неверный ввод!")
        return

    # 2. Выбор стиля
    presets_data = load_montage_presets()
    available_styles = presets_data.get(video_format, [])
    
    print(f"\n🎨 ДОСТУПНЫЕ СТИЛИ ({video_format}):")
    for idx, style in enumerate(available_styles, 1):
        print(f"{idx}. {style['name']} (ID: {style['id']})")

    try:
        style_idx = int(input(f"\nВыберите номер стиля (1-{len(available_styles)}): "))
        selected_style = available_styles[style_idx-1]
    except (ValueError, IndexError):
        print("❌ Неверный выбор!")
        return

    # Обновляем данные проекта для рендеринга
    data['video_format'] = video_format
    data['visual_style'] = selected_style['id']
    
    audio_path = data.get('current_audio_path')
    if not audio_path:
        print("❌ В проекте не найдена озвучка! Сначала запустите tools/tts_test.py или бота.")
        return

    print(f"\n🚀 ЗАПУСК РЕНДЕРИНГА: {video_format} | Стиль: {selected_style['name']}")
    
    result = await render_project_video(project_id, audio_path)
    
    if result:
        print(f"\n✨ УСПЕХ! Видео сохранено: {result}")
    else:
        print("\n❌ Рендеринг завершился с ошибкой!")

if __name__ == "__main__":
    asyncio.run(main())
