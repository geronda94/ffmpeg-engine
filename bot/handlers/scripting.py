import json
import asyncio
import logging
import os
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.states import ProjectStates
from ai.script_writer import generate_script
from ai.storyboarder import generate_storyboard
from bot.navigation import ask_for_asset

logger = logging.getLogger(__name__)
router = Router()

# Вспомогательные функции ИИ
def get_script_style_prompt(style_id: str):
    try:
        with open("config/script_presets.json", "r", encoding="utf-8") as f:
            presets = json.load(f)
        for s in presets['styles']:
            if s['id'] == style_id:
                return s['prompt']
    except: pass
    return ""

async def refine_script_ai(old_script: str, user_wish: str, lang: str, style_prompt: str):
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("DEEPSEEK_API_KEY"), base_url="https://api.deepseek.com")
    prompt = (
        f"You are a script writer. Update this script based on user wish.\n"
        f"Original: {old_script}\n"
        f"Wish: {user_wish}\n"
        f"Style Context: {style_prompt}\n"
        f"Language: {lang}. Return ONLY JSON: {{\"title\": \"...\", \"script\": \"...\", \"target_duration\": 60}}"
    )
    res = client.chat.completions.create(model="deepseek-chat", messages=[{"role":"user", "content":prompt}], response_format={'type':'json_object'})
    return json.loads(res.choices[0].message.content)

async def refine_scene_ai(current_desc: str, user_wish: str, lang: str):
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("DEEPSEEK_API_KEY"), base_url="https://api.deepseek.com")
    prompt = (
        f"Update this scene description.\n"
        f"Current: {current_desc}\n"
        f"Wish: {user_wish}\n"
        f"Language: {lang}. Return ONLY JSON: {{\"visual_description\": \"...\", \"image_prompt\": \"...\"}}"
    )
    res = client.chat.completions.create(model="deepseek-chat", messages=[{"role":"user", "content":prompt}], response_format={'type':'json_object'})
    return json.loads(res.choices[0].message.content)

# --- ХЕНДЛЕРЫ СЦЕНАРИЯ ---

@router.message(ProjectStates.writing_topic)
async def handle_topic_v4(message: types.Message, state: FSMContext):
    data = await state.get_data()
    mode = data.get('script_mode', 'auto')
    style_prompt = get_script_style_prompt(data.get('script_style', 'narrative'))
    status = await message.answer("✍️ Составляю сценарий...")
    
    if mode == "hybrid":
        prompt = f"Write a video script based on these facts: {message.text}. {style_prompt}"
    else:
        prompt = f"Topic: {message.text}. {style_prompt}"
        
    script_data = await asyncio.to_thread(generate_script, prompt, data['language'])
    await state.update_data(script_data=script_data)
    await status.delete()
    await show_script_approval(message, state)

@router.message(ProjectStates.writing_manual_script)
async def handle_manual_script(message: types.Message, state: FSMContext):
    script_data = {"title": "My Script", "script": message.text, "target_duration": 60}
    await state.update_data(script_data=script_data)
    await show_script_approval(message, state)

@router.message(ProjectStates.approving_script)
async def handle_script_refinement(message: types.Message, state: FSMContext):
    data = await state.get_data()
    style_prompt = get_script_style_prompt(data.get('script_style', 'narrative'))
    status = await message.answer("🔄 Обновляю сценарий...")
    try:
        new_data = await refine_script_ai(data['script_data']['script'], message.text, data['language'], style_prompt)
        await state.update_data(script_data=new_data)
    except: await message.answer("⚠️ Ошибка ИИ.")
    await status.delete()
    await show_script_approval(message, state)

@router.callback_query(F.data == "approve_script", ProjectStates.approving_script)
async def approve_script(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    data = await state.get_data()
    status = await callback.message.answer("🎨 Делаю раскадровку...")
    storyboard = await asyncio.to_thread(generate_storyboard, data['script_data']['script'], data['language'])
    await state.update_data(scenes=storyboard['scenes'], current_scene_idx=0, assets={})
    await status.delete()
    await show_scene_approval(callback.message, state)

# --- ХЕНДЛЕРЫ РАСКАДРОВКИ (СЦЕН) ---

@router.callback_query(F.data == "scene_ok", ProjectStates.approving_scenes)
async def scene_ok(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    data = await state.get_data()
    new_idx = data['current_scene_idx'] + 1
    await state.update_data(current_scene_idx=new_idx)
    await show_scene_approval(callback.message, state)

@router.callback_query(F.data == "scene_edit", ProjectStates.approving_scenes)
async def scene_edit_btn(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Опишите правки для этой сцены (текстом):")

@router.message(ProjectStates.approving_scenes)
async def handle_scene_refinement(message: types.Message, state: FSMContext):
    data = await state.get_data()
    idx = data['current_scene_idx']
    scenes = data['scenes']
    status = await message.answer("🔄 Перерисовываю сцену...")
    try:
        res = await refine_scene_ai(scenes[idx]['visual_description'], message.text, data['language'])
        scenes[idx].update(res)
        await state.update_data(scenes=scenes)
    except: await message.answer("⚠️ Ошибка ИИ.")
    await status.delete()
    await show_scene_approval(message, state)

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ОТОБРАЖЕНИЯ ---

async def show_script_approval(message: types.Message, state: FSMContext):
    data = await state.get_data()
    kb = InlineKeyboardBuilder().button(text="✅ Одобрить", callback_data="approve_script")
    await message.answer(f"📜 **Ваш сценарий:**\n\n{data['script_data']['script']}", reply_markup=kb.as_markup())
    await state.set_state(ProjectStates.approving_script)

async def show_scene_approval(message: types.Message, state: FSMContext):
    data = await state.get_data()
    idx = data['current_scene_idx']
    scenes = data['scenes']
    if idx >= len(scenes):
        await state.update_data(current_scene_idx=0)
        await ask_for_asset(message, state)
        return
    scene = scenes[idx]
    kb = InlineKeyboardBuilder().button(text="✅ Ок", callback_data="scene_ok").button(text="✏️ Править", callback_data="scene_edit")
    await message.answer(f"🖼 **Сцена {idx+1}/{len(scenes)}**\n\n{scene['visual_description']}", reply_markup=kb.as_markup())
    await state.set_state(ProjectStates.approving_scenes)
