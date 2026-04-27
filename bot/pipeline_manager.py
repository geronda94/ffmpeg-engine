import os
import json
import asyncio
import shutil
from pathlib import Path
from ai.deepseek_writer import generate_project
from ai.tts_edge import generate_tts_from_task as edge_tts_gen
from ai.tts_gemini import generate_tts_from_task as gemini_tts_gen
from ai.image_generator import generate_image
from main import assemble

async def run_full_pipeline_from_data(project_data: dict, template_type: str, tts_engine: str = "edge", image_urls: list = None, uploaded_photos: list = None, status_callback=None):
    project_id = f"project_{int(asyncio.get_event_loop().time())}"
    work_dir = Path(f"temp/{project_id}")
    work_dir.mkdir(parents=True, exist_ok=True)
    
    config = project_data.get("engine_config", {})
    if not isinstance(config, dict): config = {}
    
    # --- СТРОГАЯ ИНИЦИАЛИЗАЦИЯ (Используем черный фон как базу) ---
    config["output"] = {"fps": 30, "w": 1080, "h": 1920}
    config["resources"] = [
        {"id": "black_bg_res", "source": "color=c=black:s=1080x1920:r=30", "type": "lavfi"}
    ]
    # Базовый холст на 10 минут (FFmpeg обрежет по аудио или по -t)
    config["pipeline"] = [
        {"id": "canvas", "input": "black_bg_res", "trim": {"start": 0, "end": 600}}
    ]
    config["compose"] = {"base": "canvas", "layers": []}
    config["audio"] = []

    script = project_data.get("script", "")
    image_prompts = project_data.get("image_prompts", [])
    ui_texts = project_data.get("ui_texts", [])
    
    # 1. ОЗВУЧКА
    if status_callback: await status_callback("🎙 Озвучка...")
    audio_path = f"local_assets/audio/{project_id}_voice.wav"
    tts_task = {"text": script, "output": audio_path, "voice": "ru-RU-DmitryNeural" if tts_engine == "edge" else "Alnilam"}
    tts_task_path = work_dir / "tts_task.json"
    with open(tts_task_path, "w", encoding="utf-8") as f: json.dump(tts_task, f, ensure_ascii=False)
    
    try:
        if tts_engine == "gemini": await asyncio.to_thread(gemini_tts_gen, str(tts_task_path))
        else: await edge_tts_gen(str(tts_task_path))
    except Exception as tts_err: print(f"⚠️ Ошибка TTS: {tts_err}")

    config["resources"].append({"id": "voice_audio", "source": audio_path, "type": "audio"})
    config["audio"].append({"source": "voice_audio", "volume": 1.0})

    # 2. ФОРМИРОВАНИЕ СЦЕН (ПОСЛЕДОВАТЕЛЬНО)
    if status_callback: await status_callback("🖼 Сборка сцен...")
    
    num_scenes = max(1, len(image_prompts))
    # Если DeepSeek не дал тайминги титров, используем 60 сек как ориентир
    total_duration = ui_texts[-1]["end"] if ui_texts else 60.0
    duration_per_scene = total_duration / num_scenes
    
    for i, prompt in enumerate(image_prompts):
        res_id = f"scene_{i+1}"
        img_path = f"local_assets/images/{project_id}_{res_id}.png"
        
        # Ресурс
        config["resources"].append({"id": res_id, "source": img_path, "type": "image"})
        
        # Шаг пайплайна (с обрезкой по времени)
        step_id = f"step_{res_id}"
        start_t = i * duration_per_scene
        end_t = (i + 1) * duration_per_scene
        
        config["pipeline"].append({
            "id": step_id,
            "input": res_id,
            "trim": {"start": start_t, "end": end_t},
            "actions": [
                {"type": "scale", "w": 1080, "h": 1920}, # Масштабируем под вертикаль
                {"type": "fade", "duration": 0.5, "start_time": start_t} # Плавное появление
            ]
        })
        
        # Накладываем на черный холст
        config["compose"]["layers"].append({
            "source": step_id,
            "pos": {"x": "0", "y": "0"}
        })

    # 3. ПОДСТАНОВКА КАРТИНОК (ФОТО ИЛИ ИИ)
    image_tasks = []
    for i, prompt in enumerate(image_prompts):
        res_id = f"scene_{i+1}"
        # Ищем наш созданный ресурс
        res = next(r for r in config["resources"] if r["id"] == res_id)
        img_path = res["source"]
        
        if uploaded_photos:
            shutil.copy(uploaded_photos[i % len(uploaded_photos)], img_path)
        else:
            image_tasks.append(asyncio.to_thread(generate_image, prompt, img_path))
    
    if image_tasks: await asyncio.gather(*image_tasks)
    
    # 4. ТИТРЫ (ПОВЕРХ ВСЕХ СЦЕН)
    if ui_texts:
        plate_file = "local_assets/ui/plate_anthracite_noise.png"
        config["resources"].append({"id": "ui_plate_res", "source": plate_file, "type": "image"})
        
        ui_actions = []
        for item in ui_texts:
            ui_actions.append({
                "type": "drawtext",
                "text": item["text"],
                "start": item["start"],
                "end": item["end"],
                "fontsize": 48 if template_type == "vertical" else 32,
                "fontcolor": "white",
                "x": "(W-tw)/2",
                "y": "(H-th)/2"
            })
            
        config["pipeline"].append({
            "id": "ui_layer",
            "input": "ui_plate_res",
            "actions": ui_actions
        })
        
        config["compose"]["layers"].append({
            "source": "ui_layer",
            "pos": {"x": "(W-w)/2", "y": "1550" if template_type == "vertical" else "850"}
        })

    # 5. РЕНДЕР
    if status_callback: await status_callback("🎬 Финальный монтаж...")
    final_video_path = f"output/{project_id}_final.mp4"
    config["output"]["path"] = final_video_path
    
    # Указываем общую длительность по аудио/титрам
    config["output"]["duration"] = total_duration
    
    with open(work_dir / "final_config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    
    loop = asyncio.get_event_loop()
    render_future = loop.run_in_executor(None, assemble, config)
    while not render_future.done(): await asyncio.sleep(10)
    
    return final_video_path if await render_future else None
