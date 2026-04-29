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
    
    data = await state.get_data()
    v_format = data.get('video_format', 'vertical')
    
    v_config = load_json("config/montage_presets.json")
    # ФИКС: Берем пресеты только для выбранного формата
    styles = v_config.get(v_format, v_config['vertical'])
    
    kb = InlineKeyboardBuilder()
    for s in styles:
        kb.button(text=s['name'], callback_data=f"visstyle_{s['id']}")
    kb.adjust(1)
    await callback.message.answer(f"🎨 Выберите стиль монтажа для {'вертикального' if v_format=='vertical' else 'широкого'} видео:", reply_markup=kb.as_markup())
    await state.set_state(ProjectStates.choosing_visual_style)

@router.callback_query(F.data.startswith("visstyle_"), ProjectStates.choosing_visual_style)
async def start_final_render(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    style_id = callback.data.split("_")[1]
    await state.update_data(visual_style=style_id)
    data = await state.get_data()
    
    status = await callback.message.answer("🎬 **Монтаж запущен.**\nПрогресс: [░░░░░░░░░░] 0%")

    main_loop = asyncio.get_running_loop()
    last_text = ""

    async def safe_edit_text(new_text):
        nonlocal last_text
        if new_text == last_text: return
        try:
            await status.bot.edit_message_text(text=new_text, chat_id=status.chat.id, message_id=status.message_id)
            last_text = new_text
        except Exception: pass

    def update_progress(percent=None, **kwargs):
        if percent is None: return
        bar_count = percent // 10
        bar = "█" * bar_count + "░" * (10 - bar_count)
        text = f"🎬 **Монтаж в процессе...**\nПрогресс: [{bar}] {percent}%"
        asyncio.run_coroutine_threadsafe(safe_edit_text(text), main_loop)

    try:
        video_path = await render_project_video(data, data['current_audio_path'], progress_callback=update_progress)
        
        if video_path and os.path.exists(video_path):
            asyncio.run_coroutine_threadsafe(safe_edit_text("⏳ **Монтаж завершен!**\nНачинаю отправку файла..."), main_loop)
            
            for attempt in range(3):
                try:
                    await callback.message.answer_video(types.FSInputFile(video_path), caption="✨ **Ваш ролик готов!**", request_timeout=600)
                    break 
                except Exception as e:
                    if attempt == 2:
                        await callback.message.answer_document(types.FSInputFile(video_path), caption="✨ **Ваш ролик готов (файл)!**", request_timeout=600)
                    else: await asyncio.sleep(5)
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
