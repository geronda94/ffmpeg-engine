import logging
import asyncio
import os
import random
from datetime import datetime

from aiogram import types, Bot, Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.project_manager import ProjectManager
from core.config_loader import get_config
from core.task_manager import task_manager
from bot.pipeline_manager import generate_project_audio
from bot.states import ProjectStates
from ai.storyboarder import generate_storyboard
from ai.preview_agent import generate_preview_text
from ai.preview_designer_agent import design_preview_colors
from ai.localization_agent import translate_project_content
from bot.navigation import ask_for_asset

logger = logging.getLogger(__name__)
router = Router()
pm = ProjectManager()


def _get_preset_by_id(preset_id: str):
    presets = get_config("audio_presets")
    for engine in presets['tts_engines'].values():
        for p in engine['presets']:
            if p['id'] == preset_id:
                return p
    return None


def _lang_to_code(lang: str) -> str:
    m = {'Russian': 'ru', 'English': 'en', 'Romanian': 'ro', 'Georgian': 'ka'}
    return m.get(lang, lang.lower()[:2])


async def run_auto_pipeline(
    message: types.Message,
    channel_name: str,
    source_msg_id: int = None,
    state: FSMContext = None,
    script_text: str = None,
):
    try:
        topics_cfg = get_config("channel_topics", ttl=0)
        presets_cfg = get_config("auto_presets", ttl=0)

        channel_cfg = topics_cfg.get("channels", {}).get(channel_name)
        if not channel_cfg:
            raise ValueError(f"Channel '{channel_name}' not found")
        preset = presets_cfg.get("presets", {}).get(channel_name)
        if not preset:
            raise ValueError(f"Preset '{channel_name}' not found")

        script_text = script_text or message.text or message.caption or ""
        if not script_text.strip():
            await message.answer("❌ Пустой текст сценария.")
            return

        chat_id = message.chat.id

        # ── 1. Create project ──
        dt_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        project_id = f"proj_{dt_str}"
        pm.create_project(project_id, str(chat_id))
        proj = pm.load_project(project_id)
        proj['script'] = script_text
        proj['language'] = channel_cfg.get('language', 'Russian')
        proj['channel_profile'] = preset.get('channel_profile')
        proj['video_format'] = preset.get('video_format', 'vertical')
        proj['script_style'] = preset.get('script_style')
        proj['script_mode'] = 'auto'
        proj['burn_subtitles'] = preset.get('burn_subtitles', True)
        proj['status'] = 'auto_pipeline'
        proj['auto_pipeline'] = {
            'channel_name': channel_name,
            'preset': preset,
            'channel_cfg': channel_cfg,
            'source_msg_id': source_msg_id or message.message_id,
            'source_chat_id': chat_id,
        }
        pm.save_project(project_id, proj)

        status_msg = await message.answer(
            f"🤖 **Запущен полный автомат**\n"
            f"Канал: **{channel_name}** | Проект: `{project_id}`"
        )

        # ── 2. Storyboard ──
        await status_msg.edit_text(f"🤖 **{channel_name}** — `{project_id}`\n⏳ Раскадровка...")

        result = await asyncio.to_thread(
            generate_storyboard,
            script_text,
            proj['language'],
            preset.get('script_style', 'spiritual_direct'),
            preset.get('pacing', 'super_dynamic'),
        )
        scenes = result.get('scenes', [])
        if not scenes:
            raise ValueError("Storyboard returned no scenes")
        proj['scenes'] = scenes
        proj['status'] = 'collecting_assets'
        pm.save_project(project_id, proj)

        # ── 3. Auto-select assets ──
        await status_msg.edit_text(
            f"🤖 **{channel_name}** — `{project_id}`\n"
            f"⏳ Картинки: 0/{len(scenes)}"
        )

        from bot.handlers.assets.auto_select import _auto_pick_for_scene

        success = 0
        for idx, scene in enumerate(scenes):
            if str(idx) in proj.get("assets", {}):
                success += 1
                continue
            try:
                picked = await _auto_pick_for_scene(
                    scene, idx, preset.get('channel_profile'),
                    preset.get('script_style', ''), script_text,
                    status_msg, len(scenes), project_id,
                )
                if picked:
                    success += 1
            except Exception as e:
                logger.error(f"Auto-pick scene {idx} crashed: {e}", exc_info=True)

        proj = pm.load_project(project_id)
        missing = [i for i in range(len(scenes)) if str(i) not in proj.get("assets", {})]

        if missing:
            desc_lines = []
            for m in missing:
                sc = scenes[m]
                desc = sc.get('visual_description', sc.get('text_segment', ''))[:60]
                desc_lines.append(f"• #{m+1} — _{desc}_")
            missing_desc = '\n'.join(desc_lines)
            await status_msg.edit_text(
                f"⚠️ **{channel_name}** — `{project_id}`\n"
                f"Не собраны: {', '.join(str(m+1) for m in missing)}\n"
                f"Продолжи в ЛС."
            )
            kb = InlineKeyboardBuilder()
            kb.button(text="📝 Продолжить сбор", callback_data=f"continue_asset:{project_id}")
            try:
                await message.bot.send_message(
                    chat_id=message.from_user.id,
                    text=f"⚠️ **Не собраны сцены для канала {channel_name}**\n\n"
                         f"Проект: `{project_id}`\n\n"
                         f"{missing_desc}\n\n"
                         f"Нажми «Продолжить сбор» чтобы задать картинки вручную:",
                    reply_markup=kb.as_markup(),
                )
            except Exception:
                return
            return  # wait for user interaction

        await status_msg.edit_text(
            f"🤖 **{channel_name}** — `{project_id}`\n"
            f"✅ Картинки: {success}/{len(scenes)}\n⏳ Озвучка..."
        )

        # ── 4. TTS ──
        tts_preset_id = preset.get('tts_preset', 'edge_male_fast')
        ttd = _get_preset_by_id(tts_preset_id) or {}
        tts_config = {
            'engine': preset.get('tts_engine', 'edge'),
            'voice': (ttd.get('voices', {}).get(proj['language'])
                      or ttd.get('voice') or 'ru-RU-DmitryNeural'),
            'rate': ttd.get('rate', '+30%'),
            'pitch': ttd.get('pitch', '+0Hz'),
        }

        audio_path = await generate_project_audio(project_id, tts_config)
        if not audio_path or not os.path.exists(audio_path):
            await status_msg.edit_text(f"❌ **{channel_name}** — `{project_id}`\nОшибка озвучки.")
            return

        proj = pm.load_project(project_id)
        proj['current_audio_path'] = audio_path
        pm.save_project(project_id, proj)

        await status_msg.edit_text(
            f"🤖 **{channel_name}** — `{project_id}`\n✅ Озвучка\n⏳ Превью..."
        )

        # ── 5. Preview ──
        preview = await generate_preview_text(
            script_text, proj['language'],
            channel_profile=proj.get('channel_profile'),
            style_id=proj.get('script_style'),
        )
        first_asset = proj.get('assets', {}).get('0', {}).get('path', '')
        colors = await design_preview_colors(
            first_asset or '', preview.get('preview_text', ''),
            channel_name=proj.get('channel_profile', ''),
            script_snippet=script_text,
        )
        proj['preview_text'] = preview.get('preview_text', '')
        proj['preview_highlight'] = preview.get('highlight_word', '')
        proj['preview_colors'] = colors
        pm.save_project(project_id, proj)

        await status_msg.edit_text(
            f"🤖 **{channel_name}** — `{project_id}`\n✅ Превью\n⏳ Рендер..."
        )

        # ── 6. Queue render ──
        await task_manager.add_task(
            project_id=project_id,
            audio_path=audio_path,
            user_id=str(chat_id),
            callback_on_done=_make_auto_callback(channel_name),
            extra_data={
                'source_chat_id': chat_id,
                'source_msg_id': source_msg_id or message.message_id,
            },
        )

        await status_msg.edit_text(
            f"🤖 **{channel_name}** — `{project_id}`\n✅ **В очереди на рендер!**"
        )

    except Exception as e:
        logger.error(f"Auto pipeline error: {e}", exc_info=True)
        try:
            await message.answer(f"❌ Ошибка: {e}")
        except Exception:
            pass


