from __future__ import annotations

from backend.pipeline.confidence import estimate_confidence, set_field
from backend.schemas import ExtractionResult


def test_estimate_confidence_uses_source_and_value() -> None:
    # Different sources should yield different bases.
    assert estimate_confidence("MRZ", "ABC123") > estimate_confidence("LLM", "ABC123")

    # Richer evidence/value should yield higher score than empty.
    low = estimate_confidence("OCR", "A")
    high = estimate_confidence("OCR", "Longer value 123 with evidence", "snippet")
    assert high > low
    assert 0.0 <= high <= 0.99


def test_set_field_uses_estimate_when_confidence_missing() -> None:
    result = ExtractionResult()
    set_field(result, "passport.passport_number", "X1234567", "OCR", None, "page 1")
    conf = result.meta.confidence["passport.passport_number"]
    assert conf >= 0.8
    assert conf <= 0.99
