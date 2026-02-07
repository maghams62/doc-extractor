from __future__ import annotations

import argparse
import json
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from backend.field_registry import iter_fields
from backend.pipeline.confidence import set_field
from backend.schemas import ExtractionResult


DATASETS_DIR = Path(__file__).resolve().parents[3] / "datasets"


SPANISH_PASSPORT_TEXT = "\n".join(
    [
        "PASAPORTE",
        "Apellido: GONZALEZ",
        "Nombres: MARIA LUISA",
        "Fecha de nacimiento: 1990-01-01",
        "Fecha de expiracion: 2030-01-01",
        "Numero de pasaporte: X1234567",
    ]
)

SPANISH_G28_TEXT = "\n".join(
    [
        "G-28 Aviso de Comparecencia",
        "Apellido del cliente: Doe",
        "Nombre del cliente: Jane",
        "Correo electronico: demo@example.com",
        "Telefono diurno: (415) 555-0100",
        "Direccion: 1 Market St",
        "Ciudad: San Francisco",
        "Estado: CA",
        "Codigo postal: 94105",
        "Pais: Estados Unidos",
    ]
)

CHINESE_PASSPORT_TEXT = "\n".join(
    [
        "护照",
        "姓: 王",
        "名: 伟",
        "出生日期：1991年01月01日",
        "签发日期：2015年01月01日",
        "有效期至：2012年04月15日",
        "护照号码：X1234567",
    ]
)

CHINESE_G28_TEXT = "\n".join(
    [
        "G-28 律师出庭通知",
        "客户姓: Doe",
        "客户名: Jane",
        "电子邮箱: demo@example.com",
        "白天电话: (415) 555-0100",
        "地址: 1 Market St",
        "城市: San Francisco",
        "州: CA",
        "邮编: 94105",
        "国家: 美国",
    ]
)


def _default_value(path: str, field_type: str) -> str:
    if path.endswith("address.street"):
        return "1 Market St"
    if path.endswith("address.unit"):
        return "Unit 3"
    if path.endswith("address.city"):
        return "San Francisco"
    if path.endswith("address.state") or field_type == "state":
        return "CA"
    if path.endswith("address.zip") or field_type == "zip":
        return "94105"
    if path.endswith("address.country"):
        return "United States"
    if field_type == "date_past":
        return "1990-01-01"
    if field_type == "date_future":
        return "2030-01-01"
    if field_type == "passport_number":
        return "X1234567"
    if field_type == "sex":
        return "F"
    if field_type == "email":
        return "demo@example.com"
    if field_type == "phone":
        return "(415) 555-0100"
    if field_type == "checkbox":
        return "Yes"
    if field_type == "name":
        return "MARIA"
    return "Sample"


def _build_result(language: str) -> tuple[ExtractionResult, dict]:
    result = ExtractionResult()
    dom_readback: dict[str, str] = {}

    for spec in iter_fields():
        value = _default_value(spec.key, spec.field_type)
        evidence = f"{spec.label}: {value}"
        set_field(result, spec.key, value, "OCR", None, evidence)
        dom_readback[spec.key] = value

    if language == "es":
        set_field(
            result,
            "passport.surname",
            "GARCIA",
            "OCR",
            None,
            "Apellido: GONZALEZ",
        )
        dom_readback["passport.surname"] = "GARCIA"
        passport_text = SPANISH_PASSPORT_TEXT
        g28_text = SPANISH_G28_TEXT
    else:
        set_field(
            result,
            "passport.surname",
            "WANG",
            "OCR",
            None,
            "姓: 王 (WANG)",
        )
        set_field(
            result,
            "passport.given_names",
            "WEI",
            "OCR",
            None,
            "名: 伟 (WEI)",
        )
        set_field(
            result,
            "passport.date_of_birth",
            "1990-01-01",
            "OCR",
            None,
            "出生日期：1991年01月01日",
        )
        set_field(
            result,
            "passport.date_of_expiration",
            "2012-04-15",
            "OCR",
            None,
            "有效期至：2012年04月15日",
        )
        dom_readback["passport.surname"] = "WANG"
        dom_readback["passport.given_names"] = "WEI"
        dom_readback["passport.date_of_birth"] = "1990-01-01"
        dom_readback["passport.date_of_expiration"] = "2012-04-15"
        passport_text = CHINESE_PASSPORT_TEXT
        g28_text = CHINESE_G28_TEXT

    autofill_report = {
        "filled_fields": list(dom_readback.keys()),
        "attempted_fields": list(dom_readback.keys()),
        "fill_failures": {},
        "dom_readback": dom_readback,
        "field_results": {},
    }
    return result, {
        "passport_text": passport_text,
        "g28_text": g28_text,
        "autofill_report": autofill_report,
    }


def _write_run(run_dir: Path, payload: dict) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "autofill_summary.json").write_text(
        json.dumps(payload["autofill_report"], indent=2)
    )

    _render_text_artifacts(
        payload["passport_text"],
        run_dir / "passport_demo.png",
        run_dir / "passport_demo.pdf",
    )
    _render_text_artifacts(
        payload["g28_text"],
        run_dir / "g28_demo.png",
        run_dir / "g28_demo.pdf",
    )


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font_candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/Library/Fonts/Arial Unicode MS.ttf",
        "/Library/Fonts/NotoSansCJK-Regular.ttc",
    ]
    for candidate in font_candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _render_text_artifacts(text: str, png_path: Path, pdf_path: Path) -> None:
    width = 1200
    margin = 60
    font_size = 28
    line_height = 40
    font = _load_font(font_size)
    lines: list[str] = []
    for raw in text.splitlines():
        raw = raw.rstrip()
        if not raw:
            lines.append("")
            continue
        wrap_width = 42
        lines.extend(textwrap.wrap(raw, width=wrap_width) or [""])
    height = max(600, margin * 2 + line_height * len(lines))
    image = Image.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(image)
    y = margin
    for line in lines:
        draw.text((margin, y), line, fill=(20, 20, 20), font=font)
        y += line_height
    image.save(png_path)
    image.save(pdf_path, "PDF", resolution=150.0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create LLM validation demo datasets.")
    parser.add_argument("--language", choices=["es", "zh"], required=True)
    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional run directory name. Defaults to demo_bad_es/demo_bad_zh.",
    )
    args = parser.parse_args()

    result, payload = _build_result(args.language)
    run_id = args.run_id or f"demo_bad_{args.language}"
    run_dir = DATASETS_DIR / run_id
    _write_run(run_dir, payload)
    (run_dir / "extracted.json").write_text(json.dumps(result.model_dump(), indent=2))

    print(f"Created demo dataset in {run_dir}")
    print("Run /post_autofill_validate with run_id to generate validation output.")


if __name__ == "__main__":
    main()
