from __future__ import annotations

from backend.pipeline.confidence import set_field
from backend.schemas import ExtractionResult


def test_schema_shape_and_meta() -> None:
    result = ExtractionResult()
    set_field(result, "passport.passport_number", "X1234567", "OCR", 0.8, "snippet")

    dumped = result.model_dump()
    assert set(dumped.keys()) == {"passport", "g28", "meta"}
    assert "passport_number" in dumped["passport"]
    assert "attorney" in dumped["g28"]
    assert "client" in dumped["g28"]
    assert "sources" in dumped["meta"]
    assert "confidence" in dumped["meta"]
    assert "status" in dumped["meta"]
    assert "suggestions" in dumped["meta"]
    assert "presence" in dumped["meta"]
    assert "warnings" in dumped["meta"]

    non_null_fields = [
        ("passport.passport_number", result.passport.passport_number),
    ]
    for path, value in non_null_fields:
        assert value is not None
        assert path in result.meta.sources
        conf = result.meta.confidence.get(path)
        assert conf is not None
        assert 0.0 <= conf <= 1.0
