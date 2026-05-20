import json
import logging

logger = logging.getLogger(__name__)


class BatchReviewer:
    """Пакетный AI-ревьюер: 1 LLM вызов на проект проверяет все скачанные
    изображения на контекстные нестыковки и обновляет knowledge base."""

    async def review_assets(
        self,
        project_id: str,
        channel: str,
        queue: list[dict],
    ) -> dict:
        """
        1 LLM вызов для ВСЕХ сцен в очереди.

        queue = [
          {"scene_idx": 5, "entity_keys": ["theotokos"], "url": "https://...", "score": 8},
          {"scene_idx": 7, "entity_keys": ["st_nicholas"], "url": "https://...", "score": 6},
        ]

        Returns: {"5": "ok", "7": {"status": "mismatch", "reason": "...", "new_filters": {...}}}
        """
        if not queue:
            return {}

        from ai.llm_client import achat_json

        prompt = (
            "You are an Orthodox content quality auditor. "
            "Your task is to catch ONLY obviously wrong images.\n\n"
            "RULES:\n"
            "1. 95% of images ARE CORRECT icons/religious photos. Return 'ok' for those.\n"
            "2. Mark MISMATCH ONLY if the image is CLEARLY WRONG:\n"
            "   - A photo of a random girl/woman instead of Virgin Mary icon\n"
            "   - A cosplay/costume photo instead of a saint icon\n"
            "   - A commercial product/advertisement instead of a religious image\n"
            "   - A cartoon/meme/parody instead of an icon\n"
            "   - A fashion/beauty/celebrity photo instead of religious content\n"
            "3. TRADITIONAL ICONS (gold background, Byzantine style, Eastern Orthodox) "
            "are ALWAYS CORRECT — do NOT mark them as mismatch.\n"
            "4. Church interiors, candles, crosses are ALWAYS CORRECT.\n\n"
            "If MISMATCH, you MUST suggest concrete keywords to exclude:\n"
            '  new_filters: {"exclude_url_add": ["keyword1", "keyword2"], '
            '"exclude_tags_add": ["keyword3", "keyword4"]}\n\n'
        )

        for item in queue:
            keys = item.get("entity_keys", [])
            url = item.get("url", "")[:120]
            score = item.get("score", 0)
            prompt += (
                f"SCENE {item['scene_idx']} — key: {', '.join(keys)}\n"
                f"  URL: {url}\n"
                f"  Score: {score}/10\n\n"
            )

        prompt += (
            'Return JSON — one key per scene:\n'
            '{\n'
            '  "5": "ok",\n'
            '  "7": {\n'
            '    "status": "mismatch",\n'
            '    "reason": "A cosplay photo, not an Orthodox icon",\n'
            '    "new_filters": {\n'
            '      "exclude_url_add": ["cosplay", "costume"],\n'
            '      "exclude_tags_add": ["cosplay", "costume", "halloween"]\n'
            '    }\n'
            '  }\n'
            '}\n'
            'For OK scenes just return "ok" (the string). '
            'For MISMATCH return an object with status, reason, and new_filters.'
        )

        try:
            result = await achat_json(user_prompt=prompt)
            return result
        except Exception as e:
            logger.error(f"BatchReviewer error: {e}")
            return {}


# Singleton
batch_reviewer = BatchReviewer()
