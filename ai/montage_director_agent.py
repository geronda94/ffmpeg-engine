import json
import logging
from collections import Counter
from ai.llm_client import achat_json
from core.config_loader import get_config, get_channel_profile

logger = logging.getLogger(__name__)


def _filter_effects(effects_list, channel_tag, min_dur, max_dur, max_count=10):
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


def _filter_transitions(transitions_list, channel_tag, max_count=8):
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


def _validate_plan_diversity(plan, available_effect_ids, available_transition_ids):
    for i in range(len(plan) - 2):
        t1 = plan[i].get("transition", {}).get("type", "cut")
        t2 = plan[i + 1].get("transition", {}).get("type", "cut")
        t3 = plan[i + 2].get("transition", {}).get("type", "cut")
        if t1 == t2 == t3 and t1 != "cut":
            alt = [t for t in available_transition_ids if t != t1]
            if alt:
                plan[i + 1]["transition"]["type"] = alt[0]
                logger.info(f"Diversity fix: replaced '{t1}' with '{alt[0]}' at scene {i + 1}")

    used_types = set()
    for s in plan:
        for e in s.get("effects", []):
            etype = e.get("type", "")
            if etype:
                used_types.add(etype)
    if len(used_types) < 2 and len(plan) > 3:
        logger.warning(f"Only {len(used_types)} effect types used. Enforcing rotation.")
        effect_types = [e for e in available_effect_ids if e != ""]
        if effect_types:
            for i, s in enumerate(plan):
                if not s.get("effects"):
                    plan[i]["effects"] = [{"type": effect_types[i % len(effect_types)]}]

    for i in range(len(plan) - 1):
        e1 = [e.get("type", "") for e in plan[i].get("effects", []) if e.get("type")]
        e2 = [e.get("type", "") for e in plan[i + 1].get("effects", []) if e.get("type")]
        common = set(e1) & set(e2)
        if common:
            alt = [e for e in available_effect_ids if e not in e1]
            if alt:
                for s in [plan[i], plan[i + 1]]:
                    for e in s.get("effects", []):
                        if e.get("type") in common:
                            e["type"] = alt.pop(0)
                            logger.info(f"Diversity fix: changed '{list(common)[0]}' to '{e['type']}'")

    return plan


