import os
import sys
import asyncio
import logging
import shutil
from pathlib import Path

# Добавляем корень проекта в пути поиска модулей
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import FSInputFile
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

load_dotenv()

API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

class VideoMaker(StatesGroup):
    waiting_for_topic = State()
    waiting_for_approval = State()
    waiting_for_title_edit = State()
    waiting_for_tts_choice = State()
    waiting_for_image_mode = State()
    waiting_for_links = State()
    waiting_for_photos = State()
    processing = State()

active_tasks = set()
upload_lock = asyncio.Lock()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("👋 **Контент-Завод v2.5** (Debug Mode)\n\nОчистка файлов отключена.")

# --- ЗАГРУЗКА ФОТО ---

@dp.message(F.photo, VideoMaker.waiting_for_photos)
async def handle_photo_upload(message: types.Message, state: FSMContext):
    async with upload_lock:
        data = await state.get_data()
        photos = data.get("uploaded_photos", [])
        status_id = data.get("upload_status_id")
        
        project_id = f"up_{message.from_user.id}"
        dest = Path(f"temp/{project_id}/uploads/img_{len(photos)+1:03d}.png")
        dest.parent.mkdir(parents=True, exist_ok=True)
        
        file = await bot.get_file(message.photo[-1].file_id)
        await bot.download_file(file.file_path, str(dest))
        
        photos.append(str(dest))
        await state.update_data(uploaded_photos=photos)
        
        kb = InlineKeyboardBuilder().button(text="✅ Всё, монтируем!", callback_data="upload_done")
        text = f"📥 **Загрузка:** {len(photos)} фото получено."
        
        if status_id:
            try: await bot.edit_message_text(text, message.chat.id, status_id, reply_markup=kb.as_markup())
            except: pass
        else:
            msg = await message.answer(text, reply_markup=kb.as_markup())
            await state.update_data(upload_status_id=msg.message_id)
    
    try: await message.delete()
    except: pass

@dp.callback_query(F.data == "upload_done", VideoMaker.waiting_for_photos)
async def upload_done(callback: types.CallbackQuery, state: FSMContext):
    await start_production(callback.message, state)

# --- ГЕНЕРАЦИЯ И ПРАВКИ ---

@dp.message(F.text, VideoMaker.waiting_for_topic)
@dp.message(F.text)
async def handle_topic(message: types.Message, state: FSMContext):
    if message.from_user.id in active_tasks or await state.get_state() is not None:
        return
    status_msg = await message.answer("🧠 DeepSeek придумывает...")
    try:
        from ai.deepseek_writer import generate_project
        is_vert = "горизонтально" not in message.text.lower()
        project_data = await asyncio.to_thread(generate_project, message.text, "vertical" if is_vert else "horizontal")
        await state.update_data(project_data=project_data, template_type="vertical" if is_vert else "horizontal", video_title=project_data.get("suggested_title", "Без названия"))
        kb = InlineKeyboardBuilder()
        kb.button(text="✅ Одобрить", callback_data="approve")
        kb.button(text="✏️ Название", callback_data="edit_title")
        kb.button(text="❌ Отмена", callback_data="cancel")
        await status_msg.delete()
        await message.answer(f"🏷 **{project_data.get('suggested_title')}**\n\n📜 {project_data['script'][:300]}...", reply_markup=kb.as_markup())
        await state.set_state(VideoMaker.waiting_for_approval)
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@dp.callback_query(F.data == "edit_title", VideoMaker.waiting_for_approval)
async def edit_title(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите название:")
    await state.set_state(VideoMaker.waiting_for_title_edit)

@dp.message(F.text, VideoMaker.waiting_for_title_edit)
async def save_title(message: types.Message, state: FSMContext):
    await state.update_data(video_title=message.text)
    await message.answer(f"✅ Готово: {message.text}")
    await state.set_state(VideoMaker.waiting_for_approval)

# --- ПРОИЗВОДСТВО (БЕЗ ОЧИСТКИ) ---

async def start_production(message: types.Message, state: FSMContext):
    data = await state.get_data()
    user_id = message.chat.id
    active_tasks.add(user_id)
    await state.set_state(VideoMaker.processing)
    status_msg = await message.answer("🚀 В работе...")

    async def update_status(text):
        try: await status_msg.edit_text(f"⚙️ {text}")
        except: pass

    try:
        from bot.pipeline_manager import run_full_pipeline_from_data
        video_path = await run_full_pipeline_from_data(
            data['project_data'], data['template_type'], 
            tts_engine=data.get('tts_engine', 'edge'), 
            image_urls=data.get('image_urls'),
            uploaded_photos=data.get('uploaded_photos'),
            status_callback=update_status
        )
        if video_path:
            await update_status("📤 Отправляю...")
            await bot.send_video(user_id, FSInputFile(video_path), caption=f"🎬 **{data['video_title']}**")
            
            # --- ОЧИСТКА ВРЕМЕННО ОТКЛЮЧЕНА ---
            print(f"📁 Debug: Файлы сохранены в temp/ и {video_path}")
            # shutil.rmtree(...) # Закомментировано по просьбе пользователя
        else:
            await message.answer("❌ Ошибка.")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
    finally:
        active_tasks.discard(user_id)
        await state.clear()

@dp.callback_query(F.data == "approve", VideoMaker.waiting_for_approval)
async def tts_menu(callback: types.CallbackQuery, state: FSMContext):
    kb = InlineKeyboardBuilder().button(text="🎙 Google", callback_data="tts_gemini").button(text="🔊 Edge", callback_data="tts_edge")
    await callback.message.edit_text("🎯 Голос:", reply_markup=kb.as_markup())
    await state.set_state(VideoMaker.waiting_for_tts_choice)

@dp.callback_query(F.data.startswith("tts_"), VideoMaker.waiting_for_tts_choice)
async def img_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(tts_engine=callback.data.split("_")[1])
    kb = InlineKeyboardBuilder().button(text="🎨 AI", callback_data="img_ai").button(text="📂 Фото", callback_data="img_upload")
    await callback.message.edit_text("🎯 Картинки:", reply_markup=kb.as_markup())
    await state.set_state(VideoMaker.waiting_for_image_mode)

@dp.callback_query(F.data == "img_upload", VideoMaker.waiting_for_image_mode)
async def upload_mode(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("📥 Жду фото...")
    await state.set_state(VideoMaker.waiting_for_photos)

@dp.callback_query(F.data == "img_ai", VideoMaker.waiting_for_image_mode)
async def ai_mode(callback: types.CallbackQuery, state: FSMContext):
    await start_production(callback.message, state)

@dp.callback_query(F.data == "cancel")
async def cancel(callback: types.CallbackQuery, state: FSMContext):
    active_tasks.discard(callback.message.chat.id)
    await state.clear()
    await callback.message.edit_text("⏹ Отменено.")

async def main():
    print("🤖 Бот v2.5 (Debug) запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
