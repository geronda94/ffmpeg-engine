import asyncio
import sys
import logging
from bot.pipeline_manager import render_project_video, pm

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

async def main():
    if len(sys.argv) < 2:
        print("Usage: python3 render_only.py {project_id}")
        return

    project_id = sys.argv[1]
    print(f"🚀 Starting standalone render for project: {project_id}")
    
    data = pm.load_project(project_id)
    if not data:
        print(f"❌ Project {project_id} not found!")
        return
        
    audio_path = data.get('current_audio_path')
    if not audio_path:
        print("❌ No audio path found in project.json!")
        return

    result = await render_project_video(data, audio_path)
    
    if result:
        print(f"✨ SUCCESS! Video saved to: {result}")
    else:
        print("❌ Render failed!")

if __name__ == "__main__":
    asyncio.run(main())
