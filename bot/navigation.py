import logging
import asyncio
from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.states import ProjectStates
from core.project_manager import ProjectManager
from core.config_loader import get_config

logger = logging.getLogger(__name__)
pm = ProjectManager()

def load_presets():
    return get_config("audio_presets")

async def register_trash(message: types.Message, state: FSMContext):
    """Регистрирует сообщение для последующего удаления."""
    if not message: return
    data = await state.get_data()
    trash = data.get('trash_messages', [])
    if message.message_id not in trash:
        trash.append(message.message_id)
        await state.update_data(trash_messages=trash)

async def _do_prefetch_and_store(state: FSMContext, scene: dict, idx: int, style_id: str):
    """
    Фоновый воркер: генерирует запросы + ищет по стокам для одной сцены,
    сохраняет результат в FSM под ключом prefetched_search[idx].
    Запускается через asyncio.create_task — не блокирует UI.
    """
    try:
        from ai.image_search_agent import prefetch_scene_search
        result = await prefetch_scene_search(scene, style_id)
        if result and result.get("results"):
            data = await state.get_data()
            prefetched = data.get("prefetched_search", {})
            prefetched[str(idx)] = result
            await state.update_data(prefetched_search=prefetched)
            logger.info(f"✅ Prefetch saved for scene {idx}: {len(result['results'])} results")
    except Exception as e:
        logger.warning(f"_do_prefetch_and_store error (scene {idx}): {e}")


def _log_task_exception(task: asyncio.Task):
    """
    done_callback для asyncio.create_task.
    Перехватывает исключение задачи, чтобы подавить спам asyncio
    «Exception in callback None()» + 'NoneType' object is not callable.
    """
    if not task.cancelled() and task.exception() is not None:
        logger.warning(f"Background task '{task.get_name()}' failed: {task.exception()}")


async def ask_for_asset(message: types.Message, state: FSMContext, scene_idx: int = 0):
    """Переход к сбору материалов (v10.0 Disk-First)."""
    try:
        data = await state.get_data()
        project_id = data.get('project_id')
        if not project_id:
            logger.error("ask_for_asset: project_id not found in FSM!")
            await message.answer("❌ Ошибка: Сессия потеряна. Начните с /start")
            return

        # Источник правды — только диск!
        proj_data = pm.load_project(project_id)
        if not proj_data:
            await message.answer("❌ Ошибка: Проект не найден на диске.")
            return
            
        scenes = proj_data.get('scenes', [])
        logger.info(f"ask_for_asset: project={project_id}, idx={scene_idx}, total={len(scenes)}")
        
        if scene_idx >= len(scenes):
            logger.info("All assets collected! Proceeding to TTS engine choice.")
            await ask_for_tts_engine(message, state)
            return

        scene = scenes[scene_idx]
        await state.update_data(current_scene_idx=scene_idx)
        
        text = scene.get('visual_description', scene.get('text_segment', '...'))
        est_dur = scene.get('estimated_duration', '...')
        
        kb = InlineKeyboardBuilder()
        kb.button(text="🤖 Сгенерировать ИИ", callback_data="asset_ai")
        kb.button(text="🌐 Искать в сети", callback_data="asset_search_web")
        kb.button(text="🎬 Динамическая сцена", callback_data="asset_dynamic")
        kb.button(text="📁 Загрузить своё", callback_data="asset_manual")
        kb.adjust(1)

        await message.answer(
            f"🎬 **Сцена {scene_idx + 1}/{len(scenes)}**\n\n"
            f"Запрос: _{text}_\n"
            f"⏱ **Длительность:** ~{est_dur} сек\n\n"
            f"Выберите способ получения визуала:", 
            reply_markup=kb.as_markup()
        )
        await state.set_state(ProjectStates.collecting_assets)

        # ── Фоновый prefetch следующих 2 сцен ──────────────────────────────
        # Запускаем сразу после показа меню — не ждём результата.
        # К моменту нажатия «Искать в сети» результаты уже будут готовы в кеше.
        style_id = proj_data.get("script_style", "")
        prefetched = (await state.get_data()).get("prefetched_search", {})
        for next_idx in [scene_idx + 1, scene_idx + 2]:
            if next_idx < len(scenes) and str(next_idx) not in prefetched:
                task = asyncio.create_task(
                    _do_prefetch_and_store(state, scenes[next_idx], next_idx, style_id),
                    name=f"prefetch_scene_{next_idx}"
                )
                task.add_done_callback(_log_task_exception)
                logger.info(f"🔄 Background prefetch started for scene {next_idx}")

    except Exception as e:
        logger.error(f"Error in ask_for_asset: {e}", exc_info=True)

