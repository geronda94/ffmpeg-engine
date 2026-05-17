import os
import json
import logging
from pathlib import Path
from ai.llm_client import achat_json
from core.config_loader import get_config, get_channel_profile

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _filter_tracks(tracks, channel_id: str):
    priority = []
    regular = []
    for t in tracks:
        tags = t.get("channel_tags", [])
        blacklist = t.get("channel_blacklist", [])
        if channel_id in blacklist:
            continue
        
        is_priority = (t.get("priority_for") and channel_id in t["priority_for"])
        
        if channel_id in tags or "all" in tags:
            if is_priority:
                priority.append(t)
            else:
                regular.append(t)
                
    # Приоритетные треки идут в начало списка
    return priority + regular


def _make_loop_clip(track_path, target_duration, fade_in=1.5, fade_out=2.0, gap=1.0):
    from moviepy import AudioFileClip, AudioClip, concatenate_audioclips
    import moviepy.audio.fx as afx
    import math

    track = AudioFileClip(track_path)
    track_dur = track.duration
    if track_dur <= 0:
        return track

    if target_duration <= track_dur + fade_out:
        seg = track.copy().with_duration(min(target_duration + fade_out, track_dur))
        seg = seg.with_effects([afx.FadeOut(fade_out)])
        return seg

    segments = []
    remaining = target_duration

    while remaining > 0:
        is_first = len(segments) == 0

        seg_dur = min(track_dur, remaining + (fade_out if not is_first else 0))
        seg = track.copy().with_duration(seg_dur)

        if is_first:
            seg = seg.with_effects([afx.FadeOut(fade_out)])
            segments.append(seg)
            remaining -= seg_dur
        else:
            seg = seg.with_effects([afx.FadeIn(fade_in), afx.FadeOut(fade_out)])
            silence = AudioClip(lambda t: 0, duration=gap)
            segments.append(silence)
            segments.append(seg)
            remaining -= seg_dur - gap - fade_in

        if remaining < track_dur:
            last_seg = track.copy().with_duration(max(0.5, remaining + fade_out))
            last_seg = last_seg.with_effects([afx.FadeOut(fade_out)])
            segments.append(last_seg)
            break

    return concatenate_audioclips(segments)


