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
    """
    from ai.llm_client import get_async_client
    try:
        client = get_async_client()

        # Маппинг реальных style_id проекта → визуальные хинты для стока
        ORTHODOX_STYLES = {"spiritual_direct", "spiritual_conflict", "theology_architect", "sacred_storyteller", "orthodox"}
        IT_STYLES = {"it_b2b_architect"}

        style_hint = ""
        if style_id in ORTHODOX_STYLES:
            style_hint = (
                "STYLE CONTEXT: Orthodox Christian / spiritual content.\n"
                "VISUAL TRANSLATION RULE: Do NOT search for literal religious objects. "
                "Translate spiritual concepts into universally available stock photo subjects:\n"
                "  'monk praying' → 'elderly man bowing head silence'\n"
                "  'orthodox church' → 'ancient stone church golden dome exterior'\n"
                "  'biblical scene' → 'middle eastern landscape desert sunrise'\n"
                "  'candle prayer' → 'single candle flame dark background'\n"
                "  'holy scripture' → 'open old book hands reading'\n"
                "PREFER: nature (sunrise mountains, forest light, ocean), "
                "human moments (elderly face, bowed head, clasped hands), "
                "architecture (stone walls, arched corridor, golden dome).\n"
                "AVOID: cartoons, icons as literal clipart, violence, modern church interiors.\n"
            )
        elif style_id in IT_STYLES:
            style_hint = (
                "STYLE CONTEXT: IT/Business content.\n"
                "PREFER: code on dark monitor, server room, dashboard UI, modern office, "
                "network infrastructure, data visualization.\n"
                "AVOID: retro tech, clipart, overly generic stock smiles.\n"
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
            f"1. First query: the most specific but REALISTIC visual (must exist on stock sites like Pexels).\n"
            f"2. Second query: the main subject simplified to 2-3 words.\n"
            f"3. Third query: the mood or atmosphere (light, space, silence, urgency).\n"
            f"4. Fourth query: a broad symbolic fallback (e.g. 'light darkness contrast').\n"
            f"5. All queries in English, 2-4 words each. NO camera directions (cinematic, 4k, bokeh).\n"
            f"6. ABSTRACTION RULE: If the literal subject is unlikely on stock photos "
            f"(e.g. 'orthodox monk', 'biblical apostle'), replace with its visual essence "
            f"(e.g. 'man bowed prayer silence', 'robed figure ancient path').\n"
            f"7. ANATOMY RULE: NEVER use 'hands' or 'fingers' as the PRIMARY subject of a query "
            f"(AI models generate anatomically broken hands). Use 'hands' only as a secondary modifier.\n"
            f"8. For color: choose ONE from: red, orange, yellow, green, turquoise, blue, "
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
            # AI (Pollinations) доступен ТОЛЬКО при явном выборе источника 'ai'.
            # В режиме 'all' он отключён: AI-генерация часто даёт анатомические артефакты
            # (лишние пальцы, деформированные руки), которые портят общую выдачу.
            if source_type == "ai":
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


async def prefetch_scene_search(scene: dict, style_id: str = "") -> dict | None:
    """
    Выполняет полный цикл AI-оптимизации запроса + поиск по стокам для одной сцены.
    Предназначен для запуска через asyncio.create_task (фоновый режим).

    Returns:
        {"queries": [...], "color": str|None, "results": [...]} или None при ошибке.
    """
    try:
        visual = scene.get("image_prompt") or scene.get("visual_description") or ""
        spoken = scene.get("text_segment", "")

        if not visual and not spoken:
            return None

        queries, color = await asyncio.wait_for(
            optimize_query_ai(visual, scene_text=spoken, style_id=style_id),
            timeout=15
        )
        results = await asyncio.wait_for(
            image_search_agent.search_images(queries, color=color, source_type="all"),
            timeout=25
        )
        logger.info(f"Prefetch complete: {len(results)} results, queries={queries}")
        return {"queries": queries, "color": color, "results": results}

    except (asyncio.TimeoutError, TimeoutError):
        logger.warning("prefetch_scene_search: timed out")
        return None
    except Exception as e:
        logger.warning(f"prefetch_scene_search: error — {e}")
        return None
