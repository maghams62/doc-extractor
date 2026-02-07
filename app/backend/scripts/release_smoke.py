from __future__ import annotations

import os
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Dict

import requests
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

from backend.main import app

SAMPLE_G28_URL = "https://alma-public-assets.s3.us-west-2.amazonaws.com/interview/Example_G-28.pdf"
FIXTURES_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
LOCAL_G28_PATH = FIXTURES_DIR / "Example_G-28.pdf"
LOCAL_FORM_PATH = FIXTURES_DIR / "form.html"


def _ensure_g28_path(tmp_dir: Path) -> Path:
    if LOCAL_G28_PATH.exists():
        return LOCAL_G28_PATH
    target = tmp_dir / "Example_G-28.pdf"
    resp = requests.get(SAMPLE_G28_URL, timeout=30)
    resp.raise_for_status()
    target.write_bytes(resp.content)
    return target


def _form_fixture_url() -> str:
    if not LOCAL_FORM_PATH.exists():
        raise FileNotFoundError(f"Local form fixture missing: {LOCAL_FORM_PATH}")
    return LOCAL_FORM_PATH.resolve().as_uri()


def _build_passport_image() -> BytesIO:
    img = Image.new("RGB", (1200, 600), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()
    mrz_lines = [
        "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<",
        "L898902C36UTO7408122F1204159ZE184226B<<<<<10",
    ]
    y = 450
    for line in mrz_lines:
        draw.text((50, y), line, font=font, fill="black")
        y += 20
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def _assert_schema(payload: Dict) -> None:
    assert set(payload.keys()) == {"passport", "g28", "meta"}
    assert "attorney" in payload["g28"]
    assert "client" in payload["g28"]
    assert "sources" in payload["meta"]
    assert "confidence" in payload["meta"]
    assert "status" in payload["meta"]
    assert "evidence" in payload["meta"]
    assert "suggestions" in payload["meta"]
    assert "warnings" in payload["meta"]

    for path, value in _collect_non_null_fields(payload).items():
        assert path in payload["meta"]["sources"]
        conf = payload["meta"]["confidence"].get(path)
        assert conf is not None
        assert 0.0 <= conf <= 1.0


def _collect_non_null_fields(payload: Dict, prefix: str = "") -> Dict:
    out: Dict[str, object] = {}
    for key, value in payload.items():
        if key == "meta":
            continue
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.update(_collect_non_null_fields(value, path))
        else:
            if value is not None:
                out[path] = value
    return out


def _merge_defaults(payload: Dict) -> Dict:
    merged = {
        "passport": dict(payload.get("passport") or {}),
        "g28": dict(payload.get("g28") or {}),
        "meta": dict(payload.get("meta") or {}),
    }
    merged_passport = merged["passport"]
    merged_g28 = merged["g28"]
    merged_attorney = dict(merged_g28.get("attorney") or {})
    merged_address = dict(merged_attorney.get("address") or {})

    defaults_passport = {
        "surname": "DOE",
        "given_names": "JANE",
        "date_of_birth": "1990-01-01",
        "date_of_expiration": "2030-01-01",
        "sex": "F",
    }
    defaults_g28 = {
        "family_name": "Doe",
        "given_name": "Jane",
        "middle_name": "Q",
        "law_firm_name": "Doe Law",
        "phone_daytime": "206-555-1212",
        "phone_mobile": "206-555-3434",
        "email": "jane@example.com",
    }
    defaults_address = {
        "street": "123 Main St",
        "unit": "Suite 200",
        "city": "Seattle",
        "state": "WA",
        "zip": "98101",
        "country": "USA",
    }

    for key, value in defaults_passport.items():
        if merged_passport.get(key) in (None, ""):
            merged_passport[key] = value
    for key, value in defaults_g28.items():
        if merged_attorney.get(key) in (None, ""):
            merged_attorney[key] = value
    for key, value in defaults_address.items():
        if merged_address.get(key) in (None, ""):
            merged_address[key] = value

    merged_attorney["address"] = merged_address
    merged_g28["attorney"] = merged_attorney
    merged["passport"] = merged_passport
    merged["g28"] = merged_g28
    return merged


def run_release_smoke() -> Dict:
    tmp_dir = Path(tempfile.mkdtemp(prefix="release_smoke_"))
    g28_path = _ensure_g28_path(tmp_dir)
    passport_image = _build_passport_image()
    form_url = _form_fixture_url()
    os.environ["ALMA_FORM_URL"] = form_url

    client = TestClient(app)
    with g28_path.open("rb") as g28_file:
        extract_resp = client.post(
            "/extract",
            files={
                "passport": ("passport.png", passport_image, "image/png"),
                "g28": ("g28.pdf", g28_file, "application/pdf"),
            },
        )
    assert extract_resp.status_code == 200
    extract_payload = extract_resp.json()
    _assert_schema(extract_payload["result"])

    payload = _merge_defaults(extract_payload["result"])
    payload["run_id"] = extract_payload["run_id"]
    review_resp = client.post("/review", json=payload)
    assert review_resp.status_code == 200
    review_payload = review_resp.json()
    review_summary = (review_payload.get("review") or {}).get("summary") or {}
    assert review_summary.get("ready_for_autofill") is True

    approve_resp = client.post(
        "/approve_canonical",
        json={
            "run_id": extract_payload["run_id"],
            "result": review_payload.get("result"),
            "review_summary": review_summary,
        },
    )
    assert approve_resp.status_code == 200

    autofill_resp_1 = client.post("/autofill", json=payload)
    assert autofill_resp_1.status_code == 200
    summary_1 = autofill_resp_1.json()["summary"]
    trace_1 = Path(summary_1["trace_path"])
    assert trace_1.exists()
    assert len(summary_1.get("attempted_fields", [])) >= 8
    assert form_url in summary_1["final_url"]

    autofill_resp_2 = client.post("/autofill", json=payload)
    assert autofill_resp_2.status_code == 200
    summary_2 = autofill_resp_2.json()["summary"]

    assert summary_1.get("attempted_fields", []) == summary_2.get("attempted_fields", [])
    assert summary_1["filled_fields"] == summary_2["filled_fields"]
    assert summary_1["fill_failures"] == summary_2["fill_failures"]
    assert Path(summary_2["trace_path"]).exists()

    return {
        "extract_run_id": extract_payload["run_id"],
        "autofill_run_id": autofill_resp_1.json()["run_id"],
        "form_url": form_url,
    }


def main() -> None:
    run_release_smoke()
    print("release_smoke: ok")


if __name__ == "__main__":
    main()
