import os
import json
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

SYSTEM_PROMPT = """
You are a Professional Scriptwriter for Short-form video (Reels/TikTok).
Your task is to write a script for a video based on a topic and language.

### OUTPUT STRUCTURE
JSON with:
1. "title": Catchy title.
2. "script": The full text to be spoken.
3. "target_duration": Estimated duration in seconds (aim for ~60s unless specified).
4. "language_code": ISO code of the language used.

### RULES
- Calculate word count to match duration (~140 words per minute for RU/EN).
- Use natural, engaging tone.
- If topic is 'Mars', write about Mars.
"""

def generate_script(topic: str, language: str = "Russian", duration: int = 60):
    client = OpenAI(api_key=os.getenv("DEEPSEEK_API_KEY"), base_url="https://api.deepseek.com")
    
    user_prompt = f"Topic: {topic}. Language: {language}. Target Duration: {duration} seconds."
    
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        response_format={'type': 'json_object'}
    )
    return json.loads(response.choices[0].message.content)
