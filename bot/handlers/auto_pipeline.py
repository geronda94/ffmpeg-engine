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

_last_edit_status_times = {}
_auto_pipeline_semaphore = asyncio.Semaphore(1)
_auto_pipeline_queue_count = 0

async def safe_edit_status(msg, text: str, force: bool = False):
    import time, asyncio
    from aiogram.exceptions import TelegramRetryAfter
    
    msg_key = f"{msg.chat.id}_{msg.message_id}"
    now = time.time()
    if not force and now - _last_edit_status_times.get(msg_key, 0) < 3.0:
        return

    _last_edit_status_times[msg_key] = now
    try:
        await msg.edit_text(text)
    except TelegramRetryAfter as e:
        logger.warning(f"Flood control in auto_pipeline! Waiting {e.retry_after}s...")
        await asyncio.sleep(e.retry_after + 1)
        try:
            await msg.edit_text(text)
        except Exception:
            pass
    except Exception as e:
        logger.warning(f"Safe edit status failed: {e}")

def _get_preset_by_id(preset_id: str):
    if not preset_id:
        return None
    presets = get_config("audio_presets")
    for engine in presets['tts_engines'].values():
        for p in engine['presets']:
            if p['id'] == preset_id:
                return p
    # Try prefix compatibility (e.g. 'male_fast' vs 'edge_male_fast')
    alt_id = f"edge_{preset_id}" if not preset_id.startswith("edge_") else preset_id.replace("edge_", "")
    for engine in presets['tts_engines'].values():
        for p in engine['presets']:
            if p['id'] == alt_id:
                return p
    return None


