import os
import asyncio
import logging
import json
from pathlib import Path
from ai.tts_edge import generate_tts
from ai.timing_agent import align_scenes_with_audio
from ai.montage_agent import run_montage

logger = logging.getLogger(__name__)

async def generate_project_audio(data: dict, tts_preset: dict) -> str:
    project_id = f"proj_{int(asyncio.get_event_loop().time())}"
    audio_path = f"local_assets/audio/{project_id}_voice.wav"
    os.makedirs("local_assets/audio", exist_ok=True)
    scenes_data = data.get('scenes', [])
    full_text = " ".join([s['text_segment'] for s in scenes_data])
    try:
        await generate_tts(full_text, audio_path, data['language'], voice=tts_preset.get('voice'), rate=tts_preset.get('rate', '+0%'), pitch=tts_preset.get('pitch', '+0Hz'))
        return audio_path
    except Exception as e:
        logger.error(f"TTS Error: {e}")
        return None

async def render_project_video(data: dict, audio_path: str, progress_callback=None) -> str:
    """Рендеринг v9.0: Поддержка прогресс-бара."""
    project_id = Path(audio_path).stem.replace("_voice", "")
    output_path = f"local_assets/outputs/{project_id}_final.mp4"
    os.makedirs("local_assets/outputs", exist_ok=True)

    scenes_data = data.get('scenes', [])
    scenes = await asyncio.to_thread(align_scenes_with_audio, [s.copy() for s in scenes_data], audio_path)
    
    with open("config/montage_presets.json", "r", encoding="utf-8") as f:
        m_config = json.load(f)
    
    style_id = data.get('visual_style', 'smooth_story')
    preset = next((s for s in m_config['styles'] if s['id'] == style_id), m_config['styles'][0])
    
    assets = data.get('assets', {})
    scenes_for_agent = []
    for i, scene in enumerate(scenes):
        asset_info = assets.get(str(i)) or assets.get(i)
        if not asset_info: continue
        scenes_for_agent.append({
            "asset_path": asset_info['path'],
            "start": scene['start'],
            "end": scene['end'],
            "text_segment": scene['text_segment']
        })

    if not scenes_for_agent: return None

    try:
        # Передаем callback в MontageAgent
        success = await asyncio.to_thread(run_montage, scenes_for_agent, audio_path, output_path, preset, progress_callback)
        return output_path if success else None
    except Exception as e:
        logger.error(f"Montage Agent Failure: {e}")
        return None
