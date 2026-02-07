from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

from .label_noise import looks_like_label_value
from .prompts import build_llm_verify_prompt

DEFAULT_OPENAI_ENDPOINT = "https://api.openai.com/v1/chat/completions"
DEFAULT_OPENAI_MODEL = "gpt-4o"


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


def _truncate(text: Optional[str], limit: int = 6000) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _build_prompt(
    passport_text: str,
    g28_text: str,
    result: Dict,
    statuses: Dict[str, str],
    review_fields: List[str],
    autofill_report: Optional[Dict],
) -> str:
    return build_llm_verify_prompt(
        _truncate(passport_text),
        _truncate(g28_text),
        result,
        statuses,
        review_fields,
        autofill_report or {},
    )


def _evidence_grounded(evidence: str, passport_text: str, g28_text: str) -> bool:
    if not evidence:
        return False
    snippet = evidence.strip()
    if not snippet:
        return False
    return snippet in passport_text or snippet in g28_text


def llm_verify(
    passport_text: str,
    g28_text: str,
    result: Dict,
    statuses: Dict[str, str],
    review_fields: List[str],
    autofill_report: Optional[Dict],
) -> Tuple[Dict, Optional[str]]:
    if not _llm_enabled():
        return {}, "LLM disabled (ENABLE_LLM is not set)"
    endpoint, api_key, model, timeout = _resolve_llm_config()
    if not endpoint:
        return {}, "LLM endpoint not configured"
    if not api_key:
        return {}, "LLM API key not configured"

    prompt = _build_prompt(
        passport_text,
        g28_text,
        result,
        statuses,
        review_fields,
        autofill_report,
    )
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
        return {}, f"LLM verify failed: {exc}"

    if not isinstance(parsed, dict):
        return {}, "LLM verify returned non-object JSON"

    issues = parsed.get("issues") or []
    suggestions = parsed.get("suggestions") or {}
    summary = parsed.get("summary") or ""

    filtered_suggestions: Dict[str, List[Dict]] = {}
    if isinstance(suggestions, dict):
        for field, values in suggestions.items():
            if review_fields and field not in review_fields:
                continue
            if not isinstance(values, list):
                continue
            cleaned: List[Dict] = []
            for item in values:
                if not isinstance(item, dict):
                    continue
                value = item.get("value")
                evidence = item.get("evidence") or ""
                if not value or looks_like_label_value(str(value)):
                    continue
                if not _evidence_grounded(str(evidence), passport_text, g28_text):
                    continue
                cleaned.append(
                    {
                        "value": str(value),
                        "reason": item.get("reason") or "LLM verification suggestion",
                        "evidence": str(evidence),
                        "confidence": item.get("confidence"),
                        "requires_confirmation": bool(item.get("requires_confirmation", False)),
                    }
                )
            if cleaned:
                filtered_suggestions[field] = cleaned

    filtered_issues: List[Dict] = []
    if isinstance(issues, list):
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            filtered_issues.append(
                {
                    "field": issue.get("field") or "",
                    "severity": issue.get("severity") or "warning",
                    "message": issue.get("message") or "Verifier issue.",
                    "evidence": issue.get("evidence") or "",
                }
            )

    return {
        "issues": filtered_issues,
        "suggestions": filtered_suggestions,
        "summary": summary,
    }, None
