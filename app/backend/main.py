from __future__ import annotations

import json
import logging
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

import anyio
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .automation.fill_form import fill_form
from .config import CONFIG
from .field_registry import (
    field_registry_payload,
    iter_autofill_fields,
    iter_fields,
    iter_validation_fields,
    get_field_spec,
)
from .pipeline.confidence import add_suggestion, apply_fields, set_field
from .pipeline.g28 import extract_g28_fields
from .pipeline.ingest import load_document, preprocess_image
from .pipeline.ocr import ocr_image, ocr_mrz_text
from .pipeline.passport import extract_mrz_from_text, extract_passport_fields, extract_passport_heuristics
from .pipeline.llm_extract import llm_recover_fields
from .pipeline.label_noise import looks_like_label_value
from .pipeline.post_autofill import validate_post_autofill
from .pipeline.coverage_report import build_e2e_coverage_report
from .pipeline.rules import validate_field
from .pipeline.lang_detect import detect_language, is_english, language_name
from .pipeline.review import summarize_review
from .pipeline.text_artifact import (
    infer_doc_type,
    looks_like_g28_text,
    g28_label_match_count,
    read_text_artifact,
    translation_structure_check,
    upsert_text_artifact,
)
from .pipeline.validate import validate_and_annotate
from .pipeline.verify import llm_verify
from .pipeline.normalize import normalize_full_name
from .pipeline.translate import extract_ocr_text, translate_text, translation_engine_name
from .schemas import ExtractionResult, ResolvedField, WarningItem, empty_result

RUNS_DIR = CONFIG.runs_dir
LANGUAGE_CONFIDENCE_THRESHOLD = 0.85

logging.basicConfig(level=CONFIG.log_level, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
LOGGER = logging.getLogger("backend")
MRZ_PRESENCE_FIELDS = {
    "passport.surname",
    "passport.given_names",
    "passport.passport_number",
    "passport.date_of_birth",
    "passport.date_of_expiration",
    "passport.sex",
    "passport.nationality",
    "passport.country_of_issue",
}

app = FastAPI(title="Doc Extractor")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/field_registry")
async def field_registry() -> Dict[str, object]:
    return field_registry_payload()


def _create_run_dir() -> Path:
    run_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "inputs").mkdir(exist_ok=True)
    return run_dir


def _log_run(run_dir: Path, message: str) -> None:
    timestamp = datetime.utcnow().isoformat()
    with (run_dir / "run.log").open("a") as f:
        f.write(f"[{timestamp}] {message}\n")


def _write_text_artifact(run_dir: Path, filename: str, text: str) -> None:
    if not text:
        return
    path = run_dir / filename
    path.write_text(text)


def _read_text_artifact(run_dir: Path, filename: str) -> str:
    path = run_dir / filename
    if not path.exists():
        return ""
    try:
        return path.read_text()
    except Exception:  # noqa: BLE001
        return ""


def _write_json_artifact(run_dir: Path, filename: str, payload: Dict) -> None:
    path = run_dir / filename
    with path.open("w") as f:
        json.dump(payload, f, indent=2)


def _doc_artifact_dir(run_dir: Path, doc_type: str) -> Path:
    return run_dir / "artifacts" / doc_type


def _ocr_debug_payload(ocr_results: list, pages_total: int) -> Dict[str, object]:
    word_count = 0
    conf_sum = 0.0
    for ocr in ocr_results:
        for word in getattr(ocr, "words", []):
            word_count += 1
            conf_sum += float(getattr(word, "conf", 0.0))
    avg_conf = round(conf_sum / word_count, 3) if word_count else None
    return {
        "engine": "tesseract",
        "pages_total": pages_total,
        "pages_ocr": len(ocr_results),
        "word_count": word_count,
        "word_conf_avg": avg_conf,
    }


def _write_doc_artifacts(
    run_dir: Path,
    doc_type: str,
    doc_path: Path,
    pages: list,
    ocr_text: str,
    ocr_results: list,
) -> None:
    base_dir = _doc_artifact_dir(run_dir, doc_type)
    pages_dir = base_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    suffix = doc_path.suffix if doc_path.suffix else ".bin"
    input_copy = base_dir / f"input{suffix}"
    try:
        shutil.copyfile(doc_path, input_copy)
    except Exception as exc:  # noqa: BLE001
        _log_run(run_dir, f"Artifact copy failed for {doc_type}: {exc}")

    for idx, page in enumerate(pages, start=1):
        try:
            page_path = pages_dir / f"page_{idx}.png"
            page.convert("RGB").save(page_path, format="PNG")
        except Exception as exc:  # noqa: BLE001
            _log_run(run_dir, f"Artifact page save failed for {doc_type} page {idx}: {exc}")

    if ocr_text:
        (base_dir / "ocr_text.txt").write_text(ocr_text)
    debug_payload = _ocr_debug_payload(ocr_results, len(pages))
    _write_json_artifact(base_dir, "ocr_debug.json", debug_payload)


def _mark_doc_absent(result: ExtractionResult, prefix: str) -> None:
    for spec in iter_fields():
        if spec.key.startswith(prefix):
            result.meta.presence[spec.key] = "absent"


def _set_doc_meta(
    result: ExtractionResult,
    doc_type: str,
    *,
    status: str,
    source_file: Optional[str] = None,
    detected_type: Optional[str] = None,
    label_matches: Optional[int] = None,
    reason: Optional[str] = None,
) -> None:
    payload = {"status": status}
    if source_file:
        payload["source_file"] = source_file
    if detected_type:
        payload["detected_type"] = detected_type
    if label_matches is not None:
        payload["label_matches"] = label_matches
    if reason:
        payload["reason"] = reason
    result.meta.documents[doc_type] = payload


def _resolved_summary(resolved_fields: Dict[str, Dict]) -> Dict[str, int]:
    summary = {"green": 0, "amber": 0, "red": 0, "requires_human_input": 0}
    for entry in resolved_fields.values():
        status = str(entry.get("status", "unknown")).lower()
        if status in summary:
            summary[status] += 1
        if entry.get("requires_human_input"):
            summary["requires_human_input"] += 1
    return summary


def _write_final_snapshot(
    run_dir: Path,
    run_id: str,
    result: ExtractionResult,
    autofill_report: Optional[Dict] = None,
    validation_report: Optional[Dict] = None,
) -> None:
    resolved_payload = {
        key: value.model_dump() if hasattr(value, "model_dump") else dict(value)
        for key, value in (result.meta.resolved_fields or {}).items()
    }
    snapshot = {
        "run_id": run_id,
        "extraction": result.model_dump(exclude={"meta": True}),
        "autofill": autofill_report or {},
        "post_autofill_validation": validation_report or {},
        "resolved_fields": resolved_payload,
        "review_summary": result.meta.review_summary or {},
        "summary": _resolved_summary(resolved_payload),
    }
    _write_json_artifact(run_dir, "final_snapshot.json", snapshot)


def _find_input_document(run_dir: Path) -> Optional[Path]:
    inputs_dir = run_dir / "inputs"
    if not inputs_dir.exists():
        return None
    files = [path for path in inputs_dir.iterdir() if path.is_file()]
    if not files:
        return None
    return sorted(files)[0]


def _load_or_create_ocr_text(
    run_dir: Path, doc_path: Optional[Path], ocr_langs: Optional[str] = None
) -> str:
    ocr_path = run_dir / "ocr_text.txt"
    if ocr_path.exists() and not ocr_langs:
        return ocr_path.read_text()
    if not doc_path:
        doc_path = _find_input_document(run_dir)
    if not doc_path:
        return ""
    text = extract_ocr_text(doc_path, ocr_langs=ocr_langs)
    _write_text_artifact(run_dir, "ocr_text.txt", text)
    return text


def _detect_language_payload(text: str) -> tuple[Dict[str, object], Dict[str, object]]:
    detection = detect_language(text)
    confidence = round(detection.confidence, 4)
    language_meta = {
        "detected": detection.language,
        "confidence": confidence,
    }
    response_payload: Dict[str, object] = {
        "detected_language": detection.language,
        "language_name": language_name(detection.language),
        "language_confidence": confidence,
        "is_english": is_english(detection.language, detection.confidence, LANGUAGE_CONFIDENCE_THRESHOLD),
        "threshold": LANGUAGE_CONFIDENCE_THRESHOLD,
    }
    return language_meta, response_payload


