import os
import logging
import json
import asyncio
from ai.subtitle_agent import generate_ass_from_project, burn_subtitles
from ai.montage_agent import run_montage
from core.project_manager import ProjectManager
from core.config_loader import get_config
from ai.metadata_agent import generate_metadata

logger = logging.getLogger(__name__)
pm = ProjectManager()

def get_channel_profile(profile_id: str):
    """Загружает настройки канала из channel_context.json"""
    try:
        with open("config/channel_context.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            for profile in data.get("profiles", []):
                if profile["id"] == profile_id:
                    return profile
    except Exception as e:
        logger.error(f"Error loading channel profile: {e}")
    return {}

async def generate_project_audio(project_id: str, preset: dict):
    """Генерация аудио для проекта на основе выбранного пресета."""
    proj_data = pm.load_project(project_id)
    if not proj_data:
        return None
    
    script = proj_data.get('script', '')
    lang = proj_data.get('language', 'Russian')
    project_path = pm.get_project_path(project_id)
    
    audio_dir = project_path / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    
    engine = preset.get('engine', 'edge')
    # Возвращаем старое именование файлов, к которому привык пользователь
    output_path = str(audio_dir / f"voice_{lang}.wav")
    
    try:
        if engine == 'edge':
            from ai.tts_edge import generate_tts
            res = await generate_tts(
                text=script,
                output_path=output_path,
                lang=lang,
                voice=preset.get('voice'),
                rate=preset.get('rate', '+0%'),
                pitch=preset.get('pitch', '+0Hz')
            )
            return res
        elif engine == 'gemini':
            # Gemini требует JSON-задание
            task = {
                "text": script,
                "voice": preset.get("voice", "Alnilam"),
                "output": output_path,
                "prompt": preset.get("prompt", "Read naturally."),
                "model": preset.get("model", "gemini-1.5-flash-tts-preview")
            }
            task_path = audio_dir / "gemini_task.json"
            with open(task_path, "w", encoding="utf-8") as f:
                json.dump(task, f)
            
            from ai.tts_gemini import generate_tts_from_task
            await asyncio.to_thread(generate_tts_from_task, str(task_path))
            return output_path if os.path.exists(output_path) else None
            
    except Exception as e:
        logger.error(f"Error generating audio for {project_id}: {e}")
    return None

async def render_project_video(project_id: str, audio_path: str, render_threads: int = 4):
    """Универсальный рендер (v3.1). Пропускает монтаж, если видео уже на диске."""
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

    # БЫСТРЫЙ ПЕРЕРЕНДЕР: Если само видео уже есть, пропускаем монтаж и идем сразу к субтитрам
    if os.path.exists(output_path):
        logger.info(f"🚀 Video file already exists at {output_path}. Skipping montage phase and proceeding to subtitles.")
        return output_path

    # 2. ТАЙМИНГИ (Whisper)
    scenes_data = proj_data.get('scenes', [])
    has_timing = all('start' in s and 'end' in s for s in scenes_data)

    # Переводные проекты: всегда пересчитываем тайминги
    is_translated = bool(proj_data.get('parent_project_id'))
    if is_translated and has_timing:
        logger.warning("⚠️ Project is a translation — forcing Whisper re-timing.")
        has_timing = False
        for s in scenes_data:
            s.pop('start', None)
            s.pop('end', None)

    if is_translated:
        proj_data.pop('whisper_segments', None)

    if has_timing:
        logger.info("Timings found in JSON, skipping Whisper...")
    else:
        from ai.whisper_agent import WhisperAgent
        whisper = WhisperAgent()
        logger.info(f"Running Whisper on {audio_path} (word_timestamps=True)...")
        # Включаем пословные тайминги для идеального караоке
        # Обертываем в to_thread, чтобы не блокировать event loop
        segments = await asyncio.to_thread(whisper.transcribe, audio_path, word_timestamps=True)
        
        proj_data['whisper_segments'] = segments
        
        # Мапим сегменты на сцены через timing_agent
        from ai.timing_agent import align_scenes_with_audio
        logger.info(f"Aligning {len(scenes_data)} scenes with Whisper segments using LLM...")
        # Всегда используем LLM для стабильности по просьбе пользователя
        scenes_data = await align_scenes_with_audio(scenes_data, audio_path, whisper_segments=segments, use_llm_align=True)
        proj_data['scenes'] = scenes_data
        
        pm.save_project(project_id, proj_data)

    # 3. ПОДГОТОВКА СЦЕН ДЛЯ МОНТАЖА
    scenes_for_agent = []
    assets_map = proj_data.get('assets', {})
    
    for i, scene in enumerate(scenes_data):
        asset_info = assets_map.get(str(i), {})
        if not asset_info or 'path' not in asset_info:
            continue
            
        scenes_for_agent.append({
            "start": scene['start'],
            "end": scene['end'],
            "asset_path": asset_info['path'],
            "text_segment": scene['text_segment'],
            "start_offset": asset_info.get('start_offset', 0),
            "allow_montage_effects": asset_info.get('allow_montage_effects', True),
            "effects": scene.get('effects', []),
            "transition": scene.get('transition', {}),
            "mirror": proj_data.get('mirror_assets', False),
        })
        if i % 5 == 0:
            await asyncio.sleep(0)

    if scenes_for_agent and (proj_data.get('preview_text') or proj_data.get('preview_highlight')):
        proj_data['preview_text'] = proj_data.get('preview_text') or ''
        proj_data['preview_highlight'] = proj_data.get('preview_highlight', '')
        scenes_for_agent[0]['preview_text'] = proj_data['preview_text']
        scenes_for_agent[0]['preview_highlight'] = proj_data.get('preview_highlight', '')
        scenes_for_agent[0]['preview_colors'] = proj_data.get('preview_colors', {})
        
        channel_prof_id = proj_data.get('channel_profile')
        if channel_prof_id:
            prof = get_channel_profile(channel_prof_id)
            scenes_for_agent[0]['preview_logo'] = prof.get('logo_path')
            scenes_for_agent[0]['preview_bg_color'] = prof.get('preview_bg_color')
            scenes_for_agent[0]['preview_text_color'] = prof.get('preview_text_color', '#FFFFFF')
            scenes_for_agent[0]['preview_secondary_color'] = prof.get('preview_secondary_color')
            scenes_for_agent[0]['preview_font_path'] = prof.get('preview_font_path')
            
            s_style = prof.get('subtitle_style')
            proj_data['subtitle_style'] = s_style
            pm.save_project(project_id, proj_data)

    # 5. САУНД-ДИЗАЙН
    from ai.sound_design_agent import SoundDesignAgent
    sound_agent = SoundDesignAgent()
    sound_map = await sound_agent.generate_sound_map(project_id, scenes_for_agent)

    # 6. МОНТАЖ
    v_format = proj_data.get('video_format', 'vertical')
    all_styles = get_config("rendering_presets").get(v_format, [])
    style_id = proj_data.get('visual_style')
    
    # Ищем пресет по ID
    preset = next((s for s in all_styles if s['id'] == style_id), all_styles[0] if all_styles else {})
    
    video_meta = {
        "title": meta.get('title', slug),
        "language": proj_data.get('language', 'Russian'),
        "description": meta.get('description', '')
    }

    # Обертываем тяжелый монтаж (MoviePy) в отдельный поток, чтобы не блокировать бота
    success = await asyncio.to_thread(
        run_montage,
        scenes_for_agent, 
        audio_path, 
        output_path, 
        preset,
        sound_map=sound_map,
        render_threads=render_threads,
        video_metadata=video_meta
    )

    if success:
        proj_data['status'] = "completed"
        pm.save_project(project_id, proj_data)
        return output_path
    
    return None
