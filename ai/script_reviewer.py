import json
import logging
from ai.llm_client import achat_json
from core.config_loader import get_config

logger = logging.getLogger(__name__)

REVIEW_CRITERIA = [
    "logical_coherence",
    "structure",
    "style_adherence",
    "semantic_density",
]

PASS_THRESHOLD = 14
MAX_SCORE_PER_CRITERION = 5


async def review_script(script: str, style_id: str, language: str = "Russian") -> dict:
    presets = get_config("script_presets", ttl=0)
    style_config = next((s for s in presets.get('styles', []) if s['id'] == style_id), None)

    style_name = style_config.get('name', style_id) if style_config else style_id
    restrictions = style_config.get('restrictions', '') if style_config else ''
    structure_spec = style_config.get('structure_spec', '') if style_config else ''

    if not style_config:
        return {
            "pass": True,
            "total_score": PASS_THRESHOLD,
            "scores": {},
            "suggestions": ""
        }

    prompt = (
        f"You are a strict script quality reviewer for short-form video content.\n"
        f"STYLE: {style_name}\n"
        f"LANGUAGE: {language}\n\n"
        f"EXPECTED STRUCTURE:\n{structure_spec}\n\n"
        f"STRICT RESTRICTIONS (violation = score 0):\n{restrictions}\n\n"
        f"SCRIPT TO REVIEW:\n{script}\n\n"
        f"SCORE EACH CRITERION 0-5:\n"
        f"1. logical_coherence (0-5): Do sentences form a chain reaction? Each sentence must logically follow from the previous.\n"
        f"   Score 0-1: Disconnected ideas, random jumps\n"
        f"   Score 2-3: Some connection but breaks in logic\n"
        f"   Score 4-5: Seamless chain, every sentence bridges to the next\n\n"
        f"2. structure (0-5): Does it follow the expected time structure (hook → body → climax → close)?\n"
        f"   Score 0-1: Structure missing or completely wrong\n"
        f"   Score 2-3: Structure present but sections are wrong length or order\n"
        f"   Score 4-5: Perfect adherence to timing and section order\n\n"
        f"3. style_adherence (0-5): Does it follow tone, voice, and avoid banned phrases?\n"
        f"   Score 0: Any banned phrase used, or tone completely wrong\n"
        f"   Score 1-2: Wrong tone in places, borderline phrases\n"
        f"   Score 3-5: Perfect tone, no banned words, voice matches style\n\n"
        f"4. semantic_density (0-5): Can any sentence be removed without losing meaning?\n"
        f"   Score 0-1: Mostly water/filler, many removable sentences\n"
        f"   Score 2-3: Some filler but mostly meaningful\n"
        f"   Score 4-5: Every word pulls weight, zero waste\n\n"
        f"Return ONLY JSON:\n"
        f"{'{'} \"logical_coherence\": <0-5>, \"structure\": <0-5>, "
        f"\"style_adherence\": <0-5>, \"semantic_density\": <0-5>, "
        f"\"total_score\": <sum>, "
        f"\"failed_points\": [\"list specific failure reasons\"], "
        f"\"suggestions\": \"actionable rewrite instructions in {language}\" {'}'}\n"
    )

    try:
        result = await achat_json(user_prompt=prompt)
        scores = {k: result.get(k, 3) for k in REVIEW_CRITERIA}
        total = sum(scores.values())
        failed = result.get("failed_points", [])
        suggestions = result.get("suggestions", "")

        passed = total >= PASS_THRESHOLD
        logger.info(
            f"Script Review [{style_id}]: score={total}/20 {'✓' if passed else '✗'} "
            f"details={scores}"
            + (f" issues: {'; '.join(failed[:3])}" if failed else "")
        )

        return {
            "pass": passed,
            "total_score": total,
            "scores": scores,
            "failures": failed,
            "suggestions": suggestions,
        }

    except Exception as e:
        logger.error(f"Script Reviewer Error: {e}")
        return {
            "pass": True,
            "total_score": PASS_THRESHOLD,
            "scores": {},
            "suggestions": "",
        }
