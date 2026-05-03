"""Обработчики динамических сцен (пресеты, элементы, рендер, одобрение)."""
import logging
import os
import asyncio
import time

from aiogram import Router, types, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.states import ProjectStates
from core.project_manager import ProjectManager
from core.config_loader import get_config
from ai.dynamic_scene_agent import render_dynamic_scene

logger = logging.getLogger(__name__)
router = Router()
pm = ProjectManager()


@router.callback_query(F.data == "asset_dynamic", StateFilter(
    ProjectStates.collecting_assets,
    ProjectStates.approving_asset,
    ProjectStates.approving_dynamic_pre_render
))
async def handle_dynamic_asset_start(event: types.CallbackQuery | types.Message, state: FSMContext):
    if isinstance(event, types.CallbackQuery):
        await event.answer()
        message = event.message
    else:
        message = event

    config = get_config("dynamic_scenes")

    kb = InlineKeyboardBuilder()
    for p in config['presets']:
        kb.button(text=p['name'], callback_data=f"dynpre_{p['id']}")
    kb.button(text="📤 Загрузить свою сцену", callback_data="asset_upload_scene")
    kb.adjust(1)

    text = (
        "🎭 **Выберите пресет динамической сцены:**\n\n"
        "Это позволит собрать сложную сцену из нескольких элементов (лого, текст, фон).\n"
        "Или загрузите готовый видеофайл без эффектов."
    )

    if isinstance(event, types.CallbackQuery):
        try:
            if message.text:
                await message.edit_text(text, reply_markup=kb.as_markup())
            else:
                await message.edit_caption(caption=text, reply_markup=kb.as_markup())
        except Exception as e:
            logger.warning(f"Safe edit failed: {e}. Sending new message.")
            await message.answer(text, reply_markup=kb.as_markup())
            try: await message.delete()
            except: pass
    else:
        await message.answer(text, reply_markup=kb.as_markup())

    await state.set_state(ProjectStates.choosing_dynamic_preset)


