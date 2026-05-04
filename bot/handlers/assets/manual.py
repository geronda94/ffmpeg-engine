"""Обработчики ручной загрузки файлов, выбора тайм-кода видео, подтверждения ассета."""
import logging
import os
import asyncio
import time
import re
import aiohttp

from aiogram import Router, types, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.states import ProjectStates
from core.project_manager import ProjectManager
from core.video_utils import get_video_info, generate_storyboard, extract_single_frame
from bot.navigation import register_trash, ask_for_asset

logger = logging.getLogger(__name__)
router = Router()
pm = ProjectManager()

URL_PATTERN = re.compile(r'https?://[^\s]+')


# ── Умный хендлер: файл отправлен прямо в меню выбора ──────────────────────
@router.message(ProjectStates.collecting_assets, F.photo | F.video | F.document | F.animation)
async def smart_direct_asset_input(message: types.Message, state: FSMContext):
    logger.info(f">>> smart_direct_asset_input triggered")
    await state.set_state(ProjectStates.waiting_for_asset)
    await handle_manual_asset(message, state)


# ── Кнопка «Загрузить своё» ─────────────────────────────────────────────────
@router.callback_query(F.data == "asset_manual", StateFilter(
    ProjectStates.collecting_assets, ProjectStates.approving_asset
))
async def manual_asset_choice(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    project_id = data.get('project_id')
    idx = data.get('current_scene_idx', 0)

    proj_data = pm.load_project(project_id)
    if not proj_data or idx >= len(proj_data.get('scenes', [])):
        await callback.message.answer("❌ Ошибка: данные сцены не найдены.")
        return

    scene = proj_data['scenes'][idx]
    est_dur = scene.get('estimated_duration', 'не определена')

    msg = (
        f"📎 **Загрузка для сцены {idx+1}**\n\n"
        f"🎬 **Что нужно:** {scene.get('visual_description', 'Нет описания')}\n\n"
        f"⏱ **Рекомендуемая длина:** ~{est_dur} сек\n"
        f"🎨 **Промпт (для ИИ):** `{scene.get('image_prompt', 'Нет промпта')}`\n\n"
        f"--- \nПришлите фото, видео или **прямую ссылку** на файл:"
    )
    try: await callback.message.delete()
    except: pass
    await callback.message.answer(msg, parse_mode="Markdown")
    await state.set_state(ProjectStates.waiting_for_asset)


# ── Кнопка «Загрузить свою сцену» ───────────────────────────────────────────
@router.callback_query(F.data == "asset_upload_scene", StateFilter(
    ProjectStates.collecting_assets,
    ProjectStates.approving_asset,
    ProjectStates.choosing_dynamic_preset
))
async def upload_own_scene(callback: types.CallbackQuery, state: FSMContext):
    """Загрузить готовый видеофайл как сцену (allow_montage_effects=False)."""
    await callback.answer()
    data = await state.get_data()
    idx = data.get('current_scene_idx', 0)
    proj_data = pm.load_project(data.get('project_id'))
    scene_desc = ""
    if proj_data:
        scenes = proj_data.get('scenes', [])
        if idx < len(scenes):
            scene_desc = f"\n\n🎬 **Что нужно:** {scenes[idx].get('visual_description', '')[:120]}"

    try: await callback.message.delete()
    except: pass

    await callback.message.answer(
        f"📤 **Загрузка сцены {idx + 1}**{scene_desc}\n\n"
        "Пришлите **.mp4** видеофайл. \n"
        "⚡ Сцена будет вставлена **как есть** — эффекты монтажа применяться не будут.",
        parse_mode="Markdown"
    )
    await state.update_data(next_asset_no_effects=True)
    await state.set_state(ProjectStates.waiting_for_asset)


# ── Основной обработчик медиафайла / ссылки ─────────────────────────────────
@router.message(ProjectStates.waiting_for_asset, F.photo | F.video | F.document | F.text | F.animation)
async def handle_manual_asset(message: types.Message, state: FSMContext):
    logger.info(f">>> handle_manual_asset triggered. Content type: {message.content_type}")
    try:
        data = await state.get_data()
        project_id = data.get('project_id')
        scene_idx = data.get('current_scene_idx', 0)

        proj_data = pm.load_project(project_id)
        if not proj_data:
            await message.answer("❌ Проект не найден.")
            return

        temp_path = None
        is_video = False

        async def download_with_retry(f_id, target_path, is_v=False):
            for attempt in range(3):
                try:
                    file = await message.bot.get_file(f_id)
                    await message.bot.download_file(file.file_path, target_path)
                    return True
                except Exception as e:
                    logger.warning(f"Download attempt {attempt+1} failed: {e}")
                    if attempt == 2: raise e
                    await asyncio.sleep(1 * (attempt + 1))
            return False

        if message.photo:
            file_id = message.photo[-1].file_id
            temp_path = f"temp/{file_id}.jpg"
            await download_with_retry(file_id, temp_path)
        elif message.video:
            file_id = message.video.file_id
            temp_path = f"temp/{file_id}.mp4"
            is_video = True
            await download_with_retry(file_id, temp_path, True)
        elif message.animation:
            file_id = message.animation.file_id
            temp_path = f"temp/{file_id}.mp4"
            is_video = True
            await download_with_retry(file_id, temp_path, True)
        elif message.document:
            file_id = message.document.file_id
            ext = os.path.splitext(message.document.file_name)[1].lower()
            temp_path = f"temp/{file_id}{ext}"
            is_video = ext in ['.mp4', '.mov', '.avi']
            await download_with_retry(file_id, temp_path, is_video)
        elif message.text and URL_PATTERN.search(message.text):
            url = URL_PATTERN.search(message.text).group()
            status = await message.answer("🌐 Качаю файл по ссылке...")
            try:
                timeout = aiohttp.ClientTimeout(total=30)
                headers = {"User-Agent": "Mozilla/5.0"}
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(url, headers=headers) as resp:
                        if resp.status == 200:
                            content_type = resp.headers.get("Content-Type", "").lower()
                            is_video = "video" in content_type
                            ext = ".mp4" if is_video else ".jpg"
                            temp_path = f"temp/url_{int(time.time())}{ext}"
                            os.makedirs("temp", exist_ok=True)
                            with open(temp_path, "wb") as f:
                                f.write(await resp.read())
                        else:
                            await message.answer(f"❌ Ошибка скачивания: код {resp.status}.")
                await status.delete()
            except asyncio.TimeoutError:
                await message.answer("❌ Сервер с файлом не отвечает (таймаут).")
                try: await status.delete()
                except: pass
                return
            except Exception as e:
                await message.answer(f"❌ Не удалось скачать по ссылке: {e}")
                try: await status.delete()
                except: pass
                return
        elif message.text:
            await message.answer("❌ Ожидается файл или прямая ссылка.")
            return

        if not temp_path or not os.path.exists(temp_path):
            await message.answer("❌ Не удалось сохранить файл. Попробуйте еще раз.")
            return

        # ВАЛИДАЦИЯ И САНИТАРИЗАЦИЯ
        try:
            if not is_video:
                from PIL import Image
                with Image.open(temp_path) as img:
                    img.verify()
                with Image.open(temp_path) as img:
                    rgb_img = img.convert('RGB')
                    rgb_img.save(temp_path, "JPEG", quality=95, optimize=True)
                logger.info(f"Manual image sanitized: {temp_path}")
            else:
                info = await asyncio.to_thread(get_video_info, temp_path)
                if not info or info.get('duration', 0) <= 0:
                    raise ValueError("Файл поврежден или имеет нулевую длительность")
                logger.info(f"Manual video validated: {temp_path}")
        except Exception as err:
            logger.error(f"Asset validation failed: {err}")
            if os.path.exists(temp_path): os.remove(temp_path)
            await message.answer(f"❌ Файл поврежден или имеет неверный формат: {err}")
            return

        if is_video:
            info = await asyncio.to_thread(get_video_info, temp_path)
            video_dur = info['duration'] if info else 0

            target_dur = 5.0
            scenes = proj_data.get('scenes', [])
            if scene_idx < len(scenes):
                scene = scenes[scene_idx]
                target_dur = scene.get('estimated_duration', 5.0)
                if 'end' in scene and 'start' in scene:
                    target_dur = scene['end'] - scene['start']

            if video_dur > 0 and video_dur <= target_dur + 0.5:
                no_fx = data.get('next_asset_no_effects', False)
                pm.update_asset(project_id, scene_idx, temp_path, offset=0, allow_montage_effects=(not no_fx))
                if os.path.exists(temp_path): os.remove(temp_path)
                if no_fx:
                    await state.update_data(next_asset_no_effects=False)

                proj_data = pm.load_project(project_id)
                new_path = proj_data['assets'][str(scene_idx)]['path']
                kb = InlineKeyboardBuilder()
                kb.button(text="✅ Подтвердить", callback_data="asset_confirm")
                kb.button(text="🔄 Другой", callback_data="asset_manual")
                kb.adjust(1)
                no_fx_note = " 🔕 Эффекты отключены" if no_fx else ""
                await message.answer_video(
                    types.FSInputFile(new_path),
                    caption=f"⚡ Видео короткое ({video_dur}с), выбрано целиком.{no_fx_note}\nПодтверждаем?",
                    reply_markup=kb.as_markup()
                )
                await state.set_state(ProjectStates.approving_asset)
                return

            await state.set_state(ProjectStates.selecting_video_offset)
            await show_video_storyboard(message, state, temp_path)
            return

        # Фото
        no_fx = data.get('next_asset_no_effects', False)
        pm.update_asset(project_id, scene_idx, temp_path, allow_montage_effects=(not no_fx))
        if os.path.exists(temp_path): os.remove(temp_path)
        if no_fx:
            await state.update_data(next_asset_no_effects=False)

        proj = pm.load_project(project_id)
        new_asset_path = proj['assets'][str(scene_idx)]['path']

        all_assets = data.get('assets', {})
        all_assets[str(scene_idx)] = {"path": new_asset_path, "type": "image"}
        await state.update_data(assets=all_assets)

        kb = InlineKeyboardBuilder()
        kb.button(text="✅ Подтвердить", callback_data="asset_confirm")
        kb.button(text="🔄 Другой", callback_data="asset_manual")
        kb.adjust(1)
        msg = await message.answer_photo(
            types.FSInputFile(new_asset_path),
            caption="Принято! Подтверждаем?",
            reply_markup=kb.as_markup()
        )
        await register_trash(msg, state)
        await state.set_state(ProjectStates.approving_asset)

    except Exception as e:
        logger.error(f"CRITICAL ERROR in handle_manual_asset: {e}", exc_info=True)
        await message.answer(f"❌ Ошибка обработки файла: {e}")


# ── Раскадровка видео ────────────────────────────────────────────────────────
async def show_video_storyboard(message: types.Message, state: FSMContext, video_path: str, page: int = 0):
    info = await asyncio.to_thread(get_video_info, video_path)
    duration = info['duration'] if info else 0
    total_min = int(duration // 60)
    total_sec = int(duration % 60)

    status = await message.answer(f"🎞 Генерирую раскадровку ({total_min:02d}:{total_sec:02d})...")

    interval = 5
    start_time = page * 9 * interval
    os.makedirs("temp/storyboards", exist_ok=True)
    out_path = f"temp/storyboards/sb_{int(time.time())}.jpg"

    sb_path = await asyncio.to_thread(generate_storyboard, video_path, out_path, start_time=start_time, interval=interval)

    if not sb_path:
        await status.edit_text("❌ Не удалось создать раскадровку.")
        return

    kb = InlineKeyboardBuilder()
    for i in range(9):
        t = start_time + (i * interval)
        if t >= duration: break
        time_str = f"{int(t // 60):02d}:{int(t % 60):02d}"
        kb.button(text=time_str, callback_data=f"voff_sel_{int(t)}")
    kb.adjust(3)

    nav_kb = InlineKeyboardBuilder()
    if page > 0:
        nav_kb.button(text="⬅️ Назад", callback_data=f"voff_pg_{page-1}")
    if (page + 1) * 9 * interval < duration:
        nav_kb.button(text="➡️ Вперед", callback_data=f"voff_pg_{page+1}")
    kb.attach(nav_kb)
    kb.adjust(3, 3, 3, 2)

    await status.delete()
    await message.answer_photo(
        types.FSInputFile(sb_path),
        caption=f"📺 **Выберите момент начала**\nВсего: {total_min:02d}:{total_sec:02d} | Стр. {page + 1}",
        reply_markup=kb.as_markup()
    )
    await state.update_data(temp_video_path=video_path)


@router.callback_query(F.data.startswith("voff_pg_"), StateFilter(ProjectStates.selecting_video_offset))
async def process_offset_pagination(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    page = int(callback.data.split("_")[-1])
    data = await state.get_data()
    video_path = data['temp_video_path']
    await callback.message.delete()
    await show_video_storyboard(callback.message, state, video_path, page)


@router.callback_query(F.data.startswith("voff_sel_"), StateFilter(ProjectStates.selecting_video_offset))
async def process_offset_selection(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    offset = float(callback.data.split("_")[-1])
    data = await state.get_data()
    project_id = data.get('project_id')
    scene_idx = data.get('current_scene_idx', 0)
    video_path = data.get('temp_video_path')

    if not project_id or not video_path:
        await callback.message.answer("❌ Ошибка данных сессии.")
        return

    no_fx = data.get('next_asset_no_effects', False)
    pm.update_asset(project_id, scene_idx, video_path, offset=offset, allow_montage_effects=(not no_fx))
    if no_fx:
        await state.update_data(next_asset_no_effects=False)

    preview_path = f"temp/preview_{int(time.time())}.jpg"
    await asyncio.to_thread(extract_single_frame, video_path, preview_path, offset)
    if os.path.exists(video_path): os.remove(video_path)

    proj = pm.load_project(project_id)
    new_asset_path = proj['assets'][str(scene_idx)]['path']

    all_assets = data.get('assets', {})
    all_assets[str(scene_idx)] = {"path": new_asset_path, "type": "video", "start_offset": offset}
    await state.update_data(assets=all_assets)

    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Подтвердить", callback_data="asset_confirm")
    kb.button(text="🔄 Другой", callback_data="asset_manual")
    kb.adjust(1)

    await callback.message.delete()
    no_fx_note = " 🔕 Эффекты отключены" if no_fx else ""
    if os.path.exists(preview_path):
        await callback.message.answer_photo(
            types.FSInputFile(preview_path),
            caption=f"✅ Момент: {int(offset // 60):02d}:{int(offset % 60):02d}{no_fx_note}\nПодтверждаем?",
            reply_markup=kb.as_markup()
        )
        os.remove(preview_path)
    else:
        await callback.message.answer(
            f"✅ Момент: {int(offset // 60):02d}:{int(offset % 60):02d}\nПодтверждаем?",
            reply_markup=kb.as_markup()
        )
    await state.set_state(ProjectStates.approving_asset)


# ── Подтверждение ассета ─────────────────────────────────────────────────────
@router.callback_query(F.data == "asset_confirm", ProjectStates.approving_asset)
async def confirm_asset(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    idx = data.get('current_scene_idx', 0)
    logger.info(f">>> confirm_asset triggered for scene_idx: {idx}")

    try:
        new_caption = f"✅ **Сцена {idx + 1} одобрена**"
        if callback.message.caption:
            await callback.message.edit_caption(caption=new_caption, reply_markup=None)
        else:
            await callback.message.edit_text(text=new_caption, reply_markup=None)
    except Exception as e:
        logger.warning(f"UI update failed in confirm_asset: {e}")

    await ask_for_asset(callback.message, state, idx + 1)
