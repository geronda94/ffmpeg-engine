import json
import logging
import os
import asyncio
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.states import ProjectStates
from bot.pipeline_manager import generate_project_audio, render_project_video
from bot.navigation import ask_for_tts_preset, ask_for_tts_engine

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
    lang = data.get('language', 'Russian')
    if 'voices' in preset:
        preset['voice'] = preset['voices'].get(lang, preset['voices'].get('English'))
    status = await callback.message.answer(f"🎙 Генерирую озвучку...")
    audio_path = await generate_project_audio(data, preset)
    await status.delete()
    if audio_path:
        await state.update_data(current_audio_path=audio_path, tts_preset=preset)
        kb = InlineKeyboardBuilder()
        kb.button(text="✅ Одобрить", callback_data="audio_ok")
        kb.button(text="🔄 Переделать", callback_data="audio_retry")
        await callback.message.answer_audio(types.FSInputFile(audio_path), caption="🎧 Одобряем озвучку?", reply_markup=kb.as_markup())
        await state.set_state(ProjectStates.approving_audio)

@router.callback_query(F.data == "audio_ok", ProjectStates.approving_audio)
async def approve_audio(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    v_presets = load_json("config/montage_presets.json")
    kb = InlineKeyboardBuilder()
    for s in v_presets['styles']:
        kb.button(text=s['name'], callback_data=f"visstyle_{s['id']}")
    kb.adjust(1)
    await callback.message.answer("🎨 Выберите визуальный стиль монтажа:", reply_markup=kb.as_markup())
    await state.set_state(ProjectStates.choosing_visual_style)

@router.callback_query(F.data.startswith("visstyle_"), ProjectStates.choosing_visual_style)
async def start_final_render(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    style_id = callback.data.split("_")[1]
    await state.update_data(visual_style=style_id)
    data = await state.get_data()
    
    status = await callback.message.answer("🎬 **Монтаж запущен.**\nПрогресс: [░░░░░░░░░░] 0%")

    # ФИКС: Добавляем **kwargs, чтобы принимать любые сообщения от логгера
    def update_progress(percent=None, **kwargs):
        if percent is None: 
            return # Игнорируем текстовые логи (типа "Building video")
            
        loop = asyncio.get_event_loop()
        bar_count = percent // 10
        bar = "█" * bar_count + "░" * (10 - bar_count)
        text = f"🎬 **Монтаж в процессе...**\nПрогресс: [{bar}] {percent}%"
        asyncio.run_coroutine_threadsafe(status.edit_text(text), loop)

    try:
        video_path = await render_project_video(data, data['current_audio_path'], progress_callback=update_progress)
        
        if video_path and os.path.exists(video_path):
            await status.edit_text("⏳ **Монтаж завершен!**\nНачинаю отправку файла...")
            
            for attempt in range(3):
                try:
                    await callback.message.answer_video(
                        types.FSInputFile(video_path), 
                        caption="✨ **Ваш ролик готов!**", 
                        request_timeout=600 
                    )
                    break 
                except Exception as e:
                    logger.warning(f"Attempt {attempt+1} failed: {e}")
                    if attempt == 2:
                        await callback.message.answer_document(
                            types.FSInputFile(video_path), 
                            caption="✨ **Ваш ролик готов (отправлен как файл)!**",
                            request_timeout=600
                        )
                    else:
                        await asyncio.sleep(5)
        else:
            await status.edit_text("❌ Ошибка: Файл видео не был создан.")
    except Exception as e:
        logger.error(f"Production error: {e}")
        await callback.message.answer(f"❌ Произошла ошибка: {str(e)}")
    finally:
        await state.clear()

@router.callback_query(F.data == "audio_retry", ProjectStates.approving_audio)
async def retry_audio(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await ask_for_tts_engine(callback.message, state)
