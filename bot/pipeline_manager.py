import os
import asyncio
import logging
from pathlib import Path
from ai.tts_edge import generate_tts
from ai.timing_agent import align_scenes_with_audio
from ai.montage_agent import run_montage
from ai.metadata_agent import generate_metadata
from core.project_manager import ProjectManager
from core.config_loader import get_config, get_channel_profile

logger = logging.getLogger(__name__)
# Инициализируем менеджер один раз
pm = ProjectManager()

async def generate_project_audio(project_id: str, tts_preset: dict) -> str:
    """Генерация аудио с сохранением в структуру проекта (v3.0 Disk-First)."""
    proj_data = pm.load_project(project_id)
    if not proj_data:
        raise ValueError(f"Project {project_id} not found on disk")
        
    project_path = pm.get_project_path(project_id)
    audio_filename = f"voice_{proj_data.get('language', 'Russian')}.wav"
    audio_path = str(project_path / "audio" / audio_filename)

    scenes_data = proj_data.get('scenes', [])
    if not scenes_data:
        # Если сцен еще нет (например, скрипт только что написан), берем из скрипта
        full_text = proj_data.get('script', '')
    else:
        # Добавляем отчетливую паузу между сценами для естественного ритма
        full_text = ". ... ".join([s['text_segment'] for s in scenes_data])
    
    if not full_text:
        raise ValueError("Cannot generate audio: no script or scenes found")

    try:
        lang = proj_data.get('language', 'Russian')
        if 'voices' in tts_preset:
            tts_preset['voice'] = tts_preset['voices'].get(lang, tts_preset['voices'].get('English'))
        res = await generate_tts(full_text, audio_path, lang, 
                           voice=tts_preset.get('voice'), 
                           rate=tts_preset.get('rate', '+0%'), 
                           pitch=tts_preset.get('pitch', '+0Hz'))
        
        if not res:
            logger.error("TTS generation failed (returned None)")
            return None

        # Обновляем JSON проекта
        proj_data['current_audio_path'] = audio_path
        pm.save_project(project_id, proj_data)
        
        return audio_path
    except Exception as e:
        logger.error(f"TTS Error: {e}")
        return None

