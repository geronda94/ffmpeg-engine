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
from core.config_loader import get_config

logger = logging.getLogger(__name__)
router = Router()

def get_preset_by_id(preset_id: str):
    presets = get_config("audio_presets")
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
    
    logger.info(f"Callback send_video_result triggered for {project_id} (status: {task['status']})")
    
    if task['status'] == "completed" and video_path and os.path.exists(video_path):
        # Источник правды — диск
        proj_data = pm.load_project(project_id)
        if not proj_data:
            logger.error(f"Project {project_id} data not found on disk during callback!")
            return
            
        proj_data['status'] = "completed"
        proj_data['video_result_path'] = video_path
        pm.save_project(project_id, proj_data)
        
        from ai.metadata_agent import format_hashtags
        meta = proj_data.get('metadata', {})
        title = meta.get('title', 'Без названия')
        description = meta.get('description', '')
        hashtags = format_hashtags(meta.get('hashtags', []))
        
        caption = (
            f"✅ **Ролик готов!**\n\n"
            f"✨ **Заголовок (кликни, чтобы скопировать):**\n`{title}`\n\n"
            f"📝 **Описание:**\n`{description[:800]}`\n\n"
            f"🏷 **Теги:**\n`{hashtags}`"
        )
        
        try:
            logger.info(f"Sending video to user {user_id}: {video_path}")
            from aiogram.types import FSInputFile
            
            # Получаем ID сообщения для ответа
            extra = task.get('extra_data', {})
            reply_id = extra.get('reply_to_message_id')
            
            # Кнопки пост-обработки
            kb = InlineKeyboardBuilder()
            if not proj_data.get('burn_subtitles'):
                kb.button(text="🔥 Сделать версию с субтитрами", callback_data=f"subtitles:{project_id}")
            kb.button(text="🌍 Перевести", callback_data=f"translate_menu:{project_id}")
            kb.adjust(1)

            msg = await bot.send_video(
                user_id, 
                FSInputFile(video_path), 
                caption=caption[:1024], 
                parse_mode="Markdown",
                reply_to_message_id=reply_id,
                reply_markup=kb.as_markup(),
                request_timeout=900
            )
            # Отправляем JSON конфиг
            json_path = pm.get_project_path(project_id) / "project.json"
            if os.path.exists(json_path):
                doc_msg = await bot.send_document(
                    user_id,
                    FSInputFile(str(json_path)),
                    reply_to_message_id=msg.message_id,
                    caption="📄 Конфиг проекта",
                    request_timeout=900
                )
                pm.add_protected_message(doc_msg.message_id)

            # Сохраняем в глобальный реестр
            pm.add_protected_message(msg.message_id)
            pm.save_project(project_id, proj_data)
            
        except Exception as e:
            logger.error(f"Failed to send video to user {user_id}: {e}")
            await bot.send_message(user_id, f"❌ Ролик `{project_id}` готов, но не удалось отправить файл. Он сохранен на сервере.")
    else:
        error_msg = task.get('error', 'Неизвестная ошибка рендеринга.')
        logger.error(f"Render failed or file missing for {project_id}: {error_msg}")
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
        kb.adjust(2)
        msg = await callback.message.answer_audio(types.FSInputFile(audio_path), caption="🎧 Одобряем озвучку?", reply_markup=kb.as_markup())
        from bot.navigation import register_trash
        await register_trash(msg, state)
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
    
    if proj_data.get('visual_style'):
        from bot.navigation import ask_for_metadata_style
        await ask_for_metadata_style(message, state)
        return
        
    v_format = proj_data.get('video_format', 'vertical')
    
    v_config = get_config("rendering_presets")
    styles = v_config.get(v_format, v_config['vertical'])
    
    kb = InlineKeyboardBuilder()
    for s in styles:
        kb.button(text=s['name'], callback_data=f"visstyle_{s['id']}")
    kb.adjust(1)
    msg = await message.answer(f"🎨 Выберите стиль монтажа для {'вертикального' if v_format=='vertical' else 'широкого'} video:", reply_markup=kb.as_markup())
    from bot.navigation import register_trash
    await register_trash(msg, state)
    await state.set_state(ProjectStates.choosing_visual_style)

