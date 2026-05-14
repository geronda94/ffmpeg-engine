import logging
import asyncio
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.states import ProjectStates
from core.project_manager import ProjectManager
from core.config_loader import get_config
from ai.localization_agent import translate_project_content
from ai.preview_agent import generate_preview_text
from ai.preview_designer_agent import design_preview_colors
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
        text_err = "❌ Сначала создайте или выберите проект: /start"
        if isinstance(event, types.Message):
            await event.answer(text_err)
        else:
            await event.answer(text_err)
        return
        
    kb = InlineKeyboardBuilder()
    langs = {
        "Russian": "🇷🇺",
        "English": "🇺🇸",
        "Romanian": "🇷🇴",
        "Georgian": "🇬🇪"
    }
    
    proj_data = pm.load_project(project_id)
    current_lang = proj_data.get('language', 'Russian')
    
    for lang_name, flag in langs.items():
        if lang_name != current_lang:
            kb.button(text=f"{flag} {lang_name}", callback_data=f"trl_{lang_name}:{project_id}")
    
    kb.button(text="🎬 Добавить субтитры", callback_data=f"subtitles:{project_id}")
    kb.adjust(2, 1)
    
    text = f"🌍 **Выберите язык для перевода проекта** `{project_id}`:"
    
    if isinstance(event, types.Message):
        await event.answer(text, reply_markup=kb.as_markup())
    else:
        try:
            await event.message.edit_reply_markup(reply_markup=kb.as_markup())
        except Exception as e:
            logger.warning(f"Ignored edit_reply_markup error (likely double-click): {e}")
            
        try:
            await event.answer("🌍 Выберите язык в меню ниже")
        except Exception:
            pass

@router.callback_query(F.data.startswith("trl_"))
async def handle_translation_choice(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data_part = callback.data[4:]
    target_lang, source_id = data_part.split(":", 1)
    
    status = await callback.message.answer(f"⏳ **Клонирую и перевожу на {target_lang}...**")
    await state.update_data(flow_start_msg_id=status.message_id)
    
    try:
        source_data = pm.load_project(source_id)
        if not source_data:
            await status.edit_text("❌ Исходный проект не найден.")
            return
            
        # ШАГ 1: Клонируем проект (теперь асинхронно, чтобы не вешать бота)
        logger.info(f"Step 1: Cloning project {source_id} to {target_lang}...")
        await status.edit_text(f"⏳ **Шаг 1/3: Копирование ассетов...**")
        
        new_id = await asyncio.to_thread(pm.clone_project, source_id, target_lang)
        if not new_id:
            await status.edit_text("❌ Ошибка при создании папки проекта.")
            return
            
        # ШАГ 2: Перевод через ИИ
        logger.info(f"Step 2: Requesting AI translation for {new_id}...")
        await status.edit_text(f"⏳ **Шаг 2/3: ИИ переводит текст на {target_lang}...**")
        
        trans_res = await translate_project_content(
            source_data['script'], 
            source_data['scenes'],
            source_data.get('metadata', {}),
            target_lang
        )
        
        if trans_res:
            logger.info(f"Step 3: Saving translated data to {new_id}...")
            await status.edit_text(f"⏳ **Шаг 3/3: Финализация проекта...**")
            
            proj_data = pm.load_project(new_id)
            proj_data['script'] = trans_res['script']
            proj_data['scenes'] = trans_res['scenes']
            proj_data['metadata'] = trans_res['metadata']
            proj_data['language'] = target_lang
            proj_data['status'] = "translated"
            
            pm.save_project(new_id, proj_data)
            pm.recalc_scene_durations(new_id)
            proj_data = pm.load_project(new_id)

            await state.update_data(project_id=new_id)

            from ai.preview_agent import generate_preview_text
            preview = await generate_preview_text(
                proj_data.get('script', ''),
                target_lang,
                channel_profile=proj_data.get('channel_profile'),
                style_id=proj_data.get('script_style')
            )
            preview_text = preview.get('preview_text', '')
            hl_word = preview.get('highlight_word', '')

            first_asset = None
            assets = proj_data.get('assets', {})
            if '0' in assets:
                first_asset = assets['0'].get('path', '')

            colors = await design_preview_colors(
                first_asset or '',
                preview_text,
                channel_name=proj_data.get('channel_profile', ''),
                script_snippet=proj_data.get('script', '')
            )

            proj_data['preview_text'] = preview_text
            proj_data['preview_highlight'] = hl_word
            proj_data['preview_colors'] = colors
            pm.save_project(new_id, proj_data)

            await status.edit_text(f"✅ **Перевод на {target_lang} завершён!**")

            kb = InlineKeyboardBuilder()
            kb.button(text="✅ Одобрить превью", callback_data=f"tr_approve_preview:{new_id}")
            kb.button(text="🔄 Сгенерировать другое", callback_data=f"tr_regenerate_preview:{new_id}")
            kb.adjust(2)

            await callback.message.answer(
                f"🎬 **Превью для первого кадра ({target_lang}):**\n\n"
                f"`{preview_text}`\n\n"
                f"Подходит?",
                reply_markup=kb.as_markup()
            )
        else:
            await status.edit_text("❌ Ошибка при переводе текста ИИ-агентом.")
            
    except Exception as e:
        logger.error(f"Translation flow error: {e}", exc_info=True)
        await status.edit_text(f"❌ Критическая ошибка при локализации: {e}")


@router.callback_query(F.data.startswith("tr_approve_preview:"))
async def tr_approve_preview(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    new_id = callback.data.split(":", 1)[1]
    await state.update_data(project_id=new_id)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await ask_for_tts_engine(callback.message, state)


@router.callback_query(F.data.startswith("tr_regenerate_preview:"))
async def tr_regenerate_preview(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    new_id = callback.data.split(":", 1)[1]
    proj_data = pm.load_project(new_id)
    if not proj_data:
        await callback.message.answer("❌ Проект не найден.")
        return

    preview = await generate_preview_text(
        proj_data.get('script', ''),
        proj_data.get('language', 'Russian'),
        channel_profile=proj_data.get('channel_profile'),
        style_id=proj_data.get('script_style')
    )
    preview_text = preview.get('preview_text', '')
    hl_word = preview.get('highlight_word', '')

    first_asset = proj_data.get('assets', {}).get('0', {}).get('path', '')
    colors = await design_preview_colors(
        first_asset, preview_text,
        channel_name=proj_data.get('channel_profile', ''),
        script_snippet=proj_data.get('script', '')
    )

    proj_data['preview_text'] = preview_text
    proj_data['preview_highlight'] = hl_word
    proj_data['preview_colors'] = colors
    pm.save_project(new_id, proj_data)

    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Одобрить", callback_data=f"tr_approve_preview:{new_id}")
    kb.button(text="🔄 Ещё раз", callback_data=f"tr_regenerate_preview:{new_id}")
    kb.adjust(2)

    await callback.message.answer(
        f"🎬 **Новое превью:**\n\n`{preview_text}`\n\nПодходит?",
        reply_markup=kb.as_markup()
    )


@router.callback_query(F.data.startswith("goto_tts:"))
async def handle_goto_tts(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    new_id = callback.data.split(":")[1]
    await state.update_data(project_id=new_id)
    await ask_for_tts_engine(callback.message, state)
