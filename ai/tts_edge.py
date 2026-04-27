import asyncio
import edge_tts
import json
import argparse
from pathlib import Path

async def generate_edge_tts(text: str, output_path: str, voice: str = "ru-RU-DmitryNeural"):
    """Генерация аудио через Microsoft Edge TTS."""
    print(f"🎙 Edge-TTS: Генерирую озвучку (Голос: {voice})...")
    
    communicate = edge_tts.Communicate(text, voice)
    
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    await communicate.save(output_path)
    
    print(f"✅ Edge-TTS готово: {output_path}")

async def generate_tts_from_task(task_path: str):
    """Обертка для работы с JSON-заданиями."""
    with open(task_path, "r", encoding="utf-8") as f:
        task = json.load(f)
    
    voice = task.get("voice", "ru-RU-DmitryNeural")
    if "Neural" not in voice:
        voice = "ru-RU-DmitryNeural"
        
    text = task.get("text", "")
    output_path = task.get("output", "output/voiceover.wav")
    
    await generate_edge_tts(text, output_path, voice)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    args = parser.parse_args()
    asyncio.run(generate_tts_from_task(args.task))
