import logging
import os
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

logger = logging.getLogger(__name__)
router = Router()
pm = ProjectManager()

URL_PATTERN = re.compile(r'https?://[^\s]+')

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
            kb.button(text="🔄 Переделать", callback_data="asset_ai")
            kb.button(text="📁 Своё", callback_data="asset_manual")
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
    
    msg = (
        f"📎 **Загрузка для сцены {idx+1}**\n\n"
        f"🎬 **Что нужно:** {scene.get('visual_description', 'Нет описания')}\n\n"
        f"🎨 **Промпт (для ИИ):** `{scene.get('image_prompt', 'Нет промпта')}`\n\n"
        f"--- \nПришлите фото, видео или **прямую ссылку** на файл:"
    )
    
    try: await callback.message.delete()
    except: pass
    await callback.message.answer(msg, parse_mode="Markdown")
    await state.set_state(ProjectStates.waiting_for_asset)

@router.message(ProjectStates.waiting_for_asset, F.photo | F.video | F.document | F.text)
async def handle_manual_asset(message: types.Message, state: FSMContext):
    data = await state.get_data()
    project_id = data['project_id']
    scene_idx = data['current_scene_idx']
    
    temp_path = None
    ext = ".jpg"

    if message.photo:
        file_id = message.photo[-1].file_id
        file = await message.bot.get_file(file_id)
        temp_path = f"temp/{file_id}.jpg"
        await message.bot.download_file(file.file_path, temp_path)
    elif message.video:
        file_id = message.video.file_id
        file = await message.bot.get_file(file_id)
        temp_path = f"temp/{file_id}.mp4"
        ext = ".mp4"
        await message.bot.download_file(file.file_path, temp_path)
    elif message.document:
        file_id = message.document.file_id
        file = await message.bot.get_file(file_id)
        ext = os.path.splitext(message.document.file_name)[1]
        temp_path = f"temp/{file_id}{ext}"
        await message.bot.download_file(file.file_path, temp_path)
    elif message.text and URL_PATTERN.match(message.text):
        url = URL_PATTERN.search(message.text).group()
        status = await message.answer("🌐 Качаю файл по ссылке...")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        ext = ".mp4" if "video" in resp.headers.get("Content-Type", "") else ".jpg"
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

    pm.update_asset(project_id, scene_idx, temp_path)
    os.remove(temp_path)
    
    proj = pm.load_project(project_id)
    new_asset_path = proj['assets'][str(scene_idx)]['path']
    
    all_assets = data.get('assets', {})
    all_assets[str(scene_idx)] = {"path": new_asset_path, "type": proj['assets'][str(scene_idx)]['type']}
    await state.update_data(assets=all_assets)
    
    kb = InlineKeyboardBuilder().button(text="✅ Подтвердить", callback_data="asset_confirm").button(text="🔄 Другой", callback_data="asset_manual").adjust(1)
    
    if new_asset_path.endswith(".mp4"):
        await message.answer_video(types.FSInputFile(new_asset_path), caption="Принято! Подтверждаем?", reply_markup=kb.as_markup())
    else:
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
