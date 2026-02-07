from __future__ import annotations

from pathlib import Path

from backend.automation.fill_form import fill_form


def test_repeatability(tmp_path: Path, form_fixture_url: str) -> None:
    payload = {
        "g28": {
            "attorney": {
                "family_name": "Doe",
                "given_name": "Jane",
                "middle_name": "Q",
                "law_firm_name": "Doe Law",
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
        },
    }

    run_dir1 = tmp_path / "run1"
    run_dir2 = tmp_path / "run2"

    summary1 = fill_form(payload, run_dir1, form_url=form_fixture_url)
    summary2 = fill_form(payload, run_dir2, form_url=form_fixture_url)

    assert summary1["attempted_fields"] == summary2["attempted_fields"]
    assert summary1["filled_fields"] == summary2["filled_fields"]
    assert summary1["fill_failures"] == summary2["fill_failures"]
    assert Path(summary1["trace_path"]).exists()
    assert Path(summary2["trace_path"]).exists()
