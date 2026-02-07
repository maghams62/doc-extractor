from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import RUNS_DIR, app
from backend.pipeline.confidence import set_field
from backend.schemas import ExtractionResult, ResolvedField
from backend.pipeline.post_autofill import validate_post_autofill
from backend.field_registry import iter_fields


client = TestClient(app)


def _make_run_dir(run_id: str) -> Path:
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def test_save_field_edits_updates_resolved_fields() -> None:
    run_id = "test_run_save_edits"
    run_dir = _make_run_dir(run_id)
    result = ExtractionResult()
    set_field(result, "g28.attorney.email", "old@example.com", "OCR", None, "old@example.com")
    (run_dir / "extracted.json").write_text(json.dumps(result.model_dump()))

    resp = client.post(
        "/save_field_edits",
        json={"run_id": run_id, "edits": {"g28.attorney.email": "user@example.com"}},
    )
    assert resp.status_code == 200
    body = resp.json()
    resolved = body["result"]["meta"]["resolved_fields"]["g28.attorney.email"]
    assert resolved["value"] == "user@example.com"
    assert resolved["source"] == "USER"
    assert resolved["locked"] is True


def test_locked_fields_not_sent_to_llm(monkeypatch) -> None:
    monkeypatch.setenv("LLM_VALIDATE_SCOPE", "all")
    result = ExtractionResult()
    set_field(result, "g28.attorney.email", "user@example.com", "OCR", None, "user@example.com")
    set_field(result, "g28.attorney.phone_daytime", "not-a-phone", "OCR", None, "not-a-phone")
    result.meta.presence["g28.attorney.email"] = "present"
    result.meta.presence["g28.attorney.phone_daytime"] = "present"
    result.meta.resolved_fields["g28.attorney.email"] = ResolvedField(
        key="g28.attorney.email",
        value="user@example.com",
        status="green",
        confidence=1.0,
        source="USER",
        locked=True,
        requires_human_input=False,
        reason="Locked by user.",
        suggestions=[],
        last_validated_at="2024-01-01T00:00:00Z",
        version=1,
    )
    autofill_report = {
        "filled_fields": ["g28.attorney.email", "g28.attorney.phone_daytime"],
        "fill_failures": {},
        "dom_readback": {
            "g28.attorney.email": "user@example.com",
            "g28.attorney.phone_daytime": "not-a-phone",
        },
    }

    called = {"count": 0, "locked_seen": False, "fields": []}

    def llm_stub(contexts):
        called["count"] += len(contexts)
        called["fields"].extend([ctx.get("field") for ctx in contexts])
        called["locked_seen"] = called["locked_seen"] or any(
            ctx.get("field") == "g28.attorney.email" for ctx in contexts
        )
        return [], None

    validate_post_autofill(result, autofill_report, "", "", use_llm=True, llm_client=llm_stub)
    expected_fields = {spec.key for spec in iter_fields()}
    expected_fields.discard("g28.attorney.email")
    assert called["count"] == len(expected_fields)
    assert set(called["fields"]) == expected_fields
    assert called["locked_seen"] is False


def test_final_snapshot_written() -> None:
    run_id = "test_run_snapshot"
    run_dir = _make_run_dir(run_id)
    result = ExtractionResult()
    set_field(result, "g28.attorney.email", "jane@example.com", "OCR", None, "jane@example.com")
    (run_dir / "extracted.json").write_text(json.dumps(result.model_dump()))

    resp = client.post(
        "/post_autofill_validate",
        json={
            "run_id": run_id,
            "result": result.model_dump(),
            "autofill_report": {"filled_fields": [], "fill_failures": {}, "dom_readback": {}},
        },
    )
    assert resp.status_code == 200
    snapshot_path = run_dir / "final_snapshot.json"
    coverage_path = run_dir / "e2e_coverage_report.json"
    assert snapshot_path.exists()
    assert coverage_path.exists()
    snapshot = json.loads(snapshot_path.read_text())
    assert snapshot["run_id"] == run_id
    assert "resolved_fields" in snapshot
    assert "summary" in snapshot
