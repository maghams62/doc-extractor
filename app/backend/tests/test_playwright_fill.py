from __future__ import annotations

from pathlib import Path
import textwrap

from backend.automation.fill_form import fill_form


def test_playwright_fill(tmp_path: Path, form_fixture_url: str) -> None:
    payload = {
        "g28": {
            "attorney": {
                "family_name": "Doe",
                "given_name": "Jane",
                "middle_name": "Q",
                "law_firm_name": "Doe Law",
                "licensing_authority": "State Bar of California",
                "bar_number": "123456",
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
            "sex": "F",
            "passport_number": "X1234567",
            "country_of_issue": "United States",
            "nationality": "United States",
            "place_of_birth": "Seattle",
            "date_of_issue": "2015-05-01",
            "date_of_expiration": "2025-05-01",
        },
    }
    run_dir = tmp_path / "run"
    summary = fill_form(payload, run_dir, form_url=form_fixture_url, headless=True, keep_open_ms=0)
    trace = Path(summary["trace_path"])
    assert trace.exists()
    assert len(summary["filled_fields"]) >= 1
    assert len(summary["attempted_fields"]) >= 1
    assert summary.get("dom_readback") is not None
    assert summary["dom_readback"].get("g28.attorney.email") == "jane@example.com"
    assert summary["dom_readback"].get("g28.attorney.licensing_authority") == "State Bar of California"
    assert summary["dom_readback"].get("g28.attorney.bar_number") == "123456"
    assert summary["dom_readback"].get("passport.passport_number") == "X1234567"
    assert summary["field_results"]["g28.attorney.email"]["result"] == "PASS"
    assert summary["field_results"]["passport.passport_number"]["result"] == "PASS"


def test_autofill_prefers_user_values(tmp_path: Path, form_fixture_url: str) -> None:
    payload = {
        "g28": {
            "attorney": {
                "email": "extract@example.com",
            },
        },
        "meta": {
            "resolved_fields": {
                "g28.attorney.email": {
                    "key": "g28.attorney.email",
                    "value": "override@example.com",
                    "status": "green",
                    "confidence": 1.0,
                    "source": "USER",
                    "locked": True,
                    "requires_human_input": False,
                    "reason": "User edit",
                    "suggestions": [],
                    "last_validated_at": "2024-01-01T00:00:00Z",
                    "version": 1,
                }
            }
        },
    }
    run_dir = tmp_path / "run_override"
    summary = fill_form(payload, run_dir, form_url=form_fixture_url, headless=True, keep_open_ms=0)
    assert summary["dom_readback"].get("g28.attorney.email") == "override@example.com"
    assert summary["field_results"]["g28.attorney.email"]["result"] == "PASS"


def test_playwright_checkbox_and_date_inputs(tmp_path: Path) -> None:
    html = textwrap.dedent(
        """
        <!doctype html>
        <html lang="en">
          <head>
            <meta charset="UTF-8" />
            <title>Checkbox + Date Fixture</title>
          </head>
          <body>
            <form>
              <div>
                <label for="apt">Apt.</label>
                <input id="apt" name="apt-type" type="checkbox" value="apt" />
                <label for="ste">Ste.</label>
                <input id="ste" name="apt-type" type="checkbox" value="ste" />
                <label for="flr">Flr.</label>
                <input id="flr" name="apt-type" type="checkbox" value="flr" />
                <input id="apt-number" name="apt-number" type="text" />
              </div>
              <div>
                <label for="passport-dob">5.a. Date of Birth</label>
                <input id="passport-dob" name="passport-dob" type="date" />
              </div>
            </form>
          </body>
        </html>
        """
    ).strip()
    form_path = tmp_path / "checkbox_date_fixture.html"
    form_path.write_text(html)
    payload = {
        "g28": {
            "attorney": {
                "address": {
                    "unit": "Suite 200",
                },
            },
        },
        "passport": {
            "date_of_birth": "01/01/1990",
        },
    }
    run_dir = tmp_path / "run_checkbox"
    summary = fill_form(payload, run_dir, form_url=form_path.resolve().as_uri(), headless=True, keep_open_ms=0)
    unit_result = summary["field_results"]["g28.attorney.address.unit"]
    assert unit_result["result"] == "PASS"
    assert "ste" in (unit_result.get("selector_used") or "")
    assert summary["dom_readback"].get("passport.date_of_birth") == "1990-01-01"
