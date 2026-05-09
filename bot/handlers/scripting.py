import json
import asyncio
import logging
from aiogram import Router, types, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.states import ProjectStates
from ai.script_writer import generate_script
from ai.storyboarder import generate_storyboard
from ai.script_reviewer import review_script
from ai.llm_client import chat_json
from bot.navigation import ask_for_asset
from core.project_manager import ProjectManager
from core.config_loader import get_config

logger = logging.getLogger(__name__)
router = Router()
pm = ProjectManager()


def split_text(text: str, max_length: int = 4000):
    return [text[i:i+max_length] for i in range(0, len(text), max_length)]


def get_style_id(state_data: dict) -> str:
    return state_data.get('script_style', 'narrative')


async def refine_script_ai(old_script: str, user_wish: str, lang: str, style_prompt: str):
    prompt = (
        f"You are a script writer. Update this script based on user wish.\n"
        f"Original: {old_script}\nWish: {user_wish}\nStyle Context: {style_prompt}\n"
        f"Language: {lang}. Return ONLY JSON: {{\"title\": \"...\", \"script\": \"...\", \"target_duration\": 60}}"
    )
    return chat_json(user_prompt=prompt)


async def refine_storyboard_ai(script: str, current_scenes: list, user_wish: str, lang: str):
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
        f"5. If user specifies a custom duration for a scene (e.g., 'scene 14 — 10 seconds'), "
        f"set 'custom_duration' field (float) on that scene. Adjust adjacent scenes to compensate.\n"
        f"6. If user says a scene is too short/long, adjust text_segment boundaries to fit desired timing.\n"
        f"Return ONLY valid JSON in this format: {{\"scenes\": [{{...}}, {{...}}]}}"
    )
    return chat_json(user_prompt=prompt)


async def _generate_storyboard_with_pacing(message: types.Message, state: FSMContext, pacing_mode: str):
    status = await message.answer("🤖 Генерирую раскадровку...")
    data = await state.get_data()
    project_id = data.get('project_id')

    proj_data = pm.load_project(project_id)
    if not proj_data:
        await status.edit_text("❌ Ошибка: Проект не найден на диске.")
        return

    script = proj_data.get('script') or data.get('script_data', {}).get('script')
    lang = proj_data.get('language') or data.get('language', 'Russian')
    style_id = proj_data.get('script_style') or get_style_id(data)

    if not script:
        await status.edit_text("❌ Ошибка: Сценарий пуст.")
        return

    try:
        proj_data['scene_pacing'] = pacing_mode
        pm.save_project(project_id, proj_data)

        res = await asyncio.to_thread(generate_storyboard, script, lang, style_id, pacing_mode)
        new_scenes = res.get('scenes', [])

        if not new_scenes:
            await status.edit_text("❌ ИИ не смог сгенерировать сцены. Попробуйте еще раз.")
            return

        proj_data = pm.load_project(project_id)
        if proj_data:
            proj_data['scenes'] = new_scenes
            pm.save_project(project_id, proj_data)

        await state.update_data(scenes=new_scenes)
        await status.delete()
        await show_full_storyboard(message, state)
    except Exception as e:
        logger.error(f"Storyboard Generation Error: {e}")
        await status.edit_text(f"⚠️ Ошибка при генерации раскадровки: {e}")


@router.message(ProjectStates.writing_topic)
async def handle_topic_v4(message: types.Message, state: FSMContext):
    data = await state.get_data()
    style_id = get_style_id(data)
    status = await message.answer("✍️ Составляю сценарий...")

    project_id = data.get('project_id')
    proj = pm.load_project(project_id) if project_id else {}
    lang = proj.get('language') or data.get('language', 'Russian')

    from core.config_loader import get_channel_profile
    channel_ctx = get_channel_profile(proj.get('channel_profile'))
    script_data = await asyncio.to_thread(generate_script, message.text, lang, 60, style_id, channel_ctx)

    review = await review_script(script_data['script'], style_id, lang)
    retries = 0
    while not review.get('pass') and retries < 2:
        retries += 1
        logger.warning(f"Script review failed ({review['total_score']}/20). Regenerating...")
        await status.edit_text(f"✍️ Улучшаю сценарий (попытка {retries+1})...")
        script_data = await asyncio.to_thread(
            generate_script, message.text, lang, 60, style_id, channel_ctx,
            feedback=review.get('suggestions', '')
        )
        review = await review_script(script_data['script'], style_id, lang)

    if review.get('pass'):
        logger.info(f"Script approved by reviewer ({review['total_score']}/20)")
    else:
        logger.warning(f"Script failed all review attempts. Using last version ({review['total_score']}/20)")

    proj = pm.load_project(data['project_id'])
    proj['script'] = script_data['script']
    proj['script_style'] = style_id
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

        proj = pm.load_project(data['project_id'])
        proj['script'] = new_data['script']
        pm.save_project(data['project_id'], proj)

        await state.update_data(script_data=new_data)
        await status.delete()
        await show_script_approval(message, state)
    except:
        await message.answer("⚠️ Ошибка.")


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


