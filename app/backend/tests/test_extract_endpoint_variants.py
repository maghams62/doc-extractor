from __future__ import annotations

from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

from backend.main import app


client = TestClient(app)


def _assert_schema(payload: dict) -> None:
    assert set(payload.keys()) == {"passport", "g28", "meta"}
    assert "attorney" in payload["g28"]
    assert "client" in payload["g28"]
    assert "sources" in payload["meta"]
    assert "confidence" in payload["meta"]
    assert "status" in payload["meta"]
    assert "suggestions" in payload["meta"]
    assert "presence" in payload["meta"]
    assert "warnings" in payload["meta"]

    for path, value in _collect_non_null_fields(payload).items():
        assert path in payload["meta"]["sources"]
        conf = payload["meta"]["confidence"].get(path)
        assert conf is not None
        assert 0.0 <= conf <= 1.0


def _collect_non_null_fields(payload: dict, prefix: str = "") -> dict:
    out = {}
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


def test_extract_endpoint_variants(sample_g28_path) -> None:
    passport_image = _build_passport_image()

    # only g28
    with sample_g28_path.open("rb") as g28_file:
        response = client.post("/extract", files={"g28": ("g28.pdf", g28_file, "application/pdf")})
    assert response.status_code == 200
    data = response.json()
    _assert_schema(data["result"])

    # only passport
    response = client.post(
        "/extract",
        files={"passport": ("passport.png", passport_image, "image/png")},
    )
    assert response.status_code == 200
    data = response.json()
    _assert_schema(data["result"])
    passport = data["result"]["passport"]
    if data["result"]["meta"]["sources"].get("passport.passport_number") == "MRZ":
        assert passport["passport_number"]
        assert passport["date_of_birth"]
        assert passport["date_of_expiration"]
    else:
        assert any(
            w.get("code") == "mrz_missing" for w in data["result"]["meta"]["warnings"]
        )

    # both
    passport_image.seek(0)
    with sample_g28_path.open("rb") as g28_file:
        response = client.post(
            "/extract",
            files={
                "passport": ("passport.png", passport_image, "image/png"),
                "g28": ("g28.pdf", g28_file, "application/pdf"),
            },
        )
    assert response.status_code == 200
    data = response.json()
    _assert_schema(data["result"])


def test_extract_endpoint_jpg(synthetic_passport_jpg_path) -> None:
    with synthetic_passport_jpg_path.open("rb") as passport_file:
        response = client.post(
            "/extract",
            files={"passport": ("passport.jpg", passport_file, "image/jpeg")},
        )
    assert response.status_code == 200
    data = response.json()
    _assert_schema(data["result"])
    passport = data["result"]["passport"]
    if data["result"]["meta"]["sources"].get("passport.passport_number") == "MRZ":
        assert passport["passport_number"]
        assert passport["date_of_birth"]
        assert passport["date_of_expiration"]
    else:
        assert any(
            w.get("code") == "mrz_missing" for w in data["result"]["meta"]["warnings"]
        )
