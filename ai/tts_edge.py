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
                "ИНСТРУКЦИИ ДЛЯ РУССКОГО ЯЗЫКА:\n"
                "1. МИНИМАЛИЗМ: Современные нейросети (Edge TTS) отлично знают ударения сами. НЕ ставь ударения в обычных словах.\n"
                "2. ЗАПРЕТ НА СИМВОЛЫ: КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО использовать знаки ударения (юникод-символ \\u0301). Это ломает озвучку.\n"
                "3. УДАРЕНИЯ ЧЕРЕЗ CAPS: Используй заглавную букву (н-р, 'зАмок') ТОЛЬКО в омонимах или редких именах, где возможна ошибка. В обычном тексте это НЕ НУЖНО.\n"
                "4. БУКВА 'Ё': Всегда восстанавливай 'ё' (ещё, влюблён, самолёт). Это критически важно для правильной фонетики.\n"
                "5. РИТМ: Естественная пунктуация. Одна запятая на предложение — где нужна короткая пауза. Точки в конце смысловых блоков. НЕ добавляй лишних тире, двоеточий и многоточий для создания пауз. Текст должен дышать: живо, но не захлёбываться.\n"
            ),
            "English": (
                "LINGUISTIC GUIDELINES FOR ENGLISH:\n"
                "1. NATURAL FLOW: Aim for a conversational, smooth delivery. Use punctuation to guide rhythm.\n"
                "2. PUNCTUATION: Use commas for brief pauses and periods for full stops. Use ellipses (...) sparingly, only for significant transitions.\n"
                "3. NO PHONETIC SPELLING: Keep standard spelling; the neural engine handles linking and reductions automatically.\n"
            ),
            "Romanian": (
                "LINGUISTIC GUIDELINES FOR ROMANIAN:\n"
                "1. DIACRITICS: Ensure all diacritics (ă, â, î, ș, ț) are perfectly placed.\n"
                "2. RHYTHM: Use commas to mark natural breath points.\n"
            ),
            "Georgian": (
                "LINGUISTIC GUIDELINES FOR GEORGIAN:\n"
                "1. SCRIPT: Maintain original script. Use punctuation to help the engine find natural pauses.\n"
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


async def post_process_audio(file_path: str, profile: str):
    """
    Применяет аудиофильтры ffmpeg для создания премиального/атмосферного звучания
    и уникализации звука для алгоритмов соцсетей.
    """
    if not profile or not os.path.exists(file_path):
        return
        
    profile = profile.lower()
    filters = None
    
    if "orthodox" in profile:
            # Мощный басовый фундамент и длинный, но очень тихий шлейф эха
            filters = "bass=g=15:f=90:w=0.8,aecho=0.85:0.70:180|360|540:0.06|0.03|0.01,volume=1.3"
            logger.info(f"Applying Orthodox spiritual cathedral acoustics to: {file_path}")
    elif "tech" in profile or "it" in profile:
        # Ультра-кристальный стерео-расширитель + высокие частоты (стиль подкастов / техно-ноир)
        filters = "treble=g=3:f=5000,apulsator=hz=0.1:amount=0.1:offset_r=0.2"
        logger.info(f"Applying Tech-Noir clean spatial filter to: {file_path}")
        
    if not filters:
        return
        
    temp_output = file_path + ".processed.wav"
    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", file_path,
            "-af", filters,
            temp_output
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0 and os.path.exists(temp_output) and os.path.getsize(temp_output) > 0:
            os.replace(temp_output, file_path)
            logger.info("✨ Audio post-processing completed successfully!")
        else:
            err_msg = stderr.decode('utf-8', errors='ignore')
            logger.error(f"ffmpeg processing failed: {err_msg}")
    except Exception as e:
        logger.error(f"Error during audio post-processing: {e}")
    finally:
        if os.path.exists(temp_output):
            try:
                os.remove(temp_output)
            except:
                pass


async def generate_tts(text: str, output_path: str, lang: str = "Russian", voice: str = None, rate: str = "+0%", pitch: str = "+0Hz", channel_profile: str = None):
    """
    Генерация озвучки через Microsoft Edge TTS с автоматическим пост-процессингом звука.
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

        # Внутренний цикл ретраев для Edge TTS
        for sub_attempt in range(3):
            try:
                communicate = edge_tts.Communicate(optimized_text, voice, rate=rate, pitch=pitch)
                await communicate.save(output_path)
                if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                    logger.info(f"TTS generated: {output_path}")
                    if channel_profile:
                        await post_process_audio(output_path, channel_profile)
                    return output_path
            except Exception as e:
                logger.warning(f"Edge TTS sub-attempt {sub_attempt+1} failed: {e}")
                await asyncio.sleep(2)
        
        return None
    except Exception as e:
        logger.error(f"TTS Error: {e}")
        return None
