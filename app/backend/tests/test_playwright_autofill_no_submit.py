from __future__ import annotations

from pathlib import Path

from backend.automation.fill_form import fill_form


def test_playwright_autofill_no_submit(tmp_path: Path, form_fixture_url: str) -> None:
    payload = {
        "g28": {
            "attorney": {
                "family_name": "Doe",
                "given_name": "Jane",
                "middle_name": "Q",
                "law_firm_name": "Doe Law",
                "licensing_authority": "WA",
                "bar_number": "12345",
                "address": {
                    "street": "123 Main St",
                    "unit": "Suite 200",
                    "city": "Seattle",
                    "state": "WA",
                    "zip": "98101",
                    "country": "USA",
                },
                "phone_daytime": "206-555-1212",
                "phone_mobile": "206-555-3434",
                "email": "jane@example.com",
            },
        },
        "passport": {
            "surname": "DOE",
            "given_names": "JANE",
            "date_of_birth": "1990-01-01",
            "date_of_expiration": "2030-01-01",
            "sex": "F",
            "nationality": "USA",
            "passport_number": "X1234567",
        },
    }
    run_dir = tmp_path / "run"
    summary = fill_form(payload, run_dir, form_url=form_fixture_url, headless=True, keep_open_ms=0)
    trace_path = Path(summary["trace_path"])

    assert trace_path.exists()
    assert len(summary["filled_fields"]) >= 8
    assert len(summary["attempted_fields"]) >= 8
    assert summary.get("dom_readback")
    assert form_fixture_url in summary["final_url"]
    assert "thank" not in summary["final_url"].lower()
    assert "submitted" not in summary["final_url"].lower()