def _write_language_artifact(run_dir: Path, payload: Dict[str, object]) -> None:
    _write_json_artifact(run_dir, "language.json", payload)


def _label_snippet(text: str, label_hints: list[str], window: int = 2) -> str:
    if not text or not label_hints:
        return ""
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        for pattern in label_hints:
            if re.search(pattern, line, re.IGNORECASE):
                snippet_lines = lines[idx : idx + window + 1]
                return "\n".join([l for l in snippet_lines if l.strip()])
    return ""


def _field_contexts_for_llm(
    result: ExtractionResult,
    passport_text: str,
    g28_text: str,
) -> list[Dict]:
    contexts: list[Dict] = []
    payload = result.model_dump()
    for spec in iter_fields():
        path = spec.key
        status = result.meta.status.get(path, "unknown")
        if status not in {"red", "yellow"}:
            continue
        presence = result.meta.presence.get(path, "unknown")
        if presence not in {"present", "unknown"}:
            continue
        if not spec.label_hints:
            continue
        source_text = passport_text if path.startswith("passport.") else g28_text
        snippet = _label_snippet(source_text, spec.label_hints)
        if not snippet:
            continue
        contexts.append(
            {
                "field": path,
                "snippet": snippet,
                "current_value": _get_value(payload, path),
                "label_presence": presence,
                "status": status,
            }
        )
    return contexts


def _get_value(payload: Dict, path: str) -> Optional[str]:
    parts = path.split(".")
    value: object = payload
    for part in parts:
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    if value is None:
        return None
    return str(value)


def _add_warning(result: ExtractionResult, code: str, message: str, field: Optional[str] = None) -> None:
    result.meta.warnings.append(WarningItem(code=code, message=message, field=field))


def _set_presence(result: ExtractionResult, path: str, present: Optional[bool]) -> None:
    if present is None:
        return
    result.meta.presence[path] = "present" if present else "absent"


