import logging
import json
from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.states import ProjectStates

logger = logging.getLogger(__name__)

def load_presets():
    # ФИКС: Переименовали в audio_presets.json
    with open("config/audio_presets.json", "r", encoding="utf-8") as f:
        return json.load(f)

async def ask_for_asset(message: types.Message, state: FSMContext):
    """Переход к сбору материалов."""
    try:
        data = await state.get_data()
        idx = data.get('current_scene_idx', 0)
        scenes = data.get('scenes', [])
        
        if idx >= len(scenes):
            await ask_for_tts_engine(message, state) # ШАГ 1: Выбор движка
            return
            
        scene = scenes[idx]
        kb = InlineKeyboardBuilder()
        kb.button(text="🤖 AI", callback_data="asset_ai")
        kb.button(text="📁 Свой материал", callback_data="asset_manual")
        
        await message.answer(
            f"📥 **Сцена {idx+1}/{len(scenes)}**\n\n"
            f"🎬 *Запрос:* {scene['visual_description']}", 
            reply_markup=kb.as_markup()
        )
        await state.set_state(ProjectStates.collecting_assets)
    except Exception as e:
        logger.error(f"Error in ask_for_asset: {e}")

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
        await message.answer(f"⚠️ Ошибка загрузки пресетов: {e}")

async def ask_for_tts_preset(message: types.Message, state: FSMContext, engine_id: str):
    """ШАГ 2: Выбор конкретного пресета для выбранного движка."""
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
