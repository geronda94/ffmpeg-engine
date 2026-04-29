import os
import json
import logging
from openai import OpenAI

logger = logging.getLogger(__name__)

async def generate_video_metadata(script: str, lang: str):
    """
    Генерирует заголовок, описание и теги для видео на основе сценария.
    """
    try:
        client = OpenAI(api_key=os.getenv("DEEPSEEK_API_KEY"), base_url="https://api.deepseek.com")
        
        prompt = (
            f"You are a YouTube/TikTok SEO expert. Based on the script below, generate marketing metadata.\n"
            f"SCRIPT: {script}\n"
            f"Language: {lang}\n\n"
            f"Return ONLY a JSON object with these fields:\n"
            f"- 'title': A catchy, clickbaity title (max 60 chars).\n"
            f"- 'description': A short engaging description (2-3 sentences).\n"
            f"- 'hashtags': 5-7 relevant hashtags.\n"
            f"- 'slug': A URL-friendly version of the title in English (lowercase, no spaces)."
        )
        
        res = client.chat.completions.create(
            model="deepseek-chat", 
            messages=[{"role":"user", "content":prompt}], 
            response_format={'type':'json_object'}
        )
        return json.loads(res.choices[0].message.content)
    except Exception as e:
        logger.error(f"Metadata Agent Error: {e}")
        return {
            "title": "Amazing Video",
            "description": "Watch this incredible story.",
            "hashtags": ["#ai", "#video", "#content"],
            "slug": "amazing_video"
        }
