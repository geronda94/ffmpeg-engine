import logging
import os
import json
import asyncio
import time
import re
import aiohttp
from aiogram import Router, types, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.states import ProjectStates
from core.project_manager import ProjectManager
from bot.navigation import ask_for_asset
from ai.image_generator import generate_image
from ai.dynamic_scene_agent import render_dynamic_scene

from core.video_utils import get_video_info, generate_storyboard, extract_single_frame

logger = logging.getLogger(__name__)
router = Router()
pm = ProjectManager()

URL_PATTERN = re.compile(r'https?://[^\s]+')

@router.callback_query(F.data == "asset_dynamic", ProjectStates.collecting_assets)
async def handle_dynamic_asset_start(event: types.CallbackQuery | types.Message, state: FSMContext):
    if isinstance(event, types.CallbackQuery):
        await event.answer()
        message = event.message
    else:
        message = event
        
    with open("config/dynamic_scenes.json", "r", encoding="utf-8") as f:
        config = json.load(f)
        
    kb = InlineKeyboardBuilder()
    for p in config['presets']:
        kb.button(text=p['name'], callback_data=f"dynpre_{p['id']}")
    kb.adjust(1)
    
    text = (
        "🎭 **Выберите пресет динамической сцены:**\n\n"
        "Это позволит собрать сложную сцену из нескольких элементов (лого, текст, фон)."
    )
    
    if isinstance(event, types.CallbackQuery):
        await message.edit_text(text, reply_markup=kb.as_markup())
    else:
        await message.answer(text, reply_markup=kb.as_markup())
        
    await state.set_state(ProjectStates.choosing_dynamic_preset)

