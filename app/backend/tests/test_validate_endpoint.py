from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app


client = TestClient(app)


def test_validate_endpoint() -> None:
    payload = {
        "passport": {
            "surname": "DOE",
            "given_names": "JANE",
            "date_of_birth": "1990-01-01",
            "date_of_expiration": "2030-01-01",
            "sex": "F",
            "passport_number": "X1234567",
        },
        "g28": {
            "attorney": {
                "family_name": "Doe",
                "given_name": "Jane",
                "email": "jane@example.com",
                "address": {
                    "state": "WA",
                    "zip": "98101",
                },
            },
        },
        "meta": {
            "presence": {
                "g28.attorney.address.street": "present",
            },
        },
    }
    resp = client.post("/validate", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    report = body["report"]
    assert "result" in body
    suggestions = body["result"]["meta"]["suggestions"]
    assert "g28.attorney.address.street" in suggestions
    assert "issues" in report
    assert "score" in report
    assert isinstance(report["issues"], list)
