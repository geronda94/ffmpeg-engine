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

        # Специальные инструкции для русского языка
        lang_specific = ""
        if lang == "Russian":
            lang_specific = (
                "RUSSIAN SPECIFIC RULES:\n"
                "1. Always use 'ё' instead of 'е' where applicable (e.g., 'детёныш', 'всё').\n"
                "2. PRONUNCIATION: In loanwords or technical terms where 'е' sounds like 'э' (e.g., 'проект' -> 'проэкт', 'бренд' -> 'брэнд'), use 'э' to force the correct hard sound.\n"
                "3. ACCENTS: Capitalize the stressed vowel in any word that might be mispronounced (e.g., 'сУдьбы' vs 'судьбЫ').\n"
                "4. PAUSES: Respect and enhance the '. ... ' markers between scenes. Ensure punctuation reflects the emotional rhythm.\n"
            )

        prompt = (
            f"You are a professional voiceover director and phonetic expert for {lang}.\n"
            f"Task: Adapt the provided text for Microsoft Edge Neural TTS to ensure PERFECT pronunciation and natural prosody.\n\n"
            f"GOAL: Maximum clarity, correct accents, and natural emotional rhythm.\n"
            f"SPEED CONTEXT: The text will be read in a **{speed_info}** tempo.\n\n"
            f"{lang_specific}\n"
            f"STRICT GENERAL RULES:\n"
            f"1. WORD INTEGRITY: Do not change, add or remove words. Only adjust characters, punctuation, and capitalization for phonetics.\n"
            f"2. PUNCTUATION: Use '...' for long pauses and '-' for short breaks within words if they are often misread.\n"
            f"3. PHONETIC AIDS: For {lang}, if some words are known to be mispronounced by AI, write them in a way that guides the engine (e.g., repeating a vowel or using capitalization).\n"
            f"4. NO QUOTES: Return ONLY the optimized text for the voice engine.\n\n"
            f"TEXT TO OPTIMIZE: {text}"
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
