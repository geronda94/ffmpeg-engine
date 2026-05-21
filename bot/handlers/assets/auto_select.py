import logging
import asyncio
import aiohttp
import os
import time

from aiogram import Router, types, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.states import ProjectStates
from core.project_manager import ProjectManager
from core.config_loader import get_config, get_channel_profile
from bot.navigation import register_trash, ask_for_asset
from ai.image_search_agent import image_search_agent, optimize_query_ai
from ai.image_scoring_agent import score_images

logger = logging.getLogger(__name__)
router = Router()
pm = ProjectManager()

SCORE_THRESHOLD = 5
AUTO_FALLBACK_CHAIN = [("pexels", "📸 Pexels"), ("pixabay", "🖼 Pixabay"), ("ai", "🤖 AI Gen")]


_last_edit_times = {}

async def _safe_edit(msg, text: str, force: bool = False):
    """Обёртка edit_text с троттлингом 3с и обработкой Flood Control."""
    if not msg:
        return
    import time, asyncio
    from aiogram.exceptions import TelegramRetryAfter
    
    msg_key = f"{msg.chat.id}_{msg.message_id}"
    now = time.time()
    if not force and now - _last_edit_times.get(msg_key, 0) < 3.0:
        return

    _last_edit_times[msg_key] = now
    try:
        await msg.edit_text(text)
    except TelegramRetryAfter as e:
        logger.warning(f"Flood control in auto_select! Waiting {e.retry_after}s...")
        await asyncio.sleep(e.retry_after + 1)
        try:
            await msg.edit_text(text)
        except Exception:
            pass
    except Exception as e:
        logger.warning(f"Safe edit failed (network): {e}")

CHRISTIAN_MARKERS = ["orthodox", "christian", "jesus", "bible", "church", "icon", "saint",
                     "cross", "virgin mary", "priest", "monastery", "angel", "god", "faith",
                     "holy", "prayer", "spiritual", "divine", "gospel", "cathedral"]

FORBIDDEN_IN_QUERIES = [
    "woman", "women", "girl", "female", "lady", "mother", "man ", "men ",
    "person", "people", "human", "model", "actor", "musician", "violin",
    "violinist", "sleep", "bed", "lying", "naked", "skin", "portrait face",
    "nude", "body", "torso", "monk", "temple", "priest", "praying man",
    "praying woman", "man praying", "yoga", "buddha", "buddhist", "zen", 
    "meditation", "hindu", "islam", "mosque", "karma", "chakra",
    "statue", "sculpture", "idol", "pagan", "witch", "magic", "spell", 
    "tarot", "demon", "devil", "satan", "shiva", "ganesha", "nirvana", 
    "mantra", "guru", "mandala", "pagoda", "shrine", "muslim", "allah", 
    "quran", "minaret", "goddess", "mythology", "occult", "shaman", 
    "voodoo", "astrology", "zodiac", "wicca"
]

SAFE_FALLBACK_QUERIES = ["church building dome", "candle prayer light", "cross silhouette",
                          "bible book open", "stained glass church", "golden dome cathedral",
                          "angel wings heaven", "faith hope love symbol"]

CHANNEL_FALLBACK_POOLS = {
    "orthodox": [
        "православный храм внутри свечи",
        "золотые купола православного храма",
        "православный крест купол небо",
        "открытая библия при свечах",
        "интерьер православного монастыря",
        "молитва перед иконой свеча",
    ],
    "news": [
        "city skyline aerial view dark",
        "world map global network",
        "press room empty microphones podium",
        "tv studio control room screens",
        "police car sirens lights night blurred",
    ]
}

def _has_christian_marker(query: str) -> bool:
    ql = query.lower()
    return any(m in ql for m in CHRISTIAN_MARKERS)


