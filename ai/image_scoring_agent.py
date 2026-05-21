import json
import logging
import re
import hashlib
from ai.llm_client import achat_json

logger = logging.getLogger(__name__)

_SCORE_CACHE: dict[str, dict] = {}

def _score_cache_key(url: str, scene_text: str, visual: str, source: str) -> str:
    s = f"{url}|{scene_text[:100]}|{visual[:100]}|{source}"
    return hashlib.md5(s.encode()).hexdigest()[:16]

def _opt_cache_key(visual: str, spoken: str, style: str) -> str:
    s = f"{visual[:100]}|{spoken[:100]}|{style}"
    return hashlib.md5(s.encode()).hexdigest()[:16]


async def score_images(images_batch: list, scene_text: str, visual_description: str,
                       channel_rules: dict, search_source: str = "stock") -> dict:
    """
    LLM-оценка пачки изображений для авто-подбора.
    Возвращает лучшее и все оценки.
    """
    if not images_batch:
        return {"best_url": None, "best_score": 0, "scores": []}

    banned = channel_rules.get("banned_keywords", [])
    preferred = channel_rules.get("preferred_keywords", [])
    min_res = channel_rules.get("min_resolution", 800)
    style = channel_rules.get("style_notes", "")
    no_people = channel_rules.get("no_photos_of_people", False)

    # ── Entity filters из knowledge base ──
    from core.query_knowledge import query_knowledge
    entity_filters = {}
    entity_key = None
    for candidate_key in query_knowledge.detect_entity_keys(
        (scene_text + " " + visual_description)[:300], "orthodox"
    ):
        ef = query_knowledge.get_entity_filters("orthodox", candidate_key)
        if ef:
            entity_filters = ef
            entity_key = candidate_key
            break

    # ПРЕ-ФИЛЬТР: отсеиваем фото людей если запрещено
    filtered = []
    for img in images_batch:
        url_low = img.get("url", "").lower()
        w = img.get("width", 0) or 0
        h = img.get("height", 0) or 0

        # Разрешаем изображения с неизвестным размером (w == 0 or h == 0)
        if (w > 0 and w < min_res) or (h > 0 and h < min_res):
            continue

        tags_low = img.get("tags", "").lower()

        # 3. ФИЛЬТР КОММЕРЧЕСКОГО МУСОРА, ВАТЕРМАРОК И ВЕКТОРОВ
        trash_words = [
            # Watermark/stock commercial sites
            "shutterstock", "dreamstime", "alamy", "gettyimages", "istock", "depositphotos",
            "adobestock", "123rf", "watermark", "watermarked", "premium-preview", "sample",
            "album-cover", "poster-", "cd-cover", "advertisement", "promo-", "legacyicons",
            "monasteryicons", "cn-", "cn_", "stockphoto", "bigstockphoto", "canva", "freepik",
            "vecteezy", "vectorstock", "pinterest", "pinimg", "etsy", "ebay", "amazon",
            "redbubble", "teepublic", "society6", "deviantart",
            # Watermarked stock extensions & broken sources
            "flickr", "live.staticflickr", "staticflickr",
            "pixabay.com/get/g",
            "artstation", "shuttershock",
            # News & commercial
            "bbc.com", "cnn.com", "foxnews.com", "msnbc.com", "aljazeera.com", "reuters.com", "bloomberg.com",
            # Vector/illustration types
            "vector", "illustration", "cartoon", "drawing", "sketch", "clipart",
            # Competitor news logos & breaking news generic watermarks
            "bbc", "cnn", "foxnews", "msnbc", "aljazeera", "reuters", "bloomberg",
            "nytimes", "washingtonpost", "breaking news", "breakingnews", "breaking-news", "breaking_news",
            # UI/UX design platforms and mockups (frequently pollute news searches)
            "dribbble", "behance", "figma", "ui-kit", "uikit", "mockup", "wireframe",
            "color-palette", "colorpalette", "palette", "color-scheme", "swatches",
            "app-screenshot", "mobile-app", "android-app", "ios-app", "inbox-app",
            "template", "dashboard-design", "landing-page", "web-design", "branding",
            "colorhunt", "colordrop", "colorhex", "coolors",
        ]
        if any(tw in url_low for tw in trash_words) or any(tw in tags_low for tw in trash_words):
            logger.info(f"Pre-filter: rejecting commercial/watermarked image: {url_low[:60]}")
            continue
        if no_people and search_source not in ("web", "news", "icon"):
            people_words = ["portrait", "face", "man", "woman", "girl", "model",
                            "person", "people", "actor", "lady", "guy", "boy",
                            "female", "neck", "shoulder", "chest", "jewelry", "necklace", 
                            "sensual", "romance", "glamour", "fashion", "cleavage", "lingerie", 
                            "boudoir", "seductive", "lips", "mouth"]
            
            # Проверяем URL
            is_person_url = any(pw + "-" in url_low or "-" + pw in url_low for pw in people_words)
            
            # Проверяем ТЕГИ (точное совпадение слова с границами \b)
            is_person_tags = False
            for pw in people_words:
                if re.search(r'\b' + re.escape(pw) + r'\b', tags_low):
                    is_person_tags = True
                    break
            
            # Разрешаем изображения людей в религиозном контексте (монах, священник, молящийся у свечи)
            religious_keywords = ["icon", "saint", "pray", "prayer", "monk", "priest", "bible", "church", "worship", "christian", "spiritual", "orthodox", "liturgy"]
            has_religious_exception = any(rw in url_low or rw in tags_low for rw in religious_keywords)
            
            if (is_person_url or is_person_tags) and not has_religious_exception:
                logger.info(f"Pre-filter: rejecting person image (no_people=True) based on tags/URL: {tags_low[:60]}")
                continue
                
        # 4. ФИЛЬТР ЧУЖИХ РЕЛИГИЙ (ДЛЯ ПРАВОСЛАВИЯ)
        # Если включен no_people (характерно для православного профиля), жестко отсекаем йогу, буддизм и т.д.
        if no_people:
            non_christian = [
                "buddha", "buddhist", "yoga", "zen", "meditat", "hindu", "islam", "mosque",
                "karma", "chakra", "witch", "magic", "spell", "statue", "sculpture", "idol", "pagan", "tarot", 
                "shiva", "ganesha", "nirvana", "mantra", "guru", "mandala", "pagoda", 
                "shrine", "muslim", "allah", "quran", "minaret", "goddess", "mytholog", "occult", "shaman", 
                "voodoo", "astrolog", "zodiac", "wicca"
            ]
            if any(nc in url_low for nc in non_christian) or any(nc in tags_low for nc in non_christian):
                logger.info(f"Pre-filter: rejecting non-christian image based on tags/URL: {tags_low[:60]}")
                continue

        # 5. ФИЛЬТР AI-ГЕНЕРАЦИЙ (ЖУТКИЕ ИКОНЫ) И PINTEREST
        if search_source == "icon" or no_people:
            ai_words = ["ai-generated", "midjourney", "dall-e", "stablediffusion", "stable-diffusion", 
                       "generative", "neural", "ai-art", "generated", "pinimg.com", "pinterest", 
                       "deviantart", "artstation"]
            if any(ai in url_low for ai in ai_words) or any(ai in tags_low for ai in ai_words):
                continue

        blocked = False
        matched_bw = ""
        for bw in banned:
            bw_low = bw.lower()
            # 1. Проверяем URL
            if len(bw_low) >= 4 and bw_low in url_low:
                blocked = True
                matched_bw = bw
                break
            for url_part in url_low.replace("/", " ").replace("_", " ").replace("-", " ").split():
                if url_part == bw_low:
                    blocked = True
                    matched_bw = bw
                    break
            # 2. Проверяем ТЕГИ с границами слова (\b)
            if re.search(r'\b' + re.escape(bw_low) + r'\b', tags_low):
                blocked = True
                matched_bw = bw
                break
                
        if blocked:
            # Исключение для религиозных икон/изображений: не баним их из-за описания частей тела или терминов семьи/портрета
            religious_keywords = ["icon", "saint", "pray", "prayer", "monk", "priest", "bible", "church", "worship", "christian", "spiritual", "orthodox", "liturgy", "christ", "jesus", "cross", "mary", "god"]
            is_religious = any(rw in url_low or rw in tags_low for rw in religious_keywords)
            bypassed_religious_banned = {"neck", "shoulder", "shoulders", "lips", "mouth", "cheeks", "mother", "skin", "young man", "portrait man"}
            
            if is_religious and matched_bw.lower() in bypassed_religious_banned:
                blocked = False

        if blocked:
            logger.info(f"Pre-filter: rejecting image due to banned keyword '{matched_bw}' in tags/URL: {tags_low[:60]}")
            continue

        # ── Entity filters из knowledge base ──
        if entity_filters:
            ef_exclude = entity_filters.get("exclude_url", [])
            if any(bad in url_low for bad in ef_exclude):
                continue
            ef_exclude_tags = entity_filters.get("exclude_tags", [])
            if any(bad in tags_low for bad in ef_exclude_tags):
                continue
            ef_require = entity_filters.get("require_tags", [])
            if ef_require:
                has_any = any(req in tags_low for req in ef_require)
                if not has_any:
                    continue

        filtered.append(img)

    if not filtered:
        return {"best_url": None, "best_score": 0, "scores": []}

    # ── Кеш скоринга: если эта же сцена уже скорилась → вернуть сразу ──
    cache_ctx_key = hashlib.md5(
        f"SCENE|{scene_text[:150]}|{visual_description[:150]}|{search_source}".encode()
    ).hexdigest()[:16]
    cached_ctx = _SCORE_CACHE.get(cache_ctx_key)
    if cached_ctx and cached_ctx.get("url_set") == {img.get("url", "") for img in filtered}:
        return cached_ctx["result"]

    photos = []
    for img in filtered[:20]:
        photos.append({
            "id": len(photos),
            "url": img.get("url", ""),
            "width": img.get("width", 0),
            "height": img.get("height", 0),
            "source": img.get("source", "unknown"),
            "tags": img.get("tags", ""),
        })

    prompt = (
        f"You are an image curator for a video content factory.\n\n"
        f"SCENE TEXT: {scene_text[:200]}\n"
        f"VISUAL DESCRIPTION: {visual_description[:300]}\n\n"
        f"CHANNEL RULES:\n"
        f"  BANNED keywords (REJECT immediately): {', '.join(banned)}\n"
        f"  PREFERRED keywords: {', '.join(preferred)}\n"
        f"  STYLE NOTES: {style}\n\n"
        f"BATCH OF {len(photos)} IMAGES:\n"
        f"{json.dumps(photos, ensure_ascii=False)}\n\n"
        f"TASK: Score each image 0-10 AND decide if the ENTIRE BATCH is off-topic.\n\n"
        f"SCORING (per image):\n"
        f"- Relevance to scene (0-3): Use BOTH 'tags' AND 'url' path segments as evidence.\n"
        f"- Channel rules (0-3): Check banned/preferred in tags AND url.\n"
        f"- Resolution (0-2): >= {min_res}px per side.\n"
        f"- Aesthetic (0-2): Mood, composition fit.\n\n"
        f"CRITICAL SCORING RULES:\n"
        f"1. EMPTY TAGS → analyze URL path: words like 'palette','mockup','template','ui','inbox',"
        f"'clothing','jacket','embroidery','textile','craft','notebook','product' → score=0.\n"
        f"2. CONTEXT MISMATCH → score=0 even without banned keywords. Examples:\n"
        f"   - Color palette chart for a war/attack news scene → 0\n"
        f"   - Clothing product photo for any news/orthodox scene → 0\n"
        f"   - Embroidery/folk textile for Ukraine attack news → 0\n"
        f"   - E-commerce catalog (multiple products) for any scene → 0\n"
        f"   - Vector/outline graphic (white bg, black lines) for orthodox icon scene → 0\n"
        f"3. ORTHODOX ICON RULE: 'icon' source means a PAINTED RELIGIOUS ICON on wood (gold background).\n"
        f"   A vector SVG cross, outline cross, or clipart cross is NOT an orthodox icon → score=0.\n"
        f"4. BANNED KEYWORD VIOLATIONS → score=0.\n"
        f"   Orthodox: body parts, sensual content, non-Christian religions → 0.\n"
        f"5. COMPETITOR LOGOS → score=0 (BBC, CNN, Fox, Reuters, etc.).\n"
        f"6. ANALOGY RULE: If scene is metaphorical, allow indirect subjects but prefer artistic shots.\n\n"
        f"BATCH RELEVANCE DECISION:\n"
        f"After scoring, if ALL images score < 3 OR are clearly unrelated to the topic:\n"
        f"  → set 'all_irrelevant': true\n"
        f"  → provide 3 new 'fallback_queries' (English, 2-4 words, completely different angle)\n"
        f"  Example: if searching 'Ukraine attack' returned embroidery/clothing:\n"
        f"    fallback_queries: ['bomb explosion aftermath city', 'destroyed building rubble', 'air raid siren ukraine']\n\n"
        f"Return ONLY valid JSON:\n"
        f"{{ \"scores\": [{{\"url\": \"...\", \"score\": 7, \"reason\": \"brief\"}}], "
        f"\"best_url\": \"...\", \"best_score\": 7, "
        f"\"all_irrelevant\": false, \"fallback_queries\": [] }}"
    )

    try:
        result = await achat_json(user_prompt=prompt)
        scores = result.get("scores", [])
        best_url = result.get("best_url", "")
        best_score = result.get("best_score", 0)
        all_irrelevant = result.get("all_irrelevant", False)
        fallback_queries = result.get("fallback_queries", [])

        if not best_url and scores:
            best = max(scores, key=lambda x: x.get("score", 0))
            best_url = best.get("url", "")
            best_score = best.get("score", 0)

        # Auto-detect all_irrelevant if LLM didn't set it
        if not all_irrelevant and best_score < 3 and len(scores) >= 3:
            all_irrelevant = True

        logger.info(
            f"Image scoring: {len(scores)} evaluated, best={best_score}/10"
            f"{' [ALL IRRELEVANT → reformulate]' if all_irrelevant else ''}"
        )
        _SCORE_CACHE[cache_ctx_key] = {
            "url_set": {img.get("url", "") for img in filtered},
            "result": {
                "best_url": best_url,
                "best_score": best_score,
                "scores": scores,
                "all_irrelevant": all_irrelevant,
                "fallback_queries": fallback_queries,
            },
        }
        return _SCORE_CACHE[cache_ctx_key]["result"]
    except Exception as e:
        logger.error(f"Image scoring error: {e}", exc_info=True)
        return {"best_url": None, "best_score": 0, "scores": [],
                "all_irrelevant": True, "fallback_queries": []}