async def ask_for_tts_engine(message: types.Message, state: FSMContext):
    """ШАГ 1: Выбор метода озвучки."""
    logger.info(">>> ask_for_tts_engine triggered")
    try:
        presets = load_presets()
        kb = InlineKeyboardBuilder()
        for engine_id, engine_data in presets['tts_engines'].items():
            kb.button(text=engine_data['name'], callback_data=f"ttsengine_{engine_id}")
        kb.button(text="📁 Загрузить свою озвучку", callback_data="tts_manual")
        kb.adjust(1)
        await message.answer(
            "🎉 **Все материалы собраны!**\n\nКаким способом будем озвучивать?", 
            reply_markup=kb.as_markup()
        )
        await state.set_state(ProjectStates.choosing_tts_engine)
        logger.info("TTS engine choice menu sent.")
    except Exception as e:
        logger.error(f"Error in ask_for_tts_engine: {e}", exc_info=True)
        await message.answer(f"❌ Ошибка при переходе к озвучке: {e}")

async def ask_for_tts_preset(message: types.Message, state: FSMContext, engine_id: str):
    """ШАГ 2: Выбор пресета голоса."""
    try:
        presets = load_presets()
        engine_data = presets['tts_engines'].get(engine_id)
        if not engine_data: return
        kb = InlineKeyboardBuilder()
        for p in engine_data['presets']:
            kb.button(text=p['name'], callback_data=f"ttspreset:{p['id']}")
        kb.adjust(1)
        msg = f"🎯 **{engine_data['name']}**\nВыберите голос и стиль:"
        if message.video or message.photo:
            await message.edit_caption(caption=msg, reply_markup=kb.as_markup())
        else:
            await message.edit_text(msg, reply_markup=kb.as_markup())
        await state.set_state(ProjectStates.choosing_tts_preset)
    except Exception as e:
        logger.error(f"Error in ask_for_tts_preset: {e}")

async def ask_for_metadata_style(message: types.Message, state: FSMContext):
    """ШАГ 3: Выбор стиля именования и метаданных."""
    try:
        kb = InlineKeyboardBuilder()
        kb.button(text="🚀 Виральный (Кликбейт)", callback_data="metastyle_viral")
        kb.button(text="🎓 Экспертный (Познавательный)", callback_data="metastyle_edu")
        kb.button(text="⚡ Емкий (Shorts/TikTok)", callback_data="metastyle_shorts")
        kb.button(text="✍️ Свой промпт...", callback_data="metastyle_custom")
        kb.adjust(1)
        
        msg = (
            "📝 **Настройка метаданных**\n\n"
            "В каком ключе агент должен составить название и описание для вашего видео?"
        )
        
        if message.text: # Если пришло обычное текстовое сообщение
            await message.answer(msg, reply_markup=kb.as_markup())
        else: # Если это медиа (картинка, видео, аудио)
            if message.video or message.photo or message.audio or message.voice or message.document:
                await message.edit_caption(caption=msg, reply_markup=kb.as_markup())
            else:
                await message.edit_text(msg, reply_markup=kb.as_markup())
            
        await state.set_state(ProjectStates.choosing_metadata_style)
    except Exception as e:
        logger.error(f"Error in ask_for_metadata_style: {e}")