def _get_default_voice_by_lang(lang: str):
    lang_norm = lang.lower().strip()
    m = {
        "russian": "ru-RU-DmitryNeural",
        "ru": "ru-RU-DmitryNeural",
        "romanian": "ro-RO-EmilNeural",
        "ro": "ro-RO-EmilNeural",
        "english": "en-US-ChristopherNeural",
        "en": "en-US-ChristopherNeural",
    }
    return m.get(lang, lang.lower()[:2])


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
    global _auto_pipeline_queue_count
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
        if script_text.startswith("/"):
            import re
            script_text = re.sub(r"^/[a-zA-Z0-9_]+(@[a-zA-Z0-9_]+)?\s*", "", script_text)

        if not script_text.strip():
            await message.answer("❌ Пустой текст сценария.")
            return

        chat_id = message.chat.id

        # ── 1. Create project ──
        dt_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        project_id = f"proj_{dt_str}"
        pm.create_project(project_id, str(chat_id))
        proj = pm.load_project(project_id)

        # Парсим ссылки и медиа из сообщения
        from ai.media_parser import parse_incoming_media
        clean_text, preloaded = await parse_incoming_media(message, project_id)
        if clean_text.strip():
            script_text = clean_text
        proj['script'] = script_text
        proj['language'] = channel_cfg.get('language', 'Russian')
        proj['channel_profile'] = preset.get('channel_profile')
        proj['video_format'] = preset.get('video_format', 'vertical')
        proj['script_style'] = preset.get('script_style')
        proj['scene_pacing'] = preset.get('pacing', 'super_dynamic')
        proj['script_mode'] = 'auto'
        proj['burn_subtitles'] = preset.get('burn_subtitles', True)
        proj['preloaded_media'] = preloaded or []
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

        if _auto_pipeline_semaphore.locked():
            _auto_pipeline_queue_count += 1
            await safe_edit_status(status_msg, f"🤖 **{channel_name}** — `{project_id}`\n⏳ В очереди на генерацию контента (перед вами: {_auto_pipeline_queue_count})...", force=True)

        async with _auto_pipeline_semaphore:
            if _auto_pipeline_queue_count > 0:
                _auto_pipeline_queue_count -= 1

            # ── 2. Storyboard ──
            await safe_edit_status(status_msg, f"🤖 **{channel_name}** — `{project_id}`\n⏳ Раскадровка...", force=True)

            result = await asyncio.to_thread(
                generate_storyboard,
                script_text,
                proj['language'],
                preset.get('script_style', 'spiritual_direct'),
                preset.get('pacing', 'super_dynamic'),
                len(proj.get('preloaded_media', [])),
            )
            scenes = result.get('scenes', [])
            if not scenes:
                raise ValueError("Storyboard returned no scenes")
            proj['scenes'] = scenes
            proj['status'] = 'collecting_assets'
            pm.save_project(project_id, proj)

            # ── 3. Auto-select assets ──
            await safe_edit_status(status_msg,
                f"🤖 **{channel_name}** — `{project_id}`\n"
                f"⏳ Картинки: 0/{len(scenes)}",
                force=True
            )

            from bot.handlers.assets.auto_select import auto_pick_for_project

            try:
                success = await auto_pick_for_project(
                    scenes, preset.get('channel_profile'),
                    preset.get('script_style', ''), script_text,
                    status_msg, project_id
                )
            except Exception as e:
                logger.error(f"Auto-pick batch crashed: {e}", exc_info=True)
                success = len(proj.get("assets", {}))

            proj = pm.load_project(project_id)
            missing = [i for i in range(len(scenes)) if str(i) not in proj.get("assets", {})]

            if missing:
                desc_lines = []
                for m in missing:
                    sc = scenes[m]
                    desc = sc.get('visual_description', sc.get('text_segment', ''))[:60]
                    desc_lines.append(f"• #{m+1} — _{desc}_")
                missing_desc = '\n'.join(desc_lines)
                await safe_edit_status(status_msg,
                    f"⚠️ **{channel_name}** — `{project_id}`\n"
                    f"Не собраны: {', '.join(str(m+1) for m in missing)}\n"
                    f"Продолжи в ЛС.",
                    force=True
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

            await safe_edit_status(status_msg,
                f"🤖 **{channel_name}** — `{project_id}`\n"
                f"✅ Картинки: {success}/{len(scenes)}\n⏳ Озвучка...",
                force=True
            )

            # ── 4. TTS ──
            tts_preset_id = preset.get('tts_preset', 'edge_male_fast')
            ttd = _get_preset_by_id(tts_preset_id) or {}
            tts_config = {
                'engine': preset.get('tts_engine', 'edge'),
                'voice': (ttd.get('voices', {}).get(proj['language'])
                          or ttd.get('voice') or _get_default_voice_by_lang(proj['language'])),
                'rate': ttd.get('rate', '+30%'),
                'pitch': ttd.get('pitch', '+0Hz'),
            }

            audio_path = await generate_project_audio(project_id, tts_config)
            if not audio_path or not os.path.exists(audio_path):
                await safe_edit_status(status_msg, f"❌ **{channel_name}** — `{project_id}`\nОшибка озвучки.", force=True)
                return
            proj = pm.load_project(project_id)
            proj['current_audio_path'] = audio_path
            pm.save_project(project_id, proj)

            await safe_edit_status(status_msg,
                f"🤖 **{channel_name}** — `{project_id}`\n✅ Озвучка\n⏳ Превью...",
                force=True
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

            # ── 5.5 Metadata (Auto) ──
            if not proj.get('metadata'):
                try:
                    from ai.metadata_agent import generate_metadata
                    from core.config_loader import get_channel_profile
                    channel_ctx = get_channel_profile(proj.get('channel_profile'))
                    metadata = await generate_metadata(
                        script_text, proj['language'],
                        user_instruction="Viral, highly-engaging SEO optimization",
                        channel_ctx=channel_ctx
                    )
                    if metadata:
                        proj['metadata'] = metadata
                        pm.save_project(project_id, proj)
                except Exception as e:
                    logger.error(f"Auto pipeline SEO generation failed: {e}", exc_info=True)

            await safe_edit_status(status_msg,
                f"🤖 **{channel_name}** — `{project_id}`\n✅ Превью\n⏳ Рендер...",
                force=True
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

        await safe_edit_status(status_msg,
            f"🤖 **{channel_name}** — `{project_id}`\n✅ **В очереди на рендер!**",
            force=True
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
        
        # Проверяем размер файла — Telegram принимает до 50 МБ через Bot API
        file_size_mb = os.path.getsize(video_path) / (1024 * 1024)
        send_path = video_path
        compressed_path = None

        if file_size_mb > 49:
            logger.warning(f"Video too large ({file_size_mb:.1f} MB) for topic upload. Compressing before sending...")
            import subprocess as _sp
            compressed_path = video_path.replace(".mp4", "_compressed.mp4")

            # Проход 1: без даунскейла, CRF=28 — мягкое сжатие
            cmd_pass1 = [
                "ffmpeg", "-y", "-i", video_path,
                "-vcodec", "libx264", "-crf", "28",
                "-preset", "fast",
                "-acodec", "aac", "-b:a", "128k",
                compressed_path
            ]
            result = await asyncio.to_thread(_sp.run, cmd_pass1, capture_output=True)
            new_size = os.path.getsize(compressed_path) / (1024 * 1024) if (result.returncode == 0 and os.path.exists(compressed_path)) else 999

            # Проход 2: если всё ещё > 49MB — понижаем до 960px
            if new_size > 49:
                logger.warning(f"Pass 1 result {new_size:.1f}MB still too large, downscaling to 960px...")
                cmd_pass2 = [
                    "ffmpeg", "-y", "-i", video_path,
                    "-vcodec", "libx264", "-crf", "30",
                    "-preset", "fast",
                    "-vf", "scale=960:-2",
                    "-acodec", "aac", "-b:a", "128k",
                    compressed_path
                ]
                result = await asyncio.to_thread(_sp.run, cmd_pass2, capture_output=True)
                new_size = os.path.getsize(compressed_path) / (1024 * 1024) if (result.returncode == 0 and os.path.exists(compressed_path)) else 999

            if result.returncode == 0 and os.path.exists(compressed_path) and new_size < 999:
                logger.info(f"Compressed: {file_size_mb:.1f}MB → {new_size:.1f}MB")
                send_path = compressed_path
            else:
                logger.error("Compression failed, sending original (may fail)")

        # Format beautiful, clickable SEO caption
        from ai.metadata_agent import format_hashtags
        meta = proj.get('metadata', {})
        title = meta.get('title', 'Без названия')
        description = meta.get('description', '')
        hashtags = format_hashtags(meta.get('hashtags', []))

        proj_lang = proj.get('language', 'Russian')
        proj_lang_code = _lang_to_code(proj_lang)

        caption = (
            f"✅ **{channel_name}** | {proj_lang_code}\n\n"
            f"✨ **Заголовок (кликни, чтобы скопировать):**\n`{title}`\n\n"
            f"📝 **Описание:**\n`{description[:500]}`\n\n"
            f"🏷 **Теги:**\n`{hashtags}`"
        )
        if send_path != video_path:
            caption += f"\n\n⚠️ _Видео сжато для отправки ({os.path.getsize(send_path)/(1024*1024):.0f} МБ). Оригинал на сервере._"

        # Send only to the topic matching the project's actual language code
        for lang_code, topic_id in output_topics.items():
            if lang_code.lower() != proj_lang_code.lower():
                logger.info(f"Auto callback: skipping topic {topic_id} for lang {lang_code} (project language is {proj_lang} / {proj_lang_code})")
                continue

            try:
                logger.info(f"Auto callback: sending {channel_name} video to topic {topic_id} ({os.path.getsize(send_path)/(1024*1024):.1f} MB)")
                await bot.send_video(
                    chat_id=chat_id,
                    video=FSInputFile(send_path),
                    caption=caption[:1024],
                    parse_mode="Markdown",
                    message_thread_id=topic_id,
                    request_timeout=600,
                )
                logger.info(f"Auto callback: video sent to topic {topic_id}")
            except Exception as e:
                logger.error(f"Send to topic {topic_id}: {e}")

        # Удаляем сжатый файл после отправки
        if compressed_path and os.path.exists(compressed_path):
            try:
                os.remove(compressed_path)
            except Exception as e:
                logger.warning(f"Failed to delete compressed file: {e}")

        # auto-translate (only trigger from main project, which is Russian)
        if proj_lang_code.lower() == 'ru':
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

        # Сохраняем использованные URL в дедупликатор
        try:
            from core.url_deduplicator import deduplicator
            deduplicator.mark_project_assets(project_id, channel_name, language=proj.get("language"))
        except Exception as e:
            logger.warning(f"Deduplicator mark failed: {e}")

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

    # Фоновый авто-подбор ассетов для перевода (DuckDuckGo/SearXNG или preloaded_media)
    from bot.handlers.assets.auto_select import auto_pick_for_project
    try:
        logger.info(f"Translation pipeline: running asset selection for {new_id} ({lang})")
        await auto_pick_for_project(
            proj['scenes'], proj.get('channel_profile'),
            proj.get('script_style', ''), proj['script'],
            status_msg=None, project_id=new_id
        )
    except Exception as e:
        logger.error(f"Translation asset selection crashed for {new_id}: {e}", exc_info=True)

    # Заново загружаем проект с подобранными ассетами
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
        'voice': (ttd.get('voices', {}).get(lang) or ttd.get('voice') or _get_default_voice_by_lang(lang)),
        'rate': ttd.get('rate', '+30%'),
        'pitch': ttd.get('pitch', '+0Hz'),
    }
    pm.save_project(new_id, proj)

    audio_path = await generate_project_audio(new_id, tts_cfg)
    if not audio_path:
        return

    await task_manager.add_task(
        project_id=new_id,
        audio_path=audio_path,
        user_id=str(chat_id),
        callback_on_done=_make_auto_callback(src.get('auto_pipeline', {}).get('channel_name', '')),
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

        if not proj.get('scene_pacing'):
            proj['scene_pacing'] = preset.get('pacing', 'super_dynamic')
            pm.save_project(project_id, proj)

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
                          or ttd.get('voice') or _get_default_voice_by_lang(proj['language'])),
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

        # ── Metadata (Auto) ──
        if not proj.get('metadata'):
            try:
                from ai.metadata_agent import generate_metadata
                from core.config_loader import get_channel_profile
                channel_ctx = get_channel_profile(proj.get('channel_profile'))
                metadata = await generate_metadata(
                    script_text, proj['language'],
                    user_instruction="Viral, highly-engaging SEO optimization",
                    channel_ctx=channel_ctx
                )
                if metadata:
                    proj['metadata'] = metadata
                    pm.save_project(project_id, proj)
            except Exception as e:
                logger.error(f"Auto resume SEO generation failed: {e}", exc_info=True)

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


# ── Re-render Last Video Logic ─────────────────────────────────────

async def rebuild_last_project(event: types.CallbackQuery | types.Message):
    import json
    
    is_callback = isinstance(event, types.CallbackQuery)
    message = event.message if is_callback else event
    chat_id = message.chat.id
    
    # 1. Находим последний проект по дате создания
    base_path = pm.base_path
    if not base_path.exists():
        msg_text = "❌ Папка проектов не найдена."
        if is_callback:
            await event.answer(msg_text, show_alert=True)
        else:
            await event.answer(msg_text)
        return

    latest_id = None
    latest_proj = None
    latest_time = None

    for p_dir in base_path.iterdir():
        if p_dir.is_dir() and (p_dir / "project.json").exists():
            try:
                with open(p_dir / "project.json", "r", encoding="utf-8") as f:
                    data = json.load(f)
                created_at = data.get("created_at")
                if created_at:
                    dt = datetime.fromisoformat(created_at)
                    if latest_time is None or dt > latest_time:
                        latest_time = dt
                        latest_proj = data
                        latest_id = p_dir.name
            except Exception:
                continue

    if not latest_id or not latest_proj:
        msg_text = "❌ Ни одного проекта для перерендеринга не найдено."
        if is_callback:
            await event.answer(msg_text, show_alert=True)
        else:
            await event.answer(msg_text)
        return

    if is_callback:
        try:
            await event.answer("🔄 Запуск перерендера...")
        except Exception:
            pass
    
    status_msg = await message.answer(
        f"🔄 **Перерендеринг видео**\n"
        f"Проект: `{latest_id}` (язык: {latest_proj.get('language', 'RU')})\n"
        f"⏳ Сброс старых таймингов и очистка сцен..."
    )

    # 2. Очищаем тайминги сцен и субтитров
    for s in latest_proj.get('scenes', []):
        s.pop('start', None)
        s.pop('end', None)
        s.pop('words', None)
    latest_proj.pop('whisper_segments', None)
    latest_proj.pop('aligned_words', None)
    
    # 3. Удаляем сгенерированные видео-файлы (.mp4) и субтитры (.ass) в проекте,
    # чтобы заставить render_project_video выполнить монтаж MoviePy с чистого листа
    project_path = pm.get_project_path(latest_id)
    deleted_files = []
    for item in project_path.iterdir():
        if item.is_file() and item.suffix.lower() in ['.mp4', '.ass']:
            try:
                item.unlink()
                deleted_files.append(item.name)
            except Exception as e:
                logger.warning(f"Could not delete {item} in project {latest_id}: {e}")
                
    if deleted_files:
        logger.info(f"Deleted old media files for re-render of {latest_id}: {deleted_files}")

    # Сохраняем обновленный JSON без таймингов
    pm.save_project(latest_id, latest_proj)

    # 4. Проверяем или генерируем озвучку
    current_audio = latest_proj.get('current_audio_path')
    if current_audio and os.path.exists(current_audio):
        audio_path = current_audio
    else:
        await status_msg.edit_text(
            f"🔄 **Перерендеринг** — `{latest_id}`\n⏳ Генерация озвучки..."
        )
        pipe = latest_proj.get('auto_pipeline', {})
        preset = pipe.get('preset', {})
        tts_preset_id = preset.get('tts_preset', 'edge_male_fast')
        ttd = _get_preset_by_id(tts_preset_id) or {}
        tts_config = {
            'engine': preset.get('tts_engine', 'edge'),
            'voice': (ttd.get('voices', {}).get(latest_proj['language'])
                      or ttd.get('voice') or _get_default_voice_by_lang(latest_proj['language'])),
            'rate': ttd.get('rate', '+30%'),
            'pitch': ttd.get('pitch', '+0Hz'),
        }
        audio_path = await generate_project_audio(latest_id, tts_config)
        if not audio_path or not os.path.exists(audio_path):
            await status_msg.edit_text(f"❌ **{latest_id}** — Ошибка генерации озвучки.")
            return
        latest_proj = pm.load_project(latest_id)
        latest_proj['current_audio_path'] = audio_path
        pm.save_project(latest_id, latest_proj)

    await status_msg.edit_text(
        f"🔄 **Перерендеринг** — `{latest_id}`\n⏳ Отправка в очередь рендера..."
    )

    # 5. Выбираем callback доставки
    pipe = latest_proj.get('auto_pipeline', {})
    channel_name = pipe.get('channel_name')
    if channel_name:
        cb = _make_auto_callback(channel_name)
    else:
        # manual flow fallback
        from bot.handlers.production import send_video_result
        cb = send_video_result

    # 6. Очередь на рендеринг
    await task_manager.add_task(
        project_id=latest_id,
        audio_path=audio_path,
        user_id=str(chat_id),
        callback_on_done=cb,
        extra_data={
            'source_chat_id': chat_id,
            'source_msg_id': message.message_id,
        }
    )

    await status_msg.edit_text(
        f"✅ **Перерендер успешно запущен!**\n"
        f"Проект `{latest_id}` отправлен в очередь на полный пересчёт сцен, выравнивание субтитров и монтаж.\n"
        f"Вы получите готовый ролик в топике назначения по завершении."
    )


@router.callback_query(F.data == "rebuild_last_video")
async def callback_rebuild_last(callback: types.CallbackQuery, state: FSMContext = None):
    if state:
        await state.clear()
    await rebuild_last_project(callback)


@router.message(Command("rebuild_last"))
@router.message(Command("rebuild"))
async def cmd_rebuild_last(message: types.Message, state: FSMContext = None):
    if state:
        await state.clear()
    await rebuild_last_project(message)
