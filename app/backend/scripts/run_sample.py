from __future__ import annotations

import json
from pathlib import Path

import requests

from backend.config import CONFIG
from backend.main import extract_documents

SAMPLE_URL = "https://alma-public-assets.s3.us-west-2.amazonaws.com/interview/Example_G-28.pdf"


def main() -> None:
    fixtures_dir = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
    local_fixture = fixtures_dir / "Example_G-28.pdf"
    runs_dir = CONFIG.runs_dir / "test_inputs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    g28_path = local_fixture if local_fixture.exists() else (runs_dir / "Example_G-28.pdf")

    if not g28_path.exists():
        resp = requests.get(SAMPLE_URL, timeout=30)
        resp.raise_for_status()
        g28_path.write_bytes(resp.content)

    result = extract_documents(passport_path=None, g28_path=g28_path)
    print(json.dumps(result.model_dump(), indent=2))


if __name__ == "__main__":
    main()
