from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple

import requests

from .ingest import load_document, preprocess_image
from .ocr import ocr_image
from .prompts import build_llm_translation_prompt


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
    timeout = float(os.getenv("LLM_TIMEOUT", "30"))
    return endpoint, api_key, model, timeout


def _llm_enabled() -> bool:
    return os.getenv("ENABLE_LLM", "").strip().lower() in {"1", "true", "yes"}


def extract_ocr_text(path: Path, max_chars: Optional[int] = None) -> str:
    pages = load_document(path)
    chunks: list[str] = []
    total = 0
    for page in pages:
        pre = preprocess_image(page)
        ocr = ocr_image(pre)
        if ocr.text:
            chunks.append(ocr.text)
            total += len(ocr.text)
        if max_chars is not None and total >= max_chars:
            break
    return "\n".join(chunks)


def _build_translation_prompt(text: str) -> str:
    return build_llm_translation_prompt(text)


def translate_text(text: str) -> Tuple[Optional[str], Optional[str]]:
    if not _llm_enabled():
        return None, "LLM disabled (ENABLE_LLM is not set)"
    endpoint, api_key, model, timeout = _resolve_llm_config()
    if not endpoint:
        return None, "LLM endpoint not configured"
    if not api_key:
        return None, "LLM API key not configured"
    if not text or not text.strip():
        return None, "OCR text empty"

    prompt = _build_translation_prompt(text)
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Return only translated text. Do not wrap in markdown."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }
    try:
        resp = requests.post(endpoint, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception as exc:  # noqa: BLE001
        return None, f"LLM translation failed: {exc}"

    if not content or not content.strip():
        return None, "LLM translation returned empty text"
    return content.strip(), None


def translation_engine_name() -> str:
    _, _, model, _ = _resolve_llm_config()
    return model