def _label_present(text: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def _save_upload(upload: UploadFile, run_dir: Path, name: Optional[str]) -> Path:
    safe_name = name or f"upload_{uuid.uuid4().hex}"
    path = run_dir / "inputs" / safe_name
    with path.open("wb") as f:
        f.write(upload.file.read())
    _log_run(run_dir, f"Saved upload: {name}")
    return path


def _extract_passport(
    passport_path: Optional[Path],
    result: ExtractionResult,
    run_dir: Optional[Path] = None,
) -> str:
    if not passport_path:
        _mark_doc_absent(result, "passport.")
        result.meta.presence["passport.mrz"] = "absent"
        _set_doc_meta(result, "passport", status="absent")
        return ""
    source_file = passport_path.name
    try:
        pages = load_document(passport_path)
    except Exception as exc:  # noqa: BLE001
        _add_warning(result, "ingest_failed", f"Passport ingest failed: {exc}")
        _set_doc_meta(result, "passport", status="unreadable", source_file=source_file, reason=str(exc))
        return ""
    if not pages:
        _set_doc_meta(result, "passport", status="unreadable", source_file=source_file, reason="No pages found")
        return ""
    combined_text: list[str] = []
    ocr_results = []
    mrz_used = False
    mrz_raw = None
    mrz_fields: Dict[str, Optional[str]] = {}

    for page in pages:
        pre = preprocess_image(page)
        ocr = ocr_image(pre)
        ocr_results.append(ocr)
        combined_text.append(ocr.text)
        fields = extract_passport_fields(ocr)
        mrz_region = page.crop((0, int(page.height * 0.6), page.width, page.height))
        mrz_text = ocr_mrz_text(mrz_region)
        mrz_result = extract_mrz_from_text(mrz_text)
        if mrz_result:
            fields = {**mrz_result.fields, "_mrz_raw": "\n".join(mrz_result.raw_lines)}
        if fields.get("_mrz_raw"):
            mrz_used = True
            mrz_raw = fields.get("_mrz_raw")
            mrz_fields = {k: v for k, v in fields.items() if not k.startswith("_")}
            break

    text = "\n".join(combined_text)
    label_matches = g28_label_match_count(text)
    if not mrz_used and looks_like_g28_text(text):
        _mark_doc_absent(result, "passport.")
        result.meta.presence["passport.mrz"] = "absent"
        _set_doc_meta(
            result,
            "passport",
            status="mismatch",
            source_file=source_file,
            detected_type="g28",
            label_matches=label_matches,
        )
        _add_warning(
            result,
            "doc_type_mismatch",
            "Passport upload looks like a G-28 document. Move it to the G-28 slot.",
            field="passport",
        )
        if run_dir:
            _write_doc_artifacts(run_dir, "passport", passport_path, pages, text, ocr_results)
        return text
    _set_doc_meta(result, "passport", status="present", source_file=source_file, label_matches=label_matches)
    _set_presence(result, "passport.mrz", mrz_used)
    for spec in iter_fields():
        if not spec.key.startswith("passport.") or not spec.label_hints:
            continue
        _set_presence(result, spec.key, _label_present(text, spec.label_hints))
    if mrz_used:
        for key in MRZ_PRESENCE_FIELDS:
            result.meta.presence[key] = "present"
    heuristics = extract_passport_heuristics(text)
    LOGGER.debug("Passport OCR heuristic fields: %s", heuristics.fields)

    if mrz_used:
        LOGGER.info("Passport MRZ fields: %s", mrz_fields)
        apply_fields(
            result,
            {f"passport.{k}": v for k, v in mrz_fields.items()},
            "MRZ",
            None,
            mrz_raw,
        )
        for key, value in heuristics.fields.items():
            path = f"passport.{key}"
            existing = result.meta.sources.get(path)
            if existing and value and str(value).strip() != str(getattr(result.passport, key, "")).strip():
                if key == "passport_number" and not re.search(r"\d", str(value)):
                    _add_warning(
                        result,
                        "label_noise",
                        f"OCR candidate for {path} has no digits; ignoring.",
                        field=path,
                    )
                    continue
                if looks_like_label_value(value):
                    _add_warning(
                        result,
                        "label_noise",
                        f"OCR candidate for {path} looks like a label; ignoring.",
                        field=path,
                    )
                    continue
                _add_warning(
                    result,
                    "conflict",
                    f"Conflict between MRZ and OCR for {path}.",
                    field=path,
                )
                result.meta.conflicts[path] = {
                    "mrz_value": str(getattr(result.passport, key, "")).strip(),
                    "ocr_value": str(value).strip(),
                }
                add_suggestion(
                    result,
                    path,
                    str(value),
                    "OCR fallback value",
                    "OCR",
                    None,
                    heuristics.evidence.get(key, text[:120]),
                    True,
                )
            if not existing and value:
                if key == "passport_number" and not re.search(r"\d", str(value)):
                    _add_warning(
                        result,
                        "label_noise",
                        f"OCR candidate for {path} has no digits; ignoring.",
                        field=path,
                    )
                    continue
                if looks_like_label_value(value):
                    _add_warning(
                        result,
                        "label_noise",
                        f"OCR candidate for {path} looks like a label; ignoring.",
                        field=path,
                    )
                    continue
                set_field(result, path, value, "OCR", None, heuristics.evidence.get(key, text[:120]))
    else:
        LOGGER.info("Passport MRZ not detected. Using OCR heuristics.")
        for key, value in heuristics.fields.items():
            path = f"passport.{key}"
            if key == "passport_number" and value and not re.search(r"\d", str(value)):
                _add_warning(
                    result,
                    "label_noise",
                    f"OCR candidate for {path} has no digits; ignoring.",
                    field=path,
                )
                continue
            if looks_like_label_value(value):
                _add_warning(
                    result,
                    "label_noise",
                    f"OCR candidate for {path} looks like a label; ignoring.",
                    field=path,
                )
                continue
            set_field(result, path, value, "OCR", None, heuristics.evidence.get(key, text[:120]))
        _add_warning(result, "mrz_missing", "Passport MRZ not detected; used OCR fallback")

    for key in ["passport.passport_number", "passport.date_of_birth", "passport.date_of_expiration"]:
        if not result.meta.sources.get(key):
            _add_warning(result, "missing_required", f"Missing {key}", field=key)

    if run_dir:
        _write_doc_artifacts(run_dir, "passport", passport_path, pages, text, ocr_results)
    return text


def _extract_g28(
    g28_path: Optional[Path],
    result: ExtractionResult,
    run_dir: Optional[Path] = None,
) -> str:
    if not g28_path:
        _mark_doc_absent(result, "g28.")
        _set_doc_meta(result, "g28", status="absent")
        return ""
    source_file = g28_path.name
    try:
        pages = load_document(g28_path)
    except Exception as exc:  # noqa: BLE001
        _add_warning(result, "ingest_failed", f"G-28 ingest failed: {exc}")
        for key in ["g28.attorney.family_name", "g28.attorney.given_name", "g28.attorney.email"]:
            _add_warning(result, "missing_required", f"Missing {key}", field=key)
        _set_doc_meta(result, "g28", status="unreadable", source_file=source_file, reason=str(exc))
        return ""
    if not pages:
        _set_doc_meta(result, "g28", status="unreadable", source_file=source_file, reason="No pages found")
        return ""
    text_chunks = []
    ocr_results = []
    for page in pages[:2]:
        pre = preprocess_image(page)
        ocr = ocr_image(pre)
        ocr_results.append(ocr)
        text_chunks.append(ocr.text)
    text = "\n".join(text_chunks)
    low_text_signal = len(text.strip()) < 200 or len(text_chunks) == 0
    _set_doc_meta(
        result,
        "g28",
        status="present",
        source_file=source_file,
        label_matches=g28_label_match_count(text),
    )
    _apply_g28_extraction(result, text, low_text_signal=low_text_signal)

    if run_dir:
        _write_doc_artifacts(run_dir, "g28", g28_path, pages, text, ocr_results)
    return text


def _apply_g28_extraction(result: ExtractionResult, text: str, low_text_signal: bool) -> None:
    extraction = extract_g28_fields(text)
    for key, present in extraction.label_presence.items():
        if low_text_signal and not present:
            _set_presence(result, key, None)
        else:
            _set_presence(result, key, present)
    LOGGER.debug("G-28 extracted fields: %s", extraction.fields)
    for path, value in extraction.fields.items():
        if value is None:
            continue
        set_field(result, path, value, "OCR", None, extraction.evidence.get(path, text[:160]))

    for path, values in extraction.candidates.items():
        if not values or len(values) <= 1:
            continue
        for candidate in values[1:]:
            add_suggestion(result, path, candidate, "Alternate OCR candidate", "OCR", None)

    # warn if missing attorney fields based on label presence
    for path, label_found in extraction.label_presence.items():
        if not path.startswith("g28.attorney."):
            continue
        if result.meta.sources.get(path):
            continue
        if low_text_signal and not label_found:
            continue
        if label_found:
            _add_warning(result, "label_present_no_value", f"Label found but missing value for {path}", field=path)
        else:
            _add_warning(result, "label_absent", f"Label not found for {path}", field=path)


def _normalize_conflict_value(value: Optional[str]) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip().lower()


def _merge_identity_fields(result: ExtractionResult) -> None:
    mrz_present = result.meta.presence.get("passport.mrz") == "present"
    if not mrz_present:
        return
    payload = result.model_dump()
    mappings = [
        ("passport.surname", "g28.client.family_name"),
        ("passport.given_names", "g28.client.given_name"),
        ("passport.full_name", "g28.client.full_name"),
    ]
    now_iso = datetime.utcnow().isoformat()
    for passport_path, g28_path in mappings:
        passport_value = _get_value(payload, passport_path)
        if not passport_value:
            continue
        g28_value = _get_value(payload, g28_path)
        if g28_value:
            if _normalize_conflict_value(passport_value) == _normalize_conflict_value(g28_value):
                continue
            g28_evidence = result.meta.evidence.get(g28_path)
            result.meta.conflicts[g28_path] = {
                "passport_value": str(passport_value),
                "g28_value": str(g28_value),
            }
            _add_warning(result, "conflict", "Conflict between passport and G-28", field=g28_path)
            result.meta.status[g28_path] = "amber"
            result.meta.resolved_fields[g28_path] = ResolvedField(
                key=g28_path,
                value=str(passport_value),
                status="amber",
                confidence=0.7,
                source="MERGE",
                locked=False,
                requires_human_input=True,
                reason="Conflict between passport and G-28.",
                suggestions=result.meta.suggestions.get(g28_path, []),
                last_validated_at=now_iso,
                version=(result.meta.resolved_fields.get(g28_path).version if result.meta.resolved_fields.get(g28_path) else 0)
                + 1,
            )
            if g28_value:
                add_suggestion(
                    result,
                    g28_path,
                    str(g28_value),
                    "G-28 value",
                    "OCR",
                    None,
                    g28_evidence,
                    True,
                )
            set_field(
                result,
                g28_path,
                str(passport_value),
                "MERGE",
                None,
                result.meta.evidence.get(passport_path),
            )
            continue
        set_field(
            result,
            g28_path,
            str(passport_value),
            "PASSPORT",
            None,
            result.meta.evidence.get(passport_path),
        )


def extract_documents_with_text(
    passport_path: Optional[Path],
    g28_path: Optional[Path],
    use_llm_extract: bool = False,
    run_dir: Optional[Path] = None,
) -> Tuple[ExtractionResult, str, str]:
    result = empty_result()
    passport_text = _extract_passport(passport_path, result, run_dir=run_dir)
    g28_text = _extract_g28(g28_path, result, run_dir=run_dir)
    passport_doc = result.meta.documents.get("passport", {}) if result.meta.documents else {}
    if not g28_path and passport_doc.get("status") == "mismatch" and passport_doc.get("detected_type") == "g28":
        if passport_text.strip():
            _set_doc_meta(
                result,
                "g28",
                status="present",
                source_file=passport_doc.get("source_file"),
                label_matches=g28_label_match_count(passport_text),
            )
            _apply_g28_extraction(result, passport_text, low_text_signal=len(passport_text.strip()) < 200)
            g28_text = passport_text

    _merge_identity_fields(result)
    _finalize_names(result)
    return result, passport_text, g28_text


def extract_documents(
    passport_path: Optional[Path],
    g28_path: Optional[Path],
    use_llm_extract: bool = False,
) -> ExtractionResult:
    result, _, _ = extract_documents_with_text(passport_path, g28_path, use_llm_extract=use_llm_extract)
    return result


def _finalize_names(result: ExtractionResult) -> None:
    def name_ok(value: Optional[str]) -> bool:
        if not value:
            return False
        if len(value.strip()) < 2:
            return False
        if not re.search(r"[A-Za-z]{2,}", value):
            return False
        if looks_like_label_value(value):
            return False
        return True

    if not result.passport.full_name:
        if name_ok(result.passport.given_names) and name_ok(result.passport.surname):
            full = normalize_full_name(result.passport.given_names, None, result.passport.surname)
        else:
            full = None
        if full:
            set_field(result, "passport.full_name", full, "VALIDATOR", None, "Derived from passport name parts")

    attorney = result.g28.attorney
    if not attorney.full_name:
        if name_ok(attorney.given_name) and name_ok(attorney.family_name):
            middle = attorney.middle_name if name_ok(attorney.middle_name) else None
            full = normalize_full_name(attorney.given_name, middle, attorney.family_name)
        else:
            full = None
        if full:
            set_field(result, "g28.attorney.full_name", full, "VALIDATOR", None, "Derived from attorney name parts")

    client = result.g28.client
    if not client.full_name:
        if name_ok(client.given_name) and name_ok(client.family_name):
            middle = client.middle_name if name_ok(client.middle_name) else None
            full = normalize_full_name(client.given_name, middle, client.family_name)
        else:
            full = None
        if full:
            set_field(result, "g28.client.full_name", full, "VALIDATOR", None, "Derived from client name parts")


def _missing_fields_for_llm(result: ExtractionResult) -> list[str]:
    required = [
        "passport.surname",
        "passport.given_names",
        "passport.date_of_birth",
        "passport.date_of_expiration",
        "passport.passport_number",
        "g28.attorney.family_name",
        "g28.attorney.given_name",
        "g28.attorney.email",
        "g28.attorney.address.street",
        "g28.attorney.address.city",
        "g28.attorney.address.state",
        "g28.attorney.address.zip",
    ]
    missing = []
    for path in required:
        if not result.meta.sources.get(path):
            missing.append(path)
    return missing


def _apply_llm_suggestions(
    result: ExtractionResult, suggestions: list[dict], missing_fields: list[str]
) -> None:
    if not isinstance(suggestions, list):
        return
    missing_set = set(missing_fields)
    for suggestion in suggestions:
        if not isinstance(suggestion, dict):
            continue
        field = suggestion.get("field")
        if not field or field not in missing_set:
            continue
        if result.meta.sources.get(field):
            continue
        value = suggestion.get("value")
        if value is None:
            continue
        evidence = suggestion.get("evidence")
        if not evidence:
            continue
        confidence = suggestion.get("confidence")
        requires_confirmation = bool(suggestion.get("requires_confirmation", False))
        reason = suggestion.get("reason") or "LLM recovery suggestion"
        add_suggestion(
            result,
            field,
            str(value),
            reason,
            "LLM",
            confidence if isinstance(confidence, (int, float)) else None,
            str(evidence),
            requires_confirmation,
        )


def _apply_llm_recovery_suggestions(
    result: ExtractionResult, suggestions: list[dict], allowed_fields: list[str]
) -> None:
    if not isinstance(suggestions, list):
        return
    allowed = set(allowed_fields)
    for suggestion in suggestions:
        if not isinstance(suggestion, dict):
            continue
        field = suggestion.get("field")
        if not field or field not in allowed:
            continue
        value = suggestion.get("value")
        if value is None:
            continue
        evidence = suggestion.get("evidence")
        if not evidence:
            continue
        confidence = suggestion.get("confidence")
        requires_confirmation = bool(suggestion.get("requires_confirmation", False))
        reason = suggestion.get("reason") or "LLM recovery suggestion"
        add_suggestion(
            result,
            field,
            str(value),
            reason,
            "LLM",
            confidence if isinstance(confidence, (int, float)) else None,
            str(evidence),
            requires_confirmation,
        )


def _write_result(run_dir: Path, result: ExtractionResult) -> None:
    out_path = run_dir / "extracted.json"
    with out_path.open("w") as f:
        json.dump(result.model_dump(), f, indent=2)


@app.post("/extract")
async def extract(
    passport: UploadFile = File(None),
    g28: UploadFile = File(None),
    options: Optional[str] = Form(None),
):
    run_dir = _create_run_dir()
    _log_run(run_dir, "Starting extraction")
    passport_path = _save_upload(passport, run_dir, passport.filename) if passport else None
    g28_path = _save_upload(g28, run_dir, g28.filename) if g28 else None

    if options:
        _log_run(run_dir, "extract: request options ignored; using config")
    use_llm_extract = CONFIG.extraction.use_llm_extract
    _log_run(run_dir, f"LLM extraction enabled (config): {use_llm_extract}")
    result, passport_text, g28_text = extract_documents_with_text(
        passport_path, g28_path, use_llm_extract=use_llm_extract, run_dir=run_dir
    )
    _write_text_artifact(run_dir, "passport_ocr.txt", passport_text)
    _write_text_artifact(run_dir, "g28_ocr.txt", g28_text)
    report = validate_and_annotate(result, use_llm=False)
    if CONFIG.extraction.use_llm_extract:
        contexts = _field_contexts_for_llm(result, passport_text, g28_text)
        context_fields = [ctx.get("field") for ctx in contexts if ctx.get("field")]
        llm_suggestions, llm_error = llm_recover_fields(contexts, result.model_dump())
        if llm_error:
            _add_warning(result, "llm_skipped", f"LLM recovery skipped: {llm_error}")
        else:
            _apply_llm_recovery_suggestions(result, llm_suggestions, context_fields)
            _add_warning(result, "llm_applied", "LLM recovery suggestions added")

    extracted_fields = len(result.meta.sources)
    _log_run(run_dir, f"Extraction summary: {extracted_fields} fields with sources")
    passport_sources = {k: v for k, v in result.meta.sources.items() if k.startswith("passport.")}
    if passport_sources:
        if any(source == "MRZ" for source in passport_sources.values()):
            _log_run(run_dir, "Passport extraction: MRZ detected")
        else:
            _log_run(run_dir, "Passport extraction: OCR fallback")
    else:
        _log_run(run_dir, "Passport extraction: no passport fields")
    g28_sources = {k: v for k, v in result.meta.sources.items() if k.startswith("g28.")}
    if g28_sources:
        _log_run(run_dir, "G-28 extraction: OCR heuristics")
    else:
        _log_run(run_dir, "G-28 extraction: no g28 fields")
    for warning in result.meta.warnings:
        _log_run(run_dir, f"Warning: {warning.code} {warning.field or ''} {warning.message}")
    _log_run(
        run_dir,
        f"Validation summary: ok={report.ok} issues={len(report.issues)} score={report.score:.2f}",
    )

    _write_result(run_dir, result)
    _log_run(run_dir, "Extraction complete")

    return JSONResponse(
        {
            "run_id": run_dir.name,
            "result": result.model_dump(),
            "report": report.model_dump(),
        }
    )


@app.post("/review")
async def review(payload: Dict):
    if not isinstance(payload, dict):
        return JSONResponse({"error": "Invalid payload"}, status_code=400)
    run_id = payload.get("run_id")
    if not run_id:
        return JSONResponse({"error": "Missing run_id"}, status_code=400)
    run_dir = RUNS_DIR / str(run_id)
    if not run_dir.exists():
        return JSONResponse({"error": "Run not found"}, status_code=404)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "inputs").mkdir(exist_ok=True)
    _log_run(run_dir, "Starting review (pre-autofill)")

    result_payload = payload.get("result") if isinstance(payload, dict) else None
    if not result_payload:
        extracted_path = run_dir / "extracted.json"
        if extracted_path.exists():
            result_payload = json.loads(extracted_path.read_text())
    if not result_payload:
        return JSONResponse({"error": "Missing extracted result"}, status_code=400)

    result = ExtractionResult.model_validate(result_payload)
    passport_text = _read_text_artifact(run_dir, "passport_ocr.txt")
    g28_text = _read_text_artifact(run_dir, "g28_ocr.txt")
    review_report, llm_error, updated = validate_post_autofill(
        result,
        {},
        passport_text,
        g28_text,
        use_llm=False,
    )
    doc_status = result.meta.documents if isinstance(result.meta.documents, dict) else {}
    summary = summarize_review(review_report.get("fields", {}), doc_status)
    summary["documents"] = doc_status
    review_payload = {
        **review_report,
        "summary": summary,
        "llm_error": llm_error,
    }
    _write_json_artifact(run_dir, "review_report.json", review_payload)
    _write_json_artifact(run_dir, "review_summary.json", summary)

    updated.meta.review_summary = summary
    _write_result(run_dir, updated)

    autofill_report = {}
    validation_report = {}
    autofill_path = run_dir / "autofill_summary.json"
    validation_path = run_dir / "post_autofill_validation.json"
    if autofill_path.exists():
        autofill_report = json.loads(autofill_path.read_text())
    if validation_path.exists():
        validation_report = json.loads(validation_path.read_text())
    _write_final_snapshot(run_dir, run_id, updated, autofill_report, validation_report)

    _log_run(
        run_dir,
        f"Review summary: ready={summary.get('ready_for_autofill')} blocking={summary.get('blocking')}",
    )
    return JSONResponse({"run_id": run_id, "result": updated.model_dump(), "review": review_payload})