async def render_project_video(project_id: str, audio_path: str, progress_callback=None, render_threads: int = 4) -> str:
    """Универсальный рендер (v3.0 Disk-First). Источник правды — только project.json."""
    proj_data = pm.load_project(project_id)
    if not proj_data:
        logger.error(f"Render failed: Project {project_id} not found on disk")
        return None

    # 1. СЕО-МЕТАДАННЫЕ
    if 'metadata' not in proj_data:
        logger.info("Generating SEO metadata...")
        channel_ctx = get_channel_profile(proj_data.get('channel_profile'))
        meta = await generate_metadata(proj_data.get('script', ''), proj_data.get('language', 'Russian'), channel_ctx=channel_ctx)
        proj_data['metadata'] = meta
        pm.save_project(project_id, proj_data)
    else:
        meta = proj_data['metadata']

    # Имя файла на основе slug
    slug = meta.get('slug', project_id)
    output_path = str(pm.get_project_path(project_id) / f"{slug}.mp4")

    # 2. ТАЙМИНГИ (Whisper)
    scenes_data = proj_data.get('scenes', [])
    has_timing = all('start' in s and 'end' in s for s in scenes_data)

    # FIX #1: Если проект является переводом родительского — всегда пересчитываем тайминги через Whisper.
    # Новое аудио на другом языке имеет другую длительность — кешированные тайминги родителя бессмысленны.
    is_translated = bool(proj_data.get('parent_project_id'))
    if is_translated and has_timing:
        logger.warning("⚠️ Project is a translation — forcing Whisper re-timing (cached timings belong to parent language).")
        has_timing = False
        for s in scenes_data:
            s.pop('start', None)
            s.pop('end', None)

    # FIX #2: Для переводных проектов очищаем старые whisper_segments — они от другого языка
    # и полностью неприменимы для генерации субтитров нового видео.
    if is_translated:
        proj_data.pop('whisper_segments', None)

    if has_timing:
        logger.info("Timings found in JSON, skipping Whisper...")
        scenes = scenes_data
    else:
        logger.info(f"Timings missing or incomplete, running Whisper (lang={proj_data.get('language')})...")
        from ai.timing_agent import get_model
        model = get_model()

        # Whisper принимает ISO 639-1 коды ("ru"), а не полные названия ("Russian").
        # Передача полного названия заставляет Whisper игнорировать подсказку языка
        # и транскрибировать неверно, что ломает базу для выравнивания сцен.
        _LANG_TO_ISO = {
            "Russian": "ru", "English": "en", "Romanian": "ro",
            "Georgian": "ka", "Ukrainian": "uk", "Spanish": "es",
            "German": "de", "French": "fr", "Italian": "it",
            "Turkish": "tr", "Arabic": "ar", "Chinese": "zh",
            "Portuguese": "pt", "Polish": "pl", "Dutch": "nl",
        }
        lang_name = proj_data.get('language', 'Russian')
        lang_code = _LANG_TO_ISO.get(lang_name, lang_name.lower()[:2])
        logger.info(f"Whisper language hint: '{lang_name}' → ISO code '{lang_code}'")

        whisper_result = await asyncio.to_thread(
            model.transcribe, audio_path, language=lang_code, verbose=False
        )
        whisper_segments = whisper_result.get('segments', [])
        
        # Передаем уже полученные сегменты в агент выравнивания, чтобы не запускать Whisper второй раз
        from ai.timing_agent import align_scenes_with_audio
        scenes = await asyncio.to_thread(
            align_scenes_with_audio, 
            [s.copy() for s in scenes_data], 
            audio_path, 
            whisper_segments=whisper_segments,
            language=lang_code
        )
        
        # Сохраняем тайминги и Whisper-сегменты в проект (нужны для субтитров)
        proj_data['scenes'] = scenes
        proj_data['whisper_segments'] = [
            {'start': s['start'], 'end': s['end'], 'text': s['text']}
            for s in whisper_segments
        ]
        pm.save_project(project_id, proj_data)
    
    # 3. ПОДГРУЗКА ПРЕСЕТОВ МОНТАЖА
    m_config = get_config("rendering_presets")
    
    v_format = proj_data.get('video_format', 'vertical')
    style_id = proj_data.get('visual_style', 'v_no_effects')
    
    format_styles = m_config.get(v_format, m_config['vertical'])
    preset = next((s for s in format_styles if s['id'] == style_id), format_styles[0])
    
    w, h = (1920, 1080) if v_format == 'wide' else (1080, 1920)

    # 4. СМЕШАННЫЙ МОНТАЖ (MIXED AI)
    director_styles = ['v_mixed_ai', 'w_mixed_ai', 'v_orthodox', 'v_tech', 'v_feminine']
    if style_id in director_styles:
        logger.info(f"AI Director Style '{style_id}' detected. Planning montage...")
        from ai.montage_director_agent import montage_director

        montage_plan = await montage_director.plan_montage(
            proj_data.get('script', ''),
            scenes,
            proj_data.get('language', 'Russian'),
            channel_profile_id=proj_data.get('channel_profile'),
            pacing_mode=proj_data.get('scene_pacing', 'normal')
        )
        
        # Применяем план к сценам (в памяти для этого рендера)
        for i, scene in enumerate(scenes):
            if i < len(montage_plan):
                p = montage_plan[i]
                scene['effects'] = p.get('effects', [])
                scene['transition'] = p.get('transition', {})
                logger.info(f"🎬 Scene {i} montage plan: {p}")

    # 5. ПОДГОТОВКА СЦЕН (СТРОГАЯ ПРОВЕРКА)
    project_assets = proj_data.get('assets', {})
    scenes_for_agent = []
    logger.info(f"Preparing scenes for agent. Total assets found: {len(project_assets)}")

    # Проверка на аномально короткие тайминги (защита от сбоев Whisper)
    total_json_dur = scenes[-1].get('end', 0) if scenes else 0
    total_est_dur = sum(s.get('estimated_duration', 5.0) for s in scenes)
    
    use_fallback_timings = False
    if total_json_dur < 1.0 or total_json_dur < (total_est_dur * 0.3):
        logger.warning(f"⚠️ Detected anomaly in timings: JSON dur {total_json_dur}s vs EST dur {total_est_dur}s. Falling back to estimated durations.")
        use_fallback_timings = True

    current_time = 0.0
    for i, scene in enumerate(scenes):
        if use_fallback_timings:
            dur = scene.get('estimated_duration', 5.0)
            scene['start'] = current_time
            scene['end'] = current_time + dur
            current_time += dur

        # Гарантируем строковый ключ для поиска в JSON
        asset_info = project_assets.get(str(i))
        if not asset_info or not asset_info.get('path'):
            logger.warning(f"Scene {i} skipped: No asset registered in project.json")
            continue
            
        asset_path = asset_info['path']
        if not os.path.exists(asset_path):
            logger.error(f"Scene {i} asset file missing on disk: {asset_path}")
            continue

        logger.info(f"Adding Scene {i} to montage: {asset_path}")
        scenes_for_agent.append({
            "asset_path": asset_path,
            "start": scene['start'],
            "end": scene['end'],
            "text_segment": scene['text_segment'],
            "start_offset": asset_info.get('start_offset', 0),
            "allow_montage_effects": asset_info.get('allow_montage_effects', True),
            "effects": scene.get('effects', []),
            "transition": scene.get('transition', {})
        })

    if scenes_for_agent and proj_data.get('preview_text'):
        scenes_for_agent[0]['preview_text'] = proj_data['preview_text']
        scenes_for_agent[0]['preview_highlight'] = proj_data.get('preview_highlight', '')
        scenes_for_agent[0]['preview_colors'] = proj_data.get('preview_colors', {})

    logger.info(f"Total scenes for agent: {len(scenes_for_agent)}/{len(scenes)}")
    if not scenes_for_agent:
        logger.error("No scenes were added to agent! Rendering aborted.")
        return None

    # 5. САУНД-ДИЗАЙН (музыка + эффекты)
    from ai.sound_design_agent import SoundDesignAgent
    sound_agent = SoundDesignAgent()
    sound_map = await sound_agent.generate_sound_map(
        proj_data.get('script', ''), scenes,
        channel_profile=proj_data.get('channel_profile')
    )
    if sound_map:
        logger.info(f"Sound Map generated: {len(sound_map.get('sfx_placements', []))} effects added.")
    else:
        logger.warning("Sound Design Agent failed to generate sound map. Proceeding without SFX.")

    # 6. ФИНАЛЬНЫЙ МОНТАЖ
    try:
        success = await asyncio.to_thread(
            run_montage, scenes_for_agent, audio_path, output_path, preset, 
            progress_callback, sound_map, width=w, height=h, render_threads=render_threads
        )
        
        if success:
            proj_data['status'] = "completed"
            pm.save_project(project_id, proj_data)
            logger.info(f"PROJECT {project_id} RENDERED SUCCESSFULLY: {output_path}")
            return output_path
        return None
    except Exception as e:
        logger.error(f"Montage Agent Failure: {e}", exc_info=True)
        return None
