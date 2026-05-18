import json
import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

LIBRARY_DIR = Path(__file__).resolve().parent.parent / "media_library"
INDEX_FILE = LIBRARY_DIR / "index.json"


class MediaLibrary:
    """Библиотека медиафайлов с поиском по тегам и сущностям."""

    def __init__(self, base_dir: str = None):
        self._dir = Path(base_dir) if base_dir else LIBRARY_DIR
        self._index = self._load_index()

    def _load_index(self) -> dict:
        if INDEX_FILE.exists():
            with open(INDEX_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _reload(self):
        self._index = self._load_index()

    def search(self, channel: str, query: str, limit: int = 10) -> list[dict]:
        """Поиск файлов по ключевым словам в тегах."""
        results = []
        channel_data = self._index.get(channel, {})
        query_lower = query.lower()
        query_words = set(query_lower.split())

        for category, items in channel_data.items():
            for entity_key, entity in items.items():
                tags = [t.lower() for t in entity.get("tags", [])]
                name = entity.get("name_ru", "").lower()
                name_en = entity.get("name_en", "").lower()
                all_text = " ".join(tags + [name, name_en])

                # Простой поиск: совпадение хотя бы 2 слов запроса
                matches = sum(1 for w in query_words if w in all_text)
                if matches >= 2 or any(q in all_text for q in query_words if len(q) > 5):
                    for f in entity.get("files", []):
                        file_path = self._dir / channel / f.get("file", "")
                        if file_path.exists():
                            results.append({
                                "entity": entity_key,
                                "name": entity.get("name_ru", ""),
                                "file": str(file_path),
                                "type": f.get("type", "image"),
                                "description": f.get("description", ""),
                                "match_score": matches,
                            })

        results.sort(key=lambda x: x.get("match_score", 0), reverse=True)
        return results[:limit]

    def search_by_entity(self, channel: str, entity_name: str) -> list[str]:
        """Поиск всех файлов конкретной сущности (святого, праздника, храма)."""
        channel_data = self._index.get(channel, {})
        name_lower = entity_name.lower()

        for category, items in channel_data.items():
            if entity_name in items:
                entity = items[entity_name]
                return [str(self._dir / channel / f.get("file", ""))
                        for f in entity.get("files", [])
                        if (self._dir / channel / f.get("file", "")).exists()]

            # Поиск по имени
            for key, entity in items.items():
                if name_lower in entity.get("name_ru", "").lower() or \
                   name_lower in entity.get("name_en", "").lower():
                    return [str(self._dir / channel / f.get("file", ""))
                            for f in entity.get("files", [])
                            if (self._dir / channel / f.get("file", "")).exists()]

        return []

    def get_all_entities(self, channel: str) -> list[dict]:
        """Возвращает список всех сущностей канала."""
        channel_data = self._index.get(channel, {})
        result = []
        for category, items in channel_data.items():
            for key, entity in items.items():
                result.append({
                    "key": key,
                    "category": category,
                    "name": entity.get("name_ru", ""),
                    "files_count": len(entity.get("files", [])),
                    "tags": entity.get("tags", []),
                })
        return result


# Синглтон
media_library = MediaLibrary()