@router.callback_query(F.data.startswith("visstyle_"), ProjectStates.choosing_visual_style)
async def handle_visual_style_choice(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    style_id = callback.data.split("_", 1)[1]  # ФИКС: split("_")[1] обрезал "v_smooth_story" до "v"
    
    data = await state.get_data()
    proj_data = pm.load_project(data['project_id'])
    proj_data['visual_style'] = style_id
    pm.save_project(data['project_id'], proj_data)
    
    from bot.navigation import ask_for_metadata_style
    await ask_for_metadata_style(callback.message, state)

@router.callback_query(F.data.startswith("start_render:"))
async def start_final_render(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    subs_choice = callback.data.split(":")[1]
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
    proj_data['burn_subtitles'] = (subs_choice == "withsubs")
    pm.save_project(project_id, proj_data)
    
    lang = proj_data.get('language', 'Russian')
    title = proj_data.get('metadata', {}).get('title', 'Без названия')
    langs_flags = {
        "Russian": "🇷🇺",
        "English": "🇺🇸",
        "Romanian": "🇷🇴",
        "Georgian": "🇬🇪"
    }
    flag = langs_flags.get(lang, "🌍")
    
    q_pos = task_manager.queue.qsize()
    
    kb = InlineKeyboardBuilder()
    kb.button(text="🌍 Перевести", callback_data=f"translate_menu:{project_id}")
    kb.adjust(1)
    
    msg = await callback.message.answer(
        f"⏳ **Проект в очереди на монтаж!**\n\n"
        f"🗣 **Язык**: {flag} **{lang}**\n"
        f"📌 **Название**: **{title}**\n"
        f"🆔 ID: `{project_id}`\n"
        f"📍 Очередь: {q_pos}\n\n"
        f"Можете создавать новый проект через /start, видео придет сюда.",
        reply_markup=kb.as_markup()
    )
    
    # Очистка чата: сначала по списку trash_messages, потом по диапазону
    try:
        # 1. Удаляем явно зарегистрированный мусор
        trash = data.get('trash_messages', [])
        for t_id in trash:
            try:
                await callback.bot.delete_message(chat_id=callback.message.chat.id, message_id=t_id)
            except Exception: pass

        # 2. Дополнительная зачистка по диапазону (на всякий случай)
        current_msg_id = callback.message.message_id
        flow_start = data.get('flow_start_msg_id')
        if not flow_start: flow_start = current_msg_id
        
        start_id = max(flow_start, current_msg_id - 100)
        for msg_id in range(current_msg_id, start_id - 1, -1):
            try:
                await callback.bot.delete_message(chat_id=callback.message.chat.id, message_id=msg_id)
            except Exception: pass
    except Exception as e:
        logger.warning(f"Error clearing chat: {e}")
    
    try:
        await callback.bot.pin_chat_message(chat_id=callback.message.chat.id, message_id=msg.message_id)
    except Exception as e:
        logger.warning(f"Failed to pin message: {e}")

    await task_manager.add_task(
        project_id, audio_path, user_id, 
        callback_on_done=send_video_result,
        extra_data={"reply_to_message_id": msg.message_id}
    )
    
    await state.clear()

@router.callback_query(F.data.startswith("subtitles:"))
async def handle_add_subtitles(callback: types.CallbackQuery):
    project_id = callback.data.split(":")[1]
    logger.info(f"Button 'Add Subtitles' pressed for project: {project_id}")
    await callback.answer("⏳ Готовлю версию с субтитрами...")
    
    proj_data = pm.load_project(project_id)
    if not proj_data:
        await callback.message.answer(f"❌ Ошибка: Проект `{project_id}` не найден.")
        return

    video_path = proj_data.get('video_result_path')
    if not video_path or not os.path.exists(video_path):
        await callback.message.answer("❌ Ошибка: Исходное видео не найдено.")
        return

    status_msg = await callback.message.answer("🖋 Вшиваю субтитры (это займет около минуты)...")
    
    try:
        from ai.subtitle_agent import generate_ass_from_project, burn_subtitles
        
        # ФИКС: Если данных Whisper нет (старый проект), прогоняем его сейчас
        if 'whisper_segments' not in proj_data:
            audio_path = proj_data.get('current_audio_path')
            if audio_path and os.path.exists(audio_path):
                logger.info(f"Whisper segments missing for {project_id}, running fallback...")
                from ai.timing_agent import get_model
                model = get_model()
                whisper_res = await asyncio.to_thread(model.transcribe, audio_path, verbose=False)
                whisper_segments = whisper_res.get('segments', [])
                proj_data['whisper_segments'] = [
                    {'start': s['start'], 'end': s['end'], 'text': s['text']}
                    for s in whisper_segments
                ]
                pm.save_project(project_id, proj_data)
            else:
                await status_msg.edit_text("❌ Ошибка: данные Whisper и аудиофайл отсутствуют.")
                return

        project_path = pm.get_project_path(project_id)
        ass_path = str(project_path / "subtitles.ass")
        output_path = str(project_path / "video_with_subtitles.mp4")
        
        # 1. Генерируем ASS (пропуская динамику + анимация выезда)
        scenes_for_srt = proj_data['scenes']
        assets = proj_data.get('assets', {})
        for i, s in enumerate(scenes_for_srt):
            s['allow_montage_effects'] = assets.get(str(i), {}).get('allow_montage_effects', True)
        
        ass_res = generate_ass_from_project(scenes_for_srt, proj_data['whisper_segments'], ass_path)
        if not ass_res:
            await status_msg.edit_text("❌ Ошибка при генерации файла анимированных субтитров.")
            return
            
        # 2. Вшиваем в видео
        res_path = await asyncio.to_thread(burn_subtitles, video_path, ass_path, output_path)
        
        if res_path and os.path.exists(res_path):
            from ai.metadata_agent import format_hashtags
            meta = proj_data.get('metadata', {})
            title = meta.get('title', 'Без названия')
            description = meta.get('description', '')
            hashtags = format_hashtags(meta.get('hashtags', []))

            caption = (
                f"✨ **Версия с субтитрами готова!**\n\n"
                f"📌 **Заголовок:**\n`{title}`\n\n"
                f"📝 **Описание:**\n`{description[:800]}`\n\n"
                f"🏷 **Теги:**\n`{hashtags}`"
            )

            msg = await callback.message.answer_video(
                types.FSInputFile(res_path),
                caption=caption,
                parse_mode="Markdown",
                reply_to_message_id=callback.message.message_id
            )
            await status_msg.delete()
            
            # Отправляем JSON конфиг
            json_path = pm.get_project_path(project_id) / "project.json"
            if os.path.exists(json_path):
                doc_msg = await callback.message.answer_document(
                    types.FSInputFile(str(json_path)),
                    reply_to_message_id=msg.message_id,
                    caption="📄 Конфиг проекта"
                )
                pm.add_protected_message(doc_msg.message_id)

            # Сохраняем в глобальный реестр
            pm.add_protected_message(msg.message_id)
            pm.save_project(project_id, proj_data)
            
        else:
            await status_msg.edit_text("❌ Ошибка при вшивании субтитров через FFmpeg.")
            
    except Exception as e:
        logger.error(f"Subtitle burn error: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Критическая ошибка при работе с субтитрами: {e}")

@router.callback_query(F.data.startswith("translate_menu:"))
async def handle_translate_menu_button(callback: types.CallbackQuery, state: FSMContext):
    """Вызывает меню перевода по кнопке под видео."""
    project_id = callback.data.split(":")[1]
    logger.info(f"Button 'Translate' pressed for project: {project_id}")
    await state.update_data(project_id=project_id)
    
    from bot.handlers.localization import cmd_translate
    await cmd_translate(callback, state)

@router.callback_query(F.data == "audio_retry", ProjectStates.approving_audio)
async def retry_audio(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await ask_for_tts_engine(callback.message, state)