@app.post("/approve_canonical")
async def approve_canonical(payload: Dict):
    if not isinstance(payload, dict):
        return JSONResponse({"error": "Invalid payload"}, status_code=400)
    run_id = payload.get("run_id")
    if not run_id:
        return JSONResponse({"error": "Missing run_id"}, status_code=400)
    run_dir = RUNS_DIR / str(run_id)
    if not run_dir.exists():
        return JSONResponse({"error": "Run not found"}, status_code=404)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "inputs").mkdir(exist_ok=True)

    result_payload = payload.get("result") if isinstance(payload, dict) else None
    if not result_payload:
        extracted_path = run_dir / "extracted.json"
        if extracted_path.exists():
            result_payload = json.loads(extracted_path.read_text())
    if not result_payload:
        return JSONResponse({"error": "Missing extracted result"}, status_code=400)

    review_summary = payload.get("review_summary") if isinstance(payload, dict) else None
    if not review_summary:
        summary_path = run_dir / "review_summary.json"
        if summary_path.exists():
            review_summary = json.loads(summary_path.read_text())
    if not review_summary:
        return JSONResponse({"error": "Missing review summary. Run /review first."}, status_code=400)
    if not review_summary.get("ready_for_autofill"):
        return JSONResponse({"error": "Blocking issues remain. Resolve before autofill."}, status_code=400)

    result = ExtractionResult.model_validate(result_payload)
    if not result.meta.resolved_fields:
        return JSONResponse({"error": "Missing resolved fields. Run /review first."}, status_code=400)

    now_iso = datetime.utcnow().isoformat()
    for entry in result.meta.resolved_fields.values():
        entry.locked = True

    canonical_fields = {
        key: value.model_dump() for key, value in result.meta.resolved_fields.items()
    }
    canonical_payload = {
        "run_id": run_id,
        "approved_at": now_iso,
        "review_summary": review_summary,
        "fields": canonical_fields,
    }
    _write_json_artifact(run_dir, "canonical_fields.json", canonical_payload)

    result.meta.review_summary = review_summary
    result.meta.canonical_approved_at = now_iso
    _write_result(run_dir, result)

    autofill_report = {}
    validation_report = {}
    autofill_path = run_dir / "autofill_summary.json"
    validation_path = run_dir / "post_autofill_validation.json"
    if autofill_path.exists():
        autofill_report = json.loads(autofill_path.read_text())
    if validation_path.exists():
        validation_report = json.loads(validation_path.read_text())
    _write_final_snapshot(run_dir, run_id, result, autofill_report, validation_report)

    _log_run(run_dir, "Canonical fields approved")
    return JSONResponse({"run_id": run_id, "canonical": canonical_payload, "result": result.model_dump()})