async def _auto_pick_for_scene(scene: dict, scene_idx: int, channel_profile_id: str,
                                style_id: str, full_script: str, status_msg, total: int,
                                project_id: str) -> str | None:
    visual = scene.get("image_prompt") or scene.get("visual_description") or ""
    spoken = scene.get("text_segment", "")

    if not visual and not spoken:
        return None

    proj_data = pm.load_project(project_id) or {}
    proj_lang = proj_data.get("language", "Russian")

    # ── Приоритет 0: preloaded_media — если раскадровщик пометил use_preloaded ──
    if scene.get("use_preloaded") == True:
        preloaded = proj_data.get('preloaded_media', [])
        for med in preloaded:
            if med.get('used') or med.get('type') not in ('image', None, ''):
                continue
            local = med.get('local_path', '')
            if local and os.path.exists(local):
                pm.update_asset(project_id, scene_idx, local)
                med['used'] = True
                proj_data['preloaded_media'] = preloaded
                pm.save_project(project_id, proj_data)
                logger.info(f"✅ Scene {scene_idx}: assigned preloaded media {local} (use_preloaded=true)")
                return local

    profile = get_channel_profile(channel_profile_id) if channel_profile_id else {}
    rules = profile.get("visual_rules", {})
    if not rules:
        return None

    queries, color, search_source = await asyncio.wait_for(
        optimize_query_ai(visual, scene_text=spoken, style_id=style_id, script=full_script),
        timeout=20
    )

    if channel_profile_id == "orthodox":
        safe = []
        HOLY_EXCEPTIONS = ["virgin mary", "mother of god", "saint ", "holy "]
        for q in queries:
            ql = q.lower()
            is_holy_exception = any(ex in ql for ex in HOLY_EXCEPTIONS)
            has_forbidden = not is_holy_exception and any(fw in ql for fw in FORBIDDEN_IN_QUERIES)
            if has_forbidden:
                logger.warning(f"Removing forbidden query: '{q}'")
                continue
            safe.append(q)
        if not safe:
            import random
            safe = [random.choice(SAFE_FALLBACK_QUERIES)]
            logger.warning(f"All queries had forbidden words, using fallback: {safe}")
        queries = safe

        if search_source != "icon":
            import re
            # Проверяем и исходный текст, и то, что нагенерил AI (вдруг он сам добавил слово icon)
            text_to_check = (visual + " " + spoken + " " + " ".join(queries)).lower()
            
            # Расширенный список ключевых слов для принудительного увода в DDG (иконы)
            saint_keywords = [
                # RU - Shrines & relics
                r'святын\w*', r'мощ\w*', r'рак\w*', r'ковчег\w*', r'лавр\w*', r'паломник\w*', 
                r'купел\w*', r'источник\w*', r'святог\w*', r'афон\w*', r'монастыр\w*',
                # RU - Martyrs & Saints
                r'мученик\w*', r'страстотерп\w*', r'исповедник\w*', r'пророк\w*', r'праведн\w*', 
                r'преподобн\w*', r'святител\w*', r'свято\w*', r'старец', r'старц\w*',
                # RU - Mother of God & Marian
                r'богородиц\w*', r'богоматер\w*', r'благовещен\w*', r'успен\w*', r'дева\s+мари\w*', 
                r'введен\w*\s+во\s+храм\w*',
                # RU - Scriptures & Testaments
                r'писани\w*', r'евангел\w*', r'библи\w*', r'завет\w*', r'псалтир\w*', r'псалом\w*', 
                r'псалм\w*', r'заповед\w*', r'скрижал\w*', r'моисе\w*', r'авраам\w*', r'адам\w*', 
                r'\bева\b', r'\bевы\b', r'\bеву\b', r'\bной\b', r'\bноя\b', r'райск\w*', r'покаян\w*', 
                r'грех\w*',
                # RU - Clergy & Church
                r'храм\w*', r'церков\w*', r'собор\w*', r'священник\w*', r'батюшк\w*', r'монах\w*', 
                r'монахин\w*', r'алтар\w*', r'анало\w*', r'иконостас\w*', r'кадил\w*', r'лампад\w*', 
                r'\bмиро\b', r'\bмиром\b', r'\bелей\b', r'\bелеем\b', r'просфор\w*', r'распяти\w*', 
                # RU - Holidays & Theology
                r'литурги\w*', r'причаст\w*', r'крещен\w*', r'венчан\w*', r'соборов\w*', r'молебен\w*', 
                r'панихид\w*', r'воскресен\w*', r'вознесен\w*', r'пасх\w*', r'рождеств\w*', 
                r'богоявлен\w*', r'преображен\w*', r'велики\w*\s+пост\w*', r'троиц\w*', r'господ\w*',
                r'икон\w*', r'иисус\w*', r'христос\w*', r'ангел\w*', r'архангел\w*', r'бес\w*', 
                r'демон\w*', r'дьявол\w*', r'сатан\w*', r'духовн\w*',
                # EN
                'saint', 'icon', 'jesus', 'christ', 'mary', 'virgin', 'apostle', 'savior', 'saviour',
                'lord', 'angel', 'archangel', 'theotokos', 'orthodox icon', 'crucifixion', 'resurrection'
            ]
            pattern = r'\b(' + '|'.join(saint_keywords) + r')\b'
            
            is_saint_strong = bool(re.search(pattern, text_to_check))
            if is_saint_strong:
                search_source = "icon"
                logger.info(f"Saint/icon scene {scene_idx}: forced routing to SearXNG/Web (icon)")

    # Orthodox: first 2 scenes always from web search (real icons/churches/monasteries)
    if channel_profile_id == "orthodox" and scene_idx <= 1:
        search_source = "icon"
        logger.info(f"Orthodox scene {scene_idx}: forced SearXNG/Web (first 2 scenes rule)")

    if channel_profile_id == "news" and search_source not in ("news", "web", "ai"):
        search_source = "news"
        logger.info(f"News scene {scene_idx}: forced routing to SearXNG/Web (news real-world rule)")

    logger.info(f"Auto-select scene {scene_idx}: queries={queries}, source={search_source}")

    results = []
    if search_source in ("icon", "news", "web"):
        from ai.duckduckgo_search import search_images_ddg
        await _safe_edit(status_msg,
            f"🤖 **Авто-подбор сцены {scene_idx + 1}/{total}**\n"
            f"🔍 Web поиск ({search_source}): {queries[0]}..."
        )
        try:
            # Запускаем поиск по первым 3 запросам параллельно для максимального охвата!
            tasks = []
            for q in queries[:3]:
                if search_source == "icon":
                    q_low = q.lower()
                    abstract_words = ["рука", "силуэт", "свеча", "храм", "церковь", "купол", "небо", "ребенок", "книга", "библия", "вода", "огонь", "крест", "окно", "hand", "silhouette", "candle", "temple", "church", "dome", "sky", "child", "book", "bible", "water", "fire", "cross", "window"]
                    if any(aw in q_low for aw in abstract_words):
                        ddg_q = q
                    elif channel_profile_id == "orthodox":
                        ddg_q = f"православная икона {q}" if "икон" not in q_low else q
                    else:
                        ddg_q = f"orthodox icon {q}" if "icon" not in q_low else q
                else:
                    ddg_q = q
                tasks.append(asyncio.to_thread(search_images_ddg, ddg_q, max_results=10))
                
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            for res in responses:
                if isinstance(res, list):
                    results.extend(res)
            
            # Дедупликация результатов по URL
            seen_urls = set()
            unique_results = []
            for r in results:
                url = r.get("url")
                if url and url not in seen_urls:
                    unique_results.append(r)
                    seen_urls.add(url)
            results = unique_results
            logger.info(f"Web search gathered {len(results)} unique results across queries: {queries[:3]}")
        except Exception as ex:
            logger.error(f"DDG multi-search error: {ex}")
    else:
        await _safe_edit(status_msg,
            f"🤖 **Авто-подбор сцены {scene_idx + 1}/{total}**\n"
            f"🔍 Сток ({search_source}): {', '.join(queries[:2])}..."
        )
        stype = "all" if search_source == "stock" else search_source
        results = await asyncio.wait_for(
            image_search_agent.search_images(queries, color=color, source_type=stype),
            timeout=30
        )

    # -----------------------------------------------------------------
    # ROUND 1: Primary Search & Score
    # -----------------------------------------------------------------
    best_local = None
    best_score_overall = 0
    zero_score_fallback = None

    scored = None
    if results:
        scored = await score_images(results[:20], spoken, visual, rules, search_source=search_source)
        if scored and scored.get("scores"):
            sorted_scores = sorted(scored["scores"], key=lambda x: x.get("score", 0), reverse=True)
            for img_score in sorted_scores[:7]:
                url = img_score.get("url", "")
                if not url:
                    continue
                img_score_val = img_score.get("score", 0)
                if img_score_val == 0:
                    if not zero_score_fallback:
                        zero_score_fallback = url
                    continue
                local_path = await _download_and_dedup(url, channel_profile_id)
                if local_path:
                    label = "✅" if img_score_val >= SCORE_THRESHOLD else "⚠️"
                    pm.update_asset(project_id, scene_idx, local_path)
                    await _safe_edit(status_msg,
                        f"🤖 **Сцена {scene_idx + 1}/{total}** — {label} подобрана "
                        f"(score {img_score_val}/10)"
                    )
                    best_local = local_path
                    best_score_overall = img_score_val
                    break

    # -----------------------------------------------------------------
    # ROUND 2: AI Reformulation (If Batch was irrelevant)
    # -----------------------------------------------------------------
    # If Round 1 returned complete garbage (all_irrelevant=True) OR we didn't find anything > 0
    needs_reformulation = not best_local or best_score_overall < 3
    if needs_reformulation and scored and scored.get("all_irrelevant") and scored.get("fallback_queries"):
        await _safe_edit(status_msg,
            f"🤖 **Сцена {scene_idx + 1}/{total}** — 🔄 Мусор в выдаче. Перестраиваю запрос..."
        )
        fb_queries = scored["fallback_queries"]
        # Use DDG for orthodox/news fallbacks, stock for others
        fb_source = "web" if channel_profile_id in ("orthodox", "news") else "stock"
        
        fb_results = []
        if fb_source == "web":
            from ai.duckduckgo_search import search_images_ddg
            try:
                # Use the first fallback query for DDG
                fb_results = await asyncio.to_thread(search_images_ddg, fb_queries[0], max_results=15)
            except Exception as ex:
                logger.error(f"DDG fallback search error: {ex}")
        else:
            fb_results = await asyncio.wait_for(
                image_search_agent.search_images(fb_queries, color=color, source_type="stock"),
                timeout=30
            )

        if fb_results:
            fb_desc = f"Symbolic fallback representation: {fb_queries[0]}. original context: {visual}"
            scored_fb = await score_images(fb_results[:15], spoken, fb_desc, rules, search_source=fb_source)
            if scored_fb and scored_fb.get("scores"):
                sorted_scores = sorted(scored_fb["scores"], key=lambda x: x.get("score", 0), reverse=True)
                for img_score in sorted_scores[:5]:
                    url = img_score.get("url", "")
                    if not url or img_score.get("score", 0) < 3:
                        continue
                    local_path = await _download_and_dedup(url, channel_profile_id, language=proj_lang)
                    if local_path:
                        pm.update_asset(project_id, scene_idx, local_path)
                        best_local = local_path
                        best_score_overall = img_score.get("score", 0)
                        await _safe_edit(status_msg,
                            f"🤖 **Сцена {scene_idx + 1}/{total}** — ✅ Перестроенный запрос "
                            f"(score {best_score_overall}/10)"
                        )
                        break

    # -----------------------------------------------------------------
    # ROUND 3: Channel-Specific Safe Fallbacks
    # -----------------------------------------------------------------
    if (not best_local or best_score_overall < 3) and channel_profile_id in CHANNEL_FALLBACK_POOLS:
        await _safe_edit(status_msg,
            f"🤖 **Сцена {scene_idx + 1}/{total}** — 🛡️ Ищу безопасный фон канала..."
        )
        import random
        pool = CHANNEL_FALLBACK_POOLS[channel_profile_id]
        fb_queries = [random.choice(pool)]
        
        fb_source = "web" if channel_profile_id in ("orthodox", "news") else "stock"
        
        fb_results = []
        if fb_source == "web":
            from ai.duckduckgo_search import search_images_ddg
            try:
                fb_results = await asyncio.to_thread(search_images_ddg, fb_queries[0], max_results=15)
            except Exception as ex:
                logger.error(f"DDG fallback search error: {ex}")
        else:
            fb_results = await asyncio.wait_for(
                image_search_agent.search_images(fb_queries, color=color, source_type="stock"),
                timeout=25
            )

        if fb_results:
            # IMPORTANT: Pass the fallback query as the scene text/visual so the LLM doesn't reject 
            # the safe channel fallback for being "off-topic" from the original script.
            fb_q_text = f"Channel background: {fb_queries[0]}"
            scored_fb = await score_images(fb_results[:15], fb_q_text, fb_q_text, rules, search_source=fb_source)
            if scored_fb and scored_fb.get("scores"):
                sorted_scores = sorted(scored_fb["scores"], key=lambda x: x.get("score", 0), reverse=True)
                for img_score in sorted_scores[:5]:
                    url = img_score.get("url", "")
                    if not url or img_score.get("score", 0) == 0:
                        continue
                    local_path = await _download_and_dedup(url, channel_profile_id, language=proj_lang)
                    if local_path:
                        pm.update_asset(project_id, scene_idx, local_path)
                        best_local = local_path
                        best_score_overall = img_score.get("score", 0)
                        await _safe_edit(status_msg,
                            f"🤖 **Сцена {scene_idx + 1}/{total}** — 🛡️ Безопасный фон канала "
                            f"(score {best_score_overall}/10)"
                        )
                        break

    # -----------------------------------------------------------------
    # ROUND 4: Absolute Last Resort (score=0 from Round 1)
    # -----------------------------------------------------------------
    # Instead of picking the garbage image, if all else fails, return None
    # returning None triggers text-only fallback which is better than a coloring book page.
    if not best_local:
        await _safe_edit(status_msg,
            f"🤖 **Сцена {scene_idx + 1}/{total}** — ⚠️ не удалось подобрать, пропускаем..."
        )
        return None

    if best_local:
        return best_local

    await _safe_edit(status_msg,
        f"🤖 **Сцена {scene_idx + 1}/{total}** — ⚠️ не удалось подобрать"
    )
    return None