def _make_auto_callback(channel_name: str):
    async def callback(task: dict):
        bot = task_manager.bot
        if not bot:
            logger.error("Callback: bot is None")
            return

        project_id = task['project_id']
        video_path = task.get('video_path')
        if task['status'] != "completed" or not video_path or not os.path.exists(video_path):
            logger.error(f"Auto render failed for {project_id}: {task['status']}")
            return

        proj = pm.load_project(project_id)
        if not proj:
            return

        proj['status'] = "completed"
        proj['video_result_path'] = video_path
        pm.save_project(project_id, proj)

        pipe = proj.get('auto_pipeline', {})
        channel_cfg = pipe.get('channel_cfg', {})
        preset = pipe.get('preset', {})
        source_chat_id = pipe.get('source_chat_id')
        source_msg_id = pipe.get('source_msg_id')

        chat_username = channel_cfg.get('chat_username', '@content_factory111111')
        try:
            chat = await bot.get_chat(chat_username)
            chat_id = chat.id
        except Exception:
            chat_id = source_chat_id

        output_topics = channel_cfg.get('output_topics', {})
        from aiogram.types import FSInputFile
        for lang_code, topic_id in output_topics.items():
            try:
                logger.info(f"Auto callback: sending {channel_name} RU video to topic {topic_id}")
                await bot.send_video(
                    chat_id=chat_id,
                    video=FSInputFile(video_path),
                    caption=f"✅ **{channel_name}** | {lang_code}",
                    parse_mode="Markdown",
                    message_thread_id=topic_id,
                    request_timeout=600,
                )
                logger.info(f"Auto callback: RU video sent to topic {topic_id}")
            except Exception as e:
                logger.error(f"Send to topic {topic_id}: {e}")

        # auto-translate
        for lang_name in channel_cfg.get('translate_to', []):
            if lang_name == proj.get('language'):
                continue
            try:
                await _run_translation_pipeline(
                    project_id, lang_name, chat_id, channel_cfg, preset, chat_username,
                )
            except Exception as e:
                logger.error(f"Translate to {lang_name} failed: {e}")

        # heart
        if source_chat_id and source_msg_id:
            try:
                await bot.set_message_reaction(
                    chat_id=source_chat_id,
                    message_id=source_msg_id,
                    reaction=[types.ReactionTypeEmoji(emoji="❤")],
                )
            except Exception:
                pass

    return callback


