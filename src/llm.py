"""Thin OpenAI-compatible client wrapper shared by all agents (Gemini direct or OpenRouter)."""
import json
import re
from functools import lru_cache
from typing import Any, Dict, List, Optional

from src import config


class LLMError(RuntimeError):
    pass


@lru_cache(maxsize=None)
def get_client(api_key: str):
    from openai import OpenAI

    # Gemini returns transient 503s under load; the SDK retries 5xx/429 with backoff.
    return OpenAI(base_url=config.LLM_BASE_URL, api_key=api_key, max_retries=5, timeout=180)


def build_user_content(text: str, image_urls: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    content: List[Dict[str, Any]] = [{"type": "text", "text": text}]
    for url in image_urls or []:
        content.append({"type": "image_url", "image_url": {"url": url}})
    return content


def chat(
    agent: str,
    system: str,
    user: str,
    image_urls: Optional[List[str]] = None,
    temperature: float = 0.0,
    max_tokens: int = 4000,
    json_mode: bool = False,
    reasoning: bool = True,
) -> str:
    """agent: one of config.AGENT_NAMES; selects that agent's model and API key."""
    settings = config.AGENTS[agent]
    if not settings["api_key"]:
        raise LLMError(f"No API key for agent '{agent}'. Set {agent.upper()}_API_KEY or LLM_API_KEY in .env.")
    model = settings["model"]
    kwargs: Dict[str, Any] = dict(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": build_user_content(user, image_urls)},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    if not reasoning:
        # Thinking models (Gemini 2.5) otherwise spend the token budget on reasoning tokens.
        if config.IS_GEMINI:
            kwargs["reasoning_effort"] = "none"
        else:
            kwargs["extra_body"] = {"reasoning": {"enabled": False}}

    response = get_client(settings["api_key"]).chat.completions.create(**kwargs)
    if not response.choices or not response.choices[0].message.content:
        raise LLMError(f"Empty response from model '{model}' ({agent}).")
    return response.choices[0].message.content


def parse_json(text: str) -> Any:
    """Parse a model reply as JSON, tolerating ```json fences and leading/trailing prose."""
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # Fall back to the outermost {...} or [...] block.
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start, end = cleaned.find(open_ch), cleaned.rfind(close_ch)
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise LLMError(f"Model did not return valid JSON: {text[:300]}")


def chat_json(agent: str, system: str, user: str, **kwargs) -> Any:
    return parse_json(chat(agent, system, user, json_mode=True, **kwargs))
