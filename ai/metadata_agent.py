import os
import json
import logging
import asyncio
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# Инициализируем асинхронный клиент
client = AsyncOpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"), 
    base_url="https://api.deepseek.com"
)

async def generate_metadata(script, lang="Russian", user_instruction=""):
    """
    Генерирует заголовок, описание и теги для видео на основе сценария и пользовательских предпочтений.
    """
    try:
        # Загружаем контекст канала
        context = {
            "channel_topic": "General content",
            "tone_of_voice": "Engaging",
            "avoid_topics": [],
            "target_platform": "YouTube/TikTok"
        }
        ctx_path = "config/channel_context.json"
        if os.path.exists(ctx_path):
            with open(ctx_path, "r", encoding="utf-8") as f:
                context.update(json.load(f))

        style_instruction = f"STYLE INSTRUCTION: {user_instruction}\n" if user_instruction else ""
        
        prompt = (
            f"You are a SEO expert for {context['target_platform']}. \n"
            f"CHANNEL CONTEXT: {context['channel_topic']}\n"
            f"TONE OF VOICE: {context['tone_of_voice']}\n"
            f"AVOID: {', '.join(context['avoid_topics'])}\n\n"
            f"{style_instruction}"
            f"Based on the script below, generate marketing metadata that is platform-safe and adheres to community guidelines.\n"
            f"SCRIPT: {script}\n"
            f"Language: {lang}\n\n"
            f"Return ONLY a JSON object with these fields:\n"
            f"- 'title': A catchy title (max 60 chars).\n"
            f"- 'description': A short engaging description (2-3 sentences).\n"
            f"- 'hashtags': 5-7 relevant hashtags.\n"
            f"- 'slug': A URL-friendly version of the title in English.\n"
            f"Do not include any other text or markdown blocks."
        )
        
        # Используем await для асинхронного вызова
        response = await client.chat.completions.create(
            model="deepseek-chat", 
            messages=[{"role":"user", "content":prompt}], 
            response_format={'type':'json_object'}
        )
        
        content = response.choices[0].message.content
        # Очистка от markdown если нейросеть его добавила
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
            
        return json.loads(content)
    except Exception as e:
        logger.error(f"Metadata Agent Error: {e}")
        # Фоллбек на случай ошибки API
        return {
            "title": f"Video about {context['channel_topic']}",
            "description": "Engaging AI generated content.",
            "hashtags": ["#ai", "#video", "#shorts"],
            "slug": "video_result"
        }
