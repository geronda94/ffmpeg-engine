import logging
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.states import ProjectStates
from ai.metadata_agent import generate_metadata
from core.project_manager import ProjectManager

logger = logging.getLogger(__name__)
router = Router()
pm = ProjectManager()

@router.callback_query(F.data == "ask_metadata_style")
async def handle_ask_metadata_style(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    from bot.navigation import ask_for_metadata_style
    await ask_for_metadata_style(callback.message, state)

@router.callback_query(F.data.startswith("metastyle_"), ProjectStates.choosing_metadata_style)
async def process_metadata_style(callback: types.CallbackQuery, state: FSMContext):
    style = callback.data.split("_")[-1]
    
    if style == "custom":
        await callback.message.edit_text("✍️ **Введите ваш промпт или пожелания к названию и описанию видео:**")
        await state.set_state(ProjectStates.waiting_for_metadata_prompt)
        return

    style_map = {
        "viral": "Виральный, кликбейтный заголовок с капсом и эмодзи. Энергичное описание.",
        "edu": "Экспертный, познавательный и информативный заголовок. Структурированное описание.",
        "shorts": "Короткий, емкий заголовок. Оптимизировано под Shorts/TikTok."
    }
    
    instruction = style_map.get(style, "Standard SEO style")
    await callback.message.edit_text("🧠 **Агент метаданных генерирует SEO-пакет...** Пожалуйста, подождите.")
    await run_metadata_generation(callback.message, state, instruction)

@router.message(ProjectStates.waiting_for_metadata_prompt)
async def process_custom_metadata_prompt(message: types.Message, state: FSMContext):
    instruction = message.text
    # Удаляем сообщение пользователя для чистоты
    try: await message.delete()
    except: pass
    
    status_msg = await message.answer("🧠 **Генерирую метаданные по вашему запросу...**")
    await run_metadata_generation(status_msg, state, instruction)

async def run_metadata_generation(message: types.Message, state: FSMContext, instruction: str):
    data = await state.get_data()
    project_id = data.get('project_id')
    script = data.get('script', "")
    lang = data.get('language', 'Russian')
    
    try:
        # Вызываем асинхронный агент
        metadata = await generate_metadata(script, lang, user_instruction=instruction)
        
        # Сохраняем в проект
        if project_id:
            project_data = pm.load_project(project_id)
            if project_data:
                project_data["metadata"] = metadata
                pm.save_project(project_id, project_data)
        
        await state.update_data(metadata=metadata)
        
        res_text = (
            "✅ **SEO-метаданные готовы!**\n\n"
            f"📌 **Заголовок:** {metadata.get('title', '...')}\n\n"
            f"📝 **Описание:** {metadata.get('description', '...')}\n\n"
            f"🏷 **Теги:** {', '.join(metadata.get('hashtags', []))}\n\n"
            "🚀 **Начинаем финальный монтаж?**"
        )
        
        kb = InlineKeyboardBuilder()
        kb.button(text="🎬 Да, запускай монтаж!", callback_data="start_render")
        kb.button(text="🔄 Переделать (другой стиль)", callback_data="ask_metadata_style")
        kb.adjust(1)
        
        # Если сообщение можно редактировать - редактируем, если нет - пишем новое
        try:
            await message.edit_text(res_text, reply_markup=kb.as_markup())
        except:
            await message.answer(res_text, reply_markup=kb.as_markup())
            
        await state.set_state(ProjectStates.assembling_video)
        
    except Exception as e:
        logger.error(f"Metadata Generation Error: {e}")
        error_kb = InlineKeyboardBuilder()
        error_kb.button(text="🔄 Попробовать еще раз", callback_data="ask_metadata_style")
        
        error_text = "❌ **Ошибка при генерации метаданных.**\nВозможно, временные неполадки с API. Попробуем еще раз?"
        try:
            await message.edit_text(error_text, reply_markup=error_kb.as_markup())
        except:
            await message.answer(error_text, reply_markup=error_kb.as_markup())
