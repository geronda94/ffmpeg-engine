import aiohttp
import asyncio
import logging
import os
import random

logger = logging.getLogger(__name__)

# Ключи (можно заменить на свои в .env)
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "563492ad6f91700001000001bc3b392a5b6c4f03998b3f309a63588a")
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "43825832-75d192135d8d083f9876e5d23") # Резервный ключ

class ImageSearchAgent:
    def __init__(self):
        self.pexels_url = "https://api.pexels.com/v1/search"
        self.pixabay_url = "https://pixabay.com/api/"

    async def search_images(self, queries: str | list, per_page: int = 20, source_type: str = "all"):
        """
        ПАРАЛЛЕЛЬНЫЙ ПОИСК: только стабильные источники.
        source_type: 'all', 'photo', 'ai'
        """
        query_list = [queries] if isinstance(queries, str) else queries
        tasks = []

        for q in query_list:
            if source_type in ["all", "photo"]:
                tasks.append(self._search_pixabay(q, 10))
                tasks.append(self._search_pexels(q, 10))
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

        random.shuffle(unique_results)
        return unique_results[:per_page]

    async def _search_pollinations(self, query: str, count: int):
        """Генерирует AI картинку через стабильный эндпоинт image.pollinations.ai"""
        results = []
        # Жесткая очистка запроса для URL
        clean_q = query.replace(' ', '%20').replace('"', '').replace("'", "").strip()
        for i in range(count):
            seed = random.randint(1, 1000000)
            # Новый стабильный эндпоинт
            url = f"https://image.pollinations.ai/prompt/{clean_q}?width=720&height=1280&seed={seed}&nologo=true&enhance=false"
            results.append({"url": url, "photographer": "AI (Pollinations)"})
        return results

                        return [{"url": img["src"], "photographer": "AI (Lexica)"} for img in images[:per_page]]
                    else:
                        logger.warning(f"Lexica API returned status {resp.status}")
        except Exception as e:
            logger.error(f"Lexica error: {type(e).__name__} - {e}")
        return []

    async def _search_pexels(self, query: str, per_page: int):
        # ... остальной код без изменений
        if not PEXELS_API_KEY: return []
        headers = {"Authorization": PEXELS_API_KEY}
        params = {"query": query, "per_page": per_page, "orientation": "portrait"}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.pexels_url, headers=headers, params=params, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return [{"url": p["src"]["large"], "photographer": p["photographer"]} for p in data.get("photos", [])]
        except Exception as e:
            logger.error(f"Pexels error: {e}")
        return []

    async def _search_pixabay(self, query: str, per_page: int):
        if not PIXABAY_API_KEY: return []
        params = {
            "key": PIXABAY_API_KEY,
            "q": query,
            "image_type": "photo",
            "orientation": "vertical",
            "per_page": per_page
        }
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

image_search_agent = ImageSearchAgent()