@app.post("/detect_language")
async def detect_language_endpoint(
    document: UploadFile = File(None),
    run_id: Optional[str] = Form(None),
    doc_type: Optional[str] = Form(None),
    ocr_langs: Optional[str] = Form(None),
):
    run_dir = RUNS_DIR / run_id if run_id else _create_run_dir()
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "inputs").mkdir(exist_ok=True)
    _log_run(run_dir, "Starting language detection")

    doc_path = None
    if document:
        doc_path = _save_upload(document, run_dir, document.filename)
    elif run_id:
        doc_path = _find_input_document(run_dir)

    try:
        ocr_text = _load_or_create_ocr_text(run_dir, doc_path, ocr_langs=ocr_langs)
    except Exception as exc:  # noqa: BLE001
        _log_run(run_dir, f"Language detection OCR failed: {exc}")
        return JSONResponse({"run_id": run_dir.name, "error": f"OCR failed: {exc}"}, status_code=400)
    if not ocr_text.strip():
        if not doc_path:
            _log_run(run_dir, "Language detection failed: missing document")
            return JSONResponse({"run_id": run_dir.name, "error": "Missing document upload"}, status_code=400)
        _log_run(run_dir, "Language detection failed: empty OCR text")
        return JSONResponse({"run_id": run_dir.name, "error": "OCR text empty"}, status_code=400)

    resolved_doc_type = infer_doc_type(doc_type, doc_path.name if doc_path else None, run_dir)
    if not resolved_doc_type:
        _log_run(run_dir, "Language detection failed: doc_type missing")
        return JSONResponse({"run_id": run_dir.name, "error": "Missing doc_type (g28 or passport)"}, status_code=400)

    language_meta, response_payload = _detect_language_payload(ocr_text)
    _write_language_artifact(run_dir, response_payload)
    artifact = upsert_text_artifact(
        run_dir,
        resolved_doc_type,
        source_file=doc_path.name if doc_path else None,
        raw_text=ocr_text,
        detected_language=language_meta["detected"],
        language_confidence=language_meta["confidence"],
        ocr_engine="tesseract",
        active="raw",
    )
    _log_run(
        run_dir,
        f"Detected language: {response_payload['detected_language']} ({response_payload['language_confidence']})",
    )
    return JSONResponse(
        {
            "run_id": run_dir.name,
            "doc_type": resolved_doc_type,
            "ocr_char_count": len(ocr_text),
            "text_active": artifact["text"]["active"],
            "has_translation": bool(artifact["text"]["translated_en"]),
            "translation_warning": artifact.get("meta", {}).get("translation_warning"),
            "text_artifact_path": f"runs/{run_dir.name}/doc_artifacts/{resolved_doc_type}/text_artifact.json",
            **response_payload,
        }
    )


@app.post("/translate")
async def translate(
    document: UploadFile = File(None),
    run_id: Optional[str] = Form(None),
    doc_type: Optional[str] = Form(None),
    ocr_langs: Optional[str] = Form(None),
):
    run_dir = RUNS_DIR / run_id if run_id else _create_run_dir()
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "inputs").mkdir(exist_ok=True)
    _log_run(run_dir, "Starting translation")

    doc_path = None
    if document:
        doc_path = _save_upload(document, run_dir, document.filename)
    elif run_id:
        doc_path = _find_input_document(run_dir)

    try:
        ocr_text = _load_or_create_ocr_text(run_dir, doc_path, ocr_langs=ocr_langs)
    except Exception as exc:  # noqa: BLE001
        _log_run(run_dir, f"Translation OCR failed: {exc}")
        return JSONResponse({"run_id": run_dir.name, "error": f"OCR failed: {exc}"}, status_code=400)
    if not ocr_text.strip():
        if not doc_path:
            _log_run(run_dir, "Translation failed: missing document")
            return JSONResponse({"run_id": run_dir.name, "error": "Missing document upload"}, status_code=400)
        _log_run(run_dir, "Translation failed: empty OCR text")
        return JSONResponse({"run_id": run_dir.name, "error": "OCR text empty"}, status_code=400)

    resolved_doc_type = infer_doc_type(doc_type, doc_path.name if doc_path else None, run_dir)
    if not resolved_doc_type:
        _log_run(run_dir, "Translation failed: doc_type missing")
        return JSONResponse({"run_id": run_dir.name, "error": "Missing doc_type (g28 or passport)"}, status_code=400)

    language_meta, response_payload = _detect_language_payload(ocr_text)
    _write_language_artifact(run_dir, response_payload)
    base_artifact = upsert_text_artifact(
        run_dir,
        resolved_doc_type,
        source_file=doc_path.name if doc_path else None,
        raw_text=ocr_text,
        detected_language=language_meta["detected"],
        language_confidence=language_meta["confidence"],
        ocr_engine="tesseract",
    )
    translated_text, error = translate_text(ocr_text)
    if error:
        _log_run(run_dir, f"Translation failed: {error}")
        return JSONResponse({"run_id": run_dir.name, "error": error}, status_code=400)

    _write_text_artifact(run_dir, "translated_text.txt", translated_text)
    translated_payload = {
        "detected_language": language_meta.get("detected", "unknown"),
        "confidence": language_meta.get("confidence", 0.0),
        "translated_text": translated_text,
    }
    _write_json_artifact(run_dir, "translated_ocr.json", translated_payload)
    warning, check = translation_structure_check(ocr_text, translated_text, resolved_doc_type)
    engine_name = translation_engine_name()
    artifact = upsert_text_artifact(
        run_dir,
        resolved_doc_type,
        source_file=doc_path.name if doc_path else None,
        raw_text=base_artifact["text"]["raw"],
        detected_language=language_meta["detected"],
        language_confidence=language_meta["confidence"],
        translated_text=translated_text,
        active="translated_en",
        ocr_engine="tesseract",
        translation_engine=engine_name,
        translation_warning=warning or "",
        translation_check=check,
    )
    _log_run(run_dir, "Translation complete")

    artifacts = {
        "ocr_text": f"runs/{run_dir.name}/ocr_text.txt",
        "language": f"runs/{run_dir.name}/language.json",
        "translated_text": f"runs/{run_dir.name}/translated_text.txt",
        "translated_ocr": f"runs/{run_dir.name}/translated_ocr.json",
        "text_artifact": f"runs/{run_dir.name}/doc_artifacts/{resolved_doc_type}/text_artifact.json",
    }
    return JSONResponse(
        {
            "run_id": run_dir.name,
            "doc_type": resolved_doc_type,
            "translated_text": translated_text,
            "text_active": artifact["text"]["active"],
            "translation_warning": artifact.get("meta", {}).get("translation_warning"),
            **response_payload,
            "artifacts": artifacts,
        }
    )


