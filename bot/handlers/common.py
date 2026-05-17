import json
import time
import logging
import os
from datetime import datetime
from aiogram import Router, types, F
from aiogram.filters import Command
import asyncio
import shutil
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.states import ProjectStates
from core.project_manager import ProjectManager
from core.config_loader import get_config

logger = logging.getLogger(__name__)
router = Router()
pm = ProjectManager()

@router.message(Command("clean"))
async def cmd_clean(message: types.Message):
    """Принудительная очистка старого мусора. Оставляет только видео."""
    status_msg = await message.answer("🧹 Сканирую базу и очищаю чат от промежуточных сообщений...")
    
    # 1. Собираем ID всех важных видеосообщений из глобального реестра
    protected_msg_ids = pm.get_protected_messages()
                
    # Добавляем ID сообщения-статуса и самой команды, чтобы их тоже потом грохнуть
    protected_msg_ids.add(status_msg.message_id)
    
    current_msg_id = message.message_id
    start_id = max(0, current_msg_id - 1500) # Проверяем последние 1500 сообщений
    
    deleted_count = 0
    # Пытаемся удалить саму команду /clean
    try: await message.delete()
    except Exception: pass
    
    # Идем от старых к новым
    for msg_id in range(current_msg_id, start_id - 1, -1):
        if msg_id in protected_msg_ids:
            continue
            
        try:
            await message.bot.delete_message(chat_id=message.chat.id, message_id=msg_id)
            deleted_count += 1
            await asyncio.sleep(0.02) # Уменьшенная пауза для ускорения
            
            # Обновляем статус каждые 20 удаленных сообщений
            if deleted_count % 20 == 0:
                try: await status_msg.edit_text(f"🧹 Сканирую базу и очищаю чат...\nУдалено: {deleted_count}")
                except Exception: pass
        except Exception:
            pass
            
    # Удаляем сообщение статуса
    try:
        await status_msg.delete()
    except Exception:
        pass
        
    # Отправляем уведомление об успехе (оставляем его, чтобы юзер видел результат)
    await message.answer(f"✨ Чат очищен! Удалено старых сообщений: {deleted_count}.")

@router.message(Command("clear_projects"))
async def cmd_clear_projects(message: types.Message):
    """Принудительная очистка всех проектов с диска."""
    projects_dir = "projects"
    if not os.path.exists(projects_dir):
        await message.answer("📁 Папка проектов пуста.")
        return
        
    count = 0
    status_msg = await message.answer("🗑 Удаляю все проекты с диска...")
    
    for p_dir in os.listdir(projects_dir):
        p_path = os.path.join(projects_dir, p_dir)
        if os.path.isdir(p_path):
            try:
                shutil.rmtree(p_path)
                count += 1
            except Exception as e:
                logger.error(f"Failed to delete {p_path}: {e}")
                
    await status_msg.edit_text(f"✅ База полностью очищена!\nУдалено папок с проектами: **{count}**", parse_mode="Markdown")

@router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    user_id = str(message.from_user.id)
    
    # Ищем последний незавершенный проект пользователя
    last_proj = None
    if os.path.exists("projects"):
        all_projs = []
        for p_dir in os.listdir("projects"):
            proj = pm.load_project(p_dir)
            if proj and str(proj.get('user_id')) == user_id:
                all_projs.append(proj)
        
        if all_projs:
            all_projs.sort(key=lambda x: x.get('updated_at', x.get('created_at', '')), reverse=True)
            # Если проект не завершен и НЕ в процессе рендеринга
            latest = all_projs[0]
            if latest.get('status') not in ["completed", "rendering"]:
                last_proj = latest

    if last_proj:
        kb = InlineKeyboardBuilder()
        kb.button(text="✅ Продолжить старый", callback_data=f"resume_{last_proj['project_id']}")
        kb.button(text="🆕 Создать новый", callback_data="start_new")
        kb.adjust(1)
        
        await message.answer(
            f"👋 **С возвращением!**\n\nУ вас есть незавершенный проект: `{last_proj['project_id']}`\n"
            f"Статус: `{last_proj.get('status', 'в процессе')}`\n\n"
            f"Что будем делать?",
            reply_markup=kb.as_markup()
        )
        return

    await start_new_project(message, state)

