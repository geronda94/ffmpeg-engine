import asyncio
import sys
import os
import logging

# Добавляем корень проекта в пути
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.pipeline_manager import render_project_video
from core.project_manager import ProjectManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LocalRender")

async def main():
    if len(sys.argv) < 2:
        print("Использование: python tools/local_render.py {project_id} [user_id]")
        return

    project_id = sys.argv[1]
    user_id = sys.argv[2] if len(sys.argv) > 2 else "default"
    
    pm = ProjectManager()
    data = pm.load_project(project_id, user_id)
    
    if not data:
        print(f"❌ Проект {project_id} не найден в projects/{user_id}/")
        return

    audio_path = data.get('current_audio_path')
    if not audio_path or not os.path.exists(audio_path):
        print(f"❌ Аудиофайл не найден. Сначала сгенерируйте озвучку.")
        return

    print(f"🚀 Запуск локального рендера проекта {project_id}...")
    print(f"📐 Формат: {data['video_format']}, Стиль: {data['visual_style']}")

    def progress(p):
        print(f"📊 Прогресс: {p}%")

    output = await render_project_video(data, audio_path, progress_callback=progress)
    
    if output:
        print(f"✅ Готово! Видео сохранено: {output}")
    else:
        print("❌ Ошибка при рендеринге.")

if __name__ == "__main__":
    asyncio.run(main())