_download_cache = {}
_download_lock = asyncio.Lock()


async def _perform_download(url: str) -> str | None:
    # Use a unique name with a hash of the URL to prevent collisions at the same millisecond
    local = f"temp/auto_{int(time.time())}_{hash(url) & 0xffffffff}.jpg"
    try:
        logger.info(f"Auto download: GET {url[:80]}...")
        # Нормализация protocol-relative URL (//domain → https://domain)
        if url.startswith("//"):
            url = "https:" + url
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    logger.warning(f"Auto download failed: HTTP {resp.status} for {url[:60]}")
                    return None
                data = await resp.read()
                if not data:
                    logger.warning(f"Auto download: empty response for {url[:60]}")
                    return None
                with open(local, "wb") as f:
                    f.write(data)
                from PIL import Image
                with Image.open(local) as img:
                    img.verify()
                with Image.open(local) as img:
                    rgb = img.convert("RGB")
                    rgb.save(local, "JPEG", quality=92, optimize=True)
                size_kb = os.path.getsize(local) / 1024
                logger.info(f"Auto download OK: {local} ({size_kb:.0f} KB)")
                return local
    except Exception as e:
        logger.error(f"Auto download exception for {url[:60]}: {e}", exc_info=True)
        if os.path.exists(local):
            os.remove(local)
    return None


