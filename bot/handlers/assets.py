import os
import asyncio
import logging
from aiogram import Router, types, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.states import ProjectStates
from ai.image_generator import generate_image
from bot.navigation import ask_for_asset
import aiohttp

logger = logging.getLogger(__name__)
router = Router()

async def download_file_from_url(url: str, dest_path: str):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=30) as resp:
                if resp.status == 200:
                    with open(dest_path, "wb") as f: f.write(await resp.read())
                    return True
    except Exception as e:
        logger.error(f"Download error: {e}")
    return False

@router.callback_query(F.data.in_(["asset_ai", "asset_manual"]), ProjectStates.collecting_assets)
@router.callback_query(F.data.in_(["asset_ai", "asset_manual"]), ProjectStates.approving_asset)
async def handle_asset_choice(callback: types.CallbackQuery, state: FSMContext):
    # Пытаемся ответить на колбэк, если не вышло (таймаут) - просто логируем
    try:
        await callback.answer()
    except Exception as e:
        logger.warning(f"Could not answer callback: {e}")

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except: pass

    choice = callback.data.split("_")[1]
    logger.info(f"Asset choice triggered: {choice}")
    
    if choice == "ai":
        data = await state.get_data()
        idx = data['current_scene_idx']
        path = f"local_assets/uploads/v3_s{idx}_ai.png"
        status = await callback.message.answer("🎨 Генерирую через ИИ...")
        
        try:
            await asyncio.to_thread(generate_image, data['scenes'][idx]['image_prompt'], path)
            await status.delete()
            await state.update_data(temp_asset_path=path)
            kb = InlineKeyboardBuilder().button(text="✅ Ок", callback_data="asset_confirm").button(text="🔄 Переделать", callback_data="asset_ai")
            await callback.message.answer_photo(types.FSInputFile(path), caption="Результат ИИ. Одобряем?", reply_markup=kb.as_markup())
            await state.set_state(ProjectStates.approving_asset)
        except Exception as e:
            logger.error(f"Image generation error: {e}")
            await callback.message.answer("❌ Ошибка генерации картинки. Попробуйте еще раз или выберите другой метод.")
            
    elif choice == "manual":
        await callback.message.answer("Пришлите файл или ссылку:")
        await state.set_state(ProjectStates.waiting_for_asset)

@router.message(ProjectStates.waiting_for_asset)
async def handle_manual_asset(message: types.Message, state: FSMContext, bot: Bot):
    logger.info("Received manual asset message")
    data = await state.get_data()
    idx = data['current_scene_idx']
    path = f"local_assets/uploads/v3_s{idx}.jpg"
    
    if message.photo or message.video:
        file_id = message.photo[-1].file_id if message.photo else message.video.file_id
        file_info = await bot.get_file(file_id)
        path = f"local_assets/uploads/v3_s{idx}.{file_info.file_path.split('.')[-1]}"
        await bot.download_file(file_info.file_path, path)
        try: await message.delete()
        except: pass
    elif message.text and "http" in message.text:
        success = await download_file_from_url(message.text, path)
        if success: 
            try: await message.delete()
            except: pass
        else:
            await message.answer("❌ Ошибка загрузки по ссылке.")
            return
    
    if path:
        await state.update_data(temp_asset_path=path)
        kb = InlineKeyboardBuilder().button(text="✅ Ок", callback_data="asset_confirm").button(text="🔄 Заменить", callback_data="asset_manual")
        try:
            if ".mp4" in path or ".mov" in path: await message.answer_video(types.FSInputFile(path), reply_markup=kb.as_markup())
            else: await message.answer_photo(types.FSInputFile(path), reply_markup=kb.as_markup())
        except Exception as e:
            logger.error(f"Error sending confirmation photo: {e}")
            await message.answer("Файл получен. Одобряем?", reply_markup=kb.as_markup())
        await state.set_state(ProjectStates.approving_asset)

@router.callback_query(F.data == "asset_confirm", ProjectStates.approving_asset)
async def asset_confirm(callback: types.CallbackQuery, state: FSMContext):
    logger.info("Asset confirmed by user")
    try:
        await callback.answer("Принято!")
    except: pass

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except: pass
    
    data = await state.get_data()
    assets = data.get('assets', {})
    assets[str(data['current_scene_idx'])] = {"path": data['temp_asset_path']}
    
    new_idx = data['current_scene_idx'] + 1
    logger.info(f"Updating index to {new_idx}")
    await state.update_data(assets=assets, current_scene_idx=new_idx)
    
    # ПЕРЕХОДИМ К СЛЕДУЮЩЕЙ СЦЕНЕ
    logger.info(f"Calling ask_for_asset for next scene (new_idx={new_idx})")
    await ask_for_asset(callback.message, state)
