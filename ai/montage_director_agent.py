import json
import logging
from ai.llm_client import achat_json
from core.config_loader import get_config, get_channel_profile

logger = logging.getLogger(__name__)


def _filter_effects(effects_list, channel_tag, min_dur, max_dur, max_count=8):
    filtered = []
    for e in effects_list:
        tags = e.get("channel_tags", ["all"])
        if channel_tag not in tags and "all" not in tags:
            continue
        e_min = e.get("min_scene_duration", 0)
        if e_min > max_dur:
            continue
        filtered.append(e)
    return filtered[:max_count]


def _filter_transitions(transitions_list, channel_tag, max_count=6):
    filtered = []
    for t in transitions_list:
        tags = t.get("channel_tags", ["all"])
        if channel_tag not in tags and "all" not in tags:
            continue
        filtered.append(t)
    return filtered[:max_count]


def _format_effects_for_prompt(effects):
    lines = []
    for e in effects:
        params = json.dumps(e.get("default_params", {}), ensure_ascii=False)
        lines.append(f"  '{e['id']}': {params}")
    return "\n".join(lines)


def _format_transitions_for_prompt(transitions):
    lines = []
    for t in transitions:
        params = json.dumps(t.get("default_params", {}), ensure_ascii=False)
        lines.append(f"  '{t['id']}': {params}")
    return "\n".join(lines)


class MontageDirectorAgent:
    async def plan_montage(self, script: str, scenes: list, target_lang: str = "Russian",
                           channel_profile_id: str = None, pacing_mode: str = "normal") -> list:
        try:
            scenes_summary = []
            total_dur = 0
            for i, s in enumerate(scenes):
                dur = s.get("estimated_duration", 3.0) or s.get("end", 0) - s.get("start", 0) or 3.0
                total_dur = max(total_dur, dur)
                scenes_summary.append({
                    "id": i,
                    "text": s.get("text_segment", ""),
                    "duration": round(dur, 1)
                })

            min_dur = min((s["duration"] for s in scenes_summary), default=3.0)
            max_dur = max((s["duration"] for s in scenes_summary), default=5.0)

            channel_ctx = get_channel_profile(channel_profile_id)
            channel_tag = channel_profile_id or "all"

            effects_reg = get_config("effects_registry", ttl=0).get("effects", [])
            trans_reg = get_config("transitions_registry", ttl=0).get("transitions", [])

            available_effects = _filter_effects(effects_reg, channel_tag, min_dur, max_dur)
            available_transitions = _filter_transitions(trans_reg, channel_tag)

            channel_hint = ""
            channel_tone = channel_ctx.get("tone_of_voice", "").lower()
            if "духовн" in channel_tone or "глубок" in channel_tone:
                channel_hint = (
                    "CHANNEL STYLE: Contemplative, atmospheric. "
                    "Prefer subtle motion and atmosphere effects (ken_burns_pan, drift, chromatic_aberration, vignette_breathe). "
                    "Avoid glitch, shake, or aggressive effects."
                )
            elif "профессиональн" in channel_tone or "экспертн" in channel_tone:
                channel_hint = (
                    "CHANNEL STYLE: Clean, tech-forward. "
                    "Use precise motion effects and modern transitions (snap_zoom, ken_burns_pan, slide transitions, glitch_transition). "
                    "Atmosphere effects and heavy dissolves are not appropriate."
                )
            elif "энергичн" in channel_tone or "дерзк" in channel_tone:
                channel_hint = (
                    "CHANNEL STYLE: Energetic, viral. "
                    "Full palette available. Vary effects between scenes for maximum engagement."
                )
            else:
                channel_hint = (
                    "CHANNEL STYLE: Warm, engaging. "
                    "Prefer smooth zooms, gentle motion, and soft transitions. "
                    "Avoid aggressive effects (glitch, shake, snap_zoom)."
                )

            prompt = (
                f"You are a professional video director. "
                f"Plan the visual effects and transitions for each scene.\n\n"
                f"FULL SCRIPT:\n{script}\n\n"
                f"SCENES:\n{json.dumps(scenes_summary, ensure_ascii=False)}\n\n"
                f"{channel_hint}\n\n"
                f"SCENE PACING: {pacing_mode} (scene duration range: {min_dur}-{max_dur}s)\n\n"
                f"Available effects per scene (apply to the scene content):\n"
                f"{_format_effects_for_prompt(available_effects)}\n\n"
                f"Available transitions (apply to the START of each scene, except the first):\n"
                f"{_format_transitions_for_prompt(available_transitions)}\n\n"
                f"RULES:\n"
                f"- Aim for visual variety to keep the viewer engaged.\n"
                f"- Match the mood of the text (e.g., 'pulse' or 'snap_zoom' for energy, 'ken_burns' for storytelling).\n"
                f"- For very short scenes (<3s): prefer simple effects or none. Avoid slow zooms and atmosphere overlays.\n"
                f"- For long scenes (>5s): can use slow atmospheric effects (drift, vignette_breathe, light_leak).\n"
                f"- Ensure smooth transitions between scenes.\n"
                f"- DO NOT use the same effect for two consecutive scenes.\n\n"
                f"Return ONLY a JSON object with one field 'plan' which is a list of dictionaries (one per scene index).\n"
                f"Each dictionary can have:\n"
                f"- 'effects': a list of effect configs (max 2 per scene)\n"
                f"- 'transition': a single transition config (skip for first scene, or use {{\"type\": \"cut\"}})\n"
                f"Example: {{\"plan\": [{{\"effects\": [{{\"type\": \"ken_burns\"}}], \"transition\": {{\"type\": \"crossfade\", \"duration\": 0.5}}}}, ...]}}"
            )

            response = await achat_json(user_prompt=prompt)
            plan = response.get("plan", [])

            if len(plan) != len(scenes):
                logger.warning(f"Director Agent returned plan length {len(plan)} for {len(scenes)} scenes. Filling defaults.")
                plan = [{"effects": [], "transition": {"type": "crossfade", "duration": 0.5}} for _ in scenes]

            return plan

        except Exception as e:
            logger.error(f"Montage Director Agent error: {e}", exc_info=True)
            return [{"effects": [], "transition": {"type": "crossfade", "duration": 0.5}} for _ in scenes]


montage_director = MontageDirectorAgent()
