import json

from fastapi.testclient import TestClient

from backend import main


def test_translate_endpoint_with_mock_llm(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "RUNS_DIR", tmp_path)
    run_dir = tmp_path / "translate_run"
    (run_dir / "inputs").mkdir(parents=True)
    (run_dir / "ocr_text.txt").write_text("Hola mundo")
    def fake_translate(text: str):
        assert text == "Hola mundo"
        return "Hello world", None

    monkeypatch.setattr(main, "translate_text", fake_translate)

    client = TestClient(main.app)
    response = client.post("/translate", data={"run_id": "translate_run", "doc_type": "passport"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["translated_text"] == "Hello world"
    assert payload["text_active"] == "translated_en"
    assert (run_dir / "translated_text.txt").exists()
    assert (run_dir / "translated_ocr.json").exists()
    artifact_path = run_dir / "doc_artifacts" / "passport" / "text_artifact.json"
    assert artifact_path.exists()
    artifact = json.loads(artifact_path.read_text())
    assert artifact["doc_type"] == "passport"
    assert artifact["text"]["raw"] == "Hola mundo"
    assert artifact["text"]["translated_en"] == "Hello world"
    assert artifact["text"]["active"] == "translated_en"
