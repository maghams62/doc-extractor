from __future__ import annotations

import re
from pathlib import Path

from backend.automation.fill_form import fill_form
from backend.field_registry import iter_autofill_fields
from backend.main import extract_documents
from backend.pipeline.normalize import normalize_date


def _get_value(payload: dict, path: str):
    parts = path.split(".")
    value: object = payload
    for part in parts:
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _normalize_compare(value: str) -> str:
    return re.sub(r"\s+", "", str(value).strip()).lower()


def _assert_value_matches(expected: str, actual: str) -> None:
    exp_norm = normalize_date(expected) or _normalize_compare(expected)
    act_norm = normalize_date(actual) or _normalize_compare(actual)
    assert exp_norm == act_norm


def test_autofill_coverage_on_fixtures(
    tmp_path: Path,
    sample_g28_path: Path,
    realistic_passport_path: Path,
    form_fixture_url: str,
) -> None:
    result = extract_documents(
        passport_path=realistic_passport_path,
        g28_path=sample_g28_path,
    )
    payload = result.model_dump()
    run_dir = tmp_path / "run_e2e"
    summary = fill_form(payload, run_dir, form_url=form_fixture_url, headless=True, keep_open_ms=0)

    field_results = summary.get("field_results") or {}
    for spec in iter_autofill_fields():
        path = spec.key
        value = _get_value(payload, path)
        if value is None or str(value).strip() == "":
            continue
        entry = field_results.get(path)
        assert entry is not None, f"Missing field result for {path}"
        assert entry.get("attempted") is True, f"Field not attempted: {path}"
        assert entry.get("result") == "PASS", f"Autofill failed for {path}: {entry.get('failure_reason')}"

    expected_values = {
        "passport.given_names": "Anna Maria",
        "passport.surname": "Eriksson",
        "passport.passport_number": "L898902C3",
        "passport.date_of_birth": "1974-08-12",
        "passport.date_of_expiration": "2012-04-15",
        "passport.sex": "F",
        "g28.attorney.family_name": "Messi",
        "g28.attorney.given_name": "Kaka",
        "g28.attorney.licensing_authority": "State Bar of California",
        "g28.attorney.bar_number": "12083456",
        "g28.attorney.email": "immigration @tryalma.ai",
        "g28.attorney.address.street": "545 Bryant Street",
        "g28.attorney.address.city": "Palo Alto",
        "g28.attorney.address.state": "CA",
        "g28.attorney.address.zip": "94301",
        "g28.attorney.address.country": "United States",
    }
    for path, expected in expected_values.items():
        actual = summary.get("dom_readback", {}).get(path)
        assert actual is not None, f"Missing dom_readback for {path}"
        _assert_value_matches(expected, actual)
