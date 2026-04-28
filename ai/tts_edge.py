import edge_tts
import asyncio

async def generate_tts(text: str, output_path: str, lang: str = "Russian", voice: str = None, rate: str = "+0%", pitch: str = "0Hz"):
    """
    Генерирует озвучку через Edge-TTS с поддержкой динамических настроек.
    """
    # Если голос не передан из пресета, используем старую логику по умолчанию
    if not voice:
        voices = {
            "Russian": "ru-RU-DmitryNeural",
            "English": "en-US-GuyNeural",
            "Romanian": "ro-RO-EmilNeural",
            "Georgian": "ka-GE-GiorgiNeural"
        }
        voice = voices.get(lang, "en-US-GuyNeural")

    # Создаем объект озвучки с учетом скорости и тональности
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await communicate.save(output_path)
    return output_path
