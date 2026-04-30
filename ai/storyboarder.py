import os
import json
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

SYSTEM_PROMPT = """
You are an AI Storyboard Artist. Your task is to break down a video script into logical scenes while ensuring high VISUAL HARMONY and COLOR CONSISTENCY.

### VISUAL HARMONY RULES:
1. **Unified Style**: Define a consistent artistic style (e.g., cinematic, 3d render, minimal flat design, photorealistic) for the entire video.
2. **Color Palette**: Choose a specific color palette (e.g., teal and orange, pastel dreams, moody dark blues) and apply it to ALL scenes.
3. **Smooth Transitions**: If the mood or colors must change, ensure it happens gradually over 2-3 scenes. No jarring color jumps between consecutive shots.
4. **Lighting Consistency**: Maintain the same lighting type (e.g., soft morning sun, neon night, studio softbox) unless the story strictly requires a change.

### OUTPUT STRUCTURE
JSON with:
1. "global_visual_style": Description of the overall art style, lighting, and color palette.
2. "scenes": Array of objects:
   - "scene_id": number
   - "text_segment": Part of the script.
   - "visual_description": What happens on screen.
   - "image_prompt": Detailed AI prompt. MUST include: [style keywords], [lighting details], [specific color codes or names from the global palette].
   - "ui_caption": Short subtitle.

### CONSTRAINTS
- Each scene should be 4-8 seconds long.
- Every image_prompt MUST start with the same style prefix to maintain consistency.
- Ensure objects or characters appearing in multiple scenes look the same.
"""

def generate_storyboard(script: str, language: str = "Russian"):
    client = OpenAI(api_key=os.getenv("DEEPSEEK_API_KEY"), base_url="https://api.deepseek.com")
    
    user_prompt = f"Script: {script}\nLanguage: {language}"
    
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        response_format={'type': 'json_object'}
    )
    data = json.loads(response.choices[0].message.content)
    
    # Предварительный расчет длительности для каждой сцены
    if "scenes" in data:
        for scene in data["scenes"]:
            text = scene.get("text_segment", "")
            # Формула: ~13 символов в секунду (для русского) + 0.5с запас
            est_dur = max(2.5, round(len(text) / 13.0 + 0.5, 1))
            scene["estimated_duration"] = est_dur
            
    return data
