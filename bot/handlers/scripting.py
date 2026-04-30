import json
import asyncio
import logging
import os
from aiogram import Router, types, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.states import ProjectStates
from ai.script_writer import generate_script
from ai.storyboarder import generate_storyboard
from bot.navigation import ask_for_asset
from core.project_manager import ProjectManager

logger = logging.getLogger(__name__)
router = Router()
pm = ProjectManager()

# --- Вспомогательные функции ---

def split_text(text: str, max_length: int = 4000):
    """Дробит текст на части по лимиту Telegram."""
    return [text[i:i+max_length] for i in range(0, len(text), max_length)]

def get_script_style_prompt(style_id: str):
    try:
        with open("config/script_presets.json", "r", encoding="utf-8") as f:
            presets = json.load(f)
        for s in presets['styles']:
            if s['id'] == style_id: return s['prompt']
    except: pass
    return ""

async def refine_script_ai(old_script: str, user_wish: str, lang: str, style_prompt: str):
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("DEEPSEEK_API_KEY"), base_url="https://api.deepseek.com")
    prompt = (
        f"You are a script writer. Update this script based on user wish.\n"
        f"Original: {old_script}\nWish: {user_wish}\nStyle Context: {style_prompt}\n"
        f"Language: {lang}. Return ONLY JSON: {{\"title\": \"...\", \"script\": \"...\", \"target_duration\": 60}}"
    )
    res = client.chat.completions.create(model="deepseek-chat", messages=[{"role":"user", "content":prompt}], response_format={'type':'json_object'})
    return json.loads(res.choices[0].message.content)

async def refine_storyboard_ai(script: str, current_scenes: list, user_wish: str, lang: str):
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("DEEPSEEK_API_KEY"), base_url="https://api.deepseek.com")
    
    # Максимально строгий промпт
    prompt = (
        f"You are a Storyboard Agent. Based on the script and user instructions, create/update the storyboard.\n"
        f"SCRIPT: {script}\n"
        f"CURRENT SCENES: {json.dumps(current_scenes, ensure_ascii=False)}\n"
        f"USER WISH: {user_wish}\n"
        f"Language: {lang}.\n\n"
        f"CRITICAL INSTRUCTIONS:\n"
        f"1. You must distribute the WHOLE text of the script between scenes VERBATIM.\n"
        f"2. DO NOT CHANGE A SINGLE WORD in the 'text_segment' fields. Only split the script into parts.\n"
        f"3. Each scene must have these fields: 'text_segment', 'visual_description', 'image_prompt', 'ui_caption'.\n"
        f"4. If user says 'merge', combine the text segments of the selected scenes into one.\n"
        f"Return ONLY valid JSON in this format: {{\"scenes\": [{{...}}, {{...}}]}}"
    )
    
    res = client.chat.completions.create(
        model="deepseek-chat", 
        messages=[{"role":"user", "content":prompt}], 
        response_format={'type':'json_object'}
    )
    return json.loads(res.choices[0].message.content)

# --- Хендлеры Сценария ---

@router.message(ProjectStates.writing_topic)
async def handle_topic_v4(message: types.Message, state: FSMContext):
    data = await state.get_data()
    style_prompt = get_script_style_prompt(data.get('script_style', 'narrative'))
    status = await message.answer("✍️ Составляю сценарий...")
    prompt = f"Topic: {message.text}. {style_prompt}"
    
    project_id = data.get('project_id')
    proj = pm.load_project(project_id) if project_id else {}
    lang = proj.get('language') or data.get('language', 'Russian')
    
    script_data = await asyncio.to_thread(generate_script, prompt, lang)
    
    # ФИКС: Загружаем текущие данные проекта перед сохранением, чтобы не затереть остальное
    proj = pm.load_project(data['project_id'])
    proj['script'] = script_data['script']
    pm.save_project(data['project_id'], proj)
    
    await state.update_data(script_data=script_data)
    await status.delete()
    await show_script_approval(message, state)

