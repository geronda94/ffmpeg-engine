import logging
import numpy as np
from PIL import Image as _PILImage
from ai.llm_client import achat_json

logger = logging.getLogger(__name__)


def _extract_palette(image_path, n=5):
    try:
        img = _PILImage.open(image_path).resize((60, 60))
        pixels = np.array(img, dtype=np.float32).reshape(-1, 3)
        ys = np.linspace(0, 60, n + 1, dtype=int)
        colors = []
        for i in range(n):
            y0, y1 = ys[i], ys[i + 1]
            block = pixels[y0 * 60:y1 * 60].mean(axis=0)
            colors.append(f"#{int(block[0]):02x}{int(block[1]):02x}{int(block[2]):02x}")
        return colors
    except Exception as e:
        logger.warning(f"Palette extraction failed: {e}")
        return ["#2A1F35", "#4A3F55", "#6B5B7A", "#9B8BA8", "#C4B8CF"]


async def design_preview_colors(asset_path: str, preview_text: str,
                                channel_name: str = "", script_snippet: str = "") -> dict:
    palette = _extract_palette(asset_path)

    prompt = (
        f"You are a color designer for video preview overlays.\n"
        f"SCENE DOMINANT COLORS (from frame): {', '.join(palette)}\n"
        f"PREVIEW TEXT: {preview_text}\n"
        f"CHANNEL: {channel_name}\n"
        f"TOPIC: {script_snippet[:200]}\n\n"
        f"Design a harmonious preview overlay color scheme:\n"
        f"- glass_from: main glass panel base color (a hex color from the palette)\n"
        f"- glass_to: secondary glass panel color (a slightly different hex, forms a subtle gradient)\n"
        f"- text_primary: main text color, MUST have high contrast with glass colors\n"
        f"- text_accent: highlight word color (e.g. warm gold, coral, or complementary to the frame)\n"
        f"- opacity: glass panel opacity (0.2-0.45)\n\n"
        f"RULES:\n"
        f"- glass colors should blend WITH the frame, not clash\n"
        f"- text colors must be readable (high contrast)\n"
        f"- accent should pop but not be jarring\n"
        f"- Return ONLY JSON with these exact keys.\n"
    )

    default = {
        "glass_from": palette[0],
        "glass_to": palette[-1],
        "text_primary": "#F5F0E8",
        "text_accent": "#D4A843",
        "opacity": 0.30,
    }

    try:
        result = await achat_json(user_prompt=prompt)
        return {
            "glass_from": result.get("glass_from", default["glass_from"]),
            "glass_to": result.get("glass_to", default["glass_to"]),
            "text_primary": result.get("text_primary", default["text_primary"]),
            "text_accent": result.get("text_accent", default["text_accent"]),
            "opacity": result.get("opacity", default["opacity"]),
        }
    except Exception as e:
        logger.error(f"Preview designer agent error: {e}")
        return default