async def score_images_batch(
    scene_batches: list[dict],
    rules: dict = None,
    search_source: str = "stock"
) -> list[list[dict]]:
    """
    Пакетный скоринг: оценивает изображения для НЕСКОЛЬКИХ сцен
    в одном LLM вызове. Возвращает список списков scores — по одному на сцену.
    """
    if not scene_batches:
        return []

    batch_parts = []
    for i, sb in enumerate(scene_batches):
        images = sb.get("images", [])[:10]  # макс 10 картинок на сцену
        scene_text = sb.get("scene_text", "")[:120]
        visual = sb.get("visual", "")[:120]
        photos = [
            {"id": j, "url": img.get("url", ""), "w": img.get("width", 0), "h": img.get("height", 0)}
            for j, img in enumerate(images)
        ]
        batch_parts.append({
            "scene_idx": i,
            "scene_text": scene_text,
            "visual": visual,
            "photos": photos,
        })

    prompt = (
        "You are an image curator. Score images for MULTIPLE scenes in one response.\n\n"
        "For each SCENE, return a list of scores. "
        "Return JSON: { \"scene_0\": [{\"url\": \"...\", \"score\": 5}], \"scene_1\": [...] }\n\n"
    )
    for bp in batch_parts:
        prompt += (
            f"--- SCENE {bp['scene_idx']} ---\n"
            f"Text: {bp['scene_text']}\n"
            f"Visual: {bp['visual']}\n"
            f"Images: {json.dumps(bp['photos'], ensure_ascii=False)}\n\n"
        )

    results = [[] for _ in scene_batches]
    try:
        resp = await achat_json(user_prompt=prompt)
        for i in range(len(scene_batches)):
            scene_scores = resp.get(f"scene_{i}", [])
            if not isinstance(scene_scores, list):
                scene_scores = []
            results[i] = scene_scores
    except Exception as e:
        logger.error(f"score_images_batch error: {e}")

    return results