@router.callback_query(F.data.startswith("dynpre_"), ProjectStates.choosing_dynamic_preset)
async def handle_dynamic_preset_choice(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    preset_id = callback.data.replace("dynpre_", "")

    config = get_config("dynamic_scenes")
    preset = next((p for p in config['presets'] if p['id'] == preset_id), None)
    if not preset: return

    await state.update_data(
        dynamic_preset=preset,
        dynamic_elements_collected={},
        current_element_idx=0
    )
    await ask_next_dynamic_element(callback.message, state)


async def ask_next_dynamic_element(message: types.Message, state: FSMContext):
    data = await state.get_data()
    preset = data['dynamic_preset']
    idx = data['current_element_idx']

    last_msg_id = data.get('last_dynamic_msg_id')
    if last_msg_id:
        try: await message.bot.delete_message(chat_id=message.chat.id, message_id=last_msg_id)
        except: pass

    if idx >= len(preset['elements']):
        await start_dynamic_pre_render(message, state)
        return

    element = preset['elements'][idx]

    if element.get("type") == "plate_select":
        from bot.handlers.scene_builder import _plates_keyboard
        kb = _plates_keyboard("dyn_plate_")
        msg_text = (
            f"🎨 **Сборка сцены: {preset['name']}**\n"
            f"Шаг {idx+1}/{len(preset['elements'])}\n\n"
            f"Выберите **{element['name']}**:"
        )
        new_msg = await message.answer(msg_text, reply_markup=kb.as_markup())
        await state.update_data(last_dynamic_msg_id=new_msg.message_id)
        await state.set_state(ProjectStates.collecting_dynamic_element)
        return

    type_map = {"media": "фото или видео", "photo": "фото (PNG)", "video": "видео", "text": "текст"}
    msg_text = (
        f"📥 **Сборка сцены: {preset['name']}**\n"
        f"Шаг {idx+1}/{len(preset['elements'])}\n\n"
        f"Пришлите **{element['name']}** ({type_map.get(element['type'], 'файл')}):"
    )
    new_msg = await message.answer(msg_text)
    await state.update_data(last_dynamic_msg_id=new_msg.message_id)
    await state.set_state(ProjectStates.collecting_dynamic_element)


@router.message(ProjectStates.collecting_dynamic_element)
async def handle_dynamic_element_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    preset = data['dynamic_preset']
    idx = data['current_element_idx']
    element = preset['elements'][idx]

    val = None
    if element['type'] == "text":
        if message.text:
            val = message.text
        else:
            await message.answer("❌ Ожидается текст.")
            return
    else:
        file_id = None
        ext = ".jpg"
        if message.photo: file_id = message.photo[-1].file_id
        elif message.video: file_id = message.video.file_id; ext = ".mp4"
        elif message.animation: file_id = message.animation.file_id; ext = ".mp4"
        elif message.document:
            file_id = message.document.file_id
            ext = os.path.splitext(message.document.file_name or "")[1] or ".bin"

        if not file_id:
            await message.answer(f"❌ Ожидается {element['name']}. Пришлите файл.")
            return

        try:
            file = await message.bot.get_file(file_id)
            os.makedirs("temp/dynamic", exist_ok=True)
            val = f"temp/dynamic/{file_id}{ext}"
            await message.bot.download_file(file.file_path, val)
        except Exception as e:
            logger.error(f"Download error: {e}")
            await message.answer("❌ Ошибка загрузки файла.")
            return

    try:
        await message.delete()
    except Exception as e:
        logger.warning(f"Failed to delete user message: {e}")

    collected = data.get('dynamic_elements_collected', {})
    collected[element['id']] = val
    await state.update_data(
        dynamic_elements_collected=collected,
        current_element_idx=idx + 1
    )
    await ask_next_dynamic_element(message, state)


@router.callback_query(F.data.startswith("dyn_plate_"), ProjectStates.collecting_dynamic_element)
async def handle_dynamic_plate_choice(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    plate_id = callback.data.replace("dyn_plate_", "")
    from bot.handlers.scene_builder import _plate_path_by_id
    plate_path = _plate_path_by_id(plate_id)

    data = await state.get_data()
    preset = data['dynamic_preset']
    idx = data['current_element_idx']
    element = preset['elements'][idx]

    collected = data.get('dynamic_elements_collected', {})
    collected[element['id']] = plate_path
    await state.update_data(
        dynamic_elements_collected=collected,
        current_element_idx=idx + 1
    )
    try: await callback.message.edit_reply_markup(reply_markup=None)
    except: pass
    await ask_next_dynamic_element(callback.message, state)


async def start_dynamic_pre_render(message: types.Message, state: FSMContext):
    data = await state.get_data()
    preset = data['dynamic_preset']
    elements = data['dynamic_elements_collected']
    project_id = data['project_id']
    scene_idx = data['current_scene_idx']

    status = await message.answer(f"⚙️ **Собираю динамическую сцену: {preset['name']}**\nЭто займет немного времени...")

    output_path = f"projects/{project_id}/assets/dynamic_{scene_idx}_{int(time.time())}.mp4"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    proj_data = pm.load_project(project_id)
    if not proj_data:
        await message.answer("❌ Проект не найден.")
        return

    scenes = proj_data.get('scenes', [])
    if scene_idx < len(scenes):
        scene = scenes[scene_idx]
        duration = float(scene.get('end', 5.0) - scene.get('start', 0.0))
        if duration <= 0: duration = float(scene.get('estimated_duration', 5.0))
    else:
        duration = 5.0

    v_format = proj_data.get('video_format', 'vertical')
    res = await asyncio.to_thread(render_dynamic_scene, preset['id'], elements, duration, output_path, v_format)

    await status.delete()
    if res:
        kb = InlineKeyboardBuilder()
        kb.button(text="✅ Одобрить", callback_data="dyn_approve")
        kb.button(text="🔄 Переделать", callback_data="asset_dynamic")
        kb.adjust(1)

        try:
            await message.answer_video(
                types.FSInputFile(output_path),
                caption=f"✨ **Динамическая сцена готова!**\nПресет: {preset['name']}\n\nОдобряем?",
                reply_markup=kb.as_markup(),
                request_timeout=300
            )
        except Exception as e:
            logger.warning(f"Failed to send video preview: {e}. Trying as document...")
            try:
                await message.answer_document(
                    types.FSInputFile(output_path),
                    caption=f"📦 **Сцена собрана (отправлена файлом)**\nПресет: {preset['name']}\n\nОдобряем?",
                    reply_markup=kb.as_markup()
                )
            except Exception as e2:
                logger.error(f"Total failure sending dynamic preview: {e2}")
                await message.answer(f"❌ Не удалось отправить превью. Файл: {os.path.basename(output_path)}")

        await state.update_data(temp_dynamic_path=output_path)
        await state.set_state(ProjectStates.approving_dynamic_pre_render)
    else:
        await message.answer("❌ Ошибка при сборке сцены. Попробуем еще раз?")
        await handle_dynamic_asset_start(message, state)


@router.callback_query(F.data == "dyn_approve", ProjectStates.approving_dynamic_pre_render)
async def handle_dynamic_approval(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    video_path = data['temp_dynamic_path']
    project_id = data['project_id']
    scene_idx = data['current_scene_idx']

    pm.update_asset(project_id, scene_idx, video_path)

    dynamic_config = get_config("dynamic_scenes")
    preset_id = data.get('dynamic_preset', {}).get('id')
    preset = next((p for p in dynamic_config['presets'] if p['id'] == preset_id), {})
    allow_effects = preset.get("allow_montage_effects", True)

    proj = pm.load_project(project_id)
    proj['assets'][str(scene_idx)]['allow_montage_effects'] = allow_effects
    pm.save_project(project_id, proj)

    for path in data['dynamic_elements_collected'].values():
        if isinstance(path, str) and os.path.exists(path) and "temp/dynamic" in path:
            os.remove(path)

    from bot.navigation import ask_for_asset
    await ask_for_asset(callback.message, state, scene_idx + 1)
