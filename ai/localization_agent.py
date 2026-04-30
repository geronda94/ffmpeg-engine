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

async def translate_project_content(script: str, scenes: list, metadata: dict, target_lang: str):
    """
    Переводит сценарий, сегменты сцен и SEO-метаданные на целевой язык.
    """
    try:
        # Подготовка данных для перевода
        scenes_data = [{"id": i, "text": s['text_segment']} for i, s in enumerate(scenes)]
        meta_data = {
            "title": metadata.get('title', ''),
            "description": metadata.get('description', ''),
            "hashtags": metadata.get('hashtags', [])
        }
        
        prompt = (
            f"You are a professional translator specializing in video content. \n"
            f"Task: Translate the following script, scene segments, and SEO metadata into {target_lang}.\n"
            f"Requirements:\n"
            f"1. Keep the same tone and impact as the original.\n"
            f"2. Keep the segments short enough for a video scene.\n"
            f"3. Translate hashtags appropriately for the target language culture.\n"
            f"4. Return the exact same structure.\n\n"
            f"ORIGINAL SCRIPT: {script}\n"
            f"SCENE SEGMENTS: {json.dumps(scenes_data, ensure_ascii=False)}\n"
            f"METADATA: {json.dumps(meta_data, ensure_ascii=False)}\n\n"
            f"Return ONLY a JSON object with these fields:\n"
            f"- 'translated_script': The full script.\n"
            f"- 'translated_scenes': A list of objects with 'id' and 'text'.\n"
            f"- 'translated_metadata': Object with 'title', 'description', 'hashtags' (list).\n"
            f"Do not include any other text or markdown blocks."
        )
        
        response = await client.chat.completions.create(
            model="deepseek-chat", 
            messages=[{"role":"user", "content":prompt}], 
            response_format={'type':'json_object'}
        )
        
        content = response.choices[0].message.content
        result = json.loads(content)
        
        # Обновляем сцены новыми текстами
        new_scenes = [s.copy() for s in scenes]
        for item in result.get('translated_scenes', []):
            idx = item.get('id')
            if idx is not None and idx < len(new_scenes):
                new_scenes[idx]['text_segment'] = item.get('text')
                # Сбрасываем тайминги
                if 'start' in new_scenes[idx]: del new_scenes[idx]['start']
                if 'end' in new_scenes[idx]: del new_scenes[idx]['end']
        
        return {
            "script": result.get('translated_script'),
            "scenes": new_scenes,
            "metadata": result.get('translated_metadata')
        }
        
    except Exception as e:
        logger.error(f"Localization Agent Error: {e}")
        return None