async def _individual_stock_fallback(
    idx: int, scene: dict, results: list,
    channel_profile_id: str, style_id: str, full_script: str,
    rules: dict, selected_urls: set, search_source: str, proj_lang: str
) -> str | None:
    """Фоллбэк для одной сцены: перебирает 4 источника + SearXNG."""
    import random
    from ai.duckduckgo_search import search_images_ddg
    queries = [scene.get("visual_description", "church building")]

    for src_type, src_label in AUTO_FALLBACK_CHAIN:
        try:
            fallback = await asyncio.wait_for(
                image_search_agent.search_images(queries, color=None, source_type=src_type),
                timeout=25
            )
            if fallback:
                random.shuffle(fallback)
                scored = await score_images(fallback[:15],
                    scene.get("text_segment", ""),
                    scene.get("image_prompt") or scene.get("visual_description") or "",
                    rules, search_source=src_type)
                if scored and scored.get("scores"):
                    sorted_s = sorted(scored["scores"], key=lambda x: x.get("score", 0), reverse=True)
                    max_s = sorted_s[0].get("score", 0)
                    if max_s >= 3:
                        top = [x for x in sorted_s[:5] if x.get("score", 0) >= (max_s - 1 if max_s >= 7 else max_s)]
                        random.shuffle(top)
                        seen = {x.get("url") for x in top}
                        rest = [x for x in sorted_s if x.get("url") not in seen and x.get("score", 0) >= 3]
                        for img in top + rest:
                            url = img.get("url", "")
                            if not url or img.get("score", 0) < 3 or url in selected_urls:
                                continue
                            selected_urls.add(url)
                            local = await _download_and_dedup(url, channel_profile_id, language=proj_lang)
                            if local:
                                return local
                            selected_urls.remove(url)
        except Exception:
            pass

    # SearXNG ultra fallback
    try:
        fb_q = queries[0]
        if channel_profile_id == "orthodox" and any(k in fb_q.lower() for k in ["икон", "свято", "богородиц", "старец"]):
            fb_q = f"православная икона {fb_q}" if "икон" not in fb_q.lower() else fb_q
        await asyncio.sleep(1.0)
        web_results = await asyncio.to_thread(search_images_ddg, fb_q, max_results=10)
        if web_results:
            scored = await score_images(web_results[:10],
                scene.get("text_segment", ""),
                scene.get("image_prompt") or scene.get("visual_description") or "",
                rules, search_source="web")
            if scored and scored.get("scores"):
                for img in sorted(scored["scores"], key=lambda x: x.get("score", 0), reverse=True):
                    url = img.get("url", "")
                    if not url or img.get("score", 0) < 3 or url in selected_urls:
                        continue
                    selected_urls.add(url)
                    local = await _download_and_dedup(url, channel_profile_id, language=proj_lang)
                    if local:
                        return local
                    selected_urls.remove(url)
    except Exception:
        pass
    return None


async def _download_and_dedup(url: str, channel: str, scene_text: str = "", language: str = None) -> str | None:
    """Скачивает URL и помечает его в дедупликаторе."""
    local = await _download_best(url)
    if local:
        try:
            from core.url_deduplicator import deduplicator
            deduplicator.mark_used(url, channel, scene_text[:200], language=language)
        except Exception:
            pass
    return local


async def _download_best(url: str) -> str | None:
    if not url:
        logger.warning("Auto download: empty URL, skipping")
        return None

    async with _download_lock:
        if url in _download_cache:
            task = _download_cache[url]
            # If the download task has already finished, check if the file still exists on disk
            if task.done():
                try:
                    local_path = task.result()
                    if local_path and os.path.exists(local_path):
                        logger.info(f"Auto download: Cache hit (file exists): {local_path} for {url[:60]}")
                        return local_path
                except Exception:
                    pass
                # If the file was deleted or the task failed, remove it from the cache to trigger a fresh download
                _download_cache.pop(url, None)

        if url not in _download_cache:
            # Register a new task in the cache so any concurrent requests for the same URL will await it
            _download_cache[url] = asyncio.create_task(_perform_download(url))

        task = _download_cache[url]

    return await task


