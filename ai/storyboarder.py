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


def _build_scene_duration_instruction(pacing_mode: str) -> str:
    pacing = _get_pacing_config(pacing_mode)
    wpm = pacing.get("wpm", 180)
    min_dur = pacing.get("min_duration", 2.5)
    max_dur = pacing.get("max_duration", 5.0)
    return (
        f"### SCENE LENGTH RULES ({pacing_mode}):\n"
        f"- Each scene should contain approximately {wpm} words per minute of spoken content.\n"
        f"- Target scene duration: {min_dur}-{max_dur} seconds.\n"
        f"- Use the text_segment length to naturally control scene duration.\n"
        f"- Split longer text segments into multiple scenes, merge very short ones.\n"
    )


def generate_storyboard(script: str, language: str = "Russian",
                        style_id: str = "narrative",
                        pacing_mode: str = "normal"):
    style_directive = _get_visual_directive(style_id)
    pacing_instruction = _build_scene_duration_instruction(pacing_mode)

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
