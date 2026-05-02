import os
import json
import re
import logging
from openai import OpenAI, AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_sync_client = None
_async_client = None

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


def _get_api_key():
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        logger.warning("DEEPSEEK_API_KEY not found in environment")
    return key


def get_client() -> OpenAI:
    global _sync_client
    if _sync_client is None:
        _sync_client = OpenAI(api_key=_get_api_key(), base_url=DEEPSEEK_BASE_URL)
    return _sync_client


def get_async_client() -> AsyncOpenAI:
    global _async_client
    if _async_client is None:
        _async_client = AsyncOpenAI(api_key=_get_api_key(), base_url=DEEPSEEK_BASE_URL)
    return _async_client


def _strip_markdown(content: str) -> str:
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        content = content.split("```")[1].split("```")[0].strip()
    return content


def _parse_json_response(content: str) -> dict:
    cleaned = _strip_markdown(content)
    return json.loads(cleaned)


def chat_complete(
    system_prompt: str = "",
    user_prompt: str = "",
    model: str = DEFAULT_MODEL,
    json_mode: bool = False,
) -> str:
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})

    kwargs = {"model": model, "messages": messages}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    response = get_client().chat.completions.create(**kwargs)
    return response.choices[0].message.content


def chat_json(
    system_prompt: str = "",
    user_prompt: str = "",
    model: str = DEFAULT_MODEL,
) -> dict:
    content = chat_complete(system_prompt, user_prompt, model, json_mode=True)
    return _parse_json_response(content)


async def achat_complete(
    system_prompt: str = "",
    user_prompt: str = "",
    model: str = DEFAULT_MODEL,
    json_mode: bool = False,
) -> str:
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})

    kwargs = {"model": model, "messages": messages}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    response = await get_async_client().chat.completions.create(**kwargs)
    return response.choices[0].message.content


async def achat_json(
    system_prompt: str = "",
    user_prompt: str = "",
    model: str = DEFAULT_MODEL,
) -> dict:
    content = await achat_complete(system_prompt, user_prompt, model, json_mode=True)
    return _parse_json_response(content)
