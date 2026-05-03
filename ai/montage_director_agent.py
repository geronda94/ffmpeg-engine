import json
import logging
from ai.llm_client import achat_json

logger = logging.getLogger(__name__)

class MontageDirectorAgent:
    """
    Агент, который анализирует сценарий и раскадровку, 
    и решает, какие эффекты и переходы лучше всего подходят для каждой сцены.
    """
    
    async def plan_montage(self, script: str, scenes: list, target_lang: str = "Russian") -> list:
        """
        Принимает текст и список сцен, возвращает список настроек эффектов для каждой сцены.
        """
        try:
            # Подготавливаем данные для LLM
            scenes_summary = []
            for i, s in enumerate(scenes):
                scenes_summary.append({
                    "id": i,
                    "text": s.get("text_segment", ""),
                    "estimated_duration": s.get("estimated_duration", 3.0)
                })

            prompt = (
                f"You are a professional video director.\n"
                f"Task: Plan the visual effects and transitions for each scene in the video based on the script and scene text.\n\n"
                f"FULL SCRIPT: {script}\n\n"
                f"SCENES:\n{json.dumps(scenes_summary, ensure_ascii=False)}\n\n"
                f"Available effects per scene:\n"
                f"1. 'ken_burns': {{\"type\": \"ken_burns\", \"zoom_from\": 1.0, \"zoom_to\": 1.20}}\n"
                f"2. 'ken_burns_out': {{\"type\": \"ken_burns\", \"zoom_from\": 1.25, \"zoom_to\": 1.0}}\n"
                f"3. 'parallax_left': {{\"type\": \"parallax\", \"direction\": \"left\", \"strength\": 0.10}}\n"
                f"4. 'parallax_right': {{\"type\": \"parallax\", \"direction\": \"right\", \"strength\": 0.10}}\n"
                f"5. 'pulse': {{\"type\": \"pulse\", \"frequency\": 1.5, \"amplitude\": 6.0}}\n\n"
                f"Available transitions (apply to the START of the scene, except the first one):\n"
                f"1. 'crossfade': {{\"type\": \"crossfade\", \"duration\": 0.5}}\n"
                f"2. 'fade_black': {{\"type\": \"fade_black\", \"duration\": 0.5}}\n"
                f"3. 'slide_left': {{\"type\": \"slide_left\", \"duration\": 0.4}}\n"
                f"4. 'slide_right': {{\"type\": \"slide_right\", \"duration\": 0.4}}\n"
                f"5. 'zoom_in_out': {{\"type\": \"zoom_in_out\", \"duration\": 0.5}}\n\n"
                f"Rules for the plan:\n"
                f"- Aim for visual variety to keep the viewer engaged.\n"
                f"- Match the mood of the text (e.g., 'pulse' for high energy, 'ken_burns' for storytelling).\n"
                f"- Ensure smooth transitions between scenes.\n\n"
                f"Return ONLY a JSON object with one field 'plan' which is a list of dictionaries (one per scene index).\n"
                f"Example: {{\"plan\": [ {{\"effects\": [{{...}}], \"transition\": {{...}}}}, ... ]}}"
            )

            response = await achat_json(user_prompt=prompt)
            plan = response.get("plan", [])
            
            # Если LLM вернула пустой план или ошиблась в размере, заполняем дефолтами
            if len(plan) != len(scenes):
                logger.warning(f"Director Agent returned plan length {len(plan)} for {len(scenes)} scenes. Falling back.")
                plan = [{"effects": [], "transition": {"type": "crossfade", "duration": 0.5}} for _ in scenes]
                
            return plan

        except Exception as e:
            logger.error(f"Montage Director Agent error: {e}", exc_info=True)
            return [[] for _ in scenes]

montage_director = MontageDirectorAgent()