async def auto_pick_for_project(
    scenes: list, channel_profile_id: str, style_id: str,
    full_script: str, status_msg, project_id: str
) -> int:
    """
    Выполняет асинхронный пакетный авто-подбор картинок для всего проекта.
    Оптимизирует запросы параллельно, затем скачивает стоки параллельно, а DDG - последовательно.
    Возвращает количество успешно подобранных сцен.ё
    """
    proj_data = pm.load_project(project_id) or {}
    proj_lang = proj_data.get("language", "Russian")
    assets = proj_data.get("assets", {})
    total = len(scenes)

    # Track selected URLs in this auto-selection run to prevent duplicate images across different scenes
    selected_urls = set()

    missing_indices = [idx for idx in range(total) if str(idx) not in assets]
    if not missing_indices:
        return len(assets)

    await _safe_edit(status_msg, f"🤖 **Анализирую ссылки в тексте и оцениваю ИИ ({len(missing_indices)} шт)...**")

    from ai.image_search_agent import scrape_article_images
    scraped_urls = await scrape_article_images(full_script)
    scraped_local_paths = []
    for surl in scraped_urls:
        lpath = await _download_and_dedup(surl, channel_profile_id, language=proj_lang)
        if lpath and os.path.exists(lpath):
            scraped_local_paths.append(lpath)

    # 1. Параллельная оптимизация запросов к LLM
    opt_tasks = []
    for idx in missing_indices:
        scene = scenes[idx]
        visual = scene.get("image_prompt") or scene.get("visual_description") or ""
        spoken = scene.get("text_segment", "")
        opt_tasks.append(
            optimize_query_ai(visual, scene_text=spoken, style_id=style_id, script=full_script)
        )

    opt_results = await asyncio.gather(*opt_tasks, return_exceptions=True)

    profile = get_channel_profile(channel_profile_id) if channel_profile_id else {}
    rules = profile.get("visual_rules", {})

    ddg_queue = []
    stock_queue = []

    # 2. Фильтрация и распределение по очередям
    for i, idx in enumerate(missing_indices):
        res = opt_results[i]
        scene = scenes[idx]

        if scene.get("use_preloaded") == True:
            preloaded = proj_data.get('preloaded_media', [])
            assigned = False
            for med in preloaded:
                if med.get('used') or med.get('type') not in ('image', None, ''):
                    continue
                local = med.get('local_path', '')
                if local and os.path.exists(local):
                    pm.update_asset(project_id, idx, local)
                    med['used'] = True
                    proj_data['preloaded_media'] = preloaded
                    pm.save_project(project_id, proj_data)
                    logger.info(f"✅ Scene {idx+1}/{total}: assigned preloaded media {local} (use_preloaded=true)")
                    assigned = True
                    break
            if assigned:
                continue

        if isinstance(res, Exception):
            logger.error(f"AI Query optimization failed for scene {idx}: {res}")
            queries = [scene.get("visual_description", "church building")]
            color = None
            search_source = "stock"
        else:
            queries, color, search_source = res

        # Orthodox: применяем те же правила, что и в _auto_pick_for_scene
        if channel_profile_id == "orthodox":
            safe = []
            HOLY_EXCEPTIONS = ["virgin mary", "mother of god", "saint ", "holy "]
            for q in queries:
                ql = q.lower()
                is_holy_exception = any(ex in ql for ex in HOLY_EXCEPTIONS)
                has_forbidden = not is_holy_exception and any(fw in ql for fw in FORBIDDEN_IN_QUERIES)
                if has_forbidden:
                    logger.warning(f"Removing forbidden query: '{q}'")
                    continue
                safe.append(q)
            if not safe:
                import random
                safe = [random.choice(SAFE_FALLBACK_QUERIES)]
                logger.warning(f"All queries had forbidden words, using fallback: {safe}")
            queries = safe

            if search_source != "icon":
                import re
                visual = scene.get("image_prompt") or scene.get("visual_description") or ""
                spoken = scene.get("text_segment", "")
                text_to_check = (visual + " " + spoken + " " + " ".join(queries)).lower()
                
                saint_keywords = [
                    # RU - Shrines & relics
                    r'святын\w*', r'мощ\w*', r'рак\w*', r'ковчег\w*', r'лавр\w*', r'паломник\w*', 
                    r'купел\w*', r'источник\w*', r'святог\w*', r'афон\w*', r'монастыр\w*',
                    # RU - Martyrs & Saints
                    r'мученик\w*', r'страстотерп\w*', r'исповедник\w*', r'пророк\w*', r'праведн\w*', 
                    r'преподобн\w*', r'святител\w*', r'свято\w*', r'старец', r'старц\w*',
                    # RU - Mother of God & Marian
                    r'богородиц\w*', r'богоматер\w*', r'благовещен\w*', r'успен\w*', r'дева\s+мари\w*', 
                    r'введен\w*\s+во\s+храм\w*',
                    # RU - Scriptures & Testaments
                    r'писани\w*', r'евангел\w*', r'библи\w*', r'завет\w*', r'псалтир\w*', r'псалом\w*', 
                    r'псалм\w*', r'заповед\w*', r'скрижал\w*', r'моисе\w*', r'авраам\w*', r'адам\w*', 
                    r'\bева\b', r'\bевы\b', r'\bеву\b', r'\bной\b', r'\bноя\b', r'райск\w*', r'покаян\w*', 
                    r'грех\w*',
                    # RU - Clergy & Church
                    r'храм\w*', r'церков\w*', r'собор\w*', r'священник\w*', r'батюшк\w*', r'монах\w*', 
                    r'монахин\w*', r'алтар\w*', r'анало\w*', r'иконостас\w*', r'кадил\w*', r'лампад\w*', 
                    r'\bмиро\b', r'\bмиром\b', r'\bелей\b', r'\bелеем\b', r'просфор\w*', r'распяти\w*', 
                    # RU - Holidays & Theology
                    r'литурги\w*', r'причаст\w*', r'крещен\w*', r'венчан\w*', r'соборов\w*', r'молебен\w*', 
                    r'панихид\w*', r'воскресен\w*', r'вознесен\w*', r'пасх\w*', r'рождеств\w*', 
                    r'богоявлен\w*', r'преображен\w*', r'велики\w*\s+пост\w*', r'троиц\w*', r'господ\w*',
                    r'икон\w*', r'иисус\w*', r'христос\w*', r'ангел\w*', r'архангел\w*', r'бес\w*', 
                    r'демон\w*', r'дьявол\w*', r'сатан\w*', r'духовн\w*',
                    # EN
                    'saint', 'icon', 'jesus', 'christ', 'mary', 'virgin', 'apostle', 'savior', 'saviour',
                    'lord', 'angel', 'archangel', 'theotokos', 'orthodox icon', 'crucifixion', 'resurrection'
                ]
                pattern = r'\b(' + '|'.join(saint_keywords) + r')\b'
                is_saint_strong = bool(re.search(pattern, text_to_check))
                if is_saint_strong:
                    search_source = "icon"
                    logger.info(f"Saint/icon scene {idx}: forced routing to DDG (icon)")

        if channel_profile_id == "orthodox" and idx <= 1:
            search_source = "icon"
            logger.info(f"Orthodox scene {idx}: forced SearXNG/Web (first 2 scenes rule)")

        if channel_profile_id == "news" and search_source not in ("news", "web", "ai"):
            search_source = "news"
            logger.info(f"News scene {idx}: forced routing to SearXNG/Web (news real-world rule)")

        scene_data = {
            "idx": idx,
            "scene": scene,
            "queries": queries,
            "color": color,
            "search_source": search_source
        }

        if search_source in ("icon", "news", "web"):
            ddg_queue.append(scene_data)
        else:
            stock_queue.append(scene_data)

    # 3. PHASE 1: Поиск по стокам (search+dedup, БЕЗ скоринга)
    sem = asyncio.Semaphore(5)
    all_search_results: dict[int, dict] = {}  # {idx: {"images": [...], "scene_text": "...", "visual": "..."}}

    async def search_stock_scene(data):
        idx = data["idx"]
        scene = data["scene"]
        queries = data["queries"]
        color = data["color"]
        search_source = data["search_source"]

        async with sem:
            await _safe_edit(status_msg,
                f"🤖 **Подбор стоков**\n"
                f"🔍 Сцена {idx+1}/{total}: {', '.join(queries[:2])}..."
            )
            stype = "all" if search_source == "stock" else search_source
            try:
                results = await asyncio.wait_for(
                    image_search_agent.search_images(queries, color=color, source_type=stype),
                    timeout=30
                )
            except Exception as ex:
                logger.error(f"Stock search error for scene {idx}: {ex}")
                results = []

            if results:
                import random
                random.shuffle(results)
                from core.url_deduplicator import deduplicator
                before_dedup = len(results)
                results = deduplicator.filter_results(results, channel_profile_id, language=proj_lang)
                if before_dedup > len(results):
                    logger.info(f"Scene {idx}: stock dedup {before_dedup} → {len(results)}")
                if not results:
                    from ai.duckduckgo_search import reformulate_query_ai
                    new_qs = await reformulate_query_ai(
                        scene.get("image_prompt") or scene.get("visual_description") or "",
                        queries, style_id, full_script
                    )
                    if new_qs:
                        queries = new_qs
                        try:
                            results = await asyncio.wait_for(
                                image_search_agent.search_images(queries, color=None, source_type=stype),
                                timeout=30
                            )
                        except Exception:
                            results = []

            # Сохраняем для батч-скоринга
            if results:
                all_search_results[idx] = {
                    "images": results[:20],
                    "scene_text": scene.get("text_segment", ""),
                    "visual": scene.get("image_prompt") or scene.get("visual_description") or "",
                    "search_source": search_source,
                    "scene": scene,
                }
            return idx, all_search_results.get(idx)

    if stock_queue:
        logger.info(f"Stage 1: stock parallel SEARCH ({len(stock_queue)} scenes)")
        await asyncio.gather(*(search_stock_scene(data) for data in stock_queue))

    logger.info(f"Stage 1 complete: stock results collected for {len(all_search_results)} scenes")

    # ── PHASE 2: Батч-скоринг сток-результатов ──
    if all_search_results:
        from ai.image_scoring_agent import score_images_batch
        batch_items = list(all_search_results.values())
        batch_scores: dict[int, list] = {}
        for chunk_start in range(0, len(batch_items), 5):
            chunk = batch_items[chunk_start:chunk_start + 5]
            chunk_indices = [next(k for k, v in all_search_results.items() if v is item) for item in chunk]
            try:
                scored_list = await score_images_batch(chunk, rules, search_source=chunk[0].get("search_source", "stock"))
                for ci, scores in zip(chunk_indices, scored_list):
                    batch_scores[ci] = scores
            except Exception as e:
                logger.error(f"Batch scoring failed for chunk {chunk_start}: {e}")

    # ── PHASE 3: Скачивание лучших изображений для сток-сцен ──
    async def download_best_for_scene(idx, scene, scored_list, selected_urls, search_source="stock"):
        best_local = None
        if scored_list:
            sorted_scores = sorted(scored_list, key=lambda x: x.get("score", 0), reverse=True)
            max_score = sorted_scores[0].get("score", 0)
            if max_score >= 3:
                if max_score >= 7:
                    top = [x for x in sorted_scores[:5] if x.get("score", 0) >= max_score - 1]
                else:
                    top = [x for x in sorted_scores[:5] if x.get("score", 0) == max_score]
                import random
                random.shuffle(top)
                seen = {x.get("url") for x in top}
                rest = [x for x in sorted_scores if x.get("url") not in seen and x.get("score", 0) >= 3]
                eval_order = top + rest
                for img_score in eval_order:
                    url = img_score.get("url", "")
                    if not url or img_score.get("score", 0) < 3:
                        continue
                    if url in selected_urls:
                        continue
                    selected_urls.add(url)
                    local_path = await _download_and_dedup(url, channel_profile_id, language=proj_lang)
                    if local_path:
                        best_local = local_path
                        break
                    else:
                        selected_urls.remove(url)

        if not best_local:
            best_local = await _individual_stock_fallback(
                idx, scene, all_search_results.get(idx, {}).get("images", []),
                channel_profile_id, style_id, full_script, rules, selected_urls, search_source, proj_lang
            )

        if best_local:
            pm.update_asset(project_id, idx, best_local)
            logger.info(f"✅ Scene {idx+1}/{total} stock pick OK: {best_local}")
        else:
            logger.warning(f"❌ Scene {idx+1}/{total} stock pick FAILED")
        return best_local

    if all_search_results:
        logger.info(f"Stage 2/3: stock download ({len(all_search_results)} scenes)")
        for scene_idx, sr in all_search_results.items():
            scores = batch_scores.get(scene_idx, [])
            await download_best_for_scene(
                scene_idx, sr["scene"], scores, selected_urls,
                search_source=sr.get("search_source", "stock")
            )

    # 4. PHASE 1: Последовательный ПОИСК DuckDuckGo (БЕЗ скоринга)
    ddg_search_results: dict[int, dict] = {}
    for data in ddg_queue:
        idx = data["idx"]
        scene = data["scene"]
        queries = data["queries"]
        search_source = data["search_source"]

        # Приоритет первоисточника для новостных проектов (первые сцены)
        if scraped_local_paths and channel_profile_id == "news" and idx < len(scraped_local_paths):
            cand_path = scraped_local_paths[idx]
            pm.update_asset(project_id, idx, cand_path)
            logger.info(f"✅ Scene {idx+1}/{total} assigned scraped article image: {cand_path}")
            continue

        await _safe_edit(status_msg,
            f"🤖 **Подбор (веб-поиск SearXNG/Web)**\n"
            f"🔍 Сцена {idx+1}/{total}: {queries[0]}..."
        )

        from ai.duckduckgo_search import search_images_ddg
        results = []
        for q in queries:
            try:
                if search_source == "icon":
                    q_low = q.lower()
                    abstract_words = ["рука", "силуэт", "свеча", "храм", "церковь", "купол", "небо", "ребенок", "книга", "библия", "вода", "огонь", "крест", "окно", "hand", "silhouette", "candle", "temple", "church", "dome", "sky", "child", "book", "bible", "water", "fire", "cross", "window"]
                    if any(aw in q_low for aw in abstract_words):
                        ddg_q = q
                    elif channel_profile_id == "orthodox":
                        ddg_q = f"православная икона {q}" if "икон" not in q_low else q
                    else:
                        ddg_q = f"orthodox icon {q}" if "icon" not in q_low else q
                else:
                    ddg_q = q
                await asyncio.sleep(1.0)
                q_results = await asyncio.to_thread(search_images_ddg, ddg_q, max_results=20)
                if q_results:
                    results.extend(q_results)
                    break
            except Exception as ex:
                logger.error(f"SearXNG search error for scene {idx}, query '{q}': {ex}")

        if results:
            import random
            random.shuffle(results)
            from core.url_deduplicator import deduplicator
            before_dedup = len(results)
            results = deduplicator.filter_results(results, channel_profile_id, language=proj_lang)
            if before_dedup > len(results):
                logger.info(f"Scene {idx}: SearXNG dedup {before_dedup} → {len(results)}")

            is_reformulated = False
            if not results:
                from ai.duckduckgo_search import reformulate_query_ai
                new_qs = await reformulate_query_ai(
                    scene.get("image_prompt") or scene.get("visual_description") or "",
                    queries, style_id, full_script
                )
                if new_qs:
                    is_reformulated = True
                    queries = list(new_qs)
                    for q in queries:
                        if search_source == "icon":
                            q_low = q.lower()
                            if any(aw in q_low for aw in abstract_words):
                                new_ddg_q = q
                            elif channel_profile_id == "orthodox":
                                new_ddg_q = f"православная икона {q}" if "икон" not in q_low else q
                            else:
                                new_ddg_q = f"orthodox icon {q}" if "icon" not in q_low else q
                        else:
                            new_ddg_q = q
                        try:
                            await asyncio.sleep(1.0)
                            results = await asyncio.to_thread(search_images_ddg, new_ddg_q, max_results=20)
                            if results: break
                        except Exception:
                            pass

            visual_desc = scene.get("image_prompt") or scene.get("visual_description") or ""
            if is_reformulated and queries:
                visual_desc = f"Symbolic fallback: {queries[0]}"

            ddg_search_results[idx] = {
                "images": results[:20],
                "scene_text": scene.get("text_segment", ""),
                "visual": visual_desc,
                "search_source": search_source,
                "scene": scene,
                "queries": queries,
            }
        await asyncio.sleep(1.0)

    # ── PHASE 2: Батч-скоринг DDG-результатов ──
    if ddg_search_results:
        from ai.image_scoring_agent import score_images_batch
        ddg_items = list(ddg_search_results.values())
        ddg_batch_scores: dict[int, list] = {}
        for chunk_start in range(0, len(ddg_items), 5):
            chunk = ddg_items[chunk_start:chunk_start + 5]
            chunk_indices = [next(k for k, v in ddg_search_results.items() if v is item) for item in chunk]
            try:
                scored_list = await score_images_batch(chunk, rules, search_source=chunk[0].get("search_source", "web"))
                for ci, scores in zip(chunk_indices, scored_list):
                    ddg_batch_scores[ci] = scores
            except Exception as e:
                logger.error(f"DDG batch scoring failed for chunk {chunk_start}: {e}")

    # ── PHASE 3: Скачивание лучших DDG изображений ──
    for idx, sr in ddg_search_results.items():
        scene = sr["scene"]
        scores = ddg_batch_scores.get(idx, [])
        best_local = None
        if scores:
            import random
            sorted_scores = sorted(scores, key=lambda x: x.get("score", 0), reverse=True)
            max_score = sorted_scores[0].get("score", 0)
            if max_score >= 3:
                if max_score >= 7:
                    top = [x for x in sorted_scores[:5] if x.get("score", 0) >= max_score - 1]
                else:
                    top = [x for x in sorted_scores[:5] if x.get("score", 0) == max_score]
                random.shuffle(top)
                seen = {x.get("url") for x in top}
                rest = [x for x in sorted_scores if x.get("url") not in seen and x.get("score", 0) >= 3]
                for img_score in top + rest:
                    url = img_score.get("url", "")
                    if not url or img_score.get("score", 0) < 3 or url in selected_urls:
                        continue
                    selected_urls.add(url)
                    local_path = await _download_and_dedup(url, channel_profile_id, language=proj_lang)
                    if local_path:
                        pm.update_asset(project_id, idx, local_path)
                        best_local = local_path
                        break
                    else:
                        selected_urls.remove(url)

        if not best_local:
            # Индивидуальный фоллбэк для сцены
            import random
            if channel_profile_id in CHANNEL_FALLBACK_POOLS:
                fb_q = random.choice(CHANNEL_FALLBACK_POOLS[channel_profile_id])
                from ai.duckduckgo_search import search_images_ddg
                try:
                    await asyncio.sleep(1.0)
                    fb_results = await asyncio.to_thread(search_images_ddg, fb_q, max_results=15)
                    if fb_results:
                        scored = await score_images(fb_results[:15], fb_q, fb_q, rules, search_source="web")
                        if scored and scored.get("scores"):
                            for img in sorted(scored["scores"], key=lambda x: x.get("score", 0), reverse=True):
                                url = img.get("url", "")
                                if not url or img.get("score", 0) < 3 or url in selected_urls:
                                    continue
                                selected_urls.add(url)
                                local = await _download_and_dedup(url, channel_profile_id, language=proj_lang)
                                if local:
                                    pm.update_asset(project_id, idx, local)
                                    best_local = local
                                    break
                                else:
                                    selected_urls.remove(url)
                except Exception as e:
                    logger.error(f"DDG channel fallback error for scene {idx}: {e}")

            if not best_local:
                for src_type, src_label in AUTO_FALLBACK_CHAIN:
                    try:
                        fb_qs = sr.get("queries", [])[1:] or sr.get("queries", [chr(ord('a'))])
                        fallback = await asyncio.wait_for(
                            image_search_agent.search_images(fb_qs, color=None, source_type=src_type),
                            timeout=25
                        )
                        if fallback:
                            random.shuffle(fallback)
                            scored = await score_images(fallback[:15],
                                scene.get("text_segment", ""),
                                scene.get("image_prompt") or scene.get("visual_description") or "",
                                rules, search_source=src_type)
                            if scored and scored.get("scores"):
                                for img in sorted(scored["scores"], key=lambda x: x.get("score", 0), reverse=True):
                                    url = img.get("url", "")
                                    if not url or img.get("score", 0) < 3 or url in selected_urls:
                                        continue
                                    selected_urls.add(url)
                                    local = await _download_and_dedup(url, channel_profile_id, language=proj_lang)
                                    if local:
                                        pm.update_asset(project_id, idx, local)
                                        best_local = local
                                        break
                                    else:
                                        selected_urls.remove(url)
                    except Exception:
                        pass
                    if best_local:
                        break

        if best_local:
            logger.info(f"✅ Scene {idx+1}/{total} SearXNG/fallback pick OK: {best_local}")
        else:
            logger.warning(f"❌ Scene {idx+1}/{total} SearXNG pick FAILED completely")

    # ── PHASE FINAL: Фоллбэки для сцен, оставшихся без картинок ──
    proj_current = pm.load_project(project_id) or {}
    for idx in range(total):
        if str(idx) not in proj_current.get("assets", {}):
            scene = scenes[idx]
            logger.info(f"⚠️ Scene {idx+1}/{total} still missing — running individual fallback...")
            await _safe_edit(status_msg, f"⚠️ **Сцена {idx+1}/{total}** — фоллбэк...")
            from ai.duckduckgo_search import search_images_ddg
            fb_local = await _individual_stock_fallback(
                idx, scene, [],
                channel_profile_id, style_id, full_script,
                rules, selected_urls, "stock", proj_lang
            )
            if fb_local:
                pm.update_asset(project_id, idx, fb_local)
                logger.info(f"✅ Scene {idx+1}/{total} final fallback pick OK: {fb_local}")
            else:
                logger.warning(f"❌ Scene {idx+1}/{total} final fallback FAILED")

    # Загружаем актуальное состояние проекта
    proj_final = pm.load_project(project_id) or {}
    return len(proj_final.get("assets", {}))


