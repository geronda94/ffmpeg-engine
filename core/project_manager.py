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
            "visual_style": "v_smooth_story",
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
        s1['text_segment'] = s1['text_segment'].strip() + " " + s2['text_segment'].strip()
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
        new_scene = scene.copy()
        new_scene['text_segment'] = t2
        data['scenes'].insert(idx + 1, new_scene)
        data['status'] = "needs_retiming"
        self.save_project(project_id, data)
        return True

    def update_asset(self, project_id: str, scene_idx: int, asset_path: str):
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
            "type": "video" if ext in ['.mp4', '.mov', '.avi'] else "image"
        }
        self.save_project(project_id, data)
        return True
