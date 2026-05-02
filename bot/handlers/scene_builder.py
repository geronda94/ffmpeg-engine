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
    await state.set_state(ProjectStates.standalone_choosing_preset)


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

        # ── ОЧИСТКА: удаляем весь поток сборки до результата ──
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
    await _ask_preset(callback.message, state, edit=False)
    await state.set_state(ProjectStates.standalone_choosing_preset)
