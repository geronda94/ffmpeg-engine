import os
import argparse
import struct
import mimetypes
import json
import re
import time
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

def parse_audio_mime_type(mime_type: str) -> dict:
    bits_per_sample = 16
    rate = 24000
    parts = mime_type.split(";")
    for param in parts:
        param = param.strip()
        if param.lower().startswith("rate="):
            try: rate = int(param.split("=", 1)[1])
            except: pass
        elif param.startswith("audio/L"):
            try: bits_per_sample = int(param.split("L", 1)[1])
            except: pass
    return {"bits_per_sample": bits_per_sample, "rate": rate}

def create_wav_header(audio_data_size: int, parameters: dict) -> bytes:
    bits_per_sample = parameters["bits_per_sample"]
    sample_rate = parameters["rate"]
    num_channels = 1
    bytes_per_sample = bits_per_sample // 8
    block_align = num_channels * bytes_per_sample
    byte_rate = sample_rate * block_align
    chunk_size = 36 + audio_data_size
    header = struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", chunk_size, b"WAVE", b"fmt ", 16, 1, num_channels, sample_rate, byte_rate, block_align, bits_per_sample, b"data", audio_data_size)
    return header

def generate_tts_from_task(task_path: str):
    with open(task_path, "r", encoding="utf-8") as f:
        task = json.load(f)
    
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
    model = task.get("model", "gemini-3.1-flash-tts-preview")
    voice_name = task.get("voice", "Alnilam")
    output_path = task.get("output", "output/voiceover.wav")
    text = task.get("text", "")
    system_instruction = task.get("prompt", "Read the following transcript.")

    sentences = re.split(r'(?<=[.!?]) +', text.strip())
    print(f"🎤 Задание: {task_path} | Предложений: {len(sentences)}")
    
    full_audio_data = bytearray()
    mime_type = "audio/L16;rate=24000"

    for i, sentence in enumerate(sentences):
        if not sentence.strip(): continue
        
        success = False
        retries = 3
        while not success and retries > 0:
            try:
                print(f"⏳ {i+1}/{len(sentences)}: {sentence[:30]}...")
                full_prompt = f"{system_instruction}\n\n## Transcript:\n{sentence}"
                
                config = types.GenerateContentConfig(
                    temperature=task.get("temperature", 1.0),
                    response_modalities=["audio"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
                        )
                    ),
                )

                for chunk in client.models.generate_content_stream(
                    model=model,
                    contents=[types.Content(role="user", parts=[types.Part.from_text(text=full_prompt)])],
                    config=config,
                ):
                    if chunk.parts and chunk.parts[0].inline_data:
                        full_audio_data.extend(chunk.parts[0].inline_data.data)
                        if chunk.parts[0].inline_data.mime_type:
                            mime_type = chunk.parts[0].inline_data.mime_type
                
                # Пауза между частями для естественности
                pause_sec = task.get("pause", 0.5)
                full_audio_data.extend(b'\x00' * int(24000 * 2 * pause_sec))
                success = True
                
                # Небольшая задержка между запросами для обхода Rate Limit (Free Tier)
                time.sleep(2) 

            except Exception as e:
                if "429" in str(e):
                    print(f"⚠️ Rate limit hit! Ждем 60 секунд... (Осталось попыток: {retries})")
                    time.sleep(65)
                    retries -= 1
                else:
                    print(f"❌ Ошибка: {e}")
                    break

    if not full_audio_data: return

    params = parse_audio_mime_type(mime_type)
    header = create_wav_header(len(full_audio_data), params)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(header)
        f.write(full_audio_data)
    print(f"✅ Готово: {output_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    args = parser.parse_args()
    generate_tts_from_task(args.task)
