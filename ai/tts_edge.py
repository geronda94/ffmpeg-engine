import edge_tts
import logging
import os
import asyncio
from ai.llm_client import get_client

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv(os.path.join(root_dir, ".env"))

logger = logging.getLogger(__name__)


async def optimize_text_for_tts(text: str, lang: str, rate: str = "+0%"):
    try:
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            logger.warning("DEEPSEEK_API_KEY not found. Skipping AI optimization.")
            return text

        client = get_client()

        speed_info = "normal"
        if "+" in rate:
            val = int(rate.replace("+", "").replace("%", ""))
            if val > 15:
                speed_info = "very fast and energetic"
            elif val > 5:
                speed_info = "fast"
        elif "-" in rate:
            val = int(rate.replace("-", "").replace("%", ""))
            if val > 15:
                speed_info = "very slow and dramatic"
            elif val > 5:
                speed_info = "slow"

        prompt = (
            f"You are a professional voiceover director. Optimize this text for Microsoft Edge TTS.\n"
            f"GOAL: Maximum clarity and natural rhythm in {lang}.\n"
            f"SPEED CONTEXT: The text will be read in a **{speed_info}** tempo.\n\n"
            f"STRICT RULES:\n"
            f"1. TEXT INTEGRITY: DO NOT add, remove, or replace any words. The output must contain the EXACT same words as the input.\n"
            f"2. ALPHABET: Keep strictly in {lang}. NO Latin/transliteration.\n"
            f"3. PAUSES: If speed is fast, use FEWER pauses. If speed is slow, use MORE '...' for dramatic effect.\n"
            f"4. STRESS: Capitalize stressed vowels only in tricky words (e.g., 'крОна', 'едА').\n"
            f"5. NO QUOTES: Return ONLY the optimized text.\n\n"
            f"TEXT: {text}"
        )

        res = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}]
        )
        optimized = res.choices[0].message.content.strip().replace('"', "")
        logger.info(f"TTS Optimized Text ({speed_info}): {optimized}")
        return optimized
    except Exception as e:
        logger.error(f"TTS Optimization Error: {e}")
        return text


async def generate_tts(text: str, output_path: str, lang: str = "Russian", voice: str = None, rate: str = "+0%", pitch: str = "+0Hz"):
    """
    Генерация озвучки через Microsoft Edge TTS (бесплатно).
    """
    try:
        optimized_text = await optimize_text_for_tts(text, lang, rate)

        if not voice:
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
