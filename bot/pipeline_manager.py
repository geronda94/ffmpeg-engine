import os
import asyncio
import logging
import json
from pathlib import Path
from ai.tts_edge import generate_tts
from ai.timing_agent import align_scenes_with_audio
from ai.montage_agent import run_montage
from ai.metadata_agent import generate_metadata
from core.project_manager import ProjectManager

logger = logging.getLogger(__name__)
# Инициализируем менеджер один раз
pm = ProjectManager()

async def generate_project_audio(data: dict, tts_preset: dict) -> str:
    """Генерация аудио с сохранением в структуру проекта."""
    project_id = data.get('project_id')
    if not project_id:
        raise ValueError("Project ID must be provided in data")
        
    project_path = pm.get_project_path(project_id)
    
    audio_filename = f"voice_{data.get('language', 'Russian')}.wav"
    audio_path = str(project_path / "audio" / audio_filename)

    scenes_data = data.get('scenes', [])
    full_text = " ".join([s['text_segment'] for s in scenes_data])
    
    try:
        await generate_tts(full_text, audio_path, data['language'], 
                           voice=tts_preset.get('voice'), 
                           rate=tts_preset.get('rate', '+0%'), 
                           pitch=tts_preset.get('pitch', '+0Hz'))
        
        # Обновляем JSON проекта
        proj_data = pm.load_project(project_id)
        proj_data['language'] = data['language']
        proj_data['current_audio_path'] = audio_path
        pm.save_project(project_id, proj_data)
        
        return audio_path
    except Exception as e:
        logger.error(f"TTS Error: {e}")
        return None

async def render_project_video(data: dict, audio_path: str, progress_callback=None) -> str:
    """Универсальный рендер: работает и для бота, и для внешних вызовов."""
    project_id = data.get('project_id', Path(audio_path).parent.parent.name)
    user_id = str(data.get('user_id', 'default'))
    
    proj_data = pm.load_project(project_id)
    if not proj_data:
        pm.create_project(project_id, user_id)
        proj_data = pm.load_project(project_id)

    # Генерируем SEO-метаданные, если их еще нет
    if 'metadata' not in proj_data:
        logger.info("Generating SEO metadata...")
        meta = await generate_metadata(proj_data.get('script', ''), proj_data.get('language', 'Russian'))
        proj_data['metadata'] = meta
        pm.save_project(project_id, proj_data)
    else:
        meta = proj_data['metadata']

    # Имя файла на основе slug
    slug = meta.get('slug', project_id)
    output_path = str(pm.get_project_path(project_id) / f"{slug}.mp4")

    # Синхронизация (Whisper)
    scenes_data = data.get('scenes', [])
    
    # Проверяем, есть ли уже тайминги во всех сценах
    has_timing = all('start' in s and 'end' in s for s in scenes_data)
    
    if has_timing:
        logger.info("Timings found in JSON, skipping Whisper...")
        scenes = scenes_data
    else:
        logger.info("Timings missing or incomplete, running Whisper...")
        scenes = await asyncio.to_thread(align_scenes_with_audio, [s.copy() for s in scenes_data], audio_path)
        # Сохраняем тайминги в проект
        proj_data['scenes'] = scenes
        pm.save_project(project_id, proj_data)
    
    # Подгрузка пресетов
    with open("config/montage_presets.json", "r", encoding="utf-8") as f:
        m_config = json.load(f)
    
    v_format = data.get('video_format', proj_data.get('video_format', 'vertical'))
    style_id = data.get('visual_style', proj_data.get('visual_style'))
    
    format_styles = m_config.get(v_format, m_config['vertical'])
    preset = next((s for s in format_styles if s['id'] == style_id), format_styles[0])
    
    w, h = (1920, 1080) if v_format == 'wide' else (1080, 1920)

    # Подготовка сцен для MontageAgent
    assets = data.get('assets', {})
    scenes_for_agent = []
    for i, scene in enumerate(scenes):
        asset_info = assets.get(str(i)) or assets.get(i)
        if not asset_info: continue
        
        # Автоматически копируем ассет в проект, если он еще не там
        asset_path = asset_info['path']
        if "projects" not in asset_path:
            pm.update_asset(project_id, i, asset_path)
            asset_path = pm.load_project(project_id)['assets'][str(i)]['path']

        scenes_for_agent.append({
            "asset_path": asset_path,
            "start": scene['start'],
            "end": scene['end'],
            "text_segment": scene['text_segment'],
            "start_offset": asset_info.get('start_offset', 0)
        })

    if not scenes_for_agent: return None

    try:
        success = await asyncio.to_thread(
            run_montage, scenes_for_agent, audio_path, output_path, preset, 
            progress_callback, None, width=w, height=h
        )
        
        if success:
            proj_data['status'] = "completed"
            pm.save_project(project_id, proj_data)
            return output_path
        return None
    except Exception as e:
        logger.error(f"Montage Agent Failure: {e}")
        return None
