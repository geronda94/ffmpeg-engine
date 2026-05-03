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
    """
    Оптимизация текста через LLM для улучшения произношения (акценты, паузы, 'ё').
    """
    try:
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            logger.warning("DEEPSEEK_API_KEY not found. Skipping AI optimization.")
            return text

        client = get_client()

        speed_info = "normal"
        if "+" in rate:
            val = int(rate.replace("+", "").replace("%", ""))
            if val > 15: speed_info = "very fast and energetic"
            elif val > 5: speed_info = "fast"
        elif "-" in rate:
            val = int(rate.replace("-", "").replace("%", ""))
            if val > 15: speed_info = "very slow and dramatic"
            elif val > 5: speed_info = "slow"

        lang_specific = ""
        if lang == "Russian":
            lang_specific = (
                "RUSSIAN SPECIFIC RULES:\n"
                "1. Use 'ё' where applicable (e.g., 'всё', 'идёт').\n"
                "2. ACCENTS: Capitalize the stressed vowel ONLY if the word is ambiguous (e.g., 'сУдьбы' vs 'судьбЫ').\n"
                "3. PHONETICS: DO NOT change 'г' to 'v' or 'э' to 'e' aggressively. Edge TTS already knows natural Russian phonetics. Keep word spelling natural.\n"
                "4. PAUSES: Enhance the '. ... ' markers for clear scene transitions.\n"
            )

        prompt = (
            f"You are a professional voiceover director for {lang}.\n"
            f"Task: Adapt the provided text for Microsoft Edge Neural TTS to ensure natural prosody and correct accents.\n\n"
            f"GOAL: Natural emotional rhythm and clarity. Avoid robotic over-correction.\n"
            f"SPEED CONTEXT: {speed_info} tempo.\n\n"
            f"{lang_specific}\n"
            f"STRICT RULES:\n"
            f"1. DO NOT change words. Only adjust punctuation, capitalization (for stress), and use 'ё'.\n"
            f"2. Use '...' for natural pauses.\n"
            f"3. Return ONLY the optimized text.\n\n"
            f"TEXT: {text}"
        )

        res = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}]
        )
        optimized = res.choices[0].message.content.strip().replace('"', "")
        logger.info(f"TTS Optimized Text: {optimized}")
        return optimized
    except Exception as e:
        logger.error(f"TTS Optimization Error: {e}")
        return text


async def generate_tts(text: str, output_path: str, lang: str = "Russian", voice: str = None, rate: str = "+0%", pitch: str = "+0Hz"):
    """
    Генерация озвучки через Microsoft Edge TTS.
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
