import json
import os
import time
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

STORAGE_DIR = Path(__file__).resolve().parent.parent / "projects" / "used_urls"
TTL_SECONDS = 4 * 24 * 3600  # 4 дня


class URLDeduplicator:
    """Хранилище использованных URL с авто-очисткой старых записей."""

    def __init__(self, storage_dir: str = None):
        self._dir = Path(storage_dir) if storage_dir else STORAGE_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, dict] = {}  # channel -> {url_hash: data}

    def _channel_key(self, channel: str, language: str = None) -> str:
        if language:
            return f"{channel}_{language.lower().strip()}"
        return channel

    def _channel_file(self, channel: str) -> Path:
        return self._dir / f"{channel}.json"

    def _load(self, channel: str) -> dict:
        if channel not in self._cache:
            fp = self._channel_file(channel)
            if fp.exists():
                try:
                    with open(fp, "r", encoding="utf-8") as f:
                        self._cache[channel] = json.load(f)
                except Exception:
                    self._cache[channel] = {}
            else:
                self._cache[channel] = {}
        return self._cache[channel]

    def _save(self, channel: str):
        fp = self._channel_file(channel)
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(self._cache.get(channel, {}), f, ensure_ascii=False)

    @staticmethod
    def _url_key(url: str) -> str:
        """Хеш URL для ключа словаря."""
        import hashlib
        return hashlib.md5(url.encode()).hexdigest()[:12]

    def is_used(self, url: str, channel: str, language: str = None) -> bool:
        """Проверяет, использовался ли URL в последние 4 дня."""
        if not url:
            return False
        channel_key = self._channel_key(channel, language)
        data = self._load(channel_key)
        key = self._url_key(url)
        entry = data.get(key)
        if not entry:
            return False
        age = time.time() - entry.get("used_at", 0)
        return age < TTL_SECONDS

    def mark_used(self, url: str, channel: str, scene_text: str = "", language: str = None):
        """Помечает URL как использованный."""
        if not url or not channel:
            return
        channel_key = self._channel_key(channel, language)
        data = self._load(channel_key)
        key = self._url_key(url)
        data[key] = {
            "url": url,
            "used_at": time.time(),
            "scene_text": scene_text[:200],
        }
        self._save(channel_key)

    def cleanup_old(self):
        """Удаляет записи старше TTL."""
        now = time.time()
        for channel_file in self._dir.glob("*.json"):
            channel = channel_file.stem
            data = self._load(channel)
            old_count = len(data)
            data = {k: v for k, v in data.items()
                    if now - v.get("used_at", 0) < TTL_SECONDS}
            if len(data) < old_count:
                self._cache[channel] = data
                self._save(channel)
                logger.info(f"URL dedup: cleaned {old_count - len(data)} old entries for {channel}")

    def filter_results(self, results: list, channel: str, language: str = None) -> list:
        """Фильтрует список результатов, убирая использованные URL."""
        return [r for r in results if not self.is_used(r.get("url", ""), channel, language)]

    def mark_project_assets(self, project_id: str, channel: str, project_manager=None, language: str = None):
        """Сохраняет URL всех ассетов проекта в хранилище."""
        if not project_manager:
            from core.project_manager import ProjectManager
            project_manager = ProjectManager()
        proj = project_manager.load_project(project_id)
        if not proj:
            return
        if not language:
            language = proj.get("language")
        assets = proj.get("assets", {})
        scenes = proj.get("scenes", [])
        for idx_str, ainfo in assets.items():
            url = ainfo.get("source_url")
            if url:
                idx = int(idx_str)
                scene_text = scenes[idx].get("text_segment", "") if idx < len(scenes) else ""
                self.mark_used(url, channel, scene_text, language)


# Синглтон
deduplicator = URLDeduplicator()
