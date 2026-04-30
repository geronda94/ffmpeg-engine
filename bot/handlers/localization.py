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
async def cmd_translate(event: types.Message | types.CallbackQuery, state: FSMContext):
    """Команда для начала перевода текущего или последнего проекта."""
    data = await state.get_data()
    project_id = data.get('project_id')
    
    if not project_id:
        msg = "❌ Сначала выберите или создайте проект через /start"
        if isinstance(event, types.Message): await event.answer(msg)
        else: await event.message.answer(msg)
        return
        
    kb = InlineKeyboardBuilder()
    # Только языки из конфига
    langs = {
        "Russian": "🇷🇺",
        "English": "🇺🇸",
        "Romanian": "🇷🇴",
        "Georgian": "🇬🇪"
    }
    
    # Загружаем проект, чтобы узнать текущий язык
    proj_data = pm.load_project(project_id)
    current_lang = proj_data.get('language', 'Russian')
    
    for lang_name, flag in langs.items():
        if lang_name != current_lang:
            kb.button(text=f"{flag} {lang_name}", callback_data=f"trl_{lang_name}:{project_id}")
    
    # Сохраняем кнопку субтитров, чтобы она не пропадала!
    kb.button(text="🎬 Добавить субтитры", callback_data=f"subtitles:{project_id}")
    kb.adjust(2, 1)
    
    text = f"🌍 **Выберите язык для перевода проекта** `{project_id}`:"
    
    if isinstance(event, types.Message):
        await event.answer(text, reply_markup=kb.as_markup())
    else:
        # ФИКС: Если это медиа, мы НЕ меняем caption (чтобы SEO не пропало), 
        # а только меняем кнопки (reply_markup).
        if event.message.video or event.message.photo:
            await event.message.edit_reply_markup(reply_markup=kb.as_markup())
            await event.answer("🌍 Выберите язык в меню ниже")
        else:
            await event.message.edit_text(text, reply_markup=kb.as_markup())

@router.callback_query(F.data.startswith("trl_"))
async def handle_translation_choice(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    # ФИКС: Разделяем по префиксу и двоеточию
    data_part = callback.data[4:] # Убираем 'trl_'
    target_lang, source_id = data_part.split(":", 1)
    
    status = await callback.message.answer(f"⏳ **Клонирую и перевожу на {target_lang}...**")
    
    try:
        source_data = pm.load_project(source_id)
        if not source_data:
            await status.edit_text("❌ Исходный проект не найден.")
            return
            
        # 1. Переводим тексты и SEO
        trans_res = await translate_project_content(
            source_data['script'], 
            source_data['scenes'],
            source_data.get('metadata', {}),
            target_lang
        )
        
        # 2. Клонируем проект с новыми данными
        new_id = pm.clone_project(source_id, target_lang)
        proj_data = pm.load_project(new_id)
        if trans_res:
            proj_data['script'] = trans_res['script']
            proj_data['scenes'] = trans_res['scenes']
            proj_data['metadata'] = trans_res['metadata']
            proj_data['language'] = target_lang
            proj_data['status'] = "translated"
            pm.save_project(new_id, proj_data)
            
            # Кнопки для продолжения или перевода на ЕЩЕ ОДИН язык
            kb = InlineKeyboardBuilder()
            kb.button(text="🎙 Выбрать озвучку", callback_data=f"goto_tts:{new_id}")
            kb.button(text="🌍 Перевести на другой", callback_data=f"translate_menu:{source_id}")
            kb.adjust(1)
            
            await status.edit_text(
                f"✅ **Проект локализован!**\n\n"
                f"Новый ID: `{new_id}`\n"
                f"Язык: {target_lang}\n\n"
                f"Что делаем дальше?",
                reply_markup=kb.as_markup()
            )
        else:
            await status.edit_text("❌ Ошибка при переводе текста ИИ-агентом.")
            
    except Exception as e:
        logger.error(f"Translation flow error: {e}", exc_info=True)
        await status.edit_text(f"❌ Критическая ошибка при локализации: {e}")

@router.callback_query(F.data.startswith("goto_tts:"))
async def handle_goto_tts(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    # ФИКС: Используем ':' как разделитель
    new_id = callback.data.split(":")[1]
    await state.update_data(project_id=new_id)
    await ask_for_tts_engine(callback.message, state)
