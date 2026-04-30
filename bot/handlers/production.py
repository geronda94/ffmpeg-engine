import json
import logging
import os
import asyncio
from aiogram import Router, types, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.states import ProjectStates
from bot.pipeline_manager import generate_project_audio, pm
from bot.navigation import ask_for_tts_preset, ask_for_tts_engine
from core.task_manager import task_manager

logger = logging.getLogger(__name__)
router = Router()

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def get_preset_by_id(preset_id: str):
    presets = load_json("config/audio_presets.json")
    for engine in presets['tts_engines'].values():
        for p in engine['presets']:
            if p['id'] == preset_id:
                return p
    return None

async def send_video_result(task: dict):
    """Коллбэк, вызываемый менеджером задач после рендеринга."""
    bot: Bot = task_manager.bot
    user_id = task['user_id']
    project_id = task['project_id']
    video_path = task.get('video_path')
    
    if task['status'] == "completed" and video_path and os.path.exists(video_path):
        proj_data = pm.load_project(project_id)
        meta = proj_data.get('metadata', {})
        caption = (
            f"✅ **Ролик готов!**\n\n"
            f"✨ <b>{meta.get('title', project_id)}</b>\n"
            f"{meta.get('description', '')[:500]}...\n\n"
            f"{' '.join(meta.get('hashtags', []))}"
        )
        
        try:
            from aiogram.types import FSInputFile
            await bot.send_video(
                user_id, 
                FSInputFile(video_path), 
                caption=caption[:1024], 
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Failed to send video to user {user_id}: {e}")
            await bot.send_message(user_id, f"❌ Ролик {project_id} готов, но не удалось отправить файл. Он сохранен на сервере.")
    else:
        error_msg = task.get('error', 'Неизвестная ошибка рендеринга.')
        await bot.send_message(user_id, f"❌ Ошибка при монтаже проекта `{project_id}`:\n{error_msg}")

@router.message(Command("render"))
async def cmd_render_retry(message: types.Message, state: FSMContext):
    data = await state.get_data()
    project_id = data.get('project_id')
    
    if not project_id:
        user_id = str(message.from_user.id)
        projects = []
        if os.path.exists("projects"):
            for p_dir in os.listdir("projects"):
                proj = pm.load_project(p_dir)
                if proj and str(proj.get('user_id')) == user_id:
                    projects.append(proj)
        
        if not projects:
            await message.answer("❌ Не найдено активных проектов. Начните с /start")
            return
            
        projects.sort(key=lambda x: x.get('updated_at', ''), reverse=True)
        project_id = projects[0]['project_id']
        await state.update_data(project_id=project_id)

    await approve_audio(message, state)

@router.callback_query(F.data.startswith("ttsengine_"), ProjectStates.choosing_tts_engine)
async def handle_engine_choice(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    engine_id = callback.data.split("_")[1]
    await ask_for_tts_preset(callback.message, state, engine_id)

@router.callback_query(F.data.startswith("ttspreset:"), ProjectStates.choosing_tts_preset)
async def handle_preset_choice(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    preset_id = callback.data.split(":")[1]
    preset = get_preset_by_id(preset_id)
    if not preset: return
    
    data = await state.get_data()
    project_id = data.get('project_id')
    
    proj_data = pm.load_project(project_id)
    lang = proj_data.get('language', 'Russian')
    
    if 'voices' in preset:
        preset['voice'] = preset['voices'].get(lang, preset['voices'].get('English'))
        
    status = await callback.message.answer(f"🎙 Генерирую озвучку...")
    audio_path = await generate_project_audio(project_id, preset)
    await status.delete()
    
    if audio_path:
        await state.update_data(current_audio_path=audio_path)
        kb = InlineKeyboardBuilder()
        kb.button(text="✅ Одобрить", callback_data="audio_ok")
        kb.button(text="🔄 Переделать", callback_data="audio_retry")
        await callback.message.answer_audio(types.FSInputFile(audio_path), caption="🎧 Одобряем озвучку?", reply_markup=kb.as_markup())
        await state.set_state(ProjectStates.approving_audio)

@router.callback_query(F.data == "audio_ok", ProjectStates.approving_audio)
async def approve_audio(event: types.CallbackQuery | types.Message, state: FSMContext):
    if isinstance(event, types.CallbackQuery):
        await event.answer()
        message = event.message
        await message.edit_reply_markup(reply_markup=None)
    else:
        message = event
    
    data = await state.get_data()
    proj_data = pm.load_project(data['project_id'])
    v_format = proj_data.get('video_format', 'vertical')
    
    v_config = load_json("config/rendering_presets.json")
    styles = v_config.get(v_format, v_config['vertical'])
    
    kb = InlineKeyboardBuilder()
    for s in styles:
        kb.button(text=s['name'], callback_data=f"visstyle_{s['id']}")
    kb.adjust(1)
    await message.answer(f"🎨 Выберите стиль монтажа для {'вертикального' if v_format=='vertical' else 'широкого'} видео:", reply_markup=kb.as_markup())
    await state.set_state(ProjectStates.choosing_visual_style)

@router.callback_query(F.data.startswith("visstyle_"), ProjectStates.choosing_visual_style)
async def handle_visual_style_choice(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    style_id = callback.data.split("_")[1]
    
    data = await state.get_data()
    proj_data = pm.load_project(data['project_id'])
    proj_data['visual_style'] = style_id
    pm.save_project(data['project_id'], proj_data)
    
    from bot.navigation import ask_for_metadata_style
    await ask_for_metadata_style(callback.message, state)

@router.callback_query(F.data == "start_render")
async def start_final_render(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    project_id = data.get('project_id')
    user_id = str(callback.from_user.id)
    
    if not project_id:
        await callback.message.answer("❌ Ошибка: ID проекта потерян.")
        return

    proj_data = pm.load_project(project_id)
    audio_path = proj_data.get('current_audio_path')

    if not audio_path or not os.path.exists(audio_path):
        await callback.message.answer("❌ Ошибка: Файл озвучки не найден.")
        return

    await callback.message.edit_reply_markup(reply_markup=None)
    
    # ДОБАВЛЯЕМ В ОЧЕРЕДЬ
    proj_data['status'] = "rendering"
    pm.save_project(project_id, proj_data)
    
    await task_manager.add_task(project_id, audio_path, user_id, callback_on_done=send_video_result)
    
    q_pos = task_manager.queue.qsize()
    msg = await callback.message.answer(
        f"⏳ **Проект `{project_id}` добавлен в очередь на монтаж!**\n"
        f"Ваша позиция: {q_pos}\n\n"
        f"Вы можете начать новый проект через /start, бот пришлет готовое видео сюда, когда оно будет готово. 🚀"
    )
    
    try:
        await callback.bot.pin_chat_message(chat_id=callback.message.chat.id, message_id=msg.message_id)
    except Exception as e:
        logger.warning(f"Failed to pin message: {e}")
    
    await state.clear()

@router.callback_query(F.data == "audio_retry", ProjectStates.approving_audio)
async def retry_audio(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await ask_for_tts_engine(callback.message, state)
