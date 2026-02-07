from fastapi.testclient import TestClient

from backend import main


def test_extract_endpoint_no_files(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "RUNS_DIR", tmp_path)
    client = TestClient(main.app)
    response = client.post("/extract")
    assert response.status_code == 200
    payload = response.json()
    assert "run_id" in payload
    assert "result" in payload
