"""Обработчики генерации ИИ-изображений для ассетов проекта."""
import logging
import os
import asyncio
import time

from aiogram import Router, types, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.states import ProjectStates
from core.project_manager import ProjectManager
from ai.image_generator import generate_image

logger = logging.getLogger(__name__)
router = Router()
pm = ProjectManager()


@router.callback_query(F.data == "asset_ai", StateFilter(ProjectStates.collecting_assets, ProjectStates.approving_asset))
async def ai_asset_choice(callback: types.CallbackQuery, state: FSMContext):
    try:
        await callback.answer()
    except Exception:
        pass
    data = await state.get_data()
    project_id = data.get('project_id')
    idx = data.get('current_scene_idx', 0)

    proj_data = pm.load_project(project_id)
    if not proj_data:
        await callback.message.answer("❌ Проект не найден. Начните с /start")
        return

    scene = proj_data['scenes'][idx]
    status = await callback.message.answer(f"🎨 Генерирую ИИ-изображение для сцены {idx+1}...")

    try:
        prompt = scene.get('image_prompt', scene.get('visual_description', 'Video scene'))
        os.makedirs("temp", exist_ok=True)
        temp_path = f"temp/ai_{int(time.time())}_{idx}.png"

        success = await asyncio.to_thread(generate_image, prompt, temp_path)

        if success and os.path.exists(temp_path):
            pm.update_asset(project_id, idx, temp_path)
            if os.path.exists(temp_path): os.remove(temp_path)

            proj_data = pm.load_project(project_id)
            new_path = proj_data['assets'][str(idx)]['path']

            try:
                await status.delete()
            except Exception:
                pass
            kb = InlineKeyboardBuilder()
            kb.button(text="✅ Подтвердить", callback_data="asset_confirm")
            kb.button(text="🖼 Сгенерировать ИИ", callback_data="asset_ai")
            kb.button(text="🎬 Динамическая сцена", callback_data="asset_dynamic")
            kb.button(text="📁 Загрузить файл / Ссылка", callback_data="asset_manual")
            kb.adjust(1)

            await callback.message.answer_photo(
                types.FSInputFile(new_path),
                caption=f"✨ Готово! Подходит для сцены {idx+1}?",
                reply_markup=kb.as_markup()
            )
            await state.set_state(ProjectStates.approving_asset)
        else:
            raise Exception("Generation failed")
    except Exception as e:
        logger.error(f"AI Generation failed: {e}")
        try:
            await status.edit_text("⚠️ Ошибка генерации. Попробуйте загрузить своё.")
        except Exception:
            pass