@router.callback_query(F.data == "approve_script", ProjectStates.approving_script)
async def approve_script_v2(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()

    project_id = data.get('project_id')
    if project_id:
        proj = pm.load_project(project_id)
        if proj:
            proj['status'] = "script_ready"
            pm.save_project(project_id, proj)

    presets = get_config("script_presets", ttl=0)
    pacing = presets.get("scene_pacing", {})
    kb = InlineKeyboardBuilder()
    for pid, pdata in pacing.items():
        kb.button(text=pdata["name"], callback_data=f"pace_{pid}")
    kb.button(text="💡 Свои идеи для сцен", callback_data="stmode_ideas")
    kb.adjust(1)

    await callback.message.answer(
        "🎭 **Текст одобрен!**\n\n"
        "Выберите темп сцен для раскадровки:",
        reply_markup=kb.as_markup()
    )
    await state.set_state(ProjectStates.choosing_scene_pacing)


@router.callback_query(F.data.startswith("pace_"), ProjectStates.choosing_scene_pacing)
async def handle_pacing_choice(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    pacing_mode = callback.data.split("_", 1)[1]
    await state.update_data(scene_pacing=pacing_mode)
    await _generate_storyboard_with_pacing(callback.message, state, pacing_mode)


@router.callback_query(F.data == "stmode_ideas", ProjectStates.choosing_scene_pacing)
async def handle_storyboard_ideas(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer("💡 Опишите ваши идеи для сцен (укажите желаемый темп, если важен):")
    await state.set_state(ProjectStates.refining_storyboard)


@router.message(ProjectStates.refining_storyboard)
async def handle_storyboard_refinement(message: types.Message, state: FSMContext):
    data = await state.get_data()
    project_id = data.get('project_id')

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

        if isinstance(res, list):
            new_scenes = res
        elif isinstance(res, dict) and "scenes" in res:
            new_scenes = res["scenes"]
        else:
            new_scenes = next((v for v in res.values() if isinstance(v, list)), [])

        if not new_scenes:
            raise Exception("ИИ не вернул список сцен")

        proj_data = pm.load_project(project_id)
        if proj_data:
            custom_durations = {}
            for s in new_scenes:
                if 'custom_duration' in s:
                    custom_durations[new_scenes.index(s)] = s.pop('custom_duration')

            proj_data['scenes'] = new_scenes
            pm.save_project(project_id, proj_data)

            if custom_durations:
                for idx, dur in custom_durations.items():
                    pm.redistribute_timings(project_id, scene_idx=idx, custom_duration=dur)

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

    pacing_name = proj_data.get('scene_pacing', 'normal') if proj_data else 'normal'

    full_text = f"📋 **Текущий план сцен** (темп: {pacing_name}):\n\n"
    for i, s in enumerate(scenes):
        dur = s.get('estimated_duration', '?')
        full_text += f"{i+1}. **{s.get('ui_caption', 'Сцена')}** [{dur}s]\n"
        full_text += f"   🎬 Визуал: {s.get('visual_description', '')[:60]}...\n"
        full_text += f"   🎙 Текст: _{s['text_segment'][:50]}..._\n\n"

    chunks = split_text(full_text)
    for i, chunk in enumerate(chunks):
        if i == len(chunks) - 1:
            kb = InlineKeyboardBuilder().button(text="✅ Принять список", callback_data="st_accept_all")
            await message.answer(chunk + "--- \n✍️ Напишите правки (напр. '14 сцена — 10 секунд') или нажмите кнопку:", reply_markup=kb.as_markup())
        else:
            await message.answer(chunk)

    await state.set_state(ProjectStates.refining_storyboard)


@router.callback_query(F.data == "st_accept_all", ProjectStates.refining_storyboard)
async def accept_storyboard(callback: types.CallbackQuery, state: FSMContext):
    try:
        await callback.answer()
    except Exception:
        pass
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
