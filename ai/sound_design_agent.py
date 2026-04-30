import os
import json
import logging
import re
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# Используем тот же ключ, что и для остальных агентов
client = AsyncOpenAI(api_key=os.getenv("DEEPSEEK_API_KEY"), base_url="https://api.deepseek.com")

class SoundDesignAgent:
    def __init__(self, library_config_path="config/audio_library.json"):
        self.config_path = library_config_path
        with open(self.config_path, "r", encoding="utf-8") as f:
            self.library = json.load(f)

    async def generate_sound_map(self, script, scenes, language="Russian"):
        """
        Анализирует текст и раскадровку, возвращая карту звуков.
        """
        # Подготавливаем упрощенный список доступных звуков для LLM
        library_summary = []
        for cat, content in self.library['categories'].items():
            for item in content['items']:
                library_summary.append({
                    "id": item['id'],
                    "path": item['path'],
                    "tags": item.get('tags', []),
                    "type": cat
                })

        prompt = (
            f"You are a professional Hollywood sound designer. Your task is to create a sound map for a video script.\n"
            f"VIDEO SCRIPT:\n{script}\n\n"
            f"SCENES TIMING:\n{json.dumps([{ 'idx': i, 'text': s['text_segment'], 'start': s['start'], 'end': s['end']} for i, s in enumerate(scenes)], ensure_ascii=False)}\n\n"
            f"AVAILABLE SOUND LIBRARY:\n{json.dumps(library_summary, ensure_ascii=False)}\n\n"
            f"RULES:\n"
            f"1. Pick ONE background music for the entire video (or segments if long).\n"
            f"2. Add SFX for keywords (e.g., 'price', 'mountain', 'attention') at the exact start time of the segment.\n"
            f"3. Add 'whoosh' sounds for EVERY transition between scenes (at the 'end' time of scene).\n"
            f"4. Output ONLY valid JSON in this format:\n"
            f"{{ 'bg_music': {{ 'id': '...', 'volume': 0.1 }}, 'sfx_placements': [ {{ 'id': '...', 'start': 0.0, 'volume': 0.4, 'label': 'reason' }} ] }}\n"
        )

        try:
            response = await client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            
            raw_content = response.choices[0].message.content
            # Очистка от markdown если есть
            raw_content = re.sub(r'```json\s*|\s*```', '', raw_content).strip()
            sound_map = json.loads(raw_content)
            
            # Обогащаем путями из библиотеки
            return self._enrich_with_paths(sound_map)

        except Exception as e:
            logger.error(f"Sound Design Agent Error: {e}")
            return None

    def _enrich_with_paths(self, sound_map):
        """Добавляет полные пути к файлам на основе ID из библиотеки."""
        all_items = {}
        for cat in self.library['categories'].values():
            for item in cat['items']:
                all_items[item['id']] = item['path']
        
        # Обработка музыки
        bg_id = sound_map.get('bg_music', {}).get('id')
        if bg_id in all_items:
            sound_map['bg_music']['path'] = os.path.join(self.library['base_path'], all_items[bg_id])
            
        # Обработка SFX
        for sfx in sound_map.get('sfx_placements', []):
            sfx_id = sfx.get('id')
            if sfx_id in all_items:
                sfx['path'] = os.path.join(self.library['base_path'], all_items[sfx_id])
                
        return sound_map
