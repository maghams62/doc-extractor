import json

from fastapi.testclient import TestClient

from backend import main


def test_detect_language_creates_text_artifact(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "RUNS_DIR", tmp_path)
    run_dir = tmp_path / "lang_run"
    (run_dir / "inputs").mkdir(parents=True)
    (run_dir / "ocr_text.txt").write_text(
        "This is a short English document used for language detection."
    )

    client = TestClient(main.app)
    response = client.post("/detect_language", data={"run_id": "lang_run", "doc_type": "g28"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["doc_type"] == "g28"
    assert payload["text_active"] == "raw"
    assert payload["detected_language"] == "en"

    artifact_path = run_dir / "doc_artifacts" / "g28" / "text_artifact.json"
    assert artifact_path.exists()
    artifact = json.loads(artifact_path.read_text())
    assert artifact["doc_type"] == "g28"
    assert artifact["text"]["raw"].startswith("This is a short English document")
    assert artifact["text"]["active"] == "raw"
    assert artifact["language"]["detected"] == "en"


def test_text_artifact_active_toggle_persists(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "RUNS_DIR", tmp_path)
    run_dir = tmp_path / "toggle_run"
    (run_dir / "inputs").mkdir(parents=True)
    (run_dir / "ocr_text.txt").write_text("Hola mundo")

    def fake_translate(text: str):
        return "Hello world", None

    monkeypatch.setattr(main, "translate_text", fake_translate)

    client = TestClient(main.app)
    response = client.post("/translate", data={"run_id": "toggle_run", "doc_type": "passport"})
    assert response.status_code == 200

    toggle_response = client.post(
        "/text_artifact/active",
        data={"run_id": "toggle_run", "doc_type": "passport", "active": "raw"},
    )
    assert toggle_response.status_code == 200
    payload = toggle_response.json()
    assert payload["text_active"] == "raw"

    artifact_path = run_dir / "doc_artifacts" / "passport" / "text_artifact.json"
    artifact = json.loads(artifact_path.read_text())
    assert artifact["text"]["active"] == "raw"
