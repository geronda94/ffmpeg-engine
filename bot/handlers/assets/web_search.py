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

# Источники: id → (emoji, название)
SOURCES = {
    "pexels":  ("📸", "Pexels"),
    "pixabay": ("🖼", "Pixabay"),
    "ai":      ("🤖", "AI Gen"),
    "all":     ("🌀", "Все"),
}
SOURCE_ORDER = ["all", "pexels", "pixabay", "ai"]


# ─────────────────────────────────────────────────────────────
# ВНУТРЕННИЕ ПОМОЩНИКИ
# ─────────────────────────────────────────────────────────────

def _source_keyboard(current_source: str, color: str = None) -> InlineKeyboardBuilder:
    """Строит клавиатуру с переключателями источника + навигацией."""
    kb = InlineKeyboardBuilder()

    # Ряд 1: навигация
    kb.button(text="⬅️", callback_data="web_prev")
    kb.button(text="✅ Выбрать", callback_data="web_confirm")
    kb.button(text="➡️", callback_data="web_next")

    # Ряд 2: явные кнопки источников (активный помечен ✓)
    for src_id, (emoji, name) in SOURCES.items():
        mark = " ✓" if src_id == current_source else ""
        kb.button(text=f"{emoji} {name}{mark}", callback_data=f"web_src_{src_id}")

    # Ряд 3: доп. кнопки
    color_label = f"🎨 Без цвета" if color else "🎨 Фильтр цвета"
    kb.button(text="⌨️ Уточнить запрос", callback_data="web_refine_query")
    kb.button(text=color_label, callback_data="web_toggle_color")
    kb.button(text="❌ Отмена", callback_data="web_cancel")

    kb.adjust(3, 4, 2, 1)
    return kb


async def _run_search(
    queries: list,
    color: str,
    source_type: str,
    status_msg=None,
    state: FSMContext = None
) -> list:
    """Запускает поиск, показывая прогресс через status_msg."""
    if status_msg:
        try:
            src_name = SOURCES.get(source_type, ("", source_type))[1]
            await status_msg.edit_text(f"🔍 Ищу в **{src_name}**...")
        except Exception:
            pass

    results = await asyncio.wait_for(
        image_search_agent.search_images(queries, color=color, source_type=source_type),
        timeout=30
    )
    return results


# ─────────────────────────────────────────────────────────────
# ОТОБРАЖЕНИЕ КАРУСЕЛИ
# ─────────────────────────────────────────────────────────────

async def show_web_search_result(message: types.Message, state: FSMContext, is_first: bool = False):
    """Отрисовка текущего результата. is_first=True → answer_photo, иначе edit_media."""
    data = await state.get_data()
    results = data.get("search_results", [])
    idx = data.get("search_idx", 0)
    source = data.get("search_source", "all")
    color = data.get("search_color")

    if not results:
        return

    await state.set_state(ProjectStates.searching_web_image)

    photo = results[idx]
    src_id = photo.get("source", source)
    emoji, src_name = SOURCES.get(src_id, ("📷", src_id.capitalize()))
    color_text = f" | 🎨 {color}" if color else ""
    dims = ""
    if photo.get("width") and photo.get("height"):
        dims = f" | {photo['width']}×{photo['height']}"

    caption = (
        f"🖼 **Вариант {idx + 1}/{len(results)}**\n"
        f"{emoji} {src_name}{color_text}{dims}\n"
        f"📷 {photo.get('photographer', 'Unknown')}\n\n"
        f"Нравится? Или листай дальше:"
    )

    kb = _source_keyboard(source, color)

    try:
        if is_first:
            msg = await message.answer_photo(
                photo=photo["url"], caption=caption, reply_markup=kb.as_markup()
            )
            await register_trash(msg, state)
        else:
            media = types.InputMediaPhoto(media=photo["url"], caption=caption)
            await message.edit_media(media=media, reply_markup=kb.as_markup())

        await state.update_data(search_idx=idx, _retry_count=0)

    except Exception as e:
        err_str = str(e).lower()
        if "canceled by new" in err_str or "message is not modified" in err_str:
            return

        logger.warning(f"Carousel error (idx={idx}): {e}")
        if any(k in err_str for k in ("failed to get", "wrong type", "file_reference", "url")):
            retry = data.get("_retry_count", 0)
            if retry < 6:
                new_idx = (idx + 1) % len(results)
                await state.update_data(search_idx=new_idx, _retry_count=retry + 1)
                await show_web_search_result(message, state, is_first=is_first)
            else:
                await state.update_data(_retry_count=0)
                await message.answer(
                    "⚠️ Несколько вариантов оказались недоступны. "
                    "Попробуйте другой источник или уточните запрос."
                )


