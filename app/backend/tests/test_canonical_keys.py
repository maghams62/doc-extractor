from __future__ import annotations

from backend.schemas import ExtractionResult


def test_canonical_schema_keys() -> None:
    result = ExtractionResult()
    dumped = result.model_dump()
    assert set(dumped["g28"].keys()) == {"attorney", "client"}
    # Ensure no old flat attorney keys exist at the top level of g28.
    assert not any(key.startswith("attorney_") for key in dumped["g28"].keys())