class SoundDesignAgent:
    def __init__(self, library_config_path="config/audio_library.json"):
        self.config_path = library_config_path
        with open(self.config_path, "r", encoding="utf-8") as f:
            self.library = json.load(f)

    def _load_music_tracks(self, channel_id: str = None):
        try:
            data = get_config("music_library", ttl=0)
            tracks = data.get("tracks", [])
            if channel_id:
                tracks = _filter_tracks(tracks, channel_id)
            return tracks, data
        except Exception as e:
            logger.warning(f"Failed to load music library: {e}")
            return [], {}

    async def generate_sound_map(self, script, scenes, language="Russian",
                                  channel_profile: str = None):
        if channel_profile == "news":
            logger.info("Channel is 'news', unbinding background music...")
            return {"bg_music": None, "sfx_placements": []}
        library_summary = []
        for cat, content in self.library["categories"].items():
            for item in content["items"]:
                library_summary.append({
                    "id": item["id"],
                    "path": item["path"],
                    "tags": item.get("tags", []),
                    "trigger_keywords": item.get("trigger_keywords", []),
                    "type": cat
                })

        music_tracks, music_cfg = self._load_music_tracks(channel_profile)
        music_volume = music_cfg.get("default_volume", 0.30)

        channel_ctx = get_channel_profile(channel_profile) if channel_profile else {}
        channel_name = channel_ctx.get("name", "General")

        music_summary = []
        for t in music_tracks:
            music_summary.append({
                "id": t["id"],
                "name": t.get("name", t["id"]),
                "mood": t.get("mood", []),
                "tempo": t.get("tempo", "medium"),
                "energy": t.get("energy", "medium"),
                "vibe": t.get("vibe", ""),
                "instruments": t.get("instruments", []),
                "description": t.get("description", ""),
                "duration_sec": t.get("duration_sec", 30),
            })

        priority_tracks = [t for t in music_tracks if t.get("priority_for") and channel_profile in t["priority_for"]]
        priority_hint = ""
        if priority_tracks:
            names = ", ".join([f"'{t['name']}' (ID: {t['id']})" for t in priority_tracks])
            priority_hint = (
                f"CRITICAL REQUIREMENT: This channel has a BRANDED background music strategy.\n"
                f"You MUST prioritize these tracks: {names}.\n"
                f"Unless the script vibe is COMPLETELY opposite (e.g. high-energy action), select one of these tracks as 'bg_music'."
            )

        output_example = (
            '{ "bg_music": {"id": "track_id", "volume": ' + str(music_volume) + '}, '
            '"sfx_placements": [{"id": "sfx_id", "start": 0.0, "volume": 0.4, "label": "reason"}] }'
        )
        prompt = (
            f"You are a professional audio director. Your task is to create a sound map for a video.\n"
            f"CHANNEL: {channel_name}\n"
            f"VIDEO SCRIPT:\n{script}\n\n"
            f"SCENES:\n{json.dumps([{'idx': i, 'text': s['text_segment'], 'start': s.get('start', 0), 'end': s.get('end', 0)} for i, s in enumerate(scenes)], ensure_ascii=False)}\n\n"
            f"AVAILABLE BACKGROUND MUSIC:\n{json.dumps(music_summary, ensure_ascii=False)}\n\n"
            f"### MUSIC POLICY ###\n"
            f"{priority_hint}\n"
            f"####################\n\n"
            f"AVAILABLE SFX (sound effects):\n{json.dumps(library_summary, ensure_ascii=False)}\n\n"
            f"RULES:\n"
            f"1. Pick ONE background music track for the entire video. Match the mood of the script.\n"
            f"2. Pick SFX for specific moments: match trigger_keywords or relevant textual moments.\n"
            f"3. Always add 'whoosh' or transition SFX at scene boundaries.\n"
            f"4. BG music volume should be {music_volume} (30%). SFX volume varies (0.2-0.8).\n"
            f"5. Output ONLY valid JSON:\n{output_example}\n"
        )

        try:
            sound_map = await achat_json(user_prompt=prompt)
            enriched = self._enrich_with_paths(sound_map, music_tracks, music_cfg)
            if enriched and enriched.get("bg_music", {}).get("path"):
                return enriched
            logger.warning("Sound map has no bg_music path, using fallback track")
        except Exception as e:
            logger.error(f"Sound Design Agent Error: {e}")

        return self._fallback_music(music_tracks, music_cfg)

    def _fallback_music(self, music_tracks, music_cfg):
        if not music_tracks:
            return None
        t = music_tracks[0]
        base = music_cfg.get("base_path", "assets/audio_library/music")
        return {
            "bg_music": {
                "id": t["id"],
                "path": str(_PROJECT_ROOT / base / t["path"]),
                "volume": music_cfg.get("default_volume", 0.30),
                "duration_sec": t.get("duration_sec", 30),
                "loopable": t.get("loopable", True),
            },
            "sfx_placements": []
        }

    def _enrich_with_paths(self, sound_map, music_tracks, music_cfg):
        all_sfx = {}
        for cat in self.library["categories"].values():
            for item in cat["items"]:
                all_sfx[item["id"]] = item["path"]

        bg_id = sound_map.get("bg_music", {}).get("id")
        if bg_id:
            for t in music_tracks:
                if t["id"] == bg_id:
                    base = music_cfg.get("base_path", "assets/audio_library/music")
                    sound_map["bg_music"]["path"] = str(_PROJECT_ROOT / base / t["path"])
                    sound_map["bg_music"]["duration_sec"] = t.get("duration_sec", 30)
                    sound_map["bg_music"]["loopable"] = t.get("loopable", True)

        for sfx in sound_map.get("sfx_placements", []):
            sfx_id = sfx.get("id")
            if sfx_id in all_sfx:
                sfx["path"] = str(_PROJECT_ROOT / self.library["base_path"] / all_sfx[sfx_id])

        return sound_map
