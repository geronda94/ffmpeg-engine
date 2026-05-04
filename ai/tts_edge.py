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

        guidelines = {
            "Russian": (
                "LINGUISTIC GUIDELINES FOR RUSSIAN:\n"
                "1. PRESERVE ORTHOGRAPHY: Maintain strict morphological spelling (e.g., 'солнце', 'его'). NEVER use phonetic spelling ('сонце', 'ево'). The neural engine handles automatic reduction perfectly.\n"
                "2. MANDATORY 'Ё': Always restore 'ё' where it belongs ('ещё', 'всё'). This is the most critical hint for the engine.\n"
                "3. PROACTIVE ACCENTUATION: Use capitalization for the stressed vowel (e.g., 'зАмок', 'красИвый', 'переключИла') to ensure correct and natural pronunciation. Prioritize complex words, long words, and ambiguous homographs. Do not mark every single word, but be proactive where the engine might stumble.\n"
                "4. PUNCTUATION AS RHYTHM: Use '...' for long pauses and ',' for breathing points.\n"
            ),
            "English": (
                "LINGUISTIC GUIDELINES FOR ENGLISH:\n"
                "1. STANDARD ORTHOGRAPHY: Do not use eye-dialect or phonetic spelling. The neural engine (e.g., Andrew) handles reduction, linking, and aspiration perfectly based on standard spelling.\n"
                "2. PHRASAL RHYTHM: Use ',' to mark natural pauses in long sentences. Use '...' for transitions between ideas.\n"
                "3. EMPHASIS: Use standard capitalization ONLY for words that require strong emotional emphasis to change the sentence's meaning.\n"
            ),
            "Romanian": (
                "LINGUISTIC GUIDELINES FOR ROMANIAN:\n"
                "1. DIACRITICS: Ensure all diacritics (ă, â, î, ș, ț) are perfectly placed. They are critical for correct phoneme selection.\n"
                "2. MELODIC FLOW: Romanian is a syllable-timed language; use punctuation to guide the engine's intonation curves.\n"
            ),
            "Georgian": (
                "LINGUISTIC GUIDELINES FOR GEORGIAN:\n"
                "1. SCRIPT INTEGRITY: Maintain the original Mkhedruli script. Do not attempt phonetic approximations.\n"
                "2. SEGMENTATION: Georgian sentences can be dense; use commas to help the engine find natural breaking points for breath.\n"
            )
        }

        lang_specific = guidelines.get(lang, "GUIDELINES: Preserve natural spelling, restore language-specific markers, and use punctuation to guide the rhythm and prosody.")

        prompt = (
            f"You are a professional linguistic consultant and voiceover director for {lang}.\n"
            f"Your task is to prepare the text for a High-End Neural TTS engine (Microsoft Edge).\n\n"
            f"STRATEGY: Do not over-process. Guide the engine's prosody and phonetics using language-specific markers without breaking the spelling.\n"
            f"SPEED & MOOD: {speed_info} tempo.\n\n"
            f"{lang_specific}\n"
            f"STRICT LIMITS:\n"
            f"1. DO NOT change, add, or remove any words. Keep the meaning 1:1.\n"
            f"2. Return ONLY the processed text, no explanations.\n\n"
            f"TEXT TO PROCESS:\n{text}"
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
