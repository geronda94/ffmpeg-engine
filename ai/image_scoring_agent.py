import json
import logging
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

        # 3. ФИЛЬТР КОММЕРЧЕСКОГО МУСОРА И ОБЛОЖЕК
        trash_words = ["shutterstock", "dreamstime", "alamy", "gettyimages", "istock", 
                       "album-cover", "poster-", "cd-cover", "advertisement", "promo-"]
        if any(tw in url_low for tw in trash_words):
            continue

        if no_people and search_source not in ("web", "news", "icon"):
            people_words = ["portrait", "face", "man-", "woman-", "girl-", "model-",
                           "person-", "people-", "actor", "photo-"]
            is_person = any(pw in url_low for pw in people_words)
            has_icon = "icon" in url_low or "saint" in url_low
            if is_person and not has_icon:
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
            if any(nc in url_low for nc in non_christian):
                continue

        # 5. ФИЛЬТР AI-ГЕНЕРАЦИЙ (ЖУТКИЕ ИКОНЫ) И PINTEREST
        if search_source == "icon" or no_people:
            ai_words = ["ai-generated", "midjourney", "dall-e", "stablediffusion", "stable-diffusion", 
                       "generative", "neural", "ai-art", "generated", "pinimg.com", "pinterest", 
                       "deviantart", "artstation"]
            if any(ai in url_low for ai in ai_words):
                continue

        blocked = False
        for bw in banned:
            if len(bw) >= 4 and bw.lower() in url_low:
                blocked = True
                break
            # Check individual words in URL
            for url_part in url_low.replace("/", " ").replace("_", " ").replace("-", " ").split():
                if url_part == bw.lower():
                    blocked = True
                    break
            if blocked:
                break
        if blocked:
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
        f"  BANNED keywords (REJECT immediately any image that depicts or suggests these): {', '.join(banned)}\n"
        f"  PREFERRED keywords (bonus points if image matches these): {', '.join(preferred)}\n"
        f"  MINIMUM resolution per side: {min_res}px\n"
        f"  STYLE NOTES: {style}\n\n"
        f"BATCH OF {len(photos)} IMAGES:\n"
        f"{json.dumps(photos, ensure_ascii=False)}\n\n"
        f"SCORE each image 0-10:\n"
        f"- Relevance to scene (0-3): Does this image match the scene's visual description? (Evaluate using the 'tags' field!)\n"
        f"- Channel rules compliance (0-3): Does it follow banned/preferred rules? (Check 'tags' carefully!)\n"
        f"- Resolution quality (0-2): Is it >= {min_res}px per side?\n"
        f"- Aesthetic (0-2): Composition, lighting, mood fit.\n\n"
        f"CRITICAL RULES:\n"
        f"1. If an image's tags or URL clearly violate banned keywords (e.g., woman, shaolin, islam for orthodox channel) → score = 0.\n"
        f"   EXCEPTION: For Orthodox channel, if search_source is 'web', 'news' or 'icon', photos of CONTEMPORARY CLERGY or ANCIENT SAINTS ARE ALLOWED and should not be penalized by the 'no people' rule.\n"
        f"2. ENTITY VERIFICATION: This is CRITICAL. If the scene requires a SPECIFIC KNOWN PERSON (e.g. 'Metropolitan Pavel', 'Gregory of Nyssa') and the image tags describe a DIFFERENT person (e.g. 'Singer', 'Joe Biden', 'Jesus Christ' when looking for a saint) → score = 0.\n"
        f"   - If looking for an 'icon', and the result is a modern photo of a person → score = 0 (unless it's a modern saint/cleric).\n"
        f"   - If looking for a specific saint, and the result is an album cover, movie poster, or modern celebrity → score = 0.\n"
        f"3. NO TEXT/WATERMARKS: Penalize heavily (score -5) if tags or URL suggest visible text, watermarks, logos, or commercial branding (unless it's a news screenshot).\n"
        f"4. ANALOGY RULE: If the scene is an analogy (e.g. 'violinist', 'body cells'), allow the subject even if 'no people' is active, but prioritize ARTISTIC, SILHOUETTE, or NON-MODERN shots over generic smiling stock people.\n\n"
        f"Return ONLY valid JSON:\n"
        f"{'{'} \"scores\": [ {{\"url\": \"...\", \"score\": 7, \"reason\": \"краткое пояснение\"}} ], "
        f"\"best_url\": \"...\", \"best_score\": 7 {'}'}"
    )

    try:
        result = await achat_json(user_prompt=prompt)
        scores = result.get("scores", [])
        best_url = result.get("best_url", "")
        best_score = result.get("best_score", 0)

        if not best_url and scores:
            best = max(scores, key=lambda x: x.get("score", 0))
            best_url = best.get("url", "")
            best_score = best.get("score", 0)

        logger.info(f"Image scoring: {len(scores)} evaluated, best={best_score}/10")
        return {
            "best_url": best_url,
            "best_score": best_score,
            "scores": scores
        }
    except Exception as e:
        logger.error(f"Image scoring error: {e}", exc_info=True)
        return {"best_url": None, "best_score": 0, "scores": []}