@router.message(ProjectStates.writing_manual_script)
async def handle_manual_script(message: types.Message, state: FSMContext):
    data = await state.get_data()
    script_data = {"title": "Manual Script", "script": message.text, "target_duration": 60}
    
    proj = pm.load_project(data['project_id'])
    proj['script'] = message.text
    pm.save_project(data['project_id'], proj)
    
    await state.update_data(script_data=script_data)
    await show_script_approval(message, state)

@router.message(ProjectStates.approving_script)
async def handle_script_refinement(message: types.Message, state: FSMContext):
    data = await state.get_data()
    status = await message.answer("🔄 Обновляю сценарий...")
    try:
        project_id = data.get('project_id')
        proj = pm.load_project(project_id) if project_id else {}
        lang = proj.get('language') or data.get('language', 'Russian')
        
        new_data = await refine_script_ai(data['script_data']['script'], message.text, lang, "")
        
        # ФИКС: Сохраняем полный объект проекта
        proj = pm.load_project(data['project_id'])
        proj['script'] = new_data['script']
        pm.save_project(data['project_id'], proj)
        
        await state.update_data(script_data=new_data)
        await status.delete()
        await show_script_approval(message, state)
    except: await message.answer("⚠️ Ошибка.")

async def show_script_approval(message: types.Message, state: FSMContext):
    data = await state.get_data()
    project_id = data.get('project_id')
    proj = pm.load_project(project_id) if project_id else {}
    
    script_data = data.get('script_data', {})
    script = script_data.get('script') or proj.get('script', 'Сценарий пуст.')
    
    chunks = split_text(f"📜 **Ваш сценарий:**\n\n{script}")
    for i, chunk in enumerate(chunks):
        if i == len(chunks) - 1:
            kb = InlineKeyboardBuilder().button(text="✅ Одобрить текст", callback_data="approve_script")
            await message.answer(chunk + "\n\n--- \n✍️ Напишите правки или нажмите кнопку:", reply_markup=kb.as_markup())
        else:
            await message.answer(chunk)
    await state.set_state(ProjectStates.approving_script)

# --- Хендлеры Раскадровки ---

