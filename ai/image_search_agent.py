import aiohttp
import asyncio
import logging
import os
import random
import re
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logger = logging.getLogger(__name__)

PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY")

if not PEXELS_API_KEY:
    logger.warning("PEXELS_API_KEY not found in .env — Pexels search will be disabled")
if not PIXABAY_API_KEY:
    logger.warning("PIXABAY_API_KEY not found in .env — Pixabay search will be disabled")


async def optimize_query_ai(visual_description: str, scene_text: str = "", style_id: str = "",
                            script: str = "", prev_scene: str = "", next_scene: str = ""):
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
                "Christian/Orthodox imagery (church dome with cross, candle-lit prayer, robed elder), "
                "architecture (stone walls, arched corridor, golden orthodox dome).\n"
                "AVOID: Buddhist monks, Hindu temples, Islamic minarets, shaolin imagery, "
                "eastern meditation, yoga poses, non-Christian religious symbols. "
                "No cartoons, icons as literal clipart, violence, modern church interiors.\n"
                "CRITICAL: Add 'christian' or 'orthodox' qualifier: 'monk' → 'christian monk', "
                "'priest' → 'orthodox priest', 'temple' → 'orthodox church'.\n"
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

        narrative_block = ""
        if prev_scene or next_scene:
            narrative_block = "NARRATIVE CONTEXT:\n"
            if prev_scene:
                narrative_block += f"  PREVIOUS SCENE: \"{prev_scene[:150]}\"\n"
            if next_scene:
                narrative_block += f"  NEXT SCENE: \"{next_scene[:150]}\"\n"
            narrative_block += "\n"

        script_block = ""
        if script:
            script_block = f"FULL VIDEO SCRIPT CONTEXT:\n{script[:600]}\n\n"

        prompt = (
            f"You are a stock photo search expert. Generate optimal search queries for a video scene.\n\n"
            f"VISUAL DESCRIPTION: {visual_description[:400]}\n"
            f"{context_block}"
            f"{script_block}"
            f"{narrative_block}"
            f"{style_hint}\n"
            f"TASK: Output EXACTLY this format (nothing else):\n"
            f"queries: [query1, query2, query3, query4]\n"
            f"color: [color_name or none]\n\n"
            f"RULES FOR QUERIES:\n"
            f"1. CONTEXT FIRST: Use the FULL SCRIPT CONTEXT to understand the video's topic. "
            f"Search for images that MATCH the overall topic, not just the literal scene description.\n"
            f"2. NARRATIVE THINKING: Identify the MAIN SUBJECT (person/object) in this scene. "
            f"If prev/next scenes are provided, keep the subject consistent — if prev scene was about a monk "
            f"and this scene is about walking, search for 'monk walking' not just 'walking'.\n"
            f"3. ACTION IS CONTEXT, NOT QUERY: 'he walked', 'she looked' → do NOT search for walking or looking. "
            f"Search for WHAT they walked towards or WHO they are.\n"
            f"4. REALITY CHECK: NEVER search for abstract, impossible, or AI-generated-looking scenes. "
            f"If the visual description describes something that doesn't exist in stock photo "
            f"databases (e.g. 'a tower made of light', 'cracks shaped like a cross'), "
            f"break it down: search for each concrete element separately "
            f"('light beams', 'tower silhouette', 'stone cracks', 'cross shape').\n"
            f"5. First query: the most specific but REALISTIC visual (must exist on stock sites like Pexels).\n"
            f"6. Second query: the main subject simplified to 2-3 words.\n"
            f"7. Third query: the mood or atmosphere related to the overall script context.\n"
            f"8. Fourth query: a broad symbolic fallback from the video's main topic.\n"
            f"9. All queries in English, 2-4 words each. NO camera directions (cinematic, 4k, bokeh).\n"
            f"10. ABSTRACTION RULE: If the literal subject is unlikely on stock photos "
            f"(e.g. 'orthodox monk', 'biblical apostle'), replace with its visual essence "
            f"(e.g. 'man bowed prayer silence', 'robed figure ancient path').\n"
            f"11. ANATOMY RULE: NEVER use 'hands' or 'fingers' as the PRIMARY subject of a query "
            f"(AI models generate anatomically broken hands). Use 'hands' only as a secondary modifier.\n"
            f"12. For color: choose ONE from: red, orange, yellow, green, turquoise, blue, "
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
            # AI (Pollinations) — добавляем в all, но с низким приоритетом.
            # Итоговый shuffle перемешивает, а плохие картинки отсеиваются визуально на карусели.
            if source_type in ("all", "ai"):
                tasks.append(self._search_pollinations(q, 3))

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


async def prefetch_scene_search(scene: dict, style_id: str = "", script: str = "",
                                  prev_scene: dict = None, next_scene: dict = None) -> dict | None:
    """
    Выполняет полный цикл AI-оптимизации запроса + поиск по стокам для одной сцены.
    """
    try:
        visual = scene.get("image_prompt") or scene.get("visual_description") or ""
        spoken = scene.get("text_segment", "")
        prev_txt = prev_scene.get("text_segment", "") if prev_scene else ""
        next_txt = next_scene.get("text_segment", "") if next_scene else ""

        if not visual and not spoken:
            return None

        queries, color = await asyncio.wait_for(
            optimize_query_ai(visual, scene_text=spoken, style_id=style_id, script=script,
                              prev_scene=prev_txt, next_scene=next_txt),
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