@app.post("/text_artifact/active")
async def set_text_artifact_active(
    run_id: str = Form(...),
    doc_type: Optional[str] = Form(None),
    active: str = Form(...),
):
    run_dir = RUNS_DIR / run_id
    if not run_dir.exists():
        return JSONResponse({"run_id": run_id, "error": "Run not found"}, status_code=404)

    resolved_doc_type = infer_doc_type(doc_type, None, run_dir)
    if not resolved_doc_type:
        return JSONResponse({"run_id": run_id, "error": "Missing doc_type (g28 or passport)"}, status_code=400)

    artifact = read_text_artifact(run_dir, resolved_doc_type)
    if not artifact:
        return JSONResponse({"run_id": run_id, "error": "text_artifact.json not found"}, status_code=404)

    if active not in {"raw", "translated_en"}:
        return JSONResponse({"run_id": run_id, "error": "active must be raw or translated_en"}, status_code=400)
    if active == "translated_en" and not artifact.get("text", {}).get("translated_en"):
        return JSONResponse({"run_id": run_id, "error": "No translated text available"}, status_code=400)

    updated = upsert_text_artifact(
        run_dir,
        resolved_doc_type,
        source_file=artifact.get("source_file"),
        raw_text=artifact.get("text", {}).get("raw"),
        detected_language=artifact.get("language", {}).get("detected"),
        language_confidence=artifact.get("language", {}).get("confidence"),
        translated_text=artifact.get("text", {}).get("translated_en"),
        active=active,
        ocr_engine=artifact.get("meta", {}).get("ocr_engine"),
        translation_engine=artifact.get("meta", {}).get("translation_engine"),
    )
    _log_run(run_dir, f"Text artifact active set to {active} for {resolved_doc_type}")
    return JSONResponse(
        {
            "run_id": run_id,
            "doc_type": resolved_doc_type,
            "text_active": updated["text"]["active"],
            "translation_warning": updated.get("meta", {}).get("translation_warning"),
        }
    )


@app.post("/autofill")
async def autofill(payload: Dict):
    if not isinstance(payload, dict):
        return JSONResponse({"error": "Invalid payload"}, status_code=400)
    run_id = payload.get("run_id")
    force = bool(payload.get("force"))
    if run_id:
        run_dir = RUNS_DIR / str(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "inputs").mkdir(exist_ok=True)
        _log_run(run_dir, "Starting autofill (reuse run_id)")
    else:
        run_dir = _create_run_dir()
        _log_run(run_dir, "Starting autofill")
    try:
        payload_dict = dict(payload)
        payload_dict.pop("run_id", None)
        payload_dict.pop("_autofill", None)
        payload_dict.pop("force", None)

        result_payload = payload_dict if payload_dict else None
        if not result_payload and run_id:
            extracted_path = run_dir / "extracted.json"
            if extracted_path.exists():
                result_payload = json.loads(extracted_path.read_text())
        if not result_payload:
            return JSONResponse(
                {
                    "run_id": run_dir.name,
                    "error": "Missing extracted payload. Run /extract before /autofill.",
                },
                status_code=400,
            )

        result = ExtractionResult.model_validate(result_payload)

        canonical_fields = None
        if run_id:
            canonical_path = run_dir / "canonical_fields.json"
            if canonical_path.exists():
                canonical_payload = json.loads(canonical_path.read_text())
                canonical_fields = canonical_payload.get("fields") if isinstance(canonical_payload, dict) else None
        if not canonical_fields and run_id:
            resolved_path = run_dir / "resolved_fields.json"
            if resolved_path.exists():
                resolved_payload = json.loads(resolved_path.read_text())
                if isinstance(resolved_payload, dict):
                    canonical_fields = resolved_payload

        if isinstance(canonical_fields, dict):
            result.meta.resolved_fields = {
                key: ResolvedField.model_validate(value)
                for key, value in canonical_fields.items()
            }
        else:
            canonical_fields = None

        passport_text = _read_text_artifact(run_dir, "passport_ocr.txt") if run_id else ""
        g28_text = _read_text_artifact(run_dir, "g28_ocr.txt") if run_id else ""
        review_report, _, _ = validate_post_autofill(
            result,
            {},
            passport_text,
            g28_text,
            use_llm=False,
        )
        review_summary = summarize_review(review_report.get("fields", {}))
        if not review_summary.get("ready_for_autofill") and not force:
            return JSONResponse(
                {
                    "error": "NOT_READY_FOR_AUTOFILL",
                    "summary": review_summary,
                    "blocking_fields": review_summary.get("blocking_fields", []),
                    "review_fields": review_summary.get("review_fields", []),
                },
                status_code=409,
            )
        if force and run_id:
            _log_run(run_dir, "Autofill gate bypassed (force=true)")

        if not payload_dict:
            extracted_path = run_dir / "extracted.json"
            if extracted_path.exists():
                payload_dict = json.loads(extracted_path.read_text())
            else:
                return JSONResponse(
                    {
                        "run_id": run_dir.name,
                        "error": "Missing extracted payload. Run /extract before /autofill.",
                    },
                    status_code=400,
                )
        resolved_payload = None
        if canonical_fields and isinstance(canonical_fields, dict):
            resolved_payload = canonical_fields
        elif result.meta.resolved_fields:
            resolved_payload = {
                key: value.model_dump() if hasattr(value, "model_dump") else dict(value)
                for key, value in result.meta.resolved_fields.items()
            }
        if not resolved_payload:
            return JSONResponse(
                {
                    "run_id": run_dir.name,
                    "error": "No canonical fields available. Run /review and /approve_canonical before /autofill.",
                },
                status_code=400,
            )
        payload_dict = result.model_dump()
        if isinstance(payload_dict, dict):
            payload_dict.setdefault("meta", {})
            payload_dict["meta"]["resolved_fields"] = resolved_payload
        if not _payload_has_autofill_values(payload_dict):
            return JSONResponse(
                {
                    "run_id": run_dir.name,
                    "error": "No extracted values available. Run /extract before /autofill.",
                },
                status_code=400,
            )
        autofill_cfg = CONFIG.autofill
        headless = autofill_cfg.headless
        slow_mo_ms = autofill_cfg.slow_mo_ms
        keep_open_ms = autofill_cfg.keep_open_ms
        form_url = None
        summary = await anyio.to_thread.run_sync(
            fill_form,
            payload_dict,
            run_dir,
            form_url,
            headless,
            slow_mo_ms,
            keep_open_ms,
        )
        _write_json_artifact(run_dir, "autofill_summary.json", summary)
        _log_run(
            run_dir,
            f"Autofill complete. Filled: {len(summary.get('filled_fields', []))} "
            f"Failures: {len(summary.get('fill_failures', {}))}",
        )
        summary["autofill_options"] = {
            "headless": headless,
            "slow_mo_ms": slow_mo_ms,
            "keep_open_ms": keep_open_ms,
            "form_url": form_url or summary.get("form_url"),
        }
        return JSONResponse({"run_id": run_dir.name, "summary": summary})
    except Exception as exc:  # noqa: BLE001
        _log_run(run_dir, f"Autofill failed: {exc}")
        summary = {
            "filled_fields": [],
            "attempted_fields": [],
            "fill_failures": {},
            "dom_readback": {},
            "field_results": {},
            "trace_path": "",
            "final_url": "",
            "error": str(exc),
        }
        return JSONResponse({"run_id": run_dir.name, "summary": summary})


