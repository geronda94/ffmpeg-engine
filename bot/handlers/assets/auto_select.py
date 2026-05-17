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


async def _safe_edit(msg, text: str):
    """Обёртка edit_text, не роняет pipeline при сетевых ошибках."""
    try:
        await msg.edit_text(text)
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
        for q in queries:
            ql = q.lower()
            has_forbidden = any(fw in ql for fw in FORBIDDEN_IN_QUERIES)
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
                # RU
                r'икон\w*', 'святой', 'святая', 'святитель', 'иисус', 'христос', 'апостол', 
                'богородица', 'мария', 'преподобный', 'мученик', 'мученица', 'ангел', 'архангел',
                'икона', 'матрона', 'ксения', 'сергий', 'серафим', 'николай', 'пантелеимон', 'лука',
                'спаситель', 'троица', 'господь',
                # EN
                'saint', 'icon', 'jesus', 'christ', 'mary', 'virgin', 'apostle', 'savior', 'saviour',
                'lord', 'angel', 'archangel', 'theotokos', 'orthodox icon', 'crucifixion', 'resurrection'
            ]
            pattern = r'\b(' + '|'.join(saint_keywords) + r')\b'
            
            is_saint_strong = bool(re.search(pattern, text_to_check))
            if is_saint_strong:
                search_source = "icon"
                logger.info(f"Saint/icon scene {scene_idx}: forced routing to DDG (icon)")

    # Orthodox: first 2 scenes always from web search (real icons/churches/monasteries)
    if channel_profile_id == "orthodox" and scene_idx <= 1:
        search_source = "icon"
        logger.info(f"Orthodox scene {scene_idx}: forced DDG (first 2 scenes rule)")

    logger.info(f"Auto-select scene {scene_idx}: queries={queries}, source={search_source}")

    results = []
    if search_source in ("icon", "news", "web"):
        from ai.duckduckgo_search import search_images_ddg
        await _safe_edit(status_msg,
            f"🤖 **Авто-подбор сцены {scene_idx + 1}/{total}**\n"
            f"🔍 Web поиск ({search_source}): {queries[0]}..."
        )
        try:
            ddg_q = f"orthodox icon {queries[0]}" if search_source == "icon" else queries[0]
            results = await asyncio.to_thread(search_images_ddg, ddg_q, max_results=15)
        except Exception as ex:
            logger.error(f"DDG search error: {ex}")
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

    best_local = None
    best_score_overall = 0

    if results:
        scored = await score_images(results[:20], spoken, visual, rules, search_source=search_source)
        if scored and scored.get("scores"):
            sorted_scores = sorted(scored["scores"], key=lambda x: x.get("score", 0), reverse=True)
            for img_score in sorted_scores[:5]:
                url = img_score.get("url", "")
                if not url:
                    continue
                local_path = await _download_best(url)
                if local_path:
                    img_score_val = img_score.get("score", 0)
                    label = "✅" if img_score_val >= SCORE_THRESHOLD else "⚠️"
                    pm.update_asset(project_id, scene_idx, local_path)
                    await _safe_edit(status_msg,
                        f"🤖 **Сцена {scene_idx + 1}/{total}** — {label} подобрана "
                        f"(score {img_score_val}/10)"
                    )
                    best_local = local_path
                    best_score_overall = img_score_val
                    break

    if not best_local and search_source not in ("icon", "news", "web"):
        for src_type, src_label in AUTO_FALLBACK_CHAIN:
            await _safe_edit(status_msg,
                f"🤖 **Сцена {scene_idx + 1}/{total}** — пробую {src_label}..."
            )
            try:
                fallback = await asyncio.wait_for(
                    image_search_agent.search_images(queries, color=None, source_type=src_type),
                    timeout=25
                )
                if fallback:
                    scored = await score_images(fallback[:15], spoken, visual, rules)
                    if scored and scored.get("scores"):
                        sorted_scores = sorted(scored["scores"], key=lambda x: x.get("score", 0), reverse=True)
                        for img_score in sorted_scores[:5]:
                            url = img_score.get("url", "")
                            if not url:
                                continue
                            local_path = await _download_best(url)
                            if local_path:
                                fb_score = img_score.get("score", 0)
                                pm.update_asset(project_id, scene_idx, local_path)
                                await _safe_edit(status_msg,
                                    f"🤖 **Сцена {scene_idx + 1}/{total}** — ⚠️ {src_label} "
                                    f"(score {fb_score}/10)"
                                )
                                best_local = local_path
                                break
            except Exception:
                pass


    if best_local:
        return best_local

    await _safe_edit(status_msg,
        f"🤖 **Сцена {scene_idx + 1}/{total}** — ⚠️ не удалось подобрать"
    )
    return None


async def _download_best(url: str) -> str | None:
    if not url:
        logger.warning("Auto download: empty URL, skipping")
        return None
    local = f"temp/auto_{int(time.time())}.jpg"
    try:
        logger.info(f"Auto download: GET {url[:80]}...")
        async with aiohttp.ClientSession() as session:
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
        f"🤖 **Запущен авто-подбор**\n"
        f"Сцен: **{total}** | Канал: **{channel_prof}**\n"
        f"Оцениваю первую сцену..."
    )
    await register_trash(status, state)

    success = 0
    for idx in range(total):
        if str(idx) in proj_data.get("assets", {}):
            success += 1
            continue

        picked = await _auto_pick_for_scene(
            scenes[idx], idx, channel_prof, style_id, full_script, status, total, project_id
        )
        if picked:
            success += 1
            if os.path.exists(picked):
                os.remove(picked)

    await _safe_edit(status,
        f"🤖 **Авто-подбор завершён**\n"
        f"Подобрано: **{success}/{total}** сцен"
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
        from bot.navigation import ask_for_tts_engine
        await ask_for_tts_engine(callback.message, state)
    else:
        chat_type = callback.message.chat.type
        if chat_type in ("group", "supergroup"):
            kb = InlineKeyboardBuilder()
            kb.button(text="📝 Продолжить сбор", callback_data=f"continue_asset:{project_id}")
            await _safe_edit(status,
                f"⚠️ **Не все сцены собраны** ({next_missing + 1}/{len(scenes)})\n"
                f"Бот написал в ЛС — проверь."
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
