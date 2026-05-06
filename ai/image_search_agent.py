import aiohttp
import asyncio
import logging
import os
import random
import re

logger = logging.getLogger(__name__)

PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "563492ad6f91700001000001bc3b392a5b6c4f03998b3f309a63588a")
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "43825832-75d192135d8d083f9876e5d23")


async def optimize_query_ai(visual_description: str, scene_text: str = "", style_id: str = ""):
    """
    Превращает описание сцены в набор умных поисковых запросов + цвет.

    Улучшения:
    - Принимает text_segment как дополнительный контекст
    - Учитывает стиль (orthodox, scientific и т.д.) при выборе ключевых слов
    - Генерирует 4 запроса: от конкретного к абстрактному
    - Явно запрещает технические термины в запросах
    """
    from ai.llm_client import get_async_client
    try:
        client = get_async_client()

        style_hint = ""
        if style_id == "orthodox":
            style_hint = (
                "STYLE CONTEXT: This is Orthodox Christian content. "
                "Prefer queries for: nature (sunrise, mountains, forest light), "
                "human moments (prayer hands, elderly face, child), "
                "church architecture (golden dome, icon, candle flame). "
                "AVOID: cartoons, abstract art, violence, secular party imagery.\n"
            )
        elif style_id == "scientific":
            style_hint = (
                "STYLE CONTEXT: Scientific/educational content. "
                "Prefer queries for: macro photography, space, microscopic, physics, nature close-ups. "
                "AVOID: talking heads, office settings, generic corporate stock.\n"
            )
        elif style_id == "news":
            style_hint = (
                "STYLE CONTEXT: News broadcast content. "
                "Prefer queries for: city skylines, government buildings, press conferences, data charts. "
                "AVOID: cute or whimsical imagery.\n"
            )
        elif style_id == "hype":
            style_hint = (
                "STYLE CONTEXT: Viral/hype marketing content. "
                "Prefer queries for: dramatic lighting, luxury items, intense faces, neon cityscape at night. "
                "AVOID: soft pastels, calm nature, anything boring.\n"
            )

        context_block = ""
        if scene_text:
            context_block = f"SPOKEN TEXT IN THIS SCENE: \"{scene_text[:200]}\"\n"

        prompt = (
            f"You are a stock photo search expert. Generate optimal search queries for a video scene.\n\n"
            f"VISUAL DESCRIPTION: {visual_description[:400]}\n"
            f"{context_block}"
            f"{style_hint}\n"
            f"TASK: Output EXACTLY this format (nothing else):\n"
            f"queries: [query1, query2, query3, query4]\n"
            f"color: [color_name or none]\n\n"
            f"RULES FOR QUERIES:\n"
            f"1. First query: most specific visual element (e.g. 'astronaut red planet surface')\n"
            f"2. Second query: the key subject alone (e.g. 'astronaut space')\n"
            f"3. Third query: the mood/atmosphere (e.g. 'red desert landscape vast')\n"
            f"4. Fourth query: abstract/symbolic fallback (e.g. 'space exploration mystery')\n"
            f"5. All queries in English, 2-4 words each.\n"
            f"6. NO camera directions, NO style words (cinematic, 4k, photorealistic).\n"
            f"7. For color: choose ONE from: red, orange, yellow, green, turquoise, blue, "
            f"violet, pink, brown, black, gray, white — or 'none' if not important."
        )

        response = await client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
            temperature=0.2
        )
        content = response.choices[0].message.content.strip().lower()

        queries_match = re.findall(r"queries:\s*\[(.*?)\]", content, re.DOTALL)
        color_match = re.findall(r"color:\s*\[(.*?)\]", content)

        if queries_match:
            raw = queries_match[0]
            k_list = [k.strip().strip("'\"") for k in raw.split(",") if k.strip()]
            k_list = [k for k in k_list if len(k) > 1][:4]
        else:
            # fallback: берём первые слова описания
            words = visual_description.split()[:6]
            k_list = [" ".join(words[:3]), " ".join(words[3:6]) or words[0]]

        c_val = None
        if color_match:
            c_raw = color_match[0].strip().strip("'\"")
            if c_raw and c_raw != "none":
                c_val = c_raw

        logger.info(f"AI Search Optimization: queries={k_list}, color={c_val}")
        return k_list, c_val

    except Exception as e:
        logger.error(f"Failed to optimize query via AI: {e}")
        words = visual_description.split()
        return [" ".join(words[:4]), " ".join(words[:2])], None