@app.post("/validate")
async def validate(payload: Dict):
    run_dir = _create_run_dir()
    _log_run(run_dir, "Starting validation")
    payload_dict = dict(payload)
    if isinstance(payload_dict, dict):
        payload_dict.pop("_validate", None)
    use_llm = CONFIG.validation.use_llm
    result = ExtractionResult.model_validate(payload_dict)
    report = validate_and_annotate(result, use_llm=use_llm)
    _log_run(
        run_dir,
        f"Validation complete. ok={report.ok} issues={len(report.issues)} score={report.score:.2f} llm={report.llm_used}",
    )
    if report.llm_error:
        _log_run(run_dir, f"Validation LLM error: {report.llm_error}")
    return JSONResponse({"run_id": run_dir.name, "result": result.model_dump(), "report": report.model_dump()})


@app.post("/post_autofill_validate")
async def post_autofill_validate(payload: Dict):
    if not isinstance(payload, dict):
        return JSONResponse({"error": "Invalid payload"}, status_code=400)
    run_id = payload.get("run_id")
    if not run_id:
        return JSONResponse({"error": "Missing run_id"}, status_code=400)
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    _log_run(run_dir, "Starting post-autofill validation")

    result_payload = payload.get("result") if isinstance(payload, dict) else None
    if not result_payload and run_id:
        extracted_path = run_dir / "extracted.json"
        if extracted_path.exists():
            result_payload = json.loads(extracted_path.read_text())
    if not result_payload:
        return JSONResponse({"run_id": run_dir.name, "error": "Missing result payload"}, status_code=400)

    autofill_report = payload.get("autofill_report") if isinstance(payload, dict) else None
    if not autofill_report and run_id:
        autofill_path = run_dir / "autofill_summary.json"
        if autofill_path.exists():
            autofill_report = json.loads(autofill_path.read_text())
    if not autofill_report:
        return JSONResponse(
            {"run_id": run_dir.name, "error": "Missing autofill report; run /autofill first."},
            status_code=400,
        )

    passport_text = ""
    g28_text = ""
    passport_path = run_dir / "passport_ocr.txt"
    g28_path = run_dir / "g28_ocr.txt"
    if passport_path.exists():
        passport_text = passport_path.read_text()
    if g28_path.exists():
        g28_text = g28_path.read_text()

    result = ExtractionResult.model_validate(result_payload)
    report, llm_error, updated = validate_post_autofill(
        result,
        autofill_report,
        passport_text,
        g28_text,
        use_llm=CONFIG.validation.use_llm,
    )
    report_payload = dict(report)
    if llm_error:
        report_payload["llm_error"] = llm_error
    if isinstance(autofill_report, dict) and autofill_report.get("form_completeness"):
        report_payload["form_completeness"] = autofill_report.get("form_completeness")

    _write_json_artifact(run_dir, "post_autofill_validation.json", report_payload)
    _write_final_snapshot(run_dir, run_dir.name, updated, autofill_report, report_payload)
    coverage_report = build_e2e_coverage_report(
        run_id=run_dir.name,
        result=updated,
        autofill_report=autofill_report,
        validation_report=report_payload,
    )
    _write_json_artifact(run_dir, "e2e_coverage_report.json", coverage_report)
    _log_run(run_dir, "Post-autofill validation complete")

    return JSONResponse(
        {
            "run_id": run_dir.name,
            "result": updated.model_dump(),
            "report": report_payload,
        }
    )


def _get_value_from_payload(payload: Dict, path: str) -> Optional[str]:
    parts = path.split(".")
    value: object = payload
    for part in parts:
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    if value is None:
        return None
    return str(value)


def _payload_has_autofill_values(payload: Dict) -> bool:
    if not isinstance(payload, dict):
        return False
    meta = payload.get("meta")
    if isinstance(meta, dict):
        resolved = meta.get("resolved_fields", {})
        if isinstance(resolved, dict):
            for entry in resolved.values():
                if not isinstance(entry, dict):
                    continue
                value = entry.get("value")
                if value is not None and str(value).strip():
                    return True
    for spec in iter_autofill_fields():
        value = _get_value_from_payload(payload, spec.key)
        if value is not None and str(value).strip():
            return True
    return False


def _set_value_on_result(result: ExtractionResult, path: str, value: Optional[str]) -> None:
    parts = path.split(".")
    target = result
    for part in parts[:-1]:
        target = getattr(target, part)
    setattr(target, parts[-1], value)


def _allow_placeholder(path: str, spec) -> bool:
    if not spec or spec.required:
        return False
    if path.endswith("address.unit"):
        return True
    if "phone" in path:
        return True
    return False


@app.post("/save_field_edits")
async def save_field_edits(payload: Dict):
    run_id = payload.get("run_id") if isinstance(payload, dict) else None
    edits = payload.get("edits") if isinstance(payload, dict) else None
    force = bool(payload.get("force")) if isinstance(payload, dict) else False
    if not run_id:
        return JSONResponse({"error": "Missing run_id"}, status_code=400)
    if not isinstance(edits, dict) or not edits:
        return JSONResponse({"error": "Missing edits"}, status_code=400)

    run_dir = RUNS_DIR / run_id
    if not run_dir.exists():
        return JSONResponse({"error": "Run not found"}, status_code=404)

    result_payload = payload.get("result") if isinstance(payload, dict) else None
    if not result_payload:
        extracted_path = run_dir / "extracted.json"
        if extracted_path.exists():
            result_payload = json.loads(extracted_path.read_text())
    if not result_payload:
        return JSONResponse({"error": "Missing extracted result"}, status_code=400)

    result = ExtractionResult.model_validate(result_payload)
    now_iso = datetime.utcnow().isoformat()
    errors: Dict[str, str] = {}
    missing_warning_codes = {"label_present_no_value", "label_absent", "missing_required"}

    for path, raw_value in edits.items():
        spec = get_field_spec(path)
        if not spec:
            errors[path] = "Unknown field"
            continue
        value = "" if raw_value is None else str(raw_value).strip()
        if force:
            if value:
                set_field(result, path, value, "USER", 1.0, "User auto-approved")
            else:
                _set_value_on_result(result, path, None)
                result.meta.sources[path] = "USER"
                result.meta.confidence[path] = 1.0
            result.meta.status[path] = "green"
            result.meta.evidence[path] = "User auto-approved"
            result.meta.conflicts.pop(path, None)
            result.meta.warnings = [
                warning
                for warning in result.meta.warnings
                if not (
                    warning.field == path
                    and (warning.code == "conflict" or warning.code in missing_warning_codes)
                )
            ]
            result.meta.resolved_fields[path] = ResolvedField(
                key=path,
                value=value or None,
                status="green",
                confidence=1.0,
                source="USER",
                locked=True,
                requires_human_input=False,
                reason="Auto-approved.",
                suggestions=result.meta.suggestions.get(path, []),
                last_validated_at=now_iso,
                version=(result.meta.resolved_fields.get(path).version if result.meta.resolved_fields.get(path) else 0)
                + 1,
            )
            continue
        allow_placeholder = _allow_placeholder(path, spec)
        if not value:
            status = "red" if spec.required else "amber"
            _set_value_on_result(result, path, None)
            result.meta.status[path] = status
            result.meta.sources[path] = "USER"
            result.meta.confidence[path] = 1.0
            result.meta.evidence[path] = "User cleared value"
            result.meta.conflicts.pop(path, None)
            result.meta.warnings = [
                warning
                for warning in result.meta.warnings
                if not (
                    warning.field == path
                    and (warning.code == "conflict" or warning.code in missing_warning_codes)
                )
            ]
            result.meta.resolved_fields[path] = ResolvedField(
                key=path,
                value=None,
                status=status,
                confidence=1.0,
                source="USER",
                locked=True,
                requires_human_input=True,
                reason="Empty value.",
                suggestions=result.meta.suggestions.get(path, []),
                last_validated_at=now_iso,
                version=(result.meta.resolved_fields.get(path).version if result.meta.resolved_fields.get(path) else 0)
                + 1,
            )
            continue

        context = {}
        if spec.field_type == "zip" or path.endswith("address.zip"):
            country_path = path.replace("zip", "country")
            context["country"] = _get_value_from_payload(result.model_dump(), country_path)
        rule_result = validate_field(
            path,
            spec.field_type,
            value,
            spec.label_hints,
            context=context,
            allow_placeholder=allow_placeholder,
        )
        normalized = rule_result.normalized or value
        is_valid = rule_result.is_valid
        status = "green"
        if not is_valid:
            status = "red"
        elif any(code in {"state_non_standard", "postal_ok", "unit_placeholder"} for code in rule_result.reasons):
            status = "amber"

        set_field(result, path, normalized, "USER", 1.0, "User edit")
        result.meta.status[path] = status
        reason = "User confirmed." if status == "green" else "Value format looks invalid."
        if status == "amber":
            reason = "Needs review."

        result.meta.conflicts.pop(path, None)
        result.meta.warnings = [
            warning
            for warning in result.meta.warnings
            if not (
                warning.field == path
                and (warning.code == "conflict" or warning.code in missing_warning_codes)
            )
        ]
        result.meta.resolved_fields[path] = ResolvedField(
            key=path,
            value=normalized,
            status=status,
            confidence=1.0,
            source="USER",
            locked=True,
            requires_human_input=status != "green",
            reason=reason,
            suggestions=result.meta.suggestions.get(path, []),
            last_validated_at=now_iso,
            version=(result.meta.resolved_fields.get(path).version if result.meta.resolved_fields.get(path) else 0) + 1,
        )

    resolved_payload = {
        key: value.model_dump() for key, value in result.meta.resolved_fields.items()
    }
    _write_json_artifact(run_dir, "resolved_fields.json", resolved_payload)

    autofill_report = {}
    validation_report = {}
    autofill_path = run_dir / "autofill_summary.json"
    validation_path = run_dir / "post_autofill_validation.json"
    if autofill_path.exists():
        autofill_report = json.loads(autofill_path.read_text())
    if validation_path.exists():
        validation_report = json.loads(validation_path.read_text())
    _write_final_snapshot(run_dir, run_id, result, autofill_report, validation_report)

    response_payload = {"run_id": run_id, "result": result.model_dump(), "errors": errors}
    return JSONResponse(response_payload)


