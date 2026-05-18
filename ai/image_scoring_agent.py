import json
import logging
import re
from ai.llm_client import achat_json

logger = logging.getLogger(__name__)


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

    # ПРЕ-ФИЛЬТР: отсеиваем фото людей если запрещено
    filtered = []
    for img in images_batch:
        url_low = img.get("url", "").lower()
        w = img.get("width", 0) or 0
        h = img.get("height", 0) or 0

        if w < min_res or h < min_res:
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
            # Vector/illustration types
            "vector", "illustration", "cartoon", "drawing", "sketch", "clipart",
            # Competitor news logos
            "bbc", "cnn", "foxnews", "msnbc", "aljazeera", "reuters", "bloomberg",
            "nytimes", "washingtonpost",
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
                            "person", "people", "actor", "photo", "lady", "guy", "boy",
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
            
            has_icon = "icon" in url_low or "saint" in url_low or "icon" in tags_low or "saint" in tags_low
            if (is_person_url or is_person_tags) and not has_icon:
                logger.info(f"Pre-filter: rejecting person image (no_people=True) based on tags/URL: {tags_low[:60]}")
                continue
                
        # 4. ФИЛЬТР ЧУЖИХ РЕЛИГИЙ (ДЛЯ ПРАВОСЛАВИЯ)
        # Если включен no_people (характерно для православного профиля), жестко отсекаем йогу, буддизм и т.д.
        if no_people:
            non_christian = [
                "buddha", "buddhist", "yoga", "zen", "meditat", "hindu", "islam", "mosque", "monk", "temple", 
                "karma", "chakra", "witch", "magic", "spell", "statue", "sculpture", "idol", "pagan", "tarot", 
                "demon", "devil", "satan", "shiva", "ganesha", "nirvana", "mantra", "guru", "mandala", "pagoda", 
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
            logger.info(f"Pre-filter: rejecting image due to banned keyword '{matched_bw}' in tags/URL: {tags_low[:60]}")
            continue

        filtered.append(img)

    if not filtered:
        return {"best_url": None, "best_score": 0, "scores": []}

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
        return {
            "best_url": best_url,
            "best_score": best_score,
            "scores": scores,
            "all_irrelevant": all_irrelevant,
            "fallback_queries": fallback_queries,
        }
    except Exception as e:
        logger.error(f"Image scoring error: {e}", exc_info=True)
        return {"best_url": None, "best_score": 0, "scores": [],
                "all_irrelevant": True, "fallback_queries": []}

