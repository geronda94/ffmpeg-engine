import json
import os
import subprocess
import requests
from urllib.parse import urlparse

# Папка для временных файлов
TEMP_DIR = "temp_assets"
os.makedirs(TEMP_DIR, exist_ok=True)

def get_resource(source):
    """Скачивает файл, если это URL, или возвращает локальный путь."""
    parsed = urlparse(source)
    if parsed.scheme in ('http', 'https'):
        filename = os.path.basename(parsed.path)
        local_path = os.path.join(TEMP_DIR, filename)
        if not os.path.exists(local_path):
            print(f"Downloading {source}...")
            r = requests.get(source)
            with open(local_path, 'wb') as f:
                f.write(r.content)
        return local_path
    return source

def build_filter(action):
    """Превращает абстрактную команду из JSON в синтаксис FFmpeg."""
    if action['type'] == 'scale_and_crop':
        w, h = action['w'], action['h']
        return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
    if action['type'] == 'scale':
        return f"scale={action['w']}:{action['h']}"
    if action['type'] == 'blur':
        return f"boxblur={action['sigma']}"
    return ""

def main(config_path):
    with open(config_path, 'r') as f:
        conf = json.load(f)

    # 1. Готовим ресурсы и входы
    inputs = []
    resource_map = {} # id -> index
    for i, res in enumerate(conf['resources']):
        path = get_resource(res['source'])
        inputs.extend(['-i', path])
        resource_map[res['id']] = i

    # 2. Строим filter_complex
    filters = []
    
    # Обработка слоев (Pipeline)
    for step in conf['pipeline']:
        idx = resource_map[step['input']]
        actions = ",".join([build_filter(a) for a in step['actions']])
        filters.append(f"[{idx}:v]{actions}[{step['alias']}]")

    # Композиция (Склейка слоев)
    last_label = conf['compose'][0]['base']
    for i, comp in enumerate(conf['compose']):
        top_label = comp['top']
        # Если top это ресурс, а не слой из pipeline
        if top_label in resource_map:
            top_label = f"{resource_map[top_label]}:v"
            
        out_label = f"v{i}"
        
        pos = "x=(W-w)/2:y=(H-h)/2" # По умолчанию центр
        if comp['pos'] == 'bottom':
            pos = "x=(W-w)/2:y=H-h-100"

        filters.append(f"[{last_label}][{top_label}]overlay={pos}[{out_label}]")
        last_label = out_label

    # 3. Финальная сборка команды
    cmd = [
        'ffmpeg', '-y',
        '-hwaccel', 'qsv' # Твой i3-7gen
    ]
    cmd.extend(inputs)
    cmd.extend([
        '-filter_complex', ";".join(filters),
        '-map', f"[{last_label}]",
        '-map', f"{resource_map['voice']}:a", # Берем аудио по ID
        '-c:v', 'h264_qsv',
        '-shortest',
        conf['output']
    ])

    print("Running FFmpeg...")
    subprocess.run(cmd)

if __name__ == "__main__":
    main('task.json')