# ─────────────────────────────────────────────────────────────
# ВХОД В ПОИСК (автоматический — по данным сцены)
# ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "asset_search_web", StateFilter(ProjectStates.collecting_assets))
async def handle_web_search_start(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if data.get("_searching"):
        await callback.answer("⏳ Уже идёт поиск...", show_alert=False)
        return
    await state.update_data(_searching=True)
    await callback.answer("🤖 Анализирую сцену...")

    project_id = data.get("project_id")
    scene_idx = data.get("current_scene_idx", 0)

    proj_data = pm.load_project(project_id)
    if not proj_data:
        await state.update_data(_searching=False)
        return

    scene = proj_data["scenes"][scene_idx]
    # Передаём и visual_description и text_segment для более точного запроса
    visual = scene.get("image_prompt") or scene.get("visual_description") or "nature background"
    spoken = scene.get("text_segment", "")
    style_id = proj_data.get("script_style", "")

    status = await callback.message.answer("🤖 ИИ подбирает ключевые слова...")
    await register_trash(status, state)

    try:
        queries, color = await asyncio.wait_for(
            optimize_query_ai(visual, scene_text=spoken, style_id=style_id), timeout=20
        )
        logger.info(f"Auto-search: queries={queries}, color={color}, style={style_id}")

        results = await _run_search(queries, color, "all", status_msg=status, state=state)
        await status.delete()

    except asyncio.TimeoutError:
        await status.edit_text("❌ Поиск занял слишком много времени. Попробуйте ручной ввод.")
        await state.update_data(_searching=False)
        return
    except Exception as e:
        logger.error(f"Search error: {e}", exc_info=True)
        await status.edit_text(f"❌ Ошибка при поиске: {e}")
        await state.update_data(_searching=False)
        return

    await state.update_data(_searching=False)

    if not results:
        await callback.message.answer("❌ Авто-поиск не дал результатов. Попробуйте уточнить вручную.")
        return

    await state.update_data(
        search_results=results, search_idx=0,
        search_queries=queries, search_color=color, search_source="all"
    )
    try:
        await callback.message.delete()
    except Exception:
        pass
    await show_web_search_result(callback.message, state, is_first=True)


# ─────────────────────────────────────────────────────────────
# РУЧНОЙ ВВОД ЗАПРОСА
# ─────────────────────────────────────────────────────────────

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

    data = await state.get_data()
    project_id = data.get("project_id")
    style_id = ""
    if project_id:
        proj = pm.load_project(project_id)
        if proj:
            style_id = proj.get("script_style", "")

    status = await message.answer("🤖 ИИ подбирает ключевые слова...")
    await register_trash(status, state)

    try:
        queries, color = await asyncio.wait_for(
            optimize_query_ai(user_query, style_id=style_id), timeout=20
        )
        logger.info(f"Manual search: queries={queries}, color={color}")
        results = await _run_search(queries, color, "all", status_msg=status, state=state)
        await status.delete()
    except asyncio.TimeoutError:
        await status.edit_text("❌ Поиск занял слишком много времени. Попробуйте другой запрос.")
        return
    except Exception as e:
        logger.error(f"Manual search error: {e}", exc_info=True)
        await status.edit_text(f"❌ Ошибка: {e}")
        return

    if not results:
        msg = await message.answer("❌ Ничего не нашлось. Попробуйте описать иначе:")
        await register_trash(msg, state)
        return

    current_source = data.get("search_source", "all")
    await state.update_data(
        search_results=results, search_idx=0,
        search_queries=queries, search_color=color, search_source=current_source
    )
    await show_web_search_result(message, state, is_first=True)


# ─────────────────────────────────────────────────────────────
# НАВИГАЦИЯ: СЛЕДУЮЩИЙ / ПРЕДЫДУЩИЙ
# ─────────────────────────────────────────────────────────────

async def _is_fast_click(state: FSMContext) -> bool:
    data = await state.get_data()
    last = data.get("_last_web_click", 0)
    now = time.time()
    if now - last < 0.4:
        return True
    await state.update_data(_last_web_click=now)
    return False


@router.callback_query(F.data == "web_next", ProjectStates.searching_web_image)
async def handle_web_next(callback: types.CallbackQuery, state: FSMContext):
    if await _is_fast_click(state):
        await callback.answer()
        return
    await callback.answer()
    data = await state.get_data()
    results = data.get("search_results", [])
    idx = data.get("search_idx", 0)
    await state.update_data(search_idx=(idx + 1) % len(results))
    await show_web_search_result(callback.message, state)


@router.callback_query(F.data == "web_prev", ProjectStates.searching_web_image)
async def handle_web_prev(callback: types.CallbackQuery, state: FSMContext):
    if await _is_fast_click(state):
        await callback.answer()
        return
    await callback.answer()
    data = await state.get_data()
    results = data.get("search_results", [])
    idx = data.get("search_idx", 0)
    await state.update_data(search_idx=(idx - 1) % len(results))
    await show_web_search_result(callback.message, state)


# ─────────────────────────────────────────────────────────────
# ПЕРЕКЛЮЧАТЕЛИ ИСТОЧНИКА (явные кнопки вместо кольца)
# ─────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("web_src_"), ProjectStates.searching_web_image)
async def handle_web_source_switch(callback: types.CallbackQuery, state: FSMContext):
    """Переключение на конкретный источник по нажатию его кнопки."""
    new_source = callback.data.replace("web_src_", "")
    if new_source not in SOURCES:
        await callback.answer("❓ Неизвестный источник")
        return

    data = await state.get_data()
    current_source = data.get("search_source", "all")
    color = data.get("search_color")

    if new_source == current_source:
        await callback.answer("Уже выбран этот источник", show_alert=False)
        return

    queries = data.get("search_queries", [])
    src_emoji, src_name = SOURCES.get(new_source, ("📸", "Источник"))

    await callback.answer(f"🔎 Ищу в {src_name}...")

    # Чтобы пользователь видел, что что-то происходит, можем обновить текст под текущим фото
    try:
        await _edit_carousel_status(callback.message, data, f"🔄 Поиск в {src_name}...")
    except:
        pass

    try:
        results = await asyncio.wait_for(
            image_search_agent.search_images(queries, color=color, source_type=new_source),
            timeout=30
        )
    except Exception as e:
        logger.error(f"Source switch error: {e}")
        await _edit_carousel_error(callback.message, data, f"❌ Ошибка поиска в {src_name}: {e}")
        return

    if not results:
        await _edit_carousel_error(callback.message, data, f"❌ В {src_name} ничего не нашлось.")
        return

    await state.update_data(search_results=results, search_idx=0, search_source=new_source)
    await show_web_search_result(callback.message, state)


async def _edit_carousel_status(message: types.Message, data: dict, status_text: str):
    """Обновляет подпись текущего фото временным статусом."""
    results = data.get("search_results", [])
    idx = data.get("search_idx", 0)
    source = data.get("search_source", "all")
    if not results: return
    
    photo = results[idx]
    caption = (
        f"🖼 **Вариант {idx + 1}/{len(results)}**\n"
        f"━━━━━━━━━━━━━━\n"
        f"{status_text}\n"
        f"━━━━━━━━━━━━━━\n"
        f"📷 {photo.get('photographer', 'Unknown')}"
    )
    kb = _source_keyboard(source, data.get("search_color"))
    await message.edit_caption(caption=caption, reply_markup=kb.as_markup())


async def _edit_carousel_error(message: types.Message, data: dict, error_text: str):
    """Показывает ошибку в подписи, сохраняя кнопки для повторной попытки."""
    results = data.get("search_results", [])
    idx = data.get("search_idx", 0)
    source = data.get("search_source", "all")
    if not results:
        await message.answer(error_text)
        return
        
    photo = results[idx]
    caption = (
        f"🖼 **Вариант {idx + 1}/{len(results)}**\n\n"
        f"{error_text}\n\n"
        f"Попробуйте другой источник или уточните запрос."
    )
    kb = _source_keyboard(source, data.get("search_color"))
    try:
        await message.edit_caption(caption=caption, reply_markup=kb.as_markup())
    except:
        await message.answer(error_text)


# ─────────────────────────────────────────────────────────────
# ПЕРЕКЛЮЧЕНИЕ ЦВЕТОВОГО ФИЛЬТРА
# ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "web_toggle_color", ProjectStates.searching_web_image)
async def handle_web_toggle_color(callback: types.CallbackQuery, state: FSMContext):
    """Включает/выключает цветовой фильтр."""
    data = await state.get_data()
    current_color = data.get("search_color")
    queries = data.get("search_queries", [])
    source = data.get("search_source", "all")

    new_color = None if current_color else data.get("search_color_original")
    action = "отключён" if not new_color else f"включён ({new_color})"
    await callback.answer(f"🎨 Цветовой фильтр {action}")

    try:
        results = await asyncio.wait_for(
            image_search_agent.search_images(queries, color=new_color, source_type=source),
            timeout=30
        )
    except Exception as e:
        await _edit_carousel_error(callback.message, data, f"❌ Ошибка при смене цвета: {e}")
        return

    if not results:
        await callback.answer("❌ С этим цветом ничего не нашлось", show_alert=True)
        return

    await state.update_data(search_results=results, search_idx=0, search_color=new_color)
    await show_web_search_result(callback.message, state)


# ─────────────────────────────────────────────────────────────
# УТОЧНЕНИЕ ЗАПРОСА ИЗ КАРУСЕЛИ
# ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "web_refine_query", ProjectStates.searching_web_image)
async def handle_web_refine_query(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    msg = await callback.message.answer("⌨️ Введите свой запрос для поиска:")
    await register_trash(msg, state)
    await state.set_state(ProjectStates.entering_query)


# ─────────────────────────────────────────────────────────────
# ОТМЕНА
# ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "web_cancel", ProjectStates.searching_web_image)
async def handle_web_cancel(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    await ask_for_asset(callback.message, state, data.get("current_scene_idx", 0))


# ─────────────────────────────────────────────────────────────
# ПОДТВЕРЖДЕНИЕ ВЫБОРА
# ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "web_confirm", ProjectStates.searching_web_image)
async def handle_web_confirm(callback: types.CallbackQuery, state: FSMContext):
    if await _is_fast_click(state):
        await callback.answer()
        return
        
    await callback.answer("⏳ Сохраняю...")
    
    # Запоминаем старую клавиатуру на случай ошибки
    old_kb = callback.message.reply_markup
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    data = await state.get_data()
    results = data.get("search_results", [])
    idx = data.get("search_idx", 0)
    photo = results[idx]
    project_id = data.get("project_id")
    scene_idx = data.get("current_scene_idx", 0)

    temp_path = f"temp/web_{int(time.time())}.jpg"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(photo["url"], timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status == 200:
                    content = await resp.read()
                    with open(temp_path, "wb") as f:
                        f.write(content)

                    # Валидация + нормализация (RGB, JPEG)
                    try:
                        from PIL import Image
                        with Image.open(temp_path) as img:
                            img.verify()
                        with Image.open(temp_path) as img:
                            rgb = img.convert("RGB")
                            rgb.save(temp_path, "JPEG", quality=95, optimize=True)
                        logger.info(f"Image saved & sanitized: {temp_path}")
                    except Exception as img_err:
                        logger.warning(f"Invalid image: {img_err}")
                        if os.path.exists(temp_path):
                            os.remove(temp_path)
                        await callback.message.edit_reply_markup(reply_markup=old_kb)
                        await callback.message.answer(
                            "⚠️ Файл повреждён или неверного формата. Выберите другой вариант."
                        )
                        return

                    pm.update_asset(project_id, scene_idx, temp_path)
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                    
                    # При успехе удаляем старое сообщение или переходим к следующему
                    try:
                        await callback.message.delete()
                    except: pass
                    await ask_for_asset(callback.message, state, scene_idx + 1)
                else:
                    await callback.message.edit_reply_markup(reply_markup=old_kb)
                    await callback.message.answer(f"❌ Ошибка скачивания (HTTP {resp.status})")
    except Exception as e:
        logger.error(f"Web confirm error: {e}")
        try:
            await callback.message.edit_reply_markup(reply_markup=old_kb)
        except: pass
        await callback.message.answer(f"❌ Ошибка: {e}")
