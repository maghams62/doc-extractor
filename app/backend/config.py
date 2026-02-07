from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).parent
FORM_URL_ENV = "ALMA_FORM_URL"


def _load_dotenv() -> None:
    repo_root = Path(__file__).resolve().parents[2]
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


_load_dotenv()


@dataclass(frozen=True)
class AutofillConfig:
    headless: bool = os.getenv("ALMA_AUTOFILL_HEADLESS", "false").lower() == "true"
    slow_mo_ms: int = int(os.getenv("ALMA_AUTOFILL_SLOW_MO_MS", "0"))
    # Negative keeps the browser open indefinitely for manual consent.
    keep_open_ms: int = int(os.getenv("ALMA_AUTOFILL_KEEP_OPEN_MS", "-1"))
    form_url: str = "https://mendrika-alma.github.io/form-submission/"


@dataclass(frozen=True)
class ExtractionConfig:
    use_llm_extract: bool = False


@dataclass(frozen=True)
class ValidationConfig:
    use_llm: bool = os.getenv("ENABLE_LLM", "true").lower() in {"1", "true", "yes"}


@dataclass(frozen=True)
class AppConfig:
    log_level: str = "INFO"
    runs_dir: Path = BASE_DIR / "runs"
    autofill: AutofillConfig = field(default_factory=AutofillConfig)
    extraction: ExtractionConfig = field(default_factory=ExtractionConfig)
    validation: ValidationConfig = field(default_factory=ValidationConfig)


CONFIG = AppConfig()


def resolve_form_url(override: Optional[str] = None) -> str:
    if override:
        return override
    env_value = os.getenv(FORM_URL_ENV)
    if env_value:
        return env_value
    return CONFIG.autofill.form_url
