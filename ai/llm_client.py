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
        from httpx import Client, Timeout
        timeout = Timeout(45.0, connect=15.0, read=45.0)
        http_client = Client(timeout=timeout)
        _sync_client = OpenAI(
            api_key=_get_api_key(),
            base_url=DEEPSEEK_BASE_URL,
            http_client=http_client,
        )
    return _sync_client


def get_async_client() -> AsyncOpenAI:
    global _async_client
    if _async_client is None:
        from httpx import AsyncClient, Timeout
        timeout = Timeout(45.0, connect=15.0, read=45.0)
        http_client = AsyncClient(timeout=timeout)
        _async_client = AsyncOpenAI(
            api_key=_get_api_key(),
            base_url=DEEPSEEK_BASE_URL,
            http_client=http_client,
        )
    return _async_client


def _strip_markdown(content: str) -> str:
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        content = content.split("```")[1].split("```")[0].strip()
    return content


def _is_boundary_quote(json_str: str, idx: int, n: int) -> bool:
    peek = idx + 1
    while peek < n and json_str[peek].isspace():
        peek += 1
    if peek >= n:
        return True
        
    char = json_str[peek]
    if char == ':':
        post_peek = peek + 1
        while post_peek < n and json_str[post_peek].isspace():
            post_peek += 1
        if post_peek < n and json_str[post_peek] in ('"', '[', '{', 't', 'f', 'n', '-', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9'):
            return True
        return False
        
    if char in (',', '}', ']'):
        post_peek = peek + 1
        while post_peek < n and json_str[post_peek].isspace():
            post_peek += 1
        if post_peek >= n:
            return True
        next_char = json_str[post_peek]
        if char == ',':
            return next_char in ('"', '{', '[', 't', 'f', 'n', '-', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9')
        if char in ('}', ']'):
            return next_char in (',', '}', ']')
        return False
        
    return False


def _escape_inner_quotes(json_str: str) -> str:
    result = []
    in_string = False
    escape_next = False
    n = len(json_str)
    i = 0
    while i < n:
        c = json_str[i]
        if escape_next:
            result.append(c)
            escape_next = False
            i += 1
            continue
            
        if c == '\\':
            result.append(c)
            escape_next = True
            i += 1
            continue
            
        if c == '"':
            if not in_string:
                in_string = True
                result.append(c)
            else:
                if _is_boundary_quote(json_str, i, n):
                    in_string = False
                    result.append(c)
                else:
                    result.append('\\"')
        else:
            result.append(c)
        i += 1
    return "".join(result)


def _parse_json_response(content: str) -> dict:
    cleaned = _strip_markdown(content).strip()
    
    # Try 1: Standard parsing
    try:
        return json.loads(cleaned)
    except Exception:
        pass
        
    # Try 2: Escape unescaped inner quotes in string values
    try:
        escaped = _escape_inner_quotes(cleaned)
        return json.loads(escaped)
    except Exception:
        pass
        
    # Try 3: Use ast.literal_eval for extremely loose and resilient parsing
    try:
        import ast
        prepared = cleaned
        prepared = re.sub(r'\btrue\b', 'True', prepared)
        prepared = re.sub(r'\bfalse\b', 'False', prepared)
        prepared = re.sub(r'\bnull\b', 'None', prepared)
        
        val = ast.literal_eval(prepared)
        if isinstance(val, dict):
            return val
    except Exception as e:
        logger.error(f"Failed all JSON repair attempts. Original error: {e}")
        
    # Final fallback: just raise original json loads
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

    import time
    for attempt in range(3):
        try:
            response = get_client().chat.completions.create(**kwargs)
            return response.choices[0].message.content
        except Exception as e:
            logger.warning(f"Sync LLM error (attempt {attempt+1}/3): {e}")
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def chat_json(
    system_prompt: str = "",
    user_prompt: str = "",
    model: str = DEFAULT_MODEL,
) -> dict:
    import time
    curr_user_prompt = user_prompt
    for attempt in range(3):
        try:
            content = chat_complete(system_prompt, curr_user_prompt, model, json_mode=True)
            return _parse_json_response(content)
        except Exception as e:
            logger.warning(f"JSON parse error in chat_json (attempt {attempt+1}/3): {e}")
            if attempt == 2:
                raise
            time.sleep(2)
            curr_user_prompt += "\n\n[System Note: Your previous response was invalid/truncated JSON. Please output strictly valid, complete JSON.]"


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

    import asyncio
    for attempt in range(3):
        try:
            response = await get_async_client().chat.completions.create(**kwargs)
            return response.choices[0].message.content
        except Exception as e:
            logger.warning(f"Async LLM error (attempt {attempt+1}/3): {e}")
            if attempt == 2:
                raise
            await asyncio.sleep(2 ** attempt)


async def achat_json(
    system_prompt: str = "",
    user_prompt: str = "",
    model: str = DEFAULT_MODEL,
) -> dict:
    import asyncio
    curr_user_prompt = user_prompt
    for attempt in range(3):
        try:
            content = await achat_complete(system_prompt, curr_user_prompt, model, json_mode=True)
            return _parse_json_response(content)
        except Exception as e:
            logger.warning(f"JSON parse error in achat_json (attempt {attempt+1}/3): {e}")
            if attempt == 2:
                raise
            await asyncio.sleep(2)
            curr_user_prompt += "\n\n[System Note: Your previous response was invalid/truncated JSON. Please output strictly valid, complete JSON.]"
