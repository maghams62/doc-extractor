from __future__ import annotations

import pytest

from backend.scripts.release_smoke import run_release_smoke


@pytest.mark.slow
def test_release_smoke() -> None:
    result = run_release_smoke()
    assert result["extract_run_id"]
    assert result["autofill_run_id"]
    assert result["form_url"].startswith("file://")
