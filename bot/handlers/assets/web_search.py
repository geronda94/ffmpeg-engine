"""Обработчики веб-поиска изображений (Pexels, Pixabay, Pollinations AI)."""
import logging
import os
import asyncio
import time
import aiohttp

from aiogram import Router, types, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.states import ProjectStates
from core.project_manager import ProjectManager
from bot.navigation import register_trash, ask_for_asset
from ai.image_search_agent import image_search_agent, optimize_query_ai

logger = logging.getLogger(__name__)
router = Router()
pm = ProjectManager()

SOURCE_MAP = {
    "all": "🌀 Смешанный",
    "pexels": "📸 Pexels",
    "pixabay": "📸 Pixabay",
    "ai": "🤖 Pollinations"
}
SOURCE_ORDER = ["all", "pexels", "pixabay", "ai"]


# ── Вход в поиск ────────────────────────────────────────────────────────────
@router.callback_query(F.data == "asset_search_web", StateFilter(ProjectStates.collecting_assets))
async def handle_web_search_start(callback: types.CallbackQuery, state: FSMContext):
    """Сразу запускаем ИИ-поиск по данным сцены."""
    # Защита от двойного нажатия
    data = await state.get_data()
    if data.get('_searching'):
        await callback.answer("⏳ Уже идёт поиск...", show_alert=False)
        return
    await state.update_data(_searching=True)
    
    logger.info(f"handle_web_search_start triggered for user {callback.from_user.id}")
    await callback.answer("🤖 Анализирую сцену...")

    project_id = data.get('project_id')
    scene_idx = data.get('current_scene_idx', 0)

    proj_data = pm.load_project(project_id)
    if not proj_data:
        await state.update_data(_searching=False)
        return

    scene = proj_data['scenes'][scene_idx]
    user_query = scene.get('image_prompt', scene.get('visual_description', 'nature background'))

    status = await callback.message.answer("🤖 ИИ подбирает ключевые слова и цвет...")
    await register_trash(status, state)

    try:
        logger.info(f"🔍 AI auto-search for: {user_query[:50]}...")
        queries, color = await asyncio.wait_for(optimize_query_ai(user_query), timeout=20)
        logger.info(f"✅ AI: queries={queries}, color={color}")
        results = await asyncio.wait_for(
            image_search_agent.search_images(queries, color=color, source_type="all"), timeout=30
        )
        await status.delete()
    except asyncio.TimeoutError:
        await status.edit_text("❌ Поиск занял слишком много времени. Попробуйте ручной ввод.")
        await state.update_data(_searching=False)
        return
    except Exception as e:
        logger.error(f"❌ Search error: {e}", exc_info=True)
        await status.edit_text(f"❌ Ошибка при поиске: {e}")
        await state.update_data(_searching=False)
        return

    await state.update_data(_searching=False)

    if not results:
        await callback.message.answer("❌ Авто-поиск не дал результатов. Попробуйте ручной ввод.")
        return

    await state.update_data(
        search_results=results, search_idx=0,
        search_queries=queries, search_color=color, search_source="all"
    )
    
    # Удаляем старое меню
    try:
        await callback.message.delete()
    except:
        pass
        
    await show_web_search_result(callback.message, state, is_first=True)


