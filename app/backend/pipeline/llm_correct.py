from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple


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


def _llm_enabled() -> bool:
    _load_dotenv()
    return os.getenv("ENABLE_LLM", "").strip().lower() in {"1", "true", "yes"}


def llm_correct_fields(
    passport_text: str,
    g28_text: str,
    existing: Dict,
) -> Tuple[List[Dict], Optional[str]]:
    # Placeholder implementation: corrections prompt/logic not defined in this repo.
    if not _llm_enabled():
        return [], "LLM disabled (ENABLE_LLM is not set)"
    return [], "LLM correction not configured"
