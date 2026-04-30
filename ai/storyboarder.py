import os
import json
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

SYSTEM_PROMPT = """
You are an AI Storyboard Artist. Your task is to break down a video script into logical scenes.

### OUTPUT STRUCTURE
JSON with:
1. "scenes": Array of objects:
   - "scene_id": number (1, 2, 3...)
   - "text_segment": Part of the script for this scene.
   - "visual_description": What should be on screen (for user approval).
   - "image_prompt": Detailed AI prompt for image generation.
   - "ui_caption": Short caption to display as a subtitle.

### RULES
- Each scene should be 5-10 seconds long.
- Visual descriptions should be clear and professional.
- Match the visual description with the meaning of the text segment.
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
