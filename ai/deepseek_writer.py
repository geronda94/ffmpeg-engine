import json
from ai.llm_client import chat_json

SYSTEM_PROMPT = """
You are an expert AI Video Producer. Generate a production package JSON.

### OUTPUT STRUCTURE
JSON with keys:
1. "suggested_title": SEO title.
2. "script": Full voiceover text.
3. "image_prompts": Array of prompts.
4. "ui_texts": Array of {"text": "...", "start": 0, "end": 5}.
5. "engine_config": FFmpeg Engine JSON (v2.0). 

### ENGINE_CONFIG EXAMPLE (STRICT KEYS)
{
  "resources": [{"id": "scene_1", "source": "path", "type": "image"}, {"id": "voice_audio", "source": "path", "type": "audio"}],
  "pipeline": [{"id": "step_1", "input": "scene_1", "trim": {"start": 0, "end": 5}}],
  "compose": {"base": "step_1", "layers": []},
  "audio": [{"source": "voice_audio", "volume": 1.0}]
}

### CRITICAL RULES
- Use "input" key in pipeline steps (NOT "image" or "resource").
- Use "source" key in resources and audio tracks.
- Ensure "compose" has "base" and "layers" (even if empty).
"""


def generate_project(topic: str, template_type: str = "vertical"):
    return chat_json(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=f"Topic: {topic}. Format: {template_type}."
    )
