import logging
import json
from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.states import ProjectStates

logger = logging.getLogger(__name__)

def load_presets():
    with open("config/audio_presets.json", "r", encoding="utf-8") as f:
        return json.load(f)

async def ask_for_asset(message: types.Message, state: FSMContext, scene_idx: int = 0):
    """Переход к сбору материалов (v9.6 Project-Aware)."""
    try:
        data = await state.get_data()
        scenes = data.get('scenes', [])
        
        if scene_idx >= len(scenes):
            # Все ассеты собраны, идем к озвучке
            await ask_for_tts_engine(message, state)
            return

        scene = scenes[scene_idx]
        await state.update_data(current_scene_idx=scene_idx)
        
        text = scene.get('visual_description', scene.get('text_segment', '...'))
        est_dur = scene.get('estimated_duration', '...')
        
        kb = InlineKeyboardBuilder()
        kb.button(text="🤖 Сгенерировать ИИ", callback_data="asset_ai")
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
    except Exception as e:
        logger.error(f"Error in ask_for_asset: {e}", exc_info=True)

async def ask_for_tts_engine(message: types.Message, state: FSMContext):
    """ШАГ 1: Выбор метода озвучки."""
    try:
        presets = load_presets()
        kb = InlineKeyboardBuilder()
        for engine_id, engine_data in presets['tts_engines'].items():
            kb.button(text=engine_data['name'], callback_data=f"ttsengine_{engine_id}")
        kb.adjust(1)
        await message.answer(
            "🎉 **Все материалы собраны!**\n\nКаким способом будем озвучивать?", 
            reply_markup=kb.as_markup()
        )
        await state.set_state(ProjectStates.choosing_tts_engine)
    except Exception as e:
        logger.error(f"Error in ask_for_tts_engine: {e}")

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
        await message.edit_text(
            f"🎯 **{engine_data['name']}**\nВыберите голос и стиль:", 
            reply_markup=kb.as_markup()
        )
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
        
        if message.text: # Если пришло сообщение
            await message.answer(msg, reply_markup=kb.as_markup())
        else: # Если callback
            await message.edit_text(msg, reply_markup=kb.as_markup())
            
        await state.set_state(ProjectStates.choosing_metadata_style)
    except Exception as e:
        logger.error(f"Error in ask_for_metadata_style: {e}")
