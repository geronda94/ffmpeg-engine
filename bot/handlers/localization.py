import logging
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.states import ProjectStates
from core.project_manager import ProjectManager
from ai.localization_agent import translate_project_content
from bot.navigation import ask_for_tts_engine

logger = logging.getLogger(__name__)
router = Router()
pm = ProjectManager()

@router.message(Command("translate"))
async def cmd_translate(message: types.Message, state: FSMContext):
    """Команда для начала перевода текущего или последнего проекта."""
    data = await state.get_data()
    project_id = data.get('project_id')
    
    if not project_id:
        await message.answer("❌ Сначала выберите или создайте проект через /start")
        return
        
    kb = InlineKeyboardBuilder()
    kb.button(text="🇺🇸 English", callback_data="trl_English")
    kb.button(text="🇷🇺 Russian", callback_data="trl_Russian")
    kb.button(text="🇷🇴 Romanian", callback_data="trl_Romanian")
    kb.button(text="🇬🇪 Georgian", callback_data="trl_Georgian")
    kb.adjust(2)
    
    await message.answer("🌍 **Локализация проекта**\n\nНа какой язык перевести текущий ролик?", reply_markup=kb.as_markup())

@router.callback_query(F.data.startswith("trl_"))
async def handle_translation_choice(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    target_lang = callback.data.split("_")[1]
    data = await state.get_data()
    source_id = data['project_id']
    
    status = await callback.message.answer(f"⏳ **Клонирую и перевожу проект на {target_lang}...**")
    
    # 1. Клонируем структуру
    new_id = pm.clone_project(source_id, target_lang)
    if not new_id:
        await status.edit_text("❌ Ошибка при клонировании проекта.")
        return
        
    # 2. Переводим контент через ИИ
    proj_data = pm.load_project(new_id)
    trans_res = await translate_project_content(proj_data['script'], proj_data['scenes'], target_lang)
    
    if trans_res:
        proj_data['script'] = trans_res['script']
        proj_data['scenes'] = trans_res['scenes']
        proj_data['status'] = "translated"
        pm.save_project(new_id, proj_data)
        
        await state.update_data(project_id=new_id, language=target_lang)
        
        await status.edit_text(
            f"✅ **Проект успешно локализован!**\n\n"
            f"Новый ID: `{new_id}`\n"
            f"Язык: {target_lang}\n\n"
            f"Теперь нужно выбрать голос для новой озвучки."
        )
        # Переходим сразу к выбору движка озвучки
        await ask_for_tts_engine(callback.message, state)
    else:
        await status.edit_text("❌ Ошибка при переводе текста ИИ-агентом.")
