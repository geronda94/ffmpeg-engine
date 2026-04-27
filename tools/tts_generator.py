import os
import argparse
import struct
import mimetypes
import json
import re
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types

# Загружаем переменные из .env
load_dotenv()

def parse_audio_mime_type(mime_type: str) -> dict:
    """Парсит параметры аудио из MIME типа (bits per sample и rate)."""
    bits_per_sample = 16
    rate = 24000
    parts = mime_type.split(";")
    for param in parts:
        param = param.strip()
        if param.lower().startswith("rate="):
            try:
                rate = int(param.split("=", 1)[1])
            except: pass
        elif param.startswith("audio/L"):
            try:
                bits_per_sample = int(param.split("L", 1)[1])
            except: pass
    return {"bits_per_sample": bits_per_sample, "rate": rate}

def create_wav_header(audio_data_size: int, parameters: dict) -> bytes:
    """Создает правильный заголовок WAV для всего объема данных."""
    bits_per_sample = parameters["bits_per_sample"]
    sample_rate = parameters["rate"]
    num_channels = 1
    bytes_per_sample = bits_per_sample // 8
    block_align = num_channels * bytes_per_sample
    byte_rate = sample_rate * block_align
    chunk_size = 36 + audio_data_size

    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", chunk_size, b"WAVE", b"fmt ",
        16, 1, num_channels, sample_rate, byte_rate,
        block_align, bits_per_sample, b"data", audio_data_size
    )
    return header

import json

def generate_tts_from_task(task_path: str):
    """Запуск генерации на основе JSON-конфига."""
    with open(task_path, "r", encoding="utf-8") as f:
        task = json.load(f)
    
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
    model = task.get("model", "gemini-3.1-flash-tts-preview")
    voice_name = task.get("voice", "Alnilam")
    output_path = task.get("output", "output/voiceover.wav")
    text = task.get("text", "")
    
    # Системный промпт (можно брать из таска или использовать дефолт)
    system_instruction = task.get("prompt", "Read the following transcript.")

    # Разбиваем текст на предложения
    sentences = re.split(r'(?<=[.!?]) +', text.strip())
    print(f"🎤 Задание загружено: {task_path}")
    print(f"🎤 Голос: {voice_name}, Модель: {model}")
    print(f"🎤 Предложений: {len(sentences)}")
    
    full_audio_data = bytearray()
    mime_type = "audio/L16;rate=24000"

    for i, sentence in enumerate(sentences):
        if not sentence.strip(): continue
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

        try:
            for chunk in client.models.generate_content_stream(
                model=model,
                contents=[types.Content(role="user", parts=[types.Part.from_text(text=full_prompt)])],
                config=config,
            ):
                if chunk.parts and chunk.parts[0].inline_data:
                    full_audio_data.extend(chunk.parts[0].inline_data.data)
                    if chunk.parts[0].inline_data.mime_type:
                        mime_type = chunk.parts[0].inline_data.mime_type
            
            # Пауза между частями
            pause_sec = task.get("pause", 0.5)
            full_audio_data.extend(b'\x00' * int(24000 * 2 * pause_sec))
            
        except Exception as e:
            print(f"⚠️ Ошибка: {e}")

    if not full_audio_data: return

    params = parse_audio_mime_type(mime_type)
    header = create_wav_header(len(full_audio_data), params)
    
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(header)
        f.write(full_audio_data)
    
    print(f"✅ Готово: {output_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gemini TTS Generator")
    parser.add_argument("--task", help="Путь к JSON-заданию озвучки")
    parser.add_argument("--input", help="Путь к тексту или сам текст (для быстрой генерации)")
    parser.add_argument("--output", help="Путь для .wav (только для --input)")
    parser.add_argument("--voice", default="Alnilam", help="Голос (только для --input)")
    
    args = parser.parse_args()

    if args.task:
        generate_tts_from_task(args.task)
    elif args.input and args.output:
        # Старый режим для обратной совместимости
        text_content = ""
        if os.path.exists(args.input):
            with open(args.input, "r", encoding="utf-8") as f:
                text_content = f.read()
        else:
            text_content = args.input
        
        # Используем дефолтные промпты
        mock_task_path = "temp_tts_task.json"
        mock_task = {
            "text": text_content,
            "output": args.output,
            "voice": args.voice,
            "prompt": "Read the following transcript. Style: Formal, steady documentary narrator."
        }
        with open(mock_task_path, "w", encoding="utf-8") as f:
            json.dump(mock_task, f)
        generate_tts_from_task(mock_task_path)
        os.remove(mock_task_path)
    else:
        parser.print_help()
