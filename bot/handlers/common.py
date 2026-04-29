import json
import time
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.states import ProjectStates
from core.project_manager import ProjectManager

router = Router()
pm = ProjectManager()

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

@router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    
    project_id = f"p_{int(time.time())}_{message.from_user.id % 1000}"
    user_id = str(message.from_user.id)
    
    pm.create_project(project_id, user_id)
    await state.update_data(project_id=project_id, user_id=user_id)
    
    kb = InlineKeyboardBuilder()
    kb.button(text="🇷🇺 Русский", callback_data="lang_Russian")
    kb.button(text="🇺🇸 English", callback_data="lang_English")
    kb.button(text="🇷🇴 Română", callback_data="lang_Romanian")
    kb.button(text="🇬🇪 ქართული", callback_data="lang_Georgian")
    kb.adjust(2)
    await message.answer("👋 **Контент-Завод v9.5 (Persist Edition)**\n\nВыберите язык ролика:", reply_markup=kb.as_markup())
    await state.set_state(ProjectStates.choosing_language)

@router.callback_query(F.data.startswith("lang_"), ProjectStates.choosing_language)
async def choose_lang(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    lang = callback.data.split("_")[1]
    data = await state.get_data()
    proj = pm.load_project(data['project_id'])
    proj['language'] = lang
    pm.save_project(data['project_id'], proj)
    await state.update_data(language=lang)
    
    kb = InlineKeyboardBuilder()
    kb.button(text="📱 Вертикальное (9:16)", callback_data="format_vertical")
    kb.button(text="📺 Широкое (16:9)", callback_data="format_wide")
    await callback.message.edit_text("📐 Выберите формат видео:", reply_markup=kb.as_markup())
    await state.set_state(ProjectStates.choosing_format)

@router.callback_query(F.data.startswith("format_"), ProjectStates.choosing_format)
async def choose_format(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    fmt = callback.data.split("_")[1]
    data = await state.get_data()
    proj = pm.load_project(data['project_id'])
    proj['video_format'] = fmt
    pm.save_project(data['project_id'], proj)
    await state.update_data(video_format=fmt)
    
    presets = load_json("config/script_presets.json")
    kb = InlineKeyboardBuilder()
    for mode in presets['modes']:
        kb.button(text=mode['name'], callback_data=f"scrmode_{mode['id']}")
    kb.adjust(1)
    await callback.message.edit_text("🧠 Как будем готовить сценарий?", reply_markup=kb.as_markup())
    await state.set_state(ProjectStates.choosing_script_mode)

@router.callback_query(F.data.startswith("scrmode_"), ProjectStates.choosing_script_mode)
async def choose_script_mode(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    mode = callback.data.split("_")[1]
    await state.update_data(script_mode=mode)
    
    if mode == "manual":
        await callback.message.edit_text("✍️ Пришлите ваш готовый текст для видео:")
        await state.set_state(ProjectStates.writing_manual_script)
    else:
        presets = load_json("config/script_presets.json")
        kb = InlineKeyboardBuilder()
        for s in presets['styles']:
            kb.button(text=s['name'], callback_data=f"scrstyle_{s['id']}")
        kb.adjust(2)
        await callback.message.edit_text("🎭 Выберите стиль повествования:", reply_markup=kb.as_markup())
        await state.set_state(ProjectStates.choosing_script_style)

@router.callback_query(F.data.startswith("scrstyle_"), ProjectStates.choosing_script_style)
async def choose_script_style(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    style_id = callback.data.split("_")[1]
    await state.update_data(script_style=style_id)
    
    data = await state.get_data()
    if data['script_mode'] == "hybrid":
        await callback.message.edit_text("🤝 Пришлите основные тезисы:")
    else:
        await callback.message.edit_text("🤖 На какую тему написать сценарий?")
    await state.set_state(ProjectStates.writing_topic)
