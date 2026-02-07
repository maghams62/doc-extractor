from __future__ import annotations

from backend.main import extract_documents, extract_documents_with_text
from backend.pipeline.validate import validate_and_annotate


def test_synthetic_g28_fixture(synthetic_g28_path) -> None:
    result = extract_documents(passport_path=None, g28_path=synthetic_g28_path)
    assert result.g28.attorney.email or any(
        w.field == "g28.attorney.email" for w in result.meta.warnings
    )


def test_synthetic_passport_fixture(synthetic_passport_path) -> None:
    result = extract_documents(passport_path=synthetic_passport_path, g28_path=None)
    # MRZ OCR should usually populate passport number; fall back to warning if not.
    assert result.passport.passport_number or any(
        w.code == "mrz_missing" for w in result.meta.warnings
    )


def test_passport_jpg_ocr_nonempty(synthetic_passport_jpg_path) -> None:
    _, passport_text, _ = extract_documents_with_text(
        passport_path=synthetic_passport_jpg_path,
        g28_path=None,
    )
    assert passport_text.strip()


def test_realistic_passport_mrz_extraction(realistic_passport_path) -> None:
    result = extract_documents(passport_path=realistic_passport_path, g28_path=None)
    assert result.passport.given_names == "Anna Maria"
    assert result.passport.surname == "Eriksson"
    assert result.passport.passport_number == "L898902C3"
    assert result.passport.date_of_birth == "1974-08-12"
    assert result.passport.date_of_expiration == "2012-04-15"
    assert result.passport.sex == "F"

    report = validate_and_annotate(result, use_llm=False)
    assert not any(issue.rule == "mrz_check_digit" for issue in report.issues)