# ── Ручной ввод запроса ──────────────────────────────────────────────────────
@router.callback_query(F.data == "web_search_manual_ai", StateFilter(ProjectStates.collecting_assets))
async def handle_web_search_manual_ai(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    msg = await callback.message.answer("⌨️ Введите описание того, что нужно найти:")
    await register_trash(msg, state)
    await state.set_state(ProjectStates.entering_query)


@router.message(ProjectStates.entering_query)
async def handle_web_search_manual_query(message: types.Message, state: FSMContext):
    user_query = message.text
    await register_trash(message, state)

    status = await message.answer("🤖 ИИ подбирает ключевые слова и цвет...")
    await register_trash(status, state)

    try:
        logger.info(f"🔍 Manual search: {user_query[:50]}...")
        queries, color = await asyncio.wait_for(optimize_query_ai(user_query), timeout=20)
        logger.info(f"✅ Manual AI: queries={queries}, color={color}")
        results = await asyncio.wait_for(
            image_search_agent.search_images(queries, color=color, source_type="all"), timeout=30
        )
        await status.delete()
    except asyncio.TimeoutError:
        await status.edit_text("❌ Поиск занял слишком много времени. Попробуйте другой запрос.")
        return
    except Exception as e:
        logger.error(f"❌ Manual search error: {e}", exc_info=True)
        await status.edit_text(f"❌ Ошибка при поиске: {e}")
        return

    if not results:
        msg = await message.answer("❌ Ничего не нашлось. Попробуйте описать иначе:")
        await register_trash(msg, state)
        return

    await state.update_data(
        search_results=results, search_idx=0,
        search_queries=queries, search_color=color, search_source="all"
    )
    # При ручном вводе тоже создаем новое сообщение
    await show_web_search_result(message, state, is_first=True)


# ── Карусель результатов ─────────────────────────────────────────────────────
async def show_web_search_result(message: types.Message, state: FSMContext, is_first: bool = False):
    """Отрисовка карусели. is_first=True создает новое сообщение, иначе редактирует."""
    data = await state.get_data()
    results = data.get('search_results', [])
    idx = data.get('search_idx', 0)
    source = data.get('search_source', 'all')
    color = data.get('search_color')

    if not results: return

    mode_text = SOURCE_MAP.get(source, "Источник")
    color_text = f" | 🎨 {color}" if color else ""

    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️", callback_data="web_prev")
    kb.button(text="✅ Выбрать", callback_data="web_confirm")
    kb.button(text="➡️", callback_data="web_next")
    kb.button(text=f"🔄 {mode_text}{color_text}", callback_data="web_toggle_source")
    kb.button(text="⌨️ Уточнить запрос", callback_data="web_refine_query")
    kb.button(text="❌ Отмена", callback_data="web_cancel")
    kb.adjust(3, 1, 1, 1)

    # Устанавливаем состояние СРАЗУ, чтобы кнопки точно работали
    await state.set_state(ProjectStates.searching_web_image)

    photo = results[idx]
    caption = (
        f"🖼 **Вариант {idx + 1}/{len(results)}**\n"
        f"📷 Автор: {photo.get('photographer', 'Unknown')}\n\n"
        f"Нравится это изображение?"
    )

    try:
        if is_first:
            msg = await message.answer_photo(photo=photo['url'], caption=caption, reply_markup=kb.as_markup())
            await register_trash(msg, state)
        else:
            media = types.InputMediaPhoto(media=photo['url'], caption=caption)
            await message.edit_media(media=media, reply_markup=kb.as_markup())
        
        await state.update_data(search_idx=idx, _retry_count=0)
    except Exception as e:
        err_str = str(e).lower()
        if "canceled by new" in err_str or "message is not modified" in err_str:
            return # Игнорируем сетевые гонки
            
        logger.warning(f"⚠️ Carousel error: {e}")
        
        # Пробуем следующий только если ссылка битая
        if "failed to get" in err_str or "wrong type" in err_str or "file_reference" in err_str:
            retry_count = data.get("_retry_count", 0)
            if retry_count < 5:
                new_idx = (idx + 1) % len(results)
                await state.update_data(search_idx=new_idx, _retry_count=retry_count + 1)
                await show_web_search_result(message, state, is_first=is_first)
            else:
                await state.update_data(_retry_count=0)
                await message.answer("⚠️ Не удалось загрузить несколько вариантов. Попробуйте другой источник.")


# ── Навигация по карусели ────────────────────────────────────────────────────
async def _is_fast_click(state: FSMContext) -> bool:
    """Защита от спама кнопками."""
    import time
    data = await state.get_data()
    last_click = data.get("_last_web_click", 0)
    now = time.time()
    if now - last_click < 0.4: # 400мс
        return True
    await state.update_data(_last_web_click=now)
    return False


@router.callback_query(F.data == "web_next", ProjectStates.searching_web_image)
async def handle_web_search_next(callback: types.CallbackQuery, state: FSMContext):
    if await _is_fast_click(state):
        await callback.answer()
        return
    await callback.answer()
    data = await state.get_data()
    results = data.get('search_results', [])
    idx = data.get('search_idx', 0)
    await state.update_data(search_idx=(idx + 1) % len(results))
    await show_web_search_result(callback.message, state)


@router.callback_query(F.data == "web_prev", ProjectStates.searching_web_image)
async def handle_web_search_prev(callback: types.CallbackQuery, state: FSMContext):
    if await _is_fast_click(state):
        await callback.answer()
        return
    await callback.answer()
    data = await state.get_data()
    results = data.get('search_results', [])
    idx = data.get('search_idx', 0)
    await state.update_data(search_idx=(idx - 1) % len(results))
    await show_web_search_result(callback.message, state)


@router.callback_query(F.data == "web_toggle_source", ProjectStates.searching_web_image)
async def handle_web_toggle_source(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    current = data.get('search_source', 'all')
    queries = data.get('search_queries', [])
    color = data.get('search_color')

    next_source = SOURCE_ORDER[(SOURCE_ORDER.index(current) + 1) % len(SOURCE_ORDER)]
    await callback.answer(f"🔎 Ищу в: {next_source.upper()}...")

    results = await image_search_agent.search_images(queries, source_type=next_source, color=color)
    if not results:
        await callback.answer("❌ В этом источнике ничего не нашлось.", show_alert=True)
        return

    await state.update_data(search_results=results, search_idx=0, search_source=next_source)
    await show_web_search_result(callback.message, state)


@router.callback_query(F.data == "web_cancel", ProjectStates.searching_web_image)
async def handle_web_search_cancel(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    scene_idx = data.get('current_scene_idx', 0)
    await ask_for_asset(callback.message, state, scene_idx)


@router.callback_query(F.data == "web_refine_query", ProjectStates.searching_web_image)
async def handle_web_refine_query(callback: types.CallbackQuery, state: FSMContext):
    """Уточнение запроса вручную прямо из карусели."""
    await callback.answer()
    msg = await callback.message.answer("⌨️ Введите свой запрос для поиска:")
    await register_trash(msg, state)
    await state.set_state(ProjectStates.entering_query)


@router.callback_query(F.data == "web_confirm", ProjectStates.searching_web_image)
async def handle_web_search_confirm(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("⏳ Сохраняю...")

    data = await state.get_data()
    results = data.get('search_results', [])
    idx = data.get('search_idx', 0)
    photo = results[idx]
    project_id = data.get('project_id')
    scene_idx = data.get('current_scene_idx', 0)

    temp_path = f"temp/web_{int(time.time())}.jpg"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(photo['url']) as resp:
                if resp.status == 200:
                    with open(temp_path, "wb") as f:
                        f.write(await resp.read())
                    pm.update_asset(project_id, scene_idx, temp_path)
                    if os.path.exists(temp_path): os.remove(temp_path)
                    await ask_for_asset(callback.message, state, scene_idx + 1)
                else:
                    await callback.message.answer("❌ Ошибка при скачивании файла.")
    except Exception as e:
        logger.error(f"Web Search Confirm Error: {e}")
        await callback.message.answer(f"❌ Ошибка: {e}")
