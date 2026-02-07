from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

from .prompts import build_llm_extract_prompt, build_llm_recover_prompt

DEFAULT_OPENAI_ENDPOINT = "https://api.openai.com/v1/chat/completions"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


def _load_dotenv() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    candidates = [repo_root / ".env", Path.cwd() / ".env"]
    for env_path in candidates:
        if not env_path.exists():
            continue
        try:
            for line in env_path.read_text().splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                key, value = stripped.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
        except Exception:  # noqa: BLE001
            continue
        break


def _resolve_llm_config() -> Tuple[Optional[str], Optional[str], str, float]:
    _load_dotenv()
    endpoint = os.getenv("LLM_ENDPOINT")
    api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    model = (
        os.getenv("LLM_MODEL")
        or os.getenv("OPENAI_MODEL")
        or DEFAULT_OPENAI_MODEL
    ).strip()
    if not endpoint and os.getenv("OPENAI_API_KEY"):
        endpoint = DEFAULT_OPENAI_ENDPOINT
    timeout = float(os.getenv("LLM_TIMEOUT", "20"))
    return endpoint, api_key, model, timeout


def _llm_enabled() -> bool:
    return os.getenv("ENABLE_LLM", "").strip().lower() in {"1", "true", "yes"}


def _truncate(text: Optional[str], limit: int = 4000) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _build_prompt(passport_text: str, g28_text: str, missing_fields: List[str], existing: Dict) -> str:
    return build_llm_extract_prompt(
        _truncate(passport_text),
        _truncate(g28_text),
        missing_fields,
        existing,
    )


def _build_field_prompt(field_contexts: List[Dict], existing: Dict) -> str:
    return build_llm_recover_prompt(field_contexts, existing)


def llm_extract_missing(
    passport_text: str,
    g28_text: str,
    missing_fields: List[str],
    existing: Dict,
) -> Tuple[List[Dict], Optional[str]]:
    if not _llm_enabled():
        return {}, "LLM disabled (ENABLE_LLM is not set)"
    endpoint, api_key, model, timeout = _resolve_llm_config()
    if not endpoint:
        return {}, "LLM endpoint not configured"
    if not api_key:
        return {}, "LLM API key not configured"
    if not missing_fields:
        return [], None

    prompt = _build_prompt(passport_text, g28_text, missing_fields, existing)
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Return JSON only. Do not wrap in markdown."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }
    try:
        resp = requests.post(endpoint, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        parsed = json.loads(content)
    except Exception as exc:  # noqa: BLE001
        return [], f"LLM extraction failed: {exc}"

    if not isinstance(parsed, dict):
        return [], "LLM extraction returned non-object JSON"
    suggestions = parsed.get("suggestions")
    if not isinstance(suggestions, list):
        return [], "LLM extraction returned missing suggestions list"
    return suggestions, None


def llm_recover_fields(
    field_contexts: List[Dict],
    existing: Dict,
) -> Tuple[List[Dict], Optional[str]]:
    if not _llm_enabled():
        return [], "LLM disabled (ENABLE_LLM is not set)"
    endpoint, api_key, model, timeout = _resolve_llm_config()
    if not endpoint:
        return [], "LLM endpoint not configured"
    if not api_key:
        return [], "LLM API key not configured"
    if not field_contexts:
        return [], None

    prompt = _build_field_prompt(field_contexts, existing)
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Return JSON only. Do not wrap in markdown."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }
    try:
        resp = requests.post(endpoint, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        parsed = json.loads(content)
    except Exception as exc:  # noqa: BLE001
        return [], f"LLM recovery failed: {exc}"

    if not isinstance(parsed, dict):
        return [], "LLM recovery returned non-object JSON"
    suggestions = parsed.get("suggestions")
    if not isinstance(suggestions, list):
        return [], "LLM recovery returned missing suggestions list"
    return suggestions, None
