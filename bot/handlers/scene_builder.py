"""
Standalone Dynamic Scene Builder
Команда /scene — создание динамической сцены без привязки к проекту.
Поток: выбор формата → выбор пресета → сбор элементов → рендер → отправка файла.
"""
import os
import asyncio
import logging
import time

from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.states import ProjectStates
from core.config_loader import get_config
from bot.navigation import register_trash
from ai.image_search_agent import image_search_agent, optimize_query_ai

logger = logging.getLogger(__name__)
router = Router()


# ─────────────────────────────────────────────
# Вспомогательные функции
# ─────────────────────────────────────────────

def _plates_keyboard(prefix: str) -> InlineKeyboardBuilder:
    """Клавиатура выбора плашки с кнопкой 'Без плашки'."""
    config = get_config("ui_plates")
    kb = InlineKeyboardBuilder()
    kb.button(text="🚫 Без плашки", callback_data=f"{prefix}none")
    for plate in config.get("plates", []):
        kb.button(text=plate["name"], callback_data=f"{prefix}{plate['id']}")
    kb.adjust(1)
    return kb


def _plate_path_by_id(plate_id: str) -> str | None:
    """Возвращает путь к файлу плашки по ID, или None."""
    if plate_id == "none":
        return None
    config = get_config("ui_plates")
    plate = next((p for p in config.get("plates", []) if p["id"] == plate_id), None)
    return plate["path"] if plate else None


async def _cleanup_flow(bot, chat_id: int, from_msg_id: int, to_msg_id: int):
    """Удаляет сообщения потока сборки сцены."""
    try:
        start = max(from_msg_id, to_msg_id - 120)
        for msg_id in range(to_msg_id, start - 1, -1):
            try:
                await bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"Cleanup error: {e}")


# ─────────────────────────────────────────────
# /scene — точка входа
# ─────────────────────────────────────────────

@router.message(Command("scene"))
async def cmd_scene(message: types.Message, state: FSMContext):
    """Старт создания отдельной динамической сцены."""
    await state.clear()

    kb = InlineKeyboardBuilder()
    kb.button(text="📱 Вертикальное (9:16)", callback_data="sc_fmt_vertical")
    kb.button(text="📺 Широкое (16:9)",      callback_data="sc_fmt_wide")
    kb.adjust(1)

    msg = await message.answer(
        "🎬 **Конструктор динамической сцены**\n\n"
        "Соберите готовую сцену с анимацией, текстом и эффектами.\n\n"
        "📐 **Выберите формат сцены:**",
        reply_markup=kb.as_markup()
    )
    # Запоминаем стартовое сообщение для последующей очистки
    await state.update_data(
        sc_flow_start_msg_id=message.message_id,
        sc_bot_msgs=[msg.message_id]
    )
    await state.set_state(ProjectStates.standalone_choosing_format)


# ─────────────────────────────────────────────
# Шаг 1 — формат
# ─────────────────────────────────────────────