class ImageSearchAgent:
    def __init__(self):
        self.pexels_url = "https://api.pexels.com/v1/search"
        self.pixabay_url = "https://pixabay.com/api/"

    async def search_images(
        self,
        queries: str | list,
        per_page: int = 20,
        source_type: str = "all",
        color: str = None
    ):
        """
        Параллельный поиск по стокам.

        source_type: 'all' | 'pexels' | 'pixabay' | 'ai'

        Ключевое улучшение: ищем БЕЗ фиксированной ориентации,
        выбираем лучшие фото по соответствию описанию, а не по размеру.
        """
        query_list = [queries] if isinstance(queries, str) else queries
        tasks = []

        for q in query_list:
            if source_type in ("all", "pixabay"):
                tasks.append(self._search_pixabay(q, 15, color))
            if source_type in ("all", "pexels"):
                tasks.append(self._search_pexels(q, 15, color))
            if source_type in ("all", "ai"):
                tasks.append(self._search_pollinations(q, 6))

        responses = await asyncio.gather(*tasks, return_exceptions=True)

        all_results = []
        for res in responses:
            if isinstance(res, list):
                all_results.extend(res)

        # Дедупликация по URL
        unique_results = []
        seen_urls = set()
        for r in all_results:
            url = r.get("url", "")
            if url and url not in seen_urls:
                unique_results.append(r)
                seen_urls.add(url)

        # Если цветовой фильтр дал < 6 результатов — дополняем без фильтра цвета
        if color and len(unique_results) < 6:
            logger.info(f"Color '{color}' too strict ({len(unique_results)} results), adding unfiltered pass...")
            extra_tasks = []
            for q in query_list[:2]:
                if source_type in ("all", "pixabay"):
                    extra_tasks.append(self._search_pixabay(q, 10, color=None))
                if source_type in ("all", "pexels"):
                    extra_tasks.append(self._search_pexels(q, 10, color=None))
            extra_responses = await asyncio.gather(*extra_tasks, return_exceptions=True)
            for res in extra_responses:
                if isinstance(res, list):
                    for r in res:
                        url = r.get("url", "")
                        if url and url not in seen_urls:
                            unique_results.append(r)
                            seen_urls.add(url)

        random.shuffle(unique_results)
        logger.info(f"Total unique results: {len(unique_results)} (source={source_type})")
        return unique_results[:per_page]

    async def _search_pollinations(self, query: str, count: int):
        """Генерирует AI-изображения через pollinations.ai (вертикальный формат 9:16)."""
        results = []
        clean_q = query.replace(" ", "%20").replace('"', "").replace("'", "").strip()
        for _ in range(count):
            seed = random.randint(1, 999999)
            url = (
                f"https://image.pollinations.ai/prompt/{clean_q}"
                f"?width=720&height=1280&seed={seed}&nologo=true&enhance=false"
            )
            results.append({"url": url, "photographer": "AI (Pollinations)", "source": "ai"})
        return results

    async def _search_pexels(self, query: str, per_page: int, color: str = None):
        """
        Поиск в Pexels.
        Убрана фиксированная orientation=portrait — ищем любые форматы,
        т.к. рендер сам сделает fit/cover. Берём large2x для максимального качества.
        """
        if not PEXELS_API_KEY:
            return []
        headers = {"Authorization": PEXELS_API_KEY}
        params = {"query": query, "per_page": per_page}
        if color:
            params["color"] = color

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.pexels_url, headers=headers, params=params, timeout=12
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return [
                            {
                                "url": p["src"].get("large2x") or p["src"]["large"],
                                "photographer": p["photographer"],
                                "source": "pexels",
                                "width": p.get("width", 0),
                                "height": p.get("height", 0),
                            }
                            for p in data.get("photos", [])
                        ]
                    else:
                        logger.warning(f"Pexels returned status {resp.status}")
        except Exception as e:
            logger.error(f"Pexels error: {e}")
        return []

    async def _search_pixabay(self, query: str, per_page: int, color: str = None):
        """
        Поиск в Pixabay.
        Убрана orientation=vertical — ищем любые форматы.
        """
        if not PIXABAY_API_KEY:
            return []
        # Pixabay limit: 100 chars + strictly alphanumeric
        clean_q = re.sub(r'[^a-zA-Z0-9\s]', '', query)[:100]
        params = {
            "key": PIXABAY_API_KEY,
            "q": clean_q,
            "image_type": "photo",
            "per_page": min(per_page, 20),
            "safesearch": "true",
        }
        if color:
            params["colors"] = color

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.pixabay_url, params=params, timeout=12
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return [
                            {
                                "url": h["largeImageURL"],
                                "photographer": h["user"],
                                "source": "pixabay",
                                "width": h.get("imageWidth", 0),
                                "height": h.get("imageHeight", 0),
                            }
                            for h in data.get("hits", [])
                        ]
                    else:
                        logger.warning(f"Pixabay returned status {resp.status}")
        except Exception as e:
            logger.error(f"Pixabay error: {e}")
        return []


image_search_agent = ImageSearchAgent()