@router.callback_query(F.data.startswith("dynpre_"), ProjectStates.choosing_dynamic_preset)
async def handle_dynamic_preset_choice(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    preset_id = callback.data.replace("dynpre_", "")
    
    with open("config/dynamic_scenes.json", "r", encoding="utf-8") as f:
        config = json.load(f)
    
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
    
    # Удаляем предыдущий вопрос бота, если он был
    last_msg_id = data.get('last_dynamic_msg_id')
    if last_msg_id:
        try: await message.bot.delete_message(chat_id=message.chat.id, message_id=last_msg_id)
        except: pass
        
    if idx >= len(preset['elements']):
        await start_dynamic_pre_render(message, state)
        return
        
    element = preset['elements'][idx]
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
        if message.text: val = message.text
        else: await message.answer("❌ Ожидается текст."); return
    else:
        file_id = None
        ext = ".jpg"
        if message.photo: file_id = message.photo[-1].file_id
        elif message.video: file_id = message.video.file_id; ext = ".mp4"
        elif message.document: file_id = message.document.file_id; ext = os.path.splitext(message.document.name)[1]
        
        if not file_id:
            await message.answer(f"❌ Ожидается {element['name']}. Пришлите файл."); return
            
        file = await message.bot.get_file(file_id)
        os.makedirs("temp/dynamic", exist_ok=True)
        val = f"temp/dynamic/{file_id}{ext}"
        await message.bot.download_file(file.file_path, val)

    # Удаляем сообщение пользователя для чистоты чата
    try: await message.delete()
    except: pass

    collected = data.get('dynamic_elements_collected', {})
    collected[element['id']] = val
    
    await state.update_data(
        dynamic_elements_collected=collected,
        current_element_idx=idx + 1
    )
    
    await ask_next_dynamic_element(message, state)

async def start_dynamic_pre_render(message: types.Message, state: FSMContext):
    data = await state.get_data()
    preset = data['dynamic_preset']
    elements = data['dynamic_elements_collected']
    project_id = data['project_id']
    scene_idx = data['current_scene_idx']
    
    status = await message.answer(f"⚙️ **Собираю динамическую сцену: {preset['name']}**\nЭто займет немного времени...")
    
    output_path = f"projects/{project_id}/assets/dynamic_{scene_idx}_{int(time.time())}.mp4"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    # Длительность берем из сцены
    scene = data['scenes'][scene_idx]
    duration = float(scene.get('end', 5.0) - scene.get('start', 0.0))
    if duration <= 0: duration = float(scene.get('estimated_duration', 5.0))

    # Выполняем рендер (в потоке, чтобы не блочить бота)
    res = await asyncio.to_thread(render_dynamic_scene, preset['id'], elements, duration, output_path)
    
    await status.delete()
    if res:
        kb = InlineKeyboardBuilder()
        kb.button(text="✅ Одобрить", callback_data="dyn_approve")
        kb.button(text="🔄 Переделать", callback_data="asset_dynamic")
        kb.adjust(1)
        
        await message.answer_video(
            types.FSInputFile(output_path),
            caption=f"✨ **Динамическая сцена готова!**\nПресет: {preset['name']}\n\nОдобряем?",
            reply_markup=kb.as_markup()
        )
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
    
    # Сохраняем как обычный ассет
    pm.update_asset(project_id, scene_idx, video_path)
    
    # Очистка временных файлов элементов
    for path in data['dynamic_elements_collected'].values():
        if isinstance(path, str) and os.path.exists(path) and "temp/dynamic" in path:
            os.remove(path)
            
    # Переход к следующей сцене
    from bot.navigation import ask_for_asset
    await ask_for_asset(callback.message, state, scene_idx + 1)

@router.callback_query(F.data == "asset_ai", StateFilter(ProjectStates.collecting_assets, ProjectStates.approving_asset))
async def ai_asset_choice(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    project_id = data['project_id']
    idx = data['current_scene_idx']
    scene = data['scenes'][idx]
    
    status = await callback.message.answer(f"🎨 Генерирую ИИ-изображение для сцены {idx+1}...")
    
    try:
        prompt = scene.get('image_prompt', scene.get('visual_description', 'Video scene'))
        os.makedirs("temp", exist_ok=True)
        temp_path = f"temp/ai_{int(time.time())}_{idx}.png"
        
        success = await asyncio.to_thread(generate_image, prompt, temp_path)
        
        if success and os.path.exists(temp_path):
            pm.update_asset(project_id, idx, temp_path)
            os.remove(temp_path)
            
            proj = pm.load_project(project_id)
            new_path = proj['assets'][str(idx)]['path']
            
            all_assets = data.get('assets', {})
            all_assets[str(idx)] = {"path": new_path, "type": "image"}
            await state.update_data(assets=all_assets)
            
            await status.delete()
            kb = InlineKeyboardBuilder()
            kb.button(text="✅ Подтвердить", callback_data="asset_confirm")
            kb.button(text="🖼 Сгенерировать ИИ", callback_data="asset_ai")
            kb.button(text="🎬 Динамическая сцена", callback_data="asset_dynamic")
            kb.button(text="📁 Загрузить файл / Ссылка", callback_data="asset_manual")
            kb.adjust(1)
            
            await callback.message.answer_photo(
                types.FSInputFile(new_path), 
                caption=f"✨ Готово! Подходит для сцены {idx+1}?", 
                reply_markup=kb.as_markup()
            )
            await state.set_state(ProjectStates.approving_asset)
        else: raise Exception("Fail")
    except:
        await status.edit_text("⚠️ Ошибка генерации. Попробуйте загрузить своё.")

@router.callback_query(F.data == "asset_manual", StateFilter(ProjectStates.collecting_assets, ProjectStates.approving_asset))
async def manual_asset_choice(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    idx = data['current_scene_idx']
    scene = data['scenes'][idx]
    est_dur = scene.get('estimated_duration', 'не определена')
    
    msg = (
        f"📎 **Загрузка для сцены {idx+1}**\n\n"
        f"🎬 **Что нужно:** {scene.get('visual_description', 'Нет описания')}\n\n"
        f"⏱ **Рекомендуемая длина:** ~{est_dur} сек\n"
        f"🎨 **Промпт (для ИИ):** `{scene.get('image_prompt', 'Нет промпта')}`\n\n"
        f"--- \nПришлите фото, видео или **прямую ссылку** на файл:"
    )
    
    try: await callback.message.delete()
    except: pass
    await callback.message.answer(msg, parse_mode="Markdown")
    await state.set_state(ProjectStates.waiting_for_asset)

async def show_video_storyboard(message: types.Message, state: FSMContext, video_path: str, page: int = 0):
    """Генерирует и показывает сетку кадров для выбора момента."""
    info = await asyncio.to_thread(get_video_info, video_path)
    duration = info['duration'] if info else 0
    total_min = int(duration // 60)
    total_sec = int(duration % 60)
    
    status = await message.answer(f"🎞 Генерирую раскадровку ({total_min:02d}:{total_sec:02d})...")
    
    interval = 5 
    start_time = page * 9 * interval
    
    os.makedirs("temp/storyboards", exist_ok=True)
    out_path = f"temp/storyboards/sb_{int(time.time())}.jpg"
    
    sb_path = await asyncio.to_thread(generate_storyboard, video_path, out_path, start_time=start_time, interval=interval)
    
    if not sb_path:
        await status.edit_text("❌ Не удалось создать раскадровку.")
        return

    kb = InlineKeyboardBuilder()
    # Кнопки с таймингами (только те, что в пределах длительности)
    for i in range(9):
        t = start_time + (i * interval)
        if t >= duration: break
        time_str = f"{int(t // 60):02d}:{int(t % 60):02d}"
        kb.button(text=time_str, callback_data=f"voff_sel_{int(t)}")
    
    kb.adjust(3)
    
    # Кнопки пагинации
    nav_kb = InlineKeyboardBuilder()
    if page > 0:
        nav_kb.button(text="⬅️ Назад", callback_data=f"voff_pg_{page-1}")
    
    if (page + 1) * 9 * interval < duration:
        nav_kb.button(text="➡️ Вперед", callback_data=f"voff_pg_{page+1}")
    
    kb.attach(nav_kb)
    kb.adjust(3, 3, 3, 2)
    
    await status.delete()
    await message.answer_photo(
        types.FSInputFile(sb_path),
        caption=f"📺 **Выберите момент начала**\nВсего: {total_min:02d}:{total_sec:02d} | Стр. {page + 1}",
        reply_markup=kb.as_markup()
    )
    # Сохраняем путь к видео в состоянии, чтобы не качать заново
    await state.update_data(temp_video_path=video_path)

@router.callback_query(F.data.startswith("voff_pg_"), ProjectStates.selecting_video_offset)
async def process_offset_pagination(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    page = int(callback.data.split("_")[-1])
    data = await state.get_data()
    video_path = data['temp_video_path']
    await callback.message.delete()
    await show_video_storyboard(callback.message, state, video_path, page)

@router.callback_query(F.data.startswith("voff_sel_"), ProjectStates.selecting_video_offset)
async def process_offset_selection(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    offset = float(callback.data.split("_")[-1])
    data = await state.get_data()
    project_id = data['project_id']
    scene_idx = data['current_scene_idx']
    video_path = data['temp_video_path']
    
    # Теперь сохраняем ассет с оффсетом
    pm.update_asset(project_id, scene_idx, video_path, offset=offset)
    
    # Генерируем превью-кадр для подтверждения
    preview_path = f"temp/preview_{int(time.time())}.jpg"
    await asyncio.to_thread(extract_single_frame, video_path, preview_path, offset)
    
    if os.path.exists(video_path): os.remove(video_path)
    
    proj = pm.load_project(project_id)
    new_asset_path = proj['assets'][str(scene_idx)]['path']
    
    all_assets = data.get('assets', {})
    all_assets[str(scene_idx)] = {"path": new_asset_path, "type": "video", "start_offset": offset}
    await state.update_data(assets=all_assets)
    
    kb = InlineKeyboardBuilder().button(text="✅ Подтвердить", callback_data="asset_confirm").button(text="🔄 Другой", callback_data="asset_manual").adjust(1)
    
    await callback.message.delete()
    if os.path.exists(preview_path):
        await callback.message.answer_photo(
            types.FSInputFile(preview_path), 
            caption=f"✅ Момент выбран: {int(offset // 60):02d}:{int(offset % 60):02d}\nПодтверждаем?", 
            reply_markup=kb.as_markup()
        )
        os.remove(preview_path)
    else:
        await callback.message.answer(
            f"✅ Момент выбран: {int(offset // 60):02d}:{int(offset % 60):02d}\nПодтверждаем?", 
            reply_markup=kb.as_markup()
        )
    await state.set_state(ProjectStates.approving_asset)

@router.message(ProjectStates.waiting_for_asset, F.photo | F.video | F.document | F.text)
async def handle_manual_asset(message: types.Message, state: FSMContext):
    data = await state.get_data()
    project_id = data['project_id']
    scene_idx = data['current_scene_idx']
    
    temp_path = None
    is_video = False

    if message.photo:
        file_id = message.photo[-1].file_id
        file = await message.bot.get_file(file_id)
        temp_path = f"temp/{file_id}.jpg"
        await message.bot.download_file(file.file_path, temp_path)
    elif message.video:
        file_id = message.video.file_id
        file = await message.bot.get_file(file_id)
        temp_path = f"temp/{file_id}.mp4"
        is_video = True
        await message.bot.download_file(file.file_path, temp_path)
    elif message.document:
        file_id = message.document.file_id
        file = await message.bot.get_file(file_id)
        ext = os.path.splitext(message.document.file_name)[1].lower()
        temp_path = f"temp/{file_id}{ext}"
        is_video = ext in ['.mp4', '.mov', '.avi']
        await message.bot.download_file(file.file_path, temp_path)
    elif message.text and URL_PATTERN.match(message.text):
        url = URL_PATTERN.search(message.text).group()
        status = await message.answer("🌐 Качаю файл по ссылке...")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        content_type = resp.headers.get("Content-Type", "").lower()
                        is_video = "video" in content_type
                        ext = ".mp4" if is_video else ".jpg"
                        temp_path = f"temp/url_{int(time.time())}{ext}"
                        os.makedirs("temp", exist_ok=True)
                        with open(temp_path, "wb") as f:
                            f.write(await resp.read())
            await status.delete()
        except: 
            await message.answer("❌ Не удалось скачать по ссылке.")
            return

    if not temp_path or not os.path.exists(temp_path):
        return

    # Если это видео — переходим к выбору момента
    if is_video:
        # Проверяем длительность для авто-выбора
        info = await asyncio.to_thread(get_video_info, temp_path)
        video_dur = info['duration'] if info else 0
        
        target_dur = 5.0
        if 'scenes' in data and scene_idx < len(data['scenes']):
            scene = data['scenes'][scene_idx]
            target_dur = scene.get('estimated_duration', 5.0)
            if scene.get('end') is not None:
                target_dur = scene['end'] - scene['start']
        
        if video_dur > 0 and video_dur <= target_dur + 0.5:
            # Видео короткое, выбираем его целиком без раскадровки
            pm.update_asset(project_id, scene_idx, temp_path, offset=0)
            if os.path.exists(temp_path): os.remove(temp_path)
            
            proj = pm.load_project(project_id)
            new_path = proj['assets'][str(scene_idx)]['path']
            
            all_assets = data.get('assets', {})
            all_assets[str(scene_idx)] = {"path": new_path, "type": "video", "start_offset": 0}
            await state.update_data(assets=all_assets)
            
            kb = InlineKeyboardBuilder().button(text="✅ Подтвердить", callback_data="asset_confirm").button(text="🔄 Другой", callback_data="asset_manual").adjust(1)
            await message.answer_video(types.FSInputFile(new_path), caption=f"⚡ Видео короткое ({video_dur}с), выбрано целиком.\nПодтверждаем?", reply_markup=kb.as_markup())
            await state.set_state(ProjectStates.approving_asset)
            return

        await state.set_state(ProjectStates.selecting_video_offset)
        await show_video_storyboard(message, state, temp_path)
        return

    # Если фото — сохраняем как обычно
    pm.update_asset(project_id, scene_idx, temp_path)
    if os.path.exists(temp_path): os.remove(temp_path)
    
    proj = pm.load_project(project_id)
    new_asset_path = proj['assets'][str(scene_idx)]['path']
    
    all_assets = data.get('assets', {})
    all_assets[str(scene_idx)] = {"path": new_asset_path, "type": "image"}
    await state.update_data(assets=all_assets)
    
    kb = InlineKeyboardBuilder().button(text="✅ Подтвердить", callback_data="asset_confirm").button(text="🔄 Другой", callback_data="asset_manual").adjust(1)
    await message.answer_photo(types.FSInputFile(new_asset_path), caption="Принято! Подтверждаем?", reply_markup=kb.as_markup())
    await state.set_state(ProjectStates.approving_asset)

@router.callback_query(F.data == "asset_confirm", ProjectStates.approving_asset)
async def confirm_asset(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    idx = data['current_scene_idx']
    try:
        new_caption = f"✅ **Сцена {idx + 1} одобрена**"
        if callback.message.caption: await callback.message.edit_caption(caption=new_caption, reply_markup=None)
        else: await callback.message.edit_text(text=new_caption, reply_markup=None)
    except: pass
    await ask_for_asset(callback.message, state, idx + 1)