@router.callback_query(F.data == "start_new")
async def handle_start_new(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await start_new_project(callback.message, state)

@router.callback_query(F.data.startswith("resume_"))
async def handle_resume_project(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    project_id = callback.data.replace("resume_", "")
    proj = pm.load_project(project_id)
    
    if not proj:
        await callback.message.answer("❌ Проект не найден. Начнем новый.")
        await start_new_project(callback.message, state)
        return
        
    await state.update_data(
        project_id=project_id,
        user_id=str(callback.from_user.id),
        language=proj.get('language', 'Russian'),
        video_format=proj.get('video_format', 'vertical')
    )
    
    # Навигация в зависимости от статуса проекта
    status = proj.get('status')
    from bot.navigation import ask_for_asset, ask_for_tts_engine
    
    if status == "created":
        if proj.get('script') and not proj.get('scenes'):
            await state.update_data(script_data={"script": proj.get('script', '')})
            presets = get_config("script_presets", ttl=0)
            pacing = presets.get("scene_pacing", {})
            kb = InlineKeyboardBuilder()
            for pid, pdata in pacing.items():
                kb.button(text=pdata["name"], callback_data=f"pace_{pid}")
            kb.button(text="💡 Свои идеи для сцен", callback_data="stmode_ideas")
            kb.adjust(1)
            await callback.message.answer(
                "🔄 Восстанавливаю: создание раскадровки...\n\nВыберите темп сцен:",
                reply_markup=kb.as_markup()
            )
            await state.set_state(ProjectStates.choosing_scene_pacing)
        else:
            await callback.message.answer("🔄 Восстанавливаю: выбор параметров...")
            await start_new_project(callback.message, state)
    elif status == "script_ready" or not proj.get('scenes'):
        await state.update_data(script_data={"script": proj.get('script', '')})
        presets = get_config("script_presets", ttl=0)
        pacing = presets.get("scene_pacing", {})
        kb = InlineKeyboardBuilder()
        for pid, pdata in pacing.items():
            kb.button(text=pdata["name"], callback_data=f"pace_{pid}")
        kb.button(text="💡 Свои идеи для сцен", callback_data="stmode_ideas")
        kb.adjust(1)
        await callback.message.answer(
            "🔄 Восстанавливаю: создание раскадровки...\n\nВыберите темп сцен:",
            reply_markup=kb.as_markup()
        )
        await state.set_state(ProjectStates.choosing_scene_pacing)
    elif status == "collecting_assets":
        # Ищем первую сцену без ассета
        scenes = proj.get('scenes', [])
        assets = proj.get('assets', {})
        next_idx = 0
        for i in range(len(scenes)):
            if str(i) not in assets:
                next_idx = i
                break
        else:
            next_idx = len(scenes) # Все собраны
            
        await callback.message.answer(f"🔄 Восстанавливаю: сбор материалов (сцена {next_idx + 1})...")
        await ask_for_asset(callback.message, state, next_idx)
    else:
        await callback.message.answer("🔄 Восстанавливаю: переход к озвучке...")
        await ask_for_tts_engine(callback.message, state)

async def start_new_project(message: types.Message, state: FSMContext):
    await state.clear()
    
    # ФИКС: Человекочитаемый формат названия проекта
    dt_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    project_id = f"proj_{dt_str}"
    user_id = str(message.chat.id)
    
    pm.create_project(project_id, user_id)
    await state.update_data(project_id=project_id, user_id=user_id)
    
    kb = InlineKeyboardBuilder()
    kb.button(text="🇷🇺 Русский", callback_data="lang_Russian")
    kb.button(text="🇺🇸 English", callback_data="lang_English")
    kb.button(text="🇷🇴 Română", callback_data="lang_Romanian")
    kb.button(text="🇬🇪 ქართული", callback_data="lang_Georgian")
    kb.adjust(2)
    
    await state.update_data(flow_start_msg_id=message.message_id)
    await message.answer("👋 **Контент-Завод v10.0 (Persistence Edition)**\n\nВыберите язык ролика:", reply_markup=kb.as_markup())
    await state.set_state(ProjectStates.choosing_language)

@router.callback_query(F.data.startswith("lang_"), ProjectStates.choosing_language)
async def choose_lang(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    lang = callback.data.split("_", 1)[1]
    data = await state.get_data()
    proj = pm.load_project(data['project_id'])
    proj['language'] = lang
    pm.save_project(data['project_id'], proj)

    if data.get('audio_first'):
        await callback.message.edit_text(
            "✅ **Язык выбран!**\n\n📝 Пришлите текст или сценарий для озвучки:"
        )
        await state.set_state(ProjectStates.providing_script_for_audio)
        return

    profiles = get_config("channel_context", ttl=0).get("profiles", [])
    kb = InlineKeyboardBuilder()
    for p in profiles:
        kb.button(text=p.get("name", p["id"]), callback_data=f"chanprof_{p['id']}")
    kb.adjust(1)
    await callback.message.edit_text(
        "📺 **Выберите профиль канала**\n\n"
        "Это определит стиль контента, манеру повествования и подачу:",
        reply_markup=kb.as_markup()
    )
    await state.set_state(ProjectStates.choosing_channel_profile)


@router.callback_query(F.data.startswith("chanprof_"), ProjectStates.choosing_channel_profile)
async def choose_channel_profile(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    profile_id = callback.data.split("chanprof_")[1]
    data = await state.get_data()
    proj = pm.load_project(data['project_id'])
    proj['channel_profile'] = profile_id
    pm.save_project(data['project_id'], proj)

    kb = InlineKeyboardBuilder()
    kb.button(text="📱 Вертикальное (9:16)", callback_data="format_vertical")
    kb.button(text="📺 Широкое (16:9)", callback_data="format_wide")
    await callback.message.edit_text("📐 Выберите формат видео:", reply_markup=kb.as_markup())
    await state.set_state(ProjectStates.choosing_format)

@router.callback_query(F.data.startswith("format_"), ProjectStates.choosing_format)
async def choose_format(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    fmt = callback.data.split("_", 1)[1]
    data = await state.get_data()
    proj = pm.load_project(data['project_id'])
    proj['video_format'] = fmt
    pm.save_project(data['project_id'], proj)

    if data.get('audio_first'):
        presets = get_config("script_presets", ttl=0)
        pacing = presets.get("scene_pacing", {})
        kb = InlineKeyboardBuilder()
        for pid, pdata in pacing.items():
            kb.button(text=pdata["name"], callback_data=f"pace_{pid}")
        kb.button(text="💡 Свои идеи для сцен", callback_data="stmode_ideas")
        kb.adjust(1)
        await callback.message.edit_text(
            "📐 **Формат выбран!**\n\n"
            "Теперь подготовим раскадровку.\nВыберите темп сцен:",
            reply_markup=kb.as_markup()
        )
        await state.set_state(ProjectStates.choosing_scene_pacing)
        return
    
    presets = get_config("script_presets", ttl=0)
    kb = InlineKeyboardBuilder()
    for mode in presets['modes']:
        kb.button(text=mode['name'], callback_data=f"scrmode_{mode['id']}")
    kb.adjust(1)
    await callback.message.edit_text("🧠 Как будем готовить сценарий?", reply_markup=kb.as_markup())
    await state.set_state(ProjectStates.choosing_script_mode)

@router.callback_query(F.data.startswith("scrmode_"), ProjectStates.choosing_script_mode)
async def choose_script_mode(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    mode = callback.data.split("_", 1)[1]
    await state.update_data(script_mode=mode)
    
    if mode == "manual":
        await callback.message.edit_text("✍️ Пришлите ваш готовый текст для видео:")
        await state.set_state(ProjectStates.writing_manual_script)
    else:
        presets = get_config("script_presets", ttl=0)
        kb = InlineKeyboardBuilder()
        for s in presets['styles']:
            kb.button(text=s['name'], callback_data=f"scrstyle_{s['id']}")
        kb.adjust(2)
        await callback.message.edit_text("🎭 Выберите стиль повествования:", reply_markup=kb.as_markup())
        await state.set_state(ProjectStates.choosing_script_style)

@router.callback_query(F.data.startswith("scrstyle_"), ProjectStates.choosing_script_style)
async def choose_script_style(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    style_id = callback.data.split("_", 1)[1]
    await state.update_data(script_style=style_id)
    
    data = await state.get_data()
    if data['script_mode'] == "hybrid":
        await callback.message.edit_text("🤝 Пришлите основные тезисы:")
    else:
        await callback.message.edit_text("🤖 На какую тему написать сценарий?")
    await state.set_state(ProjectStates.writing_topic)


@router.message(Command("render_audio"))
async def cmd_render_audio(message: types.Message, state: FSMContext):
    await state.clear()
    dt_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    project_id = f"proj_{dt_str}"
    user_id = str(message.chat.id)
    pm.create_project(project_id, user_id)
    await state.update_data(project_id=project_id, user_id=user_id, audio_first=True)

    kb = InlineKeyboardBuilder()
    kb.button(text="🇷🇺 Русский", callback_data="lang_Russian")
    kb.button(text="🇺🇸 English", callback_data="lang_English")
    kb.button(text="🇷🇴 Română", callback_data="lang_Romanian")
    kb.button(text="🇬🇪 ქართული", callback_data="lang_Georgian")
    kb.adjust(2)
    await message.answer(
        "🎙 **Озвучить текст и продолжить монтаж**\n\n"
        "Сначала выберите язык, затем пришлёте текст для озвучки.\n\n"
        "🌍 **Выберите язык:**",
        reply_markup=kb.as_markup()
    )
    await state.set_state(ProjectStates.choosing_language)


@router.message(ProjectStates.providing_script_for_audio, F.text)
async def handle_script_for_audio(message: types.Message, state: FSMContext):
    data = await state.get_data()
    project_id = data.get('project_id')
    proj = pm.load_project(project_id)
    proj['script'] = message.text
    pm.save_project(project_id, proj)
    from bot.navigation import ask_for_tts_engine
    await ask_for_tts_engine(message, state)


# ── /full_automat ──────────────────────────────────────────────────

@router.message(Command("full_automat"))
async def cmd_full_automat(message: types.Message, state: FSMContext):
    await state.clear()
    topics = get_config("channel_topics", ttl=0).get("channels", {})
    if not topics:
        await message.answer("❌ Нет настроенных каналов.")
        return
    kb = InlineKeyboardBuilder()
    names = {"orthodox": "☦️ Православный", "tech_business": "💻 IT и Бизнес"}
    for name in topics:
        kb.button(text=names.get(name, name), callback_data=f"faut_{name}")
    kb.button(text="🔄 Перерендерить последнее видео", callback_data="rebuild_last_video")
    kb.adjust(1)
    await message.answer("🎯 **Выберите канал для автоматического ролика:**", reply_markup=kb.as_markup())
    await state.set_state(ProjectStates.choosing_channel_profile)


@router.callback_query(F.data.startswith("faut_"), ProjectStates.choosing_channel_profile)
async def faut_choose_channel(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    channel = callback.data.split("faut_", 1)[1]
    await state.update_data(auto_channel=channel)
    await callback.message.edit_text(
        f"📝 **Канал: {channel}**\n\n"
        f"Отправьте текст сценария для полного автомата:"
    )
    await state.set_state(ProjectStates.writing_topic)


@router.message(ProjectStates.writing_topic, F.text)
async def faut_handle_script(message: types.Message, state: FSMContext):
    data = await state.get_data()
    channel = data.get("auto_channel")
    if not channel:
        await message.answer("❌ Канал не выбран. Начните с /full_automat")
        await state.clear()
        return
    await state.clear()
    from bot.handlers.auto_pipeline import run_auto_pipeline
    await run_auto_pipeline(message, channel, source_msg_id=message.message_id)


# ── /auto — команда в топике группы ──────────────────────────────

@router.message(Command("auto"), F.chat.type.in_({"group", "supergroup"}), F.message_thread_id)
async def cmd_auto(message: types.Message):
    if message.from_user and message.from_user.is_bot:
        return
    try:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            await message.answer("❌ Использование:\n`/auto текст сценария`")
            return
        script_text = parts[1].strip()
        topics = get_config("channel_topics", ttl=0).get("channels", {})
        channel_name = None
        for name, cfg in topics.items():
            if cfg.get("input_topic") == message.message_thread_id:
                channel_name = name
                break
        if not channel_name:
            return

        # Если на сообщении уже есть реакция — другой бот обрабатывает или готово → пропустить
        if getattr(message, 'reactions', None):
            return

        # Ставим 👍 — «взято в работу»
        try:
            await message.react([types.ReactionTypeEmoji(emoji="👍")])
        except Exception:
            pass

        from bot.handlers.auto_pipeline import run_auto_pipeline
        await run_auto_pipeline(message, channel_name, source_msg_id=message.message_id, script_text=script_text)
    except Exception as e:
        logger.error(f"cmd_auto error: {e}", exc_info=True)
        try:
            await message.answer(f"❌ Ошибка: {e}")
        except Exception:
            pass


# ── Continue asset (DM auto-select failure) ────────────────────────

@router.callback_query(F.data.startswith("continue_asset:"))
async def continue_asset_handler(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    from bot.navigation import ask_for_asset, ask_for_tts_engine
    project_id = callback.data.split(":", 1)[1]
    proj = pm.load_project(project_id)
    if not proj:
        await callback.message.answer("❌ Проект не найден.")
        return
    await state.update_data(
        project_id=project_id,
        user_id=str(callback.from_user.id),
        language=proj.get('language', 'Russian'),
        video_format=proj.get('video_format', 'vertical'),
    )
    scenes = proj.get('scenes', [])
    assets = proj.get('assets', {})
    next_idx = 0
    for i in range(len(scenes)):
        if str(i) not in assets:
            next_idx = i
            break
    else:
        next_idx = len(scenes)
    if next_idx >= len(scenes):
        await callback.message.answer("✅ Все сцены уже собраны. Переходим к озвучке.")
        try:
            await ask_for_tts_engine(callback.message, state)
        except Exception as e:
            logger.error(f"continue_asset tts failed: {e}", exc_info=True)
            await callback.message.answer(f"❌ Ошибка перехода к озвучке: {e}")
        return
    try:
        scene = scenes[next_idx]
        desc = scene.get('visual_description', scene.get('text_segment', '...'))
        await callback.message.answer(
            f"🔄 **Продолжаем сбор** проекта `{project_id}`\n"
            f"Сцена {next_idx + 1}/{len(scenes)}: _{desc}_"
        )
        await ask_for_asset(callback.message, state, next_idx)
    except Exception as e:
        logger.error(f"continue_asset ask_for_asset failed: {e}", exc_info=True)
        await callback.message.answer(f"❌ Ошибка при показе меню: {e}")
