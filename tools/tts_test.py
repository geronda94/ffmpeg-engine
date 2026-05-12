import asyncio
import os
import sys
import logging
import json

# Добавляем корневую папку в путь поиска модулей
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.pipeline_manager import generate_project_audio, pm

def load_presets():
    with open("config/audio_presets.json", "r", encoding="utf-8") as f:
        return json.load(f)

async def main():
    if len(sys.argv) < 2:
        print("Usage: python3 tools/tts_test.py {project_id}")
        return

    project_id = sys.argv[1]
    data = pm.load_project(project_id)
    if not data:
        print(f"❌ Project {project_id} not found!")
        return

    presets_data = load_presets()
    print("\n🎙  ДОСТУПНЫЕ ПРЕСЕТЫ ОЗВУЧКИ:")
    
    options = []
    idx = 1
    for engine_id, engine_info in presets_data['tts_engines'].items():
        print(f"\n--- {engine_info['name']} ---")
        for p in engine_info['presets']:
            print(f"{idx}. {p['name']} ({p.get('id')})")
            options.append((engine_id, p))
            idx += 1

    try:
        choice = int(input(f"\nВыберите номер пресета (1-{idx-1}): "))
        engine_id, preset = options[choice-1]
    except (ValueError, IndexError):
        print("❌ Неверный выбор!")
        return

    # Собираем текст
    full_text = " ".join([s['text_segment'] for s in data.get('scenes', [])])
    lang = data.get('language', 'Russian')
    
    output_path = os.path.join("projects", project_id, "audio", f"test_{preset['id']}.wav")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    print(f"\n🚀 Генерирую озвучку через {engine_id} ({preset['name']})...")
    
    # ВАЖНО: Мы вызываем ту же самую функцию, что и бот
    # Это гарантирует 100% синхронизацию логики
    result_path = await generate_project_audio(project_id, preset)

    if result_path:
        # Переименовываем результат для удобства теста
        final_path = os.path.join("projects", project_id, "audio", f"test_{preset['id']}.wav")
        os.rename(result_path, final_path)
        print(f"✨ ГОТОВО! Аудио сохранено: {final_path}")
    else:
        print("❌ Ошибка генерации!")

if __name__ == "__main__":
    asyncio.run(main())
