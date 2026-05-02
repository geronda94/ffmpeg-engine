import os
import json
import logging
import shutil
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

class ProjectManager:
    """
    Единый менеджер проектов. 
    Упрощенная структура v2: projects/{project_id}/
    """
    def __init__(self, base_path="projects"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(exist_ok=True)

    def get_project_path(self, project_id: str):
        return self.base_path / project_id

    def create_project(self, project_id: str, user_id: str = "default"):
        project_dir = self.get_project_path(project_id)
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "assets").mkdir(exist_ok=True)
        (project_dir / "audio").mkdir(exist_ok=True)
        
        config_path = project_dir / "project.json"
        # Если проект уже существует, не перезаписываем его
        if config_path.exists():
            return self.load_project(project_id)

        initial_data = {
            "project_id": project_id,
            "user_id": user_id,
            "created_at": datetime.now().isoformat(),
            "status": "created",
            "video_format": "vertical",
            "language": "Russian",
            "script": "",
            "scenes": [],
            "assets": {},
            "history": []
        }
        self.save_project(project_id, initial_data)
        return initial_data

    def load_project(self, project_id: str):
        path = self.get_project_path(project_id) / "project.json"
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def clone_project(self, source_id: str, target_lang: str) -> str:
        """Создает копию проекта для перевода на другой язык."""
        import shutil
        import time
        
        source_path = self.get_project_path(source_id)
        if not source_path.exists():
            return None
            
        new_id = f"{source_id}_{target_lang.lower()[:2]}_{int(time.time()) % 100}"
        new_path = self.get_project_path(new_id)
        
        # Копируем всю структуру проекта
        shutil.copytree(source_path, new_path)
        
        # Обновляем JSON в новом проекте
        proj_data = self.load_project(new_id)
        proj_data['project_id'] = new_id
        proj_data['language'] = target_lang
        proj_data['status'] = "cloned"
        proj_data['parent_project_id'] = source_id
        
        # Очищаем результаты предыдущего рендера
        proj_data.pop('current_audio_path', None)
        proj_data.pop('metadata', None)
        
        # Обновляем пути к ассетам в новом JSON
        assets = proj_data.get('assets', {})
        for a_idx, a_info in assets.items():
            if 'path' in a_info:
                # Путь остается внутри папки проекта, так как мы скопировали всё дерево
                # Но если путь был абсолютным или указывал на старый ID, надо поправить
                old_rel = f"projects/{source_id}/"
                new_rel = f"projects/{new_id}/"
                a_info['path'] = a_info['path'].replace(old_rel, new_rel)
                
        self.save_project(new_id, proj_data)
        return new_id

    def save_project(self, project_id: str, data: dict):
        path = self.get_project_path(project_id) / "project.json"
        data["updated_at"] = datetime.now().isoformat()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True

    def merge_scenes(self, project_id: str, idx1: int, idx2: int):
        data = self.load_project(project_id)
        if not data or idx1 >= len(data['scenes']) or idx2 >= len(data['scenes']):
            return False
        s1, s2 = data['scenes'][idx1], data['scenes'][idx2]
        new_text = s1['text_segment'].strip() + " " + s2['text_segment'].strip()
        s1['text_segment'] = new_text
        # Пересчет длительности
        s1['estimated_duration'] = max(2.5, round(len(new_text) / 13.0 + 0.5, 1))
        
        data['scenes'].pop(idx2)
        data['status'] = "needs_retiming"
        self.save_project(project_id, data)
        return True

    def split_scene(self, project_id: str, idx: int, split_point: int):
        data = self.load_project(project_id)
        if not data or idx >= len(data['scenes']):
            return False
        scene = data['scenes'][idx]
        text = scene['text_segment']
        t1, t2 = text[:split_point].strip(), text[split_point:].strip()
        
        scene['text_segment'] = t1
        scene['estimated_duration'] = max(2.5, round(len(t1) / 13.0 + 0.5, 1))
        
        new_scene = scene.copy()
        new_scene['text_segment'] = t2
        new_scene['estimated_duration'] = max(2.5, round(len(t2) / 13.0 + 0.5, 1))
        
        data['scenes'].insert(idx + 1, new_scene)
        data['status'] = "needs_retiming"
        self.save_project(project_id, data)
        return True

    def update_asset(self, project_id: str, scene_idx: int, asset_path: str, offset: float = 0):
        data = self.load_project(project_id)
        if not data:
            data = self.create_project(project_id)
            
        if 'assets' not in data: data['assets'] = {}
        
        dest_dir = self.get_project_path(project_id) / "assets"
        dest_dir.mkdir(parents=True, exist_ok=True)
        
        ext = os.path.splitext(asset_path)[1].lower()
        new_path = dest_dir / f"scene_{scene_idx}{ext}"
        
        shutil.copy(asset_path, new_path)
        data['assets'][str(scene_idx)] = {
            "path": str(new_path),
            "original_path": asset_path,
            "type": "video" if ext in ['.mp4', '.mov', '.avi'] else "image",
            "start_offset": offset
        }
        self.save_project(project_id, data)
        return True

    def add_protected_message(self, message_id: int):
        path = self.base_path / "protected_messages.json"
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = []
        if message_id not in data:
            data.append(message_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
            
    def get_protected_messages(self) -> set:
        path = self.base_path / "protected_messages.json"
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return set(data)
        except Exception:
            return set()