@router.callback_query(F.data == "approve_script", ProjectStates.approving_script)
async def approve_script_v2(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    kb = InlineKeyboardBuilder()
    kb.button(text="🤖 Авто-раскадровка", callback_data="stmode_auto")
    kb.button(text="💡 Свои идеи", callback_data="stmode_ideas")
    kb.adjust(1)
    
    project_id = data.get('project_id')
    if project_id:
        proj = pm.load_project(project_id)
        if proj:
            proj['status'] = "script_ready"
            pm.save_project(project_id, proj)
        
    await callback.message.answer("🎭 **Текст одобрен!**\n\nКак подготовим раскадровку?", reply_markup=kb.as_markup())
    await state.set_state(ProjectStates.choosing_storyboard_mode)

@router.callback_query(F.data.startswith("stmode_"), ProjectStates.choosing_storyboard_mode)
async def start_storyboard(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    mode = callback.data.split("_")[1]
    await state.update_data(storyboard_mode=mode)
    
    if mode == "ideas":
        await callback.message.answer("💡 Опишите ваши идеи для сцен:")
        await state.set_state(ProjectStates.refining_storyboard)
    else:
        status = await callback.message.answer("🤖 Генерирую раскадровку...")
        data = await state.get_data()
        project_id = data.get('project_id')
        
        # ФИКС: Берем данные из файла, если в стейте пусто
        proj_data = pm.load_project(project_id)
        if not proj_data:
            await status.edit_text("❌ Ошибка: Проект не найден на диске.")
            return
            
        script = proj_data.get('script') or data.get('script_data', {}).get('script')
        lang = proj_data.get('language') or data.get('language', 'Russian')
        
        if not script:
            await status.edit_text("❌ Ошибка: Сценарий пуст. Попробуйте сначала создать текст.")
            return

        try:
            res = await asyncio.to_thread(generate_storyboard, script, lang)
            new_scenes = res.get('scenes', [])
            
            if not new_scenes:
                await status.edit_text("❌ ИИ не смог сгенерировать сцены. Попробуйте еще раз с другим описанием.")
                return

            # ФИКС: Сохраняем сцены на диск ПЕРЕД показом, чтобы show_full_storyboard их увидел
            proj_data = pm.load_project(project_id)
            if proj_data:
                proj_data['scenes'] = new_scenes
                pm.save_project(project_id, proj_data)
            
            await state.update_data(scenes=new_scenes)
            await status.delete()
            await show_full_storyboard(callback.message, state)
        except Exception as e:
            logger.error(f"Storyboard Generation Error: {e}")
            await status.edit_text(f"⚠️ Ошибка при генерации раскадровки: {e}")

@router.message(ProjectStates.refining_storyboard)
async def handle_storyboard_refinement(message: types.Message, state: FSMContext):
    data = await state.get_data()
    project_id = data.get('project_id')
    
    # Загружаем актуальные данные с диска
    proj_data = pm.load_project(project_id)
    if not proj_data:
        await message.answer("❌ Проект не найден.")
        return
        
    script = proj_data.get('script') or data.get('script_data', {}).get('script')
    lang = proj_data.get('language') or data.get('language', 'Russian')
    scenes = proj_data.get('scenes') or data.get('scenes', [])

    status = await message.answer("🧠 Агент сцен анализирует...")
    try:
        res = await refine_storyboard_ai(script, scenes, message.text, lang)
        
        # ГИБКАЯ ПРОВЕРКА: ИИ может вернуть {"scenes": [...]} или просто [...]
        if isinstance(res, list):
            new_scenes = res
        elif isinstance(res, dict) and "scenes" in res:
            new_scenes = res["scenes"]
        else:
            # Если вернул что-то странное, пробуем найти список внутри
            new_scenes = next((v for v in res.values() if isinstance(v, list)), [])
            
        if not new_scenes:
            raise Exception("ИИ не вернул список сцен")

        # ФИКС: Сохраняем обновленные сцены на диск
        proj_data = pm.load_project(project_id)
        if proj_data:
            proj_data['scenes'] = new_scenes
            pm.save_project(project_id, proj_data)

        await state.update_data(scenes=new_scenes)
        await status.delete()
        await show_full_storyboard(message, state)
    except Exception as e:
        logger.error(f"Storyboard Refine Error: {e}")
        await message.answer(f"⚠️ Ошибка: {e}")

async def show_full_storyboard(message: types.Message, state: FSMContext):
    data = await state.get_data()
    project_id = data.get('project_id')
    
    proj_data = pm.load_project(project_id)
    scenes = proj_data.get('scenes') if proj_data else data.get('scenes', [])
    
    if not scenes:
        await message.answer("⚠️ Список сцен пуст. Попробуйте сгенерировать его снова.")
        return

    full_text = "📋 **Текущий план сцен:**\n\n"
    for i, s in enumerate(scenes):
        full_text += f"{i+1}. **{s.get('ui_caption', 'Сцена')}**\n"
        full_text += f"   🎬 Визуал: {s.get('visual_description', '')[:60]}...\n"
        full_text += f"   🎙 Текст: _{s['text_segment'][:50]}..._\n\n"
    
    chunks = split_text(full_text)
    for i, chunk in enumerate(chunks):
        if i == len(chunks) - 1:
            kb = InlineKeyboardBuilder().button(text="✅ Принять список", callback_data="st_accept_all")
            await message.answer(chunk + "--- \n✍️ Напишите правки или нажмите кнопку:", reply_markup=kb.as_markup())
        else:
            await message.answer(chunk)
            
    await state.set_state(ProjectStates.refining_storyboard)

@router.callback_query(F.data == "st_accept_all", ProjectStates.refining_storyboard)
async def accept_storyboard(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    project_id = data.get('project_id')
    if not project_id:
        await callback.message.answer("❌ Ошибка: Проект не найден.")
        return
        
    proj = pm.load_project(project_id)
    if not proj:
        await callback.message.answer("❌ Ошибка: Проект не найден на диске.")
        return
        
    proj['scenes'] = data.get('scenes') or proj.get('scenes', [])
    proj['status'] = "collecting_assets"
    pm.save_project(project_id, proj)
    await callback.message.answer("🚀 Список утвержден! Начинаем сбор материалов.")
    await ask_for_asset(callback.message, state, 0)