async def _run_translation_pipeline(
    source_id: str, lang: str, chat_id: int,
    channel_cfg: dict, preset: dict, chat_username: str,
):
    src = pm.load_project(source_id)
    if not src:
        return

    new_id = await asyncio.to_thread(pm.clone_project, source_id, lang)
    if not new_id:
        return

    proj = pm.load_project(new_id)
    trans = await translate_project_content(
        src['script'], src['scenes'], src.get('metadata', {}), lang,
    )
    if not trans:
        return

    proj['script'] = trans['script']
    proj['scenes'] = trans['scenes']
    proj['metadata'] = trans['metadata']
    proj['language'] = lang
    proj['status'] = 'auto_pipeline'
    proj['auto_pipeline'] = src.get('auto_pipeline', {})
    pm.save_project(new_id, proj)
    pm.recalc_scene_durations(new_id)
    proj = pm.load_project(new_id)

    preview = await generate_preview_text(
        proj['script'], lang,
        channel_profile=proj.get('channel_profile'),
        style_id=proj.get('script_style'),
    )
    proj['preview_text'] = preview.get('preview_text', '')
    proj['preview_highlight'] = preview.get('highlight_word', '')
    first = proj.get('assets', {}).get('0', {}).get('path', '')
    colors = await design_preview_colors(
        first or '', proj['preview_text'],
        channel_name=proj.get('channel_profile', ''),
        script_snippet=proj['script'],
    )
    proj['preview_colors'] = colors

    ttd = _get_preset_by_id(preset.get('tts_preset', 'edge_male_fast')) or {}
    tts_cfg = {
        'engine': preset.get('tts_engine', 'edge'),
        'voice': (ttd.get('voices', {}).get(lang) or ttd.get('voice') or 'ru-RU-DmitryNeural'),
        'rate': ttd.get('rate', '+30%'),
        'pitch': ttd.get('pitch', '+0Hz'),
    }
    pm.save_project(new_id, proj)

    audio_path = await generate_project_audio(new_id, tts_cfg)
    if not audio_path:
        return

    topic_id = channel_cfg.get('output_topics', {}).get(_lang_to_code(lang))

    async def _cb(task):
        bot = task_manager.bot
        if not bot or task['status'] != "completed":
            return
        vp = task.get('video_path')
        if not vp:
            return
        try:
            chat = await bot.get_chat(chat_username)
            cid = chat.id
        except Exception:
            cid = chat_id
        try:
            from aiogram.types import FSInputFile
            await bot.send_video(
                chat_id=cid,
                video=FSInputFile(vp),
                caption=f"✅ **{proj.get('channel_profile', '')}** | {lang}",
                parse_mode="Markdown",
                message_thread_id=topic_id,
                request_timeout=600,
            )
        except Exception as e:
            logger.error(f"Translate send to topic {topic_id}: {e}")

    await task_manager.add_task(
        project_id=new_id,
        audio_path=audio_path,
        user_id=str(chat_id),
        callback_on_done=_cb,
    )