@router.callback_query(F.data.startswith("sc_fmt_"), ProjectStates.standalone_choosing_format)
async def sc_choose_format(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    fmt = callback.data.split("sc_fmt_")[1]
    await state.update_data(sc_format=fmt, sc_elements={}, sc_element_idx=0)
    await _ask_preset(callback.message, state, edit=True)


# ─────────────────────────────────────────────
# Шаг 2 — выбор пресета
# ─────────────────────────────────────────────

async def _ask_preset(message: types.Message, state: FSMContext, edit=False):
    config = get_config("dynamic_scenes")
    kb = InlineKeyboardBuilder()
    for p in config["presets"]:
        kb.button(text=p["name"], callback_data=f"sc_pre_{p['id']}")
    kb.adjust(1)

    text = (
        "🎭 **Выберите пресет динамической сцены:**\n\n"
        "Каждый пресет — готовый шаблон с анимацией."
    )
    # Устанавливаем состояние ДО отправки/редактирования, чтобы кнопки всегда работали
    await state.set_state(ProjectStates.standalone_choosing_preset)
    try:
        if edit:
            await message.edit_text(text, reply_markup=kb.as_markup())
            return
    except Exception:
        pass
    msg = await message.answer(text, reply_markup=kb.as_markup())
    data = await state.get_data()
    msgs = data.get("sc_bot_msgs", [])
    msgs.append(msg.message_id)
    await state.update_data(sc_bot_msgs=msgs)


@router.callback_query(F.data.startswith("sc_pre_"), ProjectStates.standalone_choosing_preset)
async def sc_choose_preset(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    preset_id = callback.data.split("sc_pre_")[1]

    config = get_config("dynamic_scenes")
    preset = next((p for p in config["presets"] if p["id"] == preset_id), None)
    if not preset:
        await callback.message.answer("❌ Пресет не найден.")
        return

    await state.update_data(sc_preset=preset, sc_elements={}, sc_element_idx=0)
    await _ask_next_element(callback.message, state)


# ─────────────────────────────────────────────
# Шаг 3 — сбор элементов
# ─────────────────────────────────────────────

async def _ask_next_element(message: types.Message, state: FSMContext):
    data = await state.get_data()
    preset = data["sc_preset"]
    idx = data.get("sc_element_idx", 0)
    elements_cfg = preset.get("elements", [])

    # Удаляем предыдущий вопрос бота
    last_msg_id = data.get("sc_last_msg_id")
    if last_msg_id:
        try:
            await message.bot.delete_message(chat_id=message.chat.id, message_id=last_msg_id)
        except Exception:
            pass

    if idx >= len(elements_cfg):
        await _render_standalone_scene(message, state)
        return

    el = elements_cfg[idx]

    # Элемент plate_select — показываем клавиатуру плашек
    if el["type"] == "plate_select":
        kb = _plates_keyboard("sc_plate_")
        msg = await message.answer(
            f"🎨 **Шаг {idx + 1}/{len(elements_cfg)}: {el['name']}**\n\n"
            "Выберите текстуру фоновой плашки под текст, или пропустите:",
            reply_markup=kb.as_markup()
        )
        await state.update_data(sc_last_msg_id=msg.message_id)
        await state.set_state(ProjectStates.standalone_choosing_plate)
        return

    type_map = {"media": "фото или видео", "photo": "фото (PNG)", "video": "видео", "text": "текст"}
    
    # ПРЕДЛАГАЕМ ПОИСК ДЛЯ ВСЕХ НЕ-ТЕКСТОВЫХ ЭЛЕМЕНТОВ
    if el["type"] not in ["text", "plate_select"]:
        kb = InlineKeyboardBuilder()
        kb.button(text="📁 Загрузить файл", callback_data="sc_upload_local")
        kb.button(text="🔍 Найти в сети (AI)", callback_data="sc_search_start")
        kb.adjust(1)
        
        msg = await message.answer(
            f"📥 **{preset['name']}** | Шаг {idx + 1}/{len(elements_cfg)}\n\n"
            f"Для элемента **{el['name']}** ({type_map.get(el['type'])}) выберите источник:",
            reply_markup=kb.as_markup()
        )
    else:
        msg = await message.answer(
            f"📥 **{preset['name']}** | Шаг {idx + 1}/{len(elements_cfg)}\n\n"
            f"Пришлите **{el['name']}** ({type_map.get(el['type'], 'файл')}):"
        )
        
    await state.update_data(sc_last_msg_id=msg.message_id)
    await state.set_state(ProjectStates.standalone_collecting_element)


@router.callback_query(F.data.startswith("sc_plate_"), ProjectStates.standalone_choosing_plate)
async def sc_choose_plate(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    plate_id = callback.data.split("sc_plate_")[1]
    plate_path = _plate_path_by_id(plate_id)

    data = await state.get_data()
    preset = data["sc_preset"]
    idx = data.get("sc_element_idx", 0)
    elements_cfg = preset.get("elements", [])
    el = elements_cfg[idx]

    collected = data.get("sc_elements", {})
    collected[el["id"]] = plate_path  # None если "без плашки"
    await state.update_data(sc_elements=collected, sc_element_idx=idx + 1)

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await _ask_next_element(callback.message, state)


@router.message(
    ProjectStates.standalone_collecting_element,
    F.photo | F.video | F.document | F.text | F.animation
)
async def sc_collect_element(message: types.Message, state: FSMContext):
    data = await state.get_data()
    preset = data["sc_preset"]
    idx = data.get("sc_element_idx", 0)
    elements_cfg = preset.get("elements", [])

    if idx >= len(elements_cfg):
        return

    el = elements_cfg[idx]
    val = None

    if el["type"] == "text":
        if message.text:
            val = message.text
        else:
            await message.answer("❌ Ожидается текст.")
            return
    else:
        file_id = None
        ext = ".jpg"
        if message.photo:
            file_id = message.photo[-1].file_id
        elif message.video:
            file_id = message.video.file_id
            ext = ".mp4"
        elif message.animation:
            file_id = message.animation.file_id
            ext = ".mp4"
        elif message.document:
            file_id = message.document.file_id
            ext = os.path.splitext(message.document.file_name or "")[1] or ".bin"

        if not file_id:
            await message.answer(f"❌ Ожидается {el['name']}. Пришлите файл.")
            return

        os.makedirs("temp/sc_builder", exist_ok=True)
        val = f"temp/sc_builder/{file_id}{ext}"
        try:
            file = await message.bot.get_file(file_id)
            await message.bot.download_file(file.file_path, val)
        except Exception as e:
            logger.error(f"SC download error: {e}")
            await message.answer("❌ Ошибка загрузки файла.")
            return

    try:
        await message.delete()
    except Exception:
        pass

    collected = data.get("sc_elements", {})
    collected[el["id"]] = val
    await state.update_data(sc_elements=collected, sc_element_idx=idx + 1)
    await _ask_next_element(message, state)

# ─────────────────────────────────────────────
# Умный поиск для конструктора сцен
# ─────────────────────────────────────────────

@router.callback_query(F.data == "sc_upload_local", ProjectStates.standalone_collecting_element)
async def handle_sc_upload_local(callback: types.CallbackQuery, state: FSMContext):
    """Пользователь выбрал локальную загрузку."""
    await callback.answer()
    data = await state.get_data()
    idx = data.get("sc_element_idx", 0)
    preset = data["sc_preset"]
    el = preset["elements"][idx]
    
    type_map = {"media": "фото или видео", "photo": "фото (PNG)", "video": "видео"}
    await callback.message.edit_text(
        f"📥 **{preset['name']}** | Шаг {idx + 1}\n\n"
        f"Жду ваш файл: **{el['name']}** ({type_map.get(el['type'])})"
    )

@router.callback_query(F.data == "sc_search_start", ProjectStates.standalone_collecting_element)
async def handle_sc_search_start(callback: types.CallbackQuery, state: FSMContext):
    """Запуск процесса поиска."""
    await callback.answer()
    kb = InlineKeyboardBuilder().button(text="🔙 Назад", callback_data="sc_search_back").adjust(1)
    await callback.message.edit_text(
        "🔍 **Что именно мы ищем?**\n\n"
        "Опишите словами (можно на русском), и ИИ подберет лучшие варианты со стоков:",
        reply_markup=kb.as_markup()
    )
    await state.set_state(ProjectStates.standalone_entering_query)

@router.callback_query(F.data == "sc_search_back", ProjectStates.standalone_entering_query)
async def handle_sc_search_back(callback: types.CallbackQuery, state: FSMContext):
    """Возврат из ввода запроса к выбору источника."""
    await callback.answer()
    await _ask_next_element(callback.message, state)

@router.message(ProjectStates.standalone_entering_query, F.text)
async def handle_sc_search_query(message: types.Message, state: FSMContext):
    """Обработка текстового описания для поиска через ИИ."""
    user_query = message.text
    status = await message.answer("🤖 ИИ анализирует запрос и ищет варианты...")
    
    # Регистрация мусора
    await register_trash(message, state)
    await register_trash(status, state)
    
    # Оптимизация запроса через ИИ
    queries = await optimize_query_ai(user_query)
    results = await image_search_agent.search_images(queries)
    
    await status.delete()
    
    if not results:
        msg = await message.answer("❌ Ничего не нашлось. Попробуйте описать иначе:")
        await register_trash(msg, state)
        return
        
    await state.update_data(sc_search_results=results, sc_search_idx=0)
    await state.set_state(ProjectStates.standalone_searching_web)
    
    # Создаем сообщение карусели
    msg = await message.answer("🖼 Загружаю результаты...")
    await register_trash(msg, state)
    await show_sc_search_result(msg, state)

async def show_sc_search_result(message: types.Message, state: FSMContext):
    """Отрисовка карусели поиска с защитой от битых ссылок."""
    data = await state.get_data()
    results = data.get('sc_search_results', [])
    idx = data.get('sc_search_idx', 0)
    source = data.get('sc_search_source', 'all')
    color = data.get('sc_search_color')
    
    if not results: return
    
    source_map = {"all": "🌀 Микс", "pexels": "📸 Pexels", "pixabay": "📸 Pixabay", "ai": "🤖 AI"}
    mode_text = source_map.get(source, "Источник")
    color_text = f" | 🎨 {color}" if color else ""

    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data="sc_snav_prev")
    kb.button(text="✅ Выбрать", callback_data="sc_snav_select")
    kb.button(text="Вперед ➡️", callback_data="sc_snav_next")
    kb.button(text=f"🔄 {mode_text}{color_text}", callback_data="sc_search_toggle_source")
    kb.button(text="🔙 К выбору источника", callback_data="sc_search_back_to_src")
    kb.adjust(3, 1, 1)

    attempts = 0
    max_attempts = min(5, len(results))
    
    while attempts < max_attempts:
        photo = results[idx]
        caption = (
            f"🖼 **Вариант {idx+1}/{len(results)}**\n"
            f"👤 Автор: {photo.get('photographer', 'Unknown')}\n\n"
            f"Нравится это изображение?"
        )
        
        try:
            from aiogram.types import InputMediaPhoto
            await message.edit_media(
                media=InputMediaPhoto(media=photo['url'], caption=caption),
                reply_markup=kb.as_markup()
            )
            # Успех
            await state.update_data(sc_search_idx=idx)
            return
        except Exception as e:
            err_msg = str(e).lower()
            if "failed to get http url content" in err_msg or "wrong type of the web page content" in err_msg:
                logger.warning(f"⚠️ SC: Broken URL detected, skipping: {photo['url']}")
                idx = (idx + 1) % len(results)
                attempts += 1
                continue
            
            if "message is not modified" in err_msg:
                return
                
            try:
                msg = await message.answer_photo(photo['url'], caption=caption, reply_markup=kb.as_markup())
                await register_trash(msg, state)
                await state.update_data(sc_search_idx=idx)
                return
            except:
                idx = (idx + 1) % len(results)
                attempts += 1

    await message.answer("❌ Эти варианты недоступны. Попробуйте другой запрос или загрузите файл локально.")

@router.callback_query(F.data == "sc_search_toggle_source", ProjectStates.standalone_searching_web)
async def handle_sc_search_toggle_source(callback: types.CallbackQuery, state: FSMContext):
    """Переключение источника в конструкторе сцен."""
    data = await state.get_data()
    current = data.get('sc_search_source', 'all')
    queries = data.get('sc_search_queries', [])
    color = data.get('sc_search_color')
    
    order = ["all", "pexels", "pixabay", "ai"]
    next_source = order[(order.index(current) + 1) % len(order)]
    
    await callback.answer(f"🔎 Ищу в: {next_source.upper()}...")
    
    results = await image_search_agent.search_images(queries, source_type=next_source, color=color)
    
    if not results:
        await callback.answer("❌ В этом источнике пусто.", show_alert=True)
        return
        
    await state.update_data(sc_search_results=results, sc_search_idx=0, sc_search_source=next_source)
    await show_sc_search_result(callback.message, state)

@router.callback_query(F.data.startswith("sc_snav_"), ProjectStates.standalone_searching_web)
async def handle_sc_search_nav(callback: types.CallbackQuery, state: FSMContext):
    """Навигация по карусели."""
    action = callback.data.split("_")[2]
    data = await state.get_data()
    results = data.get('sc_search_results', [])
    idx = data.get('sc_search_idx', 0)
    
    if action == "prev":
        idx = (idx - 1) % len(results)
    elif action == "next":
        idx = (idx + 1) % len(results)
    elif action == "select":
        await callback.answer("⏳ Скачиваю файл...")
        photo = results[idx]
        os.makedirs("temp/sc_builder", exist_ok=True)
        local_path = f"temp/sc_builder/search_{int(time.time())}.jpg"
        
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(photo['url']) as resp:
                    if resp.status == 200:
                        with open(local_path, "wb") as f:
                            f.write(await resp.read())
                        
                        # Сохраняем и идем к следующему элементу
                        preset = data["sc_preset"]
                        el_idx = data.get("sc_element_idx", 0)
                        el = preset["elements"][el_idx]
                        
                        collected = data.get("sc_elements", {})
                        collected[el["id"]] = local_path
                        await state.update_data(sc_elements=collected, sc_element_idx=el_idx + 1)
                        await callback.message.delete()
                        await _ask_next_element(callback.message, state)
                        return
        except Exception as e:
            logger.error(f"Failed to download search result: {e}")
            await callback.answer("❌ Ошибка при скачивании файла.", show_alert=True)
        return

    await state.update_data(sc_search_idx=idx)
    await show_sc_search_result(callback.message, state)
    await callback.answer()

@router.callback_query(F.data == "sc_search_back_to_src", ProjectStates.standalone_searching_web)
async def handle_sc_search_back_to_src(callback: types.CallbackQuery, state: FSMContext):
    """Возврат из карусели к выбору источника."""
    await callback.answer()
    await callback.message.delete()
    await _ask_next_element(callback.message, state)


# ─────────────────────────────────────────────
# Шаг 4 — рендер
# ─────────────────────────────────────────────

async def _render_standalone_scene(message: types.Message, state: FSMContext):
    data = await state.get_data()
    preset = data["sc_preset"]
    elements = data.get("sc_elements", {})
    fmt = data.get("sc_format", "vertical")
    duration = 6.0

    status = await message.answer(
        f"⚙️ **Рендерю сцену: {preset['name']}**\n"
        f"Формат: {'📱 9:16' if fmt == 'vertical' else '📺 16:9'}\n"
        "Это займёт несколько секунд..."
    )

    os.makedirs("temp/sc_output", exist_ok=True)
    output_path = f"temp/sc_output/scene_{int(time.time())}.mp4"

    from ai.dynamic_scene_agent import render_dynamic_scene
    res = await asyncio.to_thread(
        render_dynamic_scene, preset["id"], elements, duration, output_path, fmt
    )

    await status.delete()

    if res and os.path.exists(res):
        kb = InlineKeyboardBuilder()
        kb.button(text="🔄 Создать ещё", callback_data="sc_restart")
        kb.button(text="↩️ Другой пресет", callback_data="sc_change_preset")
        kb.adjust(1)

        try:
            result_msg = await message.answer_video(
                types.FSInputFile(res),
                caption=(
                    f"✅ **Сцена готова!**\n"
                    f"Пресет: {preset['name']}\n"
                    f"Формат: {'📱 9:16' if fmt == 'vertical' else '📺 16:9'}"
                ),
                reply_markup=kb.as_markup()
            )
        except Exception:
            result_msg = await message.answer_document(
                types.FSInputFile(res),
                caption=f"📦 Сцена готова\nПресет: {preset['name']}",
                reply_markup=kb.as_markup()
            )

        await state.update_data(sc_last_output=res, sc_result_msg_id=result_msg.message_id)
        await state.set_state(ProjectStates.standalone_approving)

        # ── ОЧИСТКА: сначала trash_messages, потом основной поток ──
        trash = data.get('trash_messages', [])
        for t_id in trash:
            try: await message.bot.delete_message(chat_id=message.chat.id, message_id=t_id)
            except: pass

        flow_start = data.get("sc_flow_start_msg_id", result_msg.message_id - 100)
        await _cleanup_flow(
            message.bot,
            message.chat.id,
            from_msg_id=flow_start,
            to_msg_id=result_msg.message_id - 1
        )
    else:
        kb = InlineKeyboardBuilder()
        kb.button(text="🔄 Попробовать снова", callback_data="sc_restart")
        kb.adjust(1)
        await message.answer("❌ Ошибка при рендере сцены.", reply_markup=kb.as_markup())
        # Устанавливаем состояние, чтобы кнопка «Попробовать снова» работала
        await state.set_state(ProjectStates.standalone_approving)


# ─────────────────────────────────────────────
# Шаг 5 — после рендера
# ─────────────────────────────────────────────

@router.callback_query(F.data == "sc_restart", ProjectStates.standalone_approving)
async def sc_restart(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await state.clear()

    kb = InlineKeyboardBuilder()
    kb.button(text="📱 Вертикальное (9:16)", callback_data="sc_fmt_vertical")
    kb.button(text="📺 Широкое (16:9)",      callback_data="sc_fmt_wide")
    kb.adjust(1)

    msg = await callback.message.answer(
        "🎬 **Создаём новую сцену!**\n\n📐 Выберите формат:",
        reply_markup=kb.as_markup()
    )
    await state.update_data(
        sc_flow_start_msg_id=callback.message.message_id,
        sc_bot_msgs=[msg.message_id]
    )
    await state.set_state(ProjectStates.standalone_choosing_format)


@router.callback_query(F.data == "sc_change_preset", ProjectStates.standalone_approving)
async def sc_change_preset(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await state.update_data(sc_elements={}, sc_element_idx=0)
    # _ask_preset сам устанавливает standalone_choosing_preset внутри
    await _ask_preset(callback.message, state, edit=False)