@router.callback_query(F.data == "asset_auto", StateFilter(ProjectStates.collecting_assets))
async def handle_auto_select(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    project_id = data.get("project_id")
    style_id = data.get("script_style", "")

    proj_data = pm.load_project(project_id)
    if not proj_data:
        await callback.message.answer("❌ Проект не найден.")
        return

    scenes = proj_data.get("scenes", [])
    if not scenes:
        await callback.message.answer("❌ Нет сцен для подбора.")
        return

    channel_prof = proj_data.get("channel_profile", "educational")
    full_script = proj_data.get("script", "")

    total = len(scenes)
    status = await callback.message.answer(
        f"🤖 **Запущен авто-подбор (пакетный режим)**\n"
        f"Сцен: **{total}** | Канал: **{channel_prof}**\n"
        f"Инициализирую параллельную очередь..."
    )
    await register_trash(status, state)

    success = await auto_pick_for_project(
        scenes, channel_prof, style_id, full_script, status, project_id
    )

    await _safe_edit(status,
        f"🤖 **Авто-подбор завершён**\n"
        f"Подобрано: **{success}/{total}** сцен",
        force=True
    )

    proj_data = pm.load_project(project_id)
    assets = proj_data.get('assets', {})
    scenes = proj_data.get('scenes', [])

    next_missing = len(scenes)
    for i in range(len(scenes)):
        if str(i) not in assets:
            next_missing = i
            break

    if next_missing >= len(scenes):
        logger.info(f"All {len(scenes)} scenes have assets. Proceeding to TTS.")
        if proj_data and proj_data.get('auto_pipeline'):
            from bot.handlers.auto_pipeline import resume_auto_after_assets
            await resume_auto_after_assets(callback.message, state, project_id)
        else:
            from bot.navigation import ask_for_tts_engine
            await ask_for_tts_engine(callback.message, state)
    else:
        chat_type = callback.message.chat.type
        if chat_type in ("group", "supergroup"):
            kb = InlineKeyboardBuilder()
            kb.button(text="📝 Продолжить сбор", callback_data=f"continue_asset:{project_id}")
            await _safe_edit(status,
                f"⚠️ **Не все сцены собраны** ({next_missing + 1}/{len(scenes)})\n"
                f"Бот написал в ЛС — проверь.",
                force=True
            )
            try:
                await callback.bot.send_message(
                    chat_id=callback.from_user.id,
                    text=f"⚠️ **В проекте `{project_id}` не собраны все сцены.**\n\n"
                         f"Первая пропущенная: сцена **{next_missing + 1}/{len(scenes)}**\n\n"
                         f"Нажми кнопку чтобы продолжить сбор вручную:",
                    reply_markup=kb.as_markup(),
                )
            except Exception as e:
                logger.warning(f"Failed to DM user: {e}")
                await ask_for_asset(callback.message, state, next_missing)
        else:
            await ask_for_asset(callback.message, state, next_missing)
