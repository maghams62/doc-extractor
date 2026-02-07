from __future__ import annotations

from backend.pipeline.confidence import set_field
from backend.pipeline.validate import validate_and_annotate
from backend.schemas import ExtractionResult


def test_missing_label_present_marks_red_with_placeholder() -> None:
    result = ExtractionResult()
    result.meta.presence["g28.attorney.email"] = "present"
    validate_and_annotate(result)
    assert result.meta.status["g28.attorney.email"] == "red"
    suggestions = result.meta.suggestions.get("g28.attorney.email", [])
    assert suggestions
    assert suggestions[0].reason is not None


def test_missing_label_absent_marks_yellow() -> None:
    result = ExtractionResult()
    result.meta.presence["g28.attorney.phone_daytime"] = "absent"
    validate_and_annotate(result)
    assert result.meta.status["g28.attorney.phone_daytime"] == "yellow"


def test_invalid_email_confidence_cap() -> None:
    result = ExtractionResult()
    set_field(result, "g28.attorney.email", "not-an-email", "OCR", None, "snippet")
    validate_and_annotate(result)
    assert result.meta.status["g28.attorney.email"] == "red"
    assert result.meta.confidence["g28.attorney.email"] <= 0.3


def test_mrz_date_green_confidence() -> None:
    result = ExtractionResult()
    set_field(result, "passport.date_of_birth", "1990-01-01", "MRZ", None, "MRZ")
    validate_and_annotate(result)
    assert result.meta.status["passport.date_of_birth"] == "green"
    assert result.meta.confidence["passport.date_of_birth"] >= 0.9


def test_user_override_confidence() -> None:
    result = ExtractionResult()
    set_field(result, "passport.surname", "DOE", "USER", None, "UI")
    validate_and_annotate(result)
    assert result.meta.sources["passport.surname"] == "USER"
    assert result.meta.confidence["passport.surname"] == 1.0
    assert result.meta.status["passport.surname"] == "green"


def test_header_noise_marks_invalid() -> None:
    result = ExtractionResult()
    set_field(
        result,
        "g28.attorney.family_name",
        "Notice of Entry of Appearance",
        "OCR",
        None,
        "Notice of Entry of Appearance as Attorney or Accredited Representative",
    )
    report = validate_and_annotate(result)
    assert result.meta.status["g28.attorney.family_name"] == "red"
    assert any(issue.rule == "label_noise" for issue in report.issues)


def test_label_noise_marks_invalid() -> None:
    result = ExtractionResult()
    set_field(
        result,
        "g28.attorney.email",
        "Address (if any)",
        "OCR",
        None,
        "Email Address (if any)",
    )
    report = validate_and_annotate(result)
    assert result.meta.status["g28.attorney.email"] == "red"
    assert any(issue.rule == "label_noise" for issue in report.issues)


def test_licensing_authority_numeric_invalid() -> None:
    result = ExtractionResult()
    set_field(
        result,
        "g28.attorney.licensing_authority",
        "12345678",
        "OCR",
        None,
        "Licensing Authority",
    )
    report = validate_and_annotate(result)
    assert result.meta.status["g28.attorney.licensing_authority"] == "red"
    assert any(issue.rule == "licensing_authority_numeric" for issue in report.issues)


def test_state_numeric_marks_red() -> None:
    result = ExtractionResult()
    set_field(
        result,
        "g28.attorney.address.state",
        "94301",
        "OCR",
        None,
        "State | 94301",
    )
    report = validate_and_annotate(result)
    assert result.meta.status["g28.attorney.address.state"] == "red"
    assert any(issue.rule == "state_format" for issue in report.issues)


def test_punctuation_name_marks_red() -> None:
    result = ExtractionResult()
    set_field(result, "g28.attorney.family_name", ")", "OCR", None, ")")
    report = validate_and_annotate(result)
    assert result.meta.status["g28.attorney.family_name"] == "red"


def test_mrz_check_digit_failure_marks_red() -> None:
    result = ExtractionResult()
    mrz_lines = (
        "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<\n"
        "L898902C30UTO7408122F1204159ZE184226B<<<<<10"
    )
    set_field(result, "passport.passport_number", "L898902C3", "MRZ", None, mrz_lines)
    result.meta.presence["passport.mrz"] = "present"
    report = validate_and_annotate(result)
    assert result.meta.status["passport.passport_number"] == "red"
    assert any(issue.rule == "mrz_check_digit" for issue in report.issues)
