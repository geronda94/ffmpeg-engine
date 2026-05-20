import json
import logging
import os
import random
from pathlib import Path

logger = logging.getLogger(__name__)

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "config" / "query_knowledge"


class QueryKnowledge:
    """Менеджер самообучаемой базы знаний запросов.
    Потокобезопасный, с атомарным сохранением."""

    def __init__(self, config_dir: str = None):
        self._dir = Path(config_dir) if config_dir else KNOWLEDGE_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._data: dict = {}
        self.load()

    def load(self):
        """Загружает все файлы из config/query_knowledge/*.json."""
        self._data = {}
        if not self._dir.exists():
            self._dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"QueryKnowledge directory created: {self._dir}")
            return
        loaded_channels = 0
        for fp in sorted(self._dir.glob("*.json")):
            channel = fp.stem  # orthodox, news, etc.
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    entities = json.load(f)
                self._data[channel] = entities
                loaded_channels += 1
            except Exception as e:
                logger.error(f"QueryKnowledge load error for {fp.name}: {e}")
        logger.info(f"QueryKnowledge loaded {loaded_channels} channels from {self._dir}")

    def save(self):
        """Сохраняет каждый канал в отдельный файл config/query_knowledge/{channel}.json."""
        self._dir.mkdir(parents=True, exist_ok=True)
        for channel, entities in self._data.items():
            fp = self._dir / f"{channel}.json"
            try:
                with open(fp, "w", encoding="utf-8") as f:
                    json.dump(entities, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"QueryKnowledge save error for {channel}: {e}")

    # ── Поиск ───────────────────────────────────────────────────────────

    def match_entity(self, text: str, channel: str = "orthodox") -> dict | None:
        """Ищет сущность по алиасам (слово/граница, не подстрока). Возвращает entity dict или None."""
        text_lower = text.lower()
        for entity_key, entity in self._data.get(channel, {}).items():
            for alias in entity.get("aliases", []):
                import re
                if re.search(r'\b' + re.escape(alias) + r'\b', text_lower):
                    return {
                        "key": entity_key,
                        "aliases": entity.get("aliases", []),
                        "queries": entity.get("queries", []),
                        "source": entity.get("source", "stock"),
                        "color": entity.get("color"),
                        "filters": entity.get("filters", {}),
                    }
        return None

    def match_all_entities(self, text: str, channel: str = "orthodox") -> list[dict]:
        """Находит ВСЕ сущности в тексте."""
        text_lower = text.lower()
        results = []
        for entity_key, entity in self._data.get(channel, {}).items():
            for alias in entity.get("aliases", []):
                if alias in text_lower:
                    results.append({
                        "key": entity_key,
                        "aliases": entity.get("aliases", []),
                        "queries": entity.get("queries", []),
                        "source": entity.get("source", "stock"),
                        "color": entity.get("color"),
                        "filters": entity.get("filters", {}),
                    })
                    break
        return results

    def detect_entity_keys(self, text: str, channel: str) -> list[str]:
        """Только ключи найденных сущностей."""
        return [e["key"] for e in self.match_all_entities(text, channel)]

    # ── Создание сущности ───────────────────────────────────────────────

    def create_entity(self, channel: str, entity_key: str, data: dict):
        """Создаёт новую сущность. Если существует — дополняет алиасы и запросы."""
        if channel not in self._data:
            self._data[channel] = {}

        existing = self._data[channel].get(entity_key, {})
        if existing:
            existing_aliases = set(existing.get("aliases", []))
            new_aliases = set(data.get("aliases", []))
            existing["aliases"] = list(existing_aliases | new_aliases)

            existing_queries = existing.get("queries", [])
            new_queries = data.get("queries", [])
            for q in new_queries:
                if q not in existing_queries:
                    existing_queries.append(q)
            existing["queries"] = existing_queries

            if data.get("filters"):
                ef = existing.setdefault("filters", {})
                for fkey in ("exclude_url", "exclude_tags", "require_tags"):
                    ef.setdefault(fkey, [])
                    for v in data["filters"].get(fkey, []):
                        if v not in ef[fkey]:
                            ef[fkey].append(v)

            self._data[channel][entity_key] = existing
        else:
            data["created_by"] = "ai"
            data["created_at"] = "auto"
            self._data[channel][entity_key] = data

        self.save()

    async def create_entity_template(self, queries: list, source: str, color: str,
                                scene_text: str, channel: str) -> str | None:
        """AI-агент вызывает этот метод при первом попадании новой сущности.
        Генерирует entity_key и сохраняет. Возвращает entity_key или None."""
        from ai.llm_client import achat_json

        prompt = (
            f"Generate an entity template for an Orthodox image search knowledge base.\n\n"
            f"Scene text: {scene_text[:300]}\n"
            f"Auto-generated queries: {queries}\n"
            f"Source: {source}, Color: {color}\n\n"
            f"Return JSON:\n"
            f"{{\n"
            f"  \"entity_key\": \"unique_slug_english\",\n"
            f"  \"aliases\": [\"all morfological forms of the main saint/entity name in russian\"],\n"
            f"  \"exclude_url\": [\"keywords to exclude from URL\"],\n"
            f"  \"exclude_tags\": [\"keywords to exclude from tags\"],\n"
            f"  \"require_tags\": [\"tags that must be present\"]\n"
            f"}}"
        )

        try:
            result = await achat_json(user_prompt=prompt)
            entity_key = result.get("entity_key", "").strip()
            if not entity_key:
                return None

            self.create_entity(channel, entity_key, {
                "aliases": result.get("aliases", []),
                "queries": queries,
                "source": source,
                "color": color,
                "filters": {
                    "exclude_url": result.get("exclude_url", []),
                    "exclude_tags": result.get("exclude_tags", []),
                    "require_tags": result.get("require_tags", []),
                },
            })
            return entity_key
        except Exception as e:
            logger.warning(f"create_entity_template failed: {e}")
            return None

    # ── Обновление ──────────────────────────────────────────────────────

    def update_filters(self, channel: str, entity_key: str,
                       add_exclude_url: list = None,
                       add_exclude_tags: list = None,
                       add_require_tags: list = None):
        """Добавляет фильтры к существующей сущности."""
        entity = self._data.get(channel, {}).get(entity_key)
        if not entity:
            return
        ef = entity.setdefault("filters", {})
        for fkey, add_list in [
            ("exclude_url", add_exclude_url),
            ("exclude_tags", add_exclude_tags),
            ("require_tags", add_require_tags),
        ]:
            if add_list:
                ef.setdefault(fkey, [])
                for v in add_list:
                    if v not in ef[fkey]:
                        ef[fkey].append(v)
        self.save()

    def record_mismatch(self, channel: str, entity_key: str):
        """Увеличивает счётчик mismatch."""
        entity = self._data.get(channel, {}).get(entity_key)
        if entity:
            entity["mismatch_count"] = entity.get("mismatch_count", 0) + 1
            entity["last_mismatch_at"] = "now"
            self.save()

    def get_entity_filters(self, channel: str, entity_key: str) -> dict:
        """Возвращает filters для entity или пустой словарь."""
        ent = self._data.get(channel, {}).get(entity_key)
        if ent:
            return ent.get("filters", {})
        return {}


# Singleton
query_knowledge = QueryKnowledge()
