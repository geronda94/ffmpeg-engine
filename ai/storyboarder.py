import json
from ai.llm_client import chat_json
from core.config_loader import get_config

_BASE_SYSTEM = """
You are an AI Storyboard Artist. Your task is to break down a video script into logical scenes
while ensuring high VISUAL HARMONY and COLOR CONSISTENCY across the entire video.

### VISUAL HARMONY RULES:
1. **Unified Style**: Define ONE consistent artistic style for the whole video (e.g., cinematic 3D render, photorealistic, minimal flat design). Do not mix styles.
2. **Color Palette**: Choose a specific palette of 3-4 hex colors and apply it to ALL scenes.
3. **Smooth Transitions**: If mood or colors must shift, do it gradually over 2-3 scenes. No jarring jumps.
4. **Lighting Consistency**: Maintain the same lighting type (e.g., soft morning sun, neon night, golden hour) unless the story strictly requires a change.

### OUTPUT STRUCTURE (return ONLY valid JSON):
{
  "global_visual_style": "Description of overall art style, lighting, and color palette.",
  "scenes": [
    {
      "scene_id": 1,
      "text_segment": "Exact fragment of the script for this scene.",
      "visual_description": "What happens on screen. Describe action, not just subject.",
      "image_prompt": "Detailed AI image prompt. MUST include: [style prefix], [lighting], [specific colors from palette]. Start every prompt with the same style prefix.",
      "ui_caption": "Short on-screen subtitle (max 5 words).",
      "stock_search_queries": ["simple keyword 1", "simple keyword 2", "simple keyword 3"]
    }
  ]
}

### CONSTRAINTS:
- Characters or objects appearing in multiple scenes MUST look identical.
- text_segment MUST be a verbatim extract from the script — do not paraphrase or add words.
"""


def _get_visual_directive(style_id: str) -> str:
    presets = get_config("script_presets", ttl=0)
    style_config = next((s for s in presets.get('styles', []) if s['id'] == style_id), None)
    if style_config and 'visual_directive' in style_config:
        return "\n" + style_config['visual_directive']
    return ""


def _get_pacing_config(pacing_mode: str) -> dict:
    presets = get_config("script_presets", ttl=0)
    pacing = presets.get("scene_pacing", {})
    return pacing.get(pacing_mode, pacing.get("normal", {}))


def _calc_estimated_duration(text: str, pacing_mode: str) -> float:
    pacing = _get_pacing_config(pacing_mode)
    formula = pacing.get("duration_formula", "max(2.5, round(len(text) / 13.0 + 0.5, 1))")
    min_dur = pacing.get("min_duration", 2.5)
    max_dur = pacing.get("max_duration", 5.0)

    try:
        dur = eval(formula, {"text": text, "round": round, "max": max, "min": min, "len": len})
    except Exception:
        dur = max(2.5, round(len(text) / 13.0 + 0.5, 1))

    return max(min_dur, min(max_dur, dur))


def _build_scene_duration_instruction(pacing_mode: str, script_len: int) -> str:
    pacing = _get_pacing_config(pacing_mode)
    wpm = pacing.get("wpm", 180)
    min_dur = pacing.get("min_duration", 2.5)
    max_dur = pacing.get("max_duration", 5.0)

    max_chars_per_scene = {240: 48, 180: 72, 140: 96}.get(wpm, 72)

    # Dynamically scale expected scene count based on text length to prevent LLM truncation!
    if pacing_mode == "super_dynamic":
        target_scenes = max(8, round(script_len / 45))
        hint = (
            f"CRITICAL RULE: BREAK EVERY SENTENCE into its own scene. NO exceptions.\n"
            f"MAXIMUM 50 characters per text_segment. If a sentence exceeds 50 chars, "
            f"cut it at the nearest comma, dash, or natural pause.\n"
            f"Target: approximately {target_scenes} scenes for this {script_len}-character script (averaging 2-3 seconds per scene).\n"
            f"If text has no periods, create scene breaks every 40 characters.\n"
            f"EVERY period MUST be a scene break. Two sentences = two scenes, always."
        )
    elif pacing_mode == "slow":
        target_scenes = max(3, round(script_len / 120))
        hint = (
            f"Allow longer text_segments: 70-120 characters.\n"
            f"Target: approximately {target_scenes} scenes for this {script_len}-character script."
        )
    else:
        target_scenes = max(5, round(script_len / 80))
        hint = (
            f"Good balance: 50-80 characters per text_segment. One complex sentence or two short sentences max.\n"
            f"Target: approximately {target_scenes} scenes for this {script_len}-character script."
        )

    return (
        f"### STRICT SCENE LENGTH RULES — {pacing_mode.upper()} MODE:\n"
        f"- Target scene duration: {min_dur}-{max_dur} seconds.\n"
        f"- Maximum spoken content speed: {wpm} words per minute.\n"
        f"- Maximum text_segment length: ~{max_chars_per_scene} characters.\n"
        f"{hint}\n"
        f"- VIOLATION CHECK: if a text_segment has more than {max_chars_per_scene} chars, "
        f"you MUST split it into two or more scenes.\n"
        f"- Merge only if text is under 15 characters and doesn't make sense alone.\n"
        f"- CRITICAL REQUIREMENT: You MUST cover the ENTIRE script from the very first word to the very last word. "
        f"DO NOT truncate, omit, or stop writing scenes before you have mapped 100% of the provided script! Every single paragraph must be fully converted into scenes.\n"
    )


def generate_storyboard(script: str, language: str = "Russian",
                        style_id: str = "narrative",
                        pacing_mode: str = "normal"):
    style_directive = _get_visual_directive(style_id)
    pacing_instruction = _build_scene_duration_instruction(pacing_mode, len(script))

    system_prompt = _BASE_SYSTEM
    if style_directive:
        system_prompt += f"\n{style_directive}"
    system_prompt += f"\n{pacing_instruction}"

    data = chat_json(
        system_prompt=system_prompt,
        user_prompt=(
            f"Script (in {language}):\n{script}\n\n"
            f"Language: {language}\n"
            f"Style: {style_id}\n"
            f"Pacing: {pacing_mode}\n"
            f"Break this script into scenes. "
            f"Each text_segment must be a VERBATIM excerpt from the script above."
        )
    )

    if "scenes" in data:
        for scene in data["scenes"]:
            text = scene.get("text_segment", "")
            scene["estimated_duration"] = _calc_estimated_duration(text, pacing_mode)

    return data
