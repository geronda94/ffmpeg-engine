import json
import logging
import time

logger = logging.getLogger(__name__)

_cache = {}
_cache_ttl = 300

CONFIG_PATHS = {
    "audio_presets": "config/audio_presets.json",
    "script_presets": "config/script_presets.json",
    "rendering_presets": "config/rendering_presets.json",
    "dynamic_scenes": "config/dynamic_scenes.json",
    "channel_context": "config/channel_context.json",
    "audio_library": "config/audio_library.json",
    "ui_plates": "config/ui_plates.json",
}


def _resolve_path(name: str) -> str:
    if name in CONFIG_PATHS:
        return CONFIG_PATHS[name]
    return name


def get_config(name: str, ttl: int = None) -> dict:
    ttl = _cache_ttl if ttl is None else ttl
    path = _resolve_path(name)

    entry = _cache.get(path)
    now = time.time()
    if entry and (ttl <= 0 or now - entry["ts"] < ttl):
        return entry["data"]

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    _cache[path] = {"data": data, "ts": now}
    return data


def reload_config(name: str) -> dict:
    path = _resolve_path(name)
    _cache.pop(path, None)
    return get_config(name, ttl=0)


def get_channel_profile(profile_id: str = None) -> dict:
    data = get_config("channel_context", ttl=0)
    profiles = data.get("profiles")
    if profiles is None:
        return data
    if profile_id:
        match = next((p for p in profiles if p["id"] == profile_id), None)
        if match:
            return match
    return profiles[0] if profiles else {}


DEFAULT_CHANNEL_PROFILE = "educational"
