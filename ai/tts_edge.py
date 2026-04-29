import edge_tts
import logging
import os
import asyncio
from openai import OpenAI
from dotenv import load_dotenv

# Загружаем переменные окружения из корня проекта
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(root_dir, ".env"))

logger = logging.getLogger(__name__)

async def optimize_text_for_tts(text: str, lang: str):
    """Оптимизация текста через ИИ для лучшего звучания робота."""
    try:
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            logger.warning("DEEPSEEK_API_KEY not found. Skipping AI optimization.")
            return text
            
        client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        
        # Улучшенный промпт для дикции и ударений
        prompt = (
            f"You are a professional voiceover director. Optimize this text for Microsoft Edge TTS.\n"
            f"GOAL: Maximum clarity and natural rhythm in {lang}.\n\n"
            f"RULES:\n"
            f"1. ALPHABET: Keep the text STRICTLY in the original alphabet ({lang}). NEVER use Latin characters or transliteration for Russian text!\n"
            f"2. STRESS: Capitalize the stressed vowel ONLY in tricky or ambiguous words (e.g., 'крОна', 'едА'). Do not capitalize every word.\n"
            f"3. PAUSES: Use '...' for natural breaths between sentences. Use dashes '—' for logical pauses.\n"
            f"4. NUMBERS: Write out numbers as words.\n"
            f"5. NO QUOTES: Return ONLY the raw optimized text.\n\n"
            f"TEXT: {text}"
        )
        
        res = client.chat.completions.create(
            model="deepseek-chat", 
            messages=[{"role":"user", "content":prompt}]
        )
        optimized = res.choices[0].message.content.strip().replace('"', '')
        logger.info(f"TTS Optimized Text: {optimized}") # ОТЛАДКА
        return optimized
    except Exception as e:
        logger.error(f"TTS Optimization Error: {e}")
        return text

async def generate_tts(text: str, output_path: str, lang: str = "Russian", voice: str = None, rate: str = "+0%", pitch: str = "+0Hz"):
    """
    Генерация озвучки через Microsoft Edge TTS (бесплатно).
    """
    try:
        # Оптимизируем текст перед озвучкой
        logger.info("Optimizing text for better TTS quality...")
        optimized_text = await optimize_text_for_tts(text, lang)
        
        if not voice:
            # Дефолтные голоса, если не переданы
            voices = {
                "Russian": "ru-RU-DmitryNeural",
                "English": "en-US-AndrewNeural",
                "Romanian": "ro-RO-EmilNeural",
                "Georgian": "ka-GE-GiorgiNeural"
            }
            voice = voices.get(lang, "en-US-AndrewNeural")

        communicate = edge_tts.Communicate(optimized_text, voice, rate=rate, pitch=pitch)
        await communicate.save(output_path)
        logger.info(f"TTS generated: {output_path}")
        return output_path
    except Exception as e:
        logger.error(f"TTS Error: {e}")
        return None