class MontageDirectorAgent:
    async def plan_montage(self, script: str, scenes: list, target_lang: str = "Russian",
                           channel_profile_id: str = None, pacing_mode: str = "normal") -> list:
        try:
            scenes_summary = []
            for i, s in enumerate(scenes):
                dur = s.get("estimated_duration", 3.0) or s.get("end", 0) - s.get("start", 0) or 3.0
                scenes_summary.append({
                    "id": i,
                    "text": s.get("text_segment", ""),
                    "duration": round(dur, 1)
                })

            min_dur = min((s["duration"] for s in scenes_summary), default=3.0)
            max_dur = max((s["duration"] for s in scenes_summary), default=5.0)
            num_scenes = len(scenes_summary)

            channel_ctx = get_channel_profile(channel_profile_id)
            channel_tag = channel_profile_id or "all"

            effects_reg = get_config("effects_registry", ttl=0).get("effects", [])
            trans_reg = get_config("transitions_registry", ttl=0).get("transitions", [])

            available_effects = _filter_effects(effects_reg, channel_tag, min_dur, max_dur)
            available_transitions = _filter_transitions(trans_reg, channel_tag)
            available_effect_ids = [e["id"] for e in available_effects]
            available_transition_ids = [t["id"] for t in available_transitions]

            channel_hint = ""
            channel_tone = channel_ctx.get("tone_of_voice", "").lower()

            if "духовн" in channel_tone or "глубок" in channel_tone:
                if pacing_mode == "super_dynamic":
                    channel_hint = (
                        "CHANNEL STYLE: Contemplative, but this is DYNAMIC mode. "
                        "Use varied effects (snap_zoom, ken_burns, chromatic_aberration, light_leak). "
                        "Transition variety is REQUIRED: use slides (slide_left/right), "
                        "crossfade, zoom_in_out. Avoid 3+ same transitions in a row. "
                        "Atmosphere overlays (light_leak, vignette_breathe) can still be used "
                        "but alternate with motion effects."
                    )
                else:
                    channel_hint = (
                        "CHANNEL STYLE: Contemplative, atmospheric. "
                        "Prefer: light_leak, chromatic_aberration, drift, vignette_breathe, ken_burns_pan. "
                        "Transition preference: blur_dissolve, fade_black over crossfade. "
                        "Avoid: glitch, shake, aggressive effects."
                    )
            elif "профессиональн" in channel_tone or "экспертн" in channel_tone:
                channel_hint = (
                    "CHANNEL STYLE: Clean, tech-forward. "
                    "Use: snap_zoom, ken_burns_pan, slide transitions, glitch_transition. "
                    "Avoid: vignette_breathe, drift, blur_dissolve."
                )
            elif "энергичн" in channel_tone or "дерзк" in channel_tone:
                channel_hint = (
                    "CHANNEL STYLE: Energetic, viral. "
                    "Full palette available. Vary effects maximally between scenes."
                )
            else:
                channel_hint = (
                    "CHANNEL STYLE: Warm, engaging. "
                    "Prefer: ken_burns, light_leak, smooth motion. "
                    "Avoid: glitch, shake, snap_zoom."
                )

            min_types = min(3, num_scenes // 2) if num_scenes > 3 else 2

            pacing_hint = ""
            if pacing_mode == "super_dynamic":
                pacing_hint = (
                    "PACING RULE (super_dynamic): Each scene is 2-3 seconds. "
                    "Use SHORT transitions (0.3-0.4s). Prefer slides over fades. "
                    "GLITCH_TRANSITION and ZOOM_IN_OUT are encouraged for energy. "
                    "Do not use crossfade more than once every 3 scenes."
                )

            prompt = (
                f"You are a professional video director. "
                f"Plan the visual effects and transitions for each scene.\n\n"
                f"FULL SCRIPT:\n{script}\n\n"
                f"SCENES:\n{json.dumps(scenes_summary, ensure_ascii=False)}\n\n"
                f"{channel_hint}\n\n"
                f"{pacing_hint}\n"
                f"SCENE PACING: {pacing_mode}\n\n"
                f"Available effects per scene:\n"
                f"{_format_effects_for_prompt(available_effects)}\n\n"
                f"Available transitions:\n"
                f"{_format_transitions_for_prompt(available_transitions)}\n\n"
                f"### STRICT RULES — VIOLATION WILL BE REJECTED:\n"
                f"1) CRITICAL: A transition MUST NOT appear 3+ times consecutively. "
                f"If scenes 0,1,2 all had 'crossfade', scene 2's transition MUST change.\n"
                f"2) You MUST use at least {min_types} DIFFERENT effect types across the entire video. "
                f"Don't just use ken_burns for everything.\n"
                f"3) If scene N used an effect, scene N+1 MUST use a DIFFERENT effect type.\n"
                f"4) The first scene's transition should be {{\"type\": \"cut\"}} (no transition before it).\n"
                f"5) Overs transition (blur_dissolve, zoom_in_out, whip_pan) prefer short durations (0.3-0.5s). "
                f"Standard transitions (crossfade, fade_black) can be 0.4-0.6s.\n"
                f"6) Empty effects list is allowed for energetic fast scenes.\n"
                f"7) At least every 3rd scene should have 2 effects or an atmosphere overlay.\n\n"
                f"Return ONLY JSON: {{\"plan\": [...]}}\n"
                f"Example: {{\"plan\": [{{\"effects\": [{{\"type\": \"parallax\"}}], \"transition\": {{\"type\": \"cut\"}}}}, "
                f"{{\"effects\": [{{\"type\": \"snap_zoom\"}}], \"transition\": {{\"type\": \"slide_left\", \"duration\": 0.3}}}}, "
                f"{{\"effects\": [{{\"type\": \"light_leak\"}}], \"transition\": {{\"type\": \"blur_dissolve\", \"duration\": 0.5}}}}]}}"
            )

            response = await achat_json(user_prompt=prompt)
            plan = response.get("plan", [])

            if len(plan) != len(scenes):
                logger.warning(f"Director Agent returned plan length {len(plan)} for {len(scenes)} scenes. Filling defaults.")
                types = available_effect_ids if available_effect_ids else ["ken_burns"]
                trans = available_transition_ids if available_transition_ids else ["crossfade"]
                plan = []
                for i in range(len(scenes)):
                    plan.append({
                        "effects": [{"type": types[i % len(types)]}],
                        "transition": {"type": "cut" if i == 0 else trans[i % len(trans)], "duration": 0.5}
                    })

            plan = _validate_plan_diversity(plan, available_effect_ids, available_transition_ids)
            return plan

        except Exception as e:
            logger.error(f"Montage Director Agent error: {e}", exc_info=True)
            types = ["ken_burns", "parallax", "zoom_out_reveal", "chromatic_aberration"]
            trans = ["crossfade", "fade_black", "slide_left", "blur_dissolve"]
            return [
                {
                    "effects": [{"type": types[i % len(types)]}],
                    "transition": {"type": "cut" if i == 0 else trans[i % len(trans)], "duration": 0.5}
                }
                for i in range(len(scenes))
            ]


montage_director = MontageDirectorAgent()
