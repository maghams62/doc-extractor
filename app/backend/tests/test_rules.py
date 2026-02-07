from __future__ import annotations

from backend.pipeline.rules import validate_field


def test_email_normalization() -> None:
    result = validate_field("g28.attorney.email", "email", "immigration @tryalma.ai", [])
    assert result.is_valid
    assert result.normalized == "immigration@tryalma.ai"


def test_invalid_email() -> None:
    result = validate_field("g28.attorney.email", "email", "address (if any)", ["Email Address"])
    assert not result.is_valid


def test_phone_validation() -> None:
    result = validate_field("g28.client.phone", "phone", "+61 454 534 34", [])
    assert result.is_valid


def test_state_validation() -> None:
    ok = validate_field("g28.attorney.address.state", "state", "CA", [])
    assert ok.is_valid
    bad = validate_field("g28.attorney.address.state", "state", "94301", [])
    assert not bad.is_valid


def test_zip_validation_with_country() -> None:
    ok = validate_field(
        "g28.client.address.zip",
        "zip",
        "6000",
        [],
        context={"country": "Australia"},
    )
    assert ok.is_valid


def test_name_validation() -> None:
    ok = validate_field("g28.attorney.family_name", "name", "Messi", ["Family Name"])
    assert ok.is_valid
    bad = validate_field("g28.attorney.family_name", "name", ")", ["Family Name"])
    assert not bad.is_valid

