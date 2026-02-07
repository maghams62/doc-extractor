from __future__ import annotations

from backend.pipeline.confidence import set_field
from backend.pipeline.post_autofill import validate_post_autofill
from backend.schemas import ExtractionResult
from backend.field_registry import iter_fields


def test_post_autofill_label_capture_red() -> None:
    result = ExtractionResult()
    set_field(
        result,
        "g28.attorney.email",
        "Email Address (if any)",
        "OCR",
        None,
        "Email Address (if any)",
    )
    result.meta.presence["g28.attorney.email"] = "present"
    autofill_report = {
        "filled_fields": ["g28.attorney.email"],
        "fill_failures": {},
        "dom_readback": {"g28.attorney.email": "Email Address (if any)"},
    }
    report, _, _ = validate_post_autofill(result, autofill_report, "", "", use_llm=False)
    field = report["fields"]["g28.attorney.email"]
    assert field["status"] == "red"
    assert field["issue_type"] == "SUSPECT_LABEL_CAPTURE"


def test_post_autofill_missing_absent_amber() -> None:
    result = ExtractionResult()
    result.meta.presence["g28.attorney.phone_daytime"] = "absent"
    autofill_report = {"filled_fields": [], "fill_failures": {}, "dom_readback": {}}
    report, _, _ = validate_post_autofill(result, autofill_report, "", "", use_llm=False)
    field = report["fields"]["g28.attorney.phone_daytime"]
    assert field["status"] == "green"
    assert field["issue_type"] == "EMPTY_OPTIONAL"


def test_post_autofill_invalid_email_red() -> None:
    result = ExtractionResult()
    set_field(result, "g28.attorney.email", "not-an-email", "OCR", None, "not-an-email")
    result.meta.presence["g28.attorney.email"] = "present"
    autofill_report = {
        "filled_fields": ["g28.attorney.email"],
        "fill_failures": {},
        "dom_readback": {"g28.attorney.email": "not-an-email"},
    }
    report, _, _ = validate_post_autofill(result, autofill_report, "", "", use_llm=False)
    field = report["fields"]["g28.attorney.email"]
    assert field["status"] == "red"
    assert field["issue_type"] == "INVALID_FORMAT"


def test_llm_reviews_all_fields(monkeypatch) -> None:
    monkeypatch.setenv("LLM_VALIDATE_SCOPE", "all")
    result = ExtractionResult()
    set_field(result, "g28.attorney.email", "not-an-email", "OCR", None, "not-an-email")
    set_field(result, "g28.attorney.given_name", "Jane", "OCR", None, "Jane")
    result.meta.presence["g28.attorney.email"] = "present"
    result.meta.presence["g28.attorney.given_name"] = "present"

    autofill_report = {
        "filled_fields": ["g28.attorney.email", "g28.attorney.given_name"],
        "fill_failures": {},
        "dom_readback": {
            "g28.attorney.email": "not-an-email",
            "g28.attorney.given_name": "Jane",
        },
    }

    called = {"count": 0, "fields": []}

    def llm_stub(contexts):
        called["count"] += len(contexts)
        called["fields"].extend([ctx.get("field") for ctx in contexts])
        return [], None

    validate_post_autofill(result, autofill_report, "", "", use_llm=True, llm_client=llm_stub)
    expected_fields = {spec.key for spec in iter_fields()}
    assert called["count"] == len(expected_fields)
    assert set(called["fields"]) == expected_fields


def test_llm_smart_scope_skips_optional_empty(monkeypatch) -> None:
    monkeypatch.delenv("LLM_VALIDATE_SCOPE", raising=False)
    result = ExtractionResult()
    result.meta.presence["g28.attorney.phone_daytime"] = "absent"
    autofill_report = {"filled_fields": [], "fill_failures": {}, "dom_readback": {}}
    called = {"count": 0, "fields": []}

    def llm_stub(contexts):
        called["count"] += len(contexts)
        called["fields"].extend([ctx.get("field") for ctx in contexts])
        return [], None

    validate_post_autofill(result, autofill_report, "", "", use_llm=True, llm_client=llm_stub)
    assert "g28.attorney.phone_daytime" not in called["fields"]
