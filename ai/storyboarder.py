import json
from ai.llm_client import chat_json

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
- Each scene: 4-8 seconds of spoken content.
- stock_search_queries: 3-5 SHORT English keywords. No camera settings, no style buzzwords.
- Characters or objects appearing in multiple scenes MUST look identical.
- text_segment MUST be a verbatim extract from the script — do not paraphrase or add words.
"""

# Визуальные директивы для каждого стиля
_STYLE_VISUAL_DIRECTIVES = {
    "news": (
        "VISUAL STYLE DIRECTIVE — NEWS:\n"
        "Use a clean, professional broadcast aesthetic. Prefer: dark studio backgrounds with "
        "accent lighting, lower-third graphics, split-screen layouts, data visualizations, "
        "city skylines, government buildings, official press settings. "
        "Color palette: deep navy, white, accent red or gold. "
        "Avoid: anything cute, hand-drawn, or whimsical. Mood: authoritative, urgent.\n"
    ),
    "scientific": (
        "VISUAL STYLE DIRECTIVE — SCIENTIFIC:\n"
        "Use photorealistic or high-quality 3D CGI. Prefer: macro photography, space vistas, "
        "microscopic worlds, physics diagrams, molecular structures, nature close-ups. "
        "Color palette: deep space blacks, electric blues, bioluminescent greens, cosmic purples. "
        "Each scene should feel like a window into a hidden layer of reality. "
        "Avoid: stock corporate imagery, talking heads, generic office settings.\n"
    ),
    "narrative": (
        "VISUAL STYLE DIRECTIVE — NARRATIVE:\n"
        "Use warm, cinematic, intimate photography. Prefer: everyday human moments, "
        "natural light through windows, hands doing things, faces with real emotion, "
        "familiar urban or natural environments. "
        "Color palette: warm amber, soft teal, natural earthy tones. "
        "Every frame should feel like a personal memory. "
        "Avoid: sterile stock imagery, overly perfect compositions, logos or brands.\n"
    ),
    "hype": (
        "VISUAL STYLE DIRECTIVE — HYPE:\n"
        "Use bold, high-contrast, maximalist visuals. Prefer: dramatic lighting, neon accents, "
        "motion blur, close-up faces with intense expressions, luxury items, cityscape at night, "
        "dynamic angles (low angle, extreme close-up). "
        "Color palette: electric yellow, deep black, hot pink or orange accents. "
        "Every frame must feel urgent and exciting. "
        "Avoid: soft pastels, slow compositions, anything that feels boring or safe.\n"
    ),
    "orthodox": (
        "VISUAL STYLE DIRECTIVE — ORTHODOX:\n"
        "Use deeply spiritual, contemplative imagery that bridges the natural and the divine. "
        "Prefer: "
        "• Natural wonders (sunrise over mountains, light through forest, ocean waves, starry sky) as metaphors for divine order. "
        "• Human faces in moments of genuine peace, prayer, or quiet reflection — not staged piety. "
        "• Orthodox church architecture: golden domes, icon-lit interiors, ancient stone monasteries. "
        "• Symbolic close-ups: a candle flame, an open Bible, incense smoke, a cross silhouette against sky. "
        "• The human body in moments of vulnerability and grace (hands clasped, a child, an elder). "
        "Color palette: gold (#C9A84C), deep burgundy (#6B1A2A), warm white (#F5F0E8), "
        "soft morning blue (#7BA7BC). Icon-style warmth.\n"
        "Lighting: always soft, warm, directional — as if lit by candles or golden hour sun. "
        "Never harsh, clinical, or cold.\n"
        "Avoid: generic stock 'religion' imagery (staged prayer poses, cheesy cross clipart), "
        "anything dark or frightening, modern megachurch aesthetics.\n"
        "Every scene should make a secular viewer feel: 'this is beautiful and true.'\n"
    ),
}

_DEFAULT_VISUAL_DIRECTIVE = ""


def generate_storyboard(script: str, language: str = "Russian", style_id: str = "narrative"):
    """
    Генерирует раскадровку для сценария.

    :param script: Полный текст сценария.
    :param language: Язык сценария.
    :param style_id: ID стиля из script_presets.json — влияет на визуальные директивы.
    """
    style_directive = _STYLE_VISUAL_DIRECTIVES.get(style_id, _DEFAULT_VISUAL_DIRECTIVE)

    system_prompt = _BASE_SYSTEM
    if style_directive:
        system_prompt += f"\n{style_directive}"

    data = chat_json(
        system_prompt=system_prompt,
        user_prompt=(
            f"Script (in {language}):\n{script}\n\n"
            f"Language: {language}\n"
            f"Style: {style_id}\n"
            f"Break this script into scenes. "
            f"Each text_segment must be a VERBATIM excerpt from the script above."
        )
    )

    if "scenes" in data:
        for scene in data["scenes"]:
            text = scene.get("text_segment", "")
            est_dur = max(2.5, round(len(text) / 13.0 + 0.5, 1))
            scene["estimated_duration"] = est_dur

    return data
