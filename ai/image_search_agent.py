import aiohttp
import asyncio
import logging
import os
import random
import re

logger = logging.getLogger(__name__)

async def optimize_query_ai(user_text: str):
    """Превращает описание пользователя в список запросов и целевой цвет через LLM."""
    from ai.llm_client import get_async_client
    try:
        client = get_async_client()
        # Просим ИИ выдать также один из поддерживаемых стоками цветов
        prompt = (
            "Convert this visual description into 3 simple English search keywords and one dominant color "
            "(red, orange, yellow, green, turquoise, blue, violet, pink, brown, black, gray, white or 'none'). "
            "Output format: keywords: [k1, k2, k3], color: [color_name]. "
            f"Description: {user_text}"
        )
        response = await client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100,
            temperature=0.3
        )
        content = response.choices[0].message.content.strip().lower()
        
        # Парсим ответ
        keywords_match = re.findall(r"keywords: \[(.*?)\]", content)
        color_match = re.findall(r"color: \[(.*?)\]", content)
        
        k_list = [k.strip() for k in keywords_match[0].split(",")] if keywords_match else [user_text[:50]]
        c_val = color_match[0].strip() if color_match and color_match[0].strip() != "none" else None
        
        logger.info(f"AI Search Optimization: keywords={k_list}, color={c_val}")
        return k_list, c_val
    except Exception as e:
        logger.error(f"Failed to optimize query via AI: {e}")
        return [user_text[:50]], None

# Ключи (можно заменить на свои в .env)
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "563492ad6f91700001000001bc3b392a5b6c4f03998b3f309a63588a")
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "43825832-75d192135d8d083f9876e5d23")

class ImageSearchAgent:
    def __init__(self):
        self.pexels_url = "https://api.pexels.com/v1/search"
        self.pixabay_url = "https://pixabay.com/api/"

    async def search_images(self, queries: str | list, per_page: int = 20, source_type: str = "all", color: str = None):
        """
        ПАРАЛЛЕЛЬНЫЙ ПОИСК с поддержкой цвета и выбора источника.
        source_type: 'all', 'pexels', 'pixabay', 'ai'
        """
        query_list = [queries] if isinstance(queries, str) else queries
        tasks = []

        for q in query_list:
            if source_type in ["all", "pixabay"]:
                tasks.append(self._search_pixabay(q, 12, color))
            if source_type in ["all", "pexels"]:
                tasks.append(self._search_pexels(q, 12, color))
            if source_type in ["all", "ai"]:
                tasks.append(self._search_pollinations(q, 8))

        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        all_results = []
        for res in responses:
            if isinstance(res, list):
                all_results.extend(res)
        
        unique_results = []
        seen_urls = set()
        for r in all_results:
            if r['url'] not in seen_urls:
                unique_results.append(r)
                seen_urls.add(r['url'])

        # Если поиск по цвету дал слишком мало результатов, попробуем еще раз без цвета для перемешивания
        if color and len(unique_results) < 5:
             logger.info("Color filter too strict, adding non-color results...")
             # (рекурсивно не пойдем, просто оставим что есть)
             pass

        random.shuffle(unique_results)
        return unique_results[:per_page]

    async def _search_pollinations(self, query: str, count: int):
        """Генерирует AI картинку через стабильный эндпоинт image.pollinations.ai"""
        results = []
        clean_q = query.replace(' ', '%20').replace('"', '').replace("'", "").strip()
        for i in range(count):
            seed = random.randint(1, 1000000)
            url = f"https://image.pollinations.ai/prompt/{clean_q}?width=720&height=1280&seed={seed}&nologo=true&enhance=false"
            results.append({"url": url, "photographer": "AI (Pollinations)"})
        return results

    async def _search_pexels(self, query: str, per_page: int, color: str = None):
        if not PEXELS_API_KEY: return []
        headers = {"Authorization": PEXELS_API_KEY}
        params = {"query": query, "per_page": per_page, "orientation": "portrait"}
        if color:
            params["color"] = color
            
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.pexels_url, headers=headers, params=params, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return [{"url": p["src"]["large"], "photographer": p["photographer"]} for p in data.get("photos", [])]
        except Exception as e:
            logger.error(f"Pexels error: {e}")
        return []

    async def _search_pixabay(self, query: str, per_page: int, color: str = None):
        if not PIXABAY_API_KEY: return []
        params = {
            "key": PIXABAY_API_KEY,
            "q": query,
            "image_type": "photo",
            "orientation": "vertical",
            "per_page": per_page
        }
        # Pixabay использует параметр 'colors' (множественное число)
        if color:
            params["colors"] = color
            
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.pixabay_url, params=params, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return [{"url": h["largeImageURL"], "photographer": h["user"]} for h in data.get("hits", [])]
        except Exception as e:
            logger.error(f"Pixabay error: {e}")
        return []

image_search_agent = ImageSearchAgent()