@app.post("/run_all")
async def run_all(
    passport: UploadFile = File(None),
    g28: UploadFile = File(None),
    options: Optional[str] = None,
):
    run_dir = _create_run_dir()
    _log_run(run_dir, "Starting run_all pipeline")
    passport_path = _save_upload(passport, run_dir, passport.filename) if passport else None
    g28_path = _save_upload(g28, run_dir, g28.filename) if g28 else None

    if options:
        _log_run(run_dir, "run_all: request options ignored; using config")

    autofill_cfg = CONFIG.autofill
    headless = autofill_cfg.headless
    slow_mo_ms = autofill_cfg.slow_mo_ms
    keep_open_ms = autofill_cfg.keep_open_ms
    form_url = None
    use_llm = CONFIG.validation.use_llm
    use_llm_extract = CONFIG.extraction.use_llm_extract

    _log_run(
        run_dir,
        f"run_all options: headless={headless} slow_mo_ms={slow_mo_ms} keep_open_ms={keep_open_ms} "
        f"use_llm_extract={use_llm_extract} use_llm_validate={use_llm}",
    )

    result, passport_text, g28_text = extract_documents_with_text(
        passport_path, g28_path, use_llm_extract=use_llm_extract, run_dir=run_dir
    )
    _write_text_artifact(run_dir, "passport_ocr.txt", passport_text)
    _write_text_artifact(run_dir, "g28_ocr.txt", g28_text)
    validate_and_annotate(result, use_llm=False)
    if CONFIG.extraction.use_llm_extract:
        contexts = _field_contexts_for_llm(result, passport_text, g28_text)
        context_fields = [ctx.get("field") for ctx in contexts if ctx.get("field")]
        llm_suggestions, llm_error = llm_recover_fields(contexts, result.model_dump())
        if llm_error:
            _add_warning(result, "llm_skipped", f"LLM recovery skipped: {llm_error}")
        else:
            _apply_llm_recovery_suggestions(result, llm_suggestions, context_fields)
            _add_warning(result, "llm_applied", "LLM recovery suggestions added")
    _write_result(run_dir, result)
    _log_run(run_dir, "run_all: extraction complete")

    summary = await anyio.to_thread.run_sync(
        fill_form,
        result.model_dump(),
        run_dir,
        form_url,
        headless,
        slow_mo_ms,
        keep_open_ms,
    )
    _write_json_artifact(run_dir, "autofill_summary.json", summary)
    _log_run(run_dir, "run_all: autofill complete")

    report = validate_and_annotate(result, use_llm=use_llm)
    _log_run(
        run_dir,
        f"run_all: validation complete ok={report.ok} issues={len(report.issues)} score={report.score:.2f}",
    )

    return JSONResponse(
        {
            "run_id": run_dir.name,
            "result": result.model_dump(),
            "summary": summary,
            "report": report.model_dump(),
        }
    )


@app.post("/verify")
async def verify(payload: Dict):
    run_id = payload.get("run_id") if isinstance(payload, dict) else None
    run_dir = RUNS_DIR / run_id if run_id else _create_run_dir()
    run_dir.mkdir(parents=True, exist_ok=True)
    _log_run(run_dir, "Starting verify")

    result_payload = payload.get("result") if isinstance(payload, dict) else None
    if not result_payload and run_id:
        extracted_path = run_dir / "extracted.json"
        if extracted_path.exists():
            result_payload = json.loads(extracted_path.read_text())
    if not result_payload:
        return JSONResponse({"run_id": run_dir.name, "error": "Missing result payload"}, status_code=400)

    autofill_report = payload.get("autofill_report") if isinstance(payload, dict) else None
    if not autofill_report and run_id:
        autofill_path = run_dir / "autofill_summary.json"
        if autofill_path.exists():
            autofill_report = json.loads(autofill_path.read_text())

    passport_text = ""
    g28_text = ""
    passport_path = run_dir / "passport_ocr.txt"
    g28_path = run_dir / "g28_ocr.txt"
    if passport_path.exists():
        passport_text = passport_path.read_text()
    if g28_path.exists():
        g28_text = g28_path.read_text()

    statuses = result_payload.get("meta", {}).get("status", {}) if isinstance(result_payload, dict) else {}
    review_fields = []
    for field in iter_validation_fields():
        status = statuses.get(field.key, "unknown")
        if status in {"red", "yellow"}:
            review_fields.append(field.key)
    if not review_fields:
        review_fields = [field.key for field in iter_validation_fields()]

    verification, error = llm_verify(
        passport_text,
        g28_text,
        result_payload,
        statuses,
        review_fields,
        autofill_report,
    )

    result = ExtractionResult.model_validate(result_payload)
    if verification:
        result.meta.llm_verification = verification
        for path, suggestions in (verification.get("suggestions") or {}).items():
            for item in suggestions:
                add_suggestion(
                    result,
                    path,
                    item.get("value", ""),
                    item.get("reason"),
                    "LLM",
                    item.get("confidence"),
                    item.get("evidence"),
                    bool(item.get("requires_confirmation", False)),
                )
    if error:
        result.meta.llm_verification = {
            "issues": [],
            "suggestions": {},
            "summary": "",
            "error": error,
        }
        _log_run(run_dir, f"Verify skipped: {error}")

    _write_result(run_dir, result)
    if result.meta.llm_verification:
        _write_json_artifact(run_dir, "verification.json", result.meta.llm_verification)
    _log_run(run_dir, "Verify complete")

    return JSONResponse(
        {
            "run_id": run_dir.name,
            "result": result.model_dump(),
            "verification": result.meta.llm_verification,
        }
    )