async def resume_auto_after_assets(
    message: types.Message,
    state: FSMContext,
    project_id: str,
):
    """Called when all assets collected for auto-pipeline project.
    Continues automatically: TTS → preview → render → callback."""
    try:
        proj = pm.load_project(project_id)
        if not proj:
            await message.answer("❌ Проект не найден.")
            return

        pipe = proj.get('auto_pipeline', {})
        preset = pipe.get('preset', {})
        channel_cfg = pipe.get('channel_cfg', {})
        channel_name = pipe.get('channel_name', '')
        script_text = proj.get('script', '')
        chat_id = pipe.get('source_chat_id') or proj.get('user_id')

        status_msg = await message.answer(
            f"🤖 **{channel_name}** — `{project_id}`\n"
            f"✅ Все сцены собраны\n⏳ Озвучка..."
        )

        # ── TTS ──
        current_audio = proj.get('current_audio_path')
        if current_audio and os.path.exists(current_audio):
            audio_path = current_audio
        else:
            ttd = _get_preset_by_id(preset.get('tts_preset', 'edge_male_fast')) or {}
            tts_config = {
                'engine': preset.get('tts_engine', 'edge'),
                'voice': (ttd.get('voices', {}).get(proj['language'])
                          or ttd.get('voice') or 'ru-RU-DmitryNeural'),
                'rate': ttd.get('rate', '+30%'),
                'pitch': ttd.get('pitch', '+0Hz'),
            }
            audio_path = await generate_project_audio(project_id, tts_config)
            if not audio_path or not os.path.exists(audio_path):
                await status_msg.edit_text(f"❌ **{channel_name}** — `{project_id}`\nОшибка озвучки.")
                return
            proj = pm.load_project(project_id)
            proj['current_audio_path'] = audio_path
            pm.save_project(project_id, proj)

        await status_msg.edit_text(
            f"🤖 **{channel_name}** — `{project_id}`\n"
            f"✅ Озвучка\n⏳ Превью..."
        )

        # ── Preview ──
        if not proj.get('preview_text'):
            preview = await generate_preview_text(
                script_text, proj['language'],
                channel_profile=proj.get('channel_profile'),
                style_id=proj.get('script_style'),
            )
            first_asset = proj.get('assets', {}).get('0', {}).get('path', '')
            colors = await design_preview_colors(
                first_asset or '', preview.get('preview_text', ''),
                channel_name=proj.get('channel_profile', ''),
                script_snippet=script_text,
            )
            proj['preview_text'] = preview.get('preview_text', '')
            proj['preview_highlight'] = preview.get('highlight_word', '')
            proj['preview_colors'] = colors
            pm.save_project(project_id, proj)

        await status_msg.edit_text(
            f"🤖 **{channel_name}** — `{project_id}`\n"
            f"✅ Превью\n⏳ Рендер..."
        )

        # ── Render ──
        await task_manager.add_task(
            project_id=project_id,
            audio_path=audio_path,
            user_id=str(chat_id),
            callback_on_done=_make_auto_callback(channel_name),
        )

        await status_msg.edit_text(
            f"🤖 **{channel_name}** — `{project_id}`\n"
            f"✅ **В очереди на рендер!**"
        )

        await state.clear()

    except Exception as e:
        logger.error(f"resume_auto_after_assets error: {e}", exc_info=True)
        try:
            await message.answer(f"❌ Ошибка при завершении: {e}")
        except Exception:
            pass
