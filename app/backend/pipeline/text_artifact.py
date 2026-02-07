from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

from ..field_registry import iter_fields

DOC_ARTIFACT_DIRNAME = "doc_artifacts"
ALLOWED_DOC_TYPES = {"g28", "passport"}
MIN_LINE_RATIO = 0.4
MAX_LINE_RATIO = 2.5
MIN_G28_LABEL_MATCHES = 3

_REGEX_META = re.compile(r"[\\.^$*+?{}\\[\\]|()]")


def normalize_doc_type(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    lowered = value.strip().lower()
    if lowered in ALLOWED_DOC_TYPES:
        return lowered
    return None


def text_artifact_path(run_dir: Path, doc_type: str) -> Path:
    return run_dir / DOC_ARTIFACT_DIRNAME / doc_type / "text_artifact.json"


def _existing_doc_type(run_dir: Path) -> Optional[str]:
    found = []
    for doc_type in sorted(ALLOWED_DOC_TYPES):
        if text_artifact_path(run_dir, doc_type).exists():
            found.append(doc_type)
    if len(found) == 1:
        return found[0]
    return None


def infer_doc_type(value: Optional[str], filename: Optional[str], run_dir: Optional[Path]) -> Optional[str]:
    normalized = normalize_doc_type(value)
    if normalized:
        return normalized
    if run_dir is not None:
        existing = _existing_doc_type(run_dir)
        if existing:
            return existing
    if filename:
        lowered = filename.lower()
        if "g28" in lowered or "g-28" in lowered:
            return "g28"
        if "passport" in lowered:
            return "passport"
    return None


def read_text_artifact(run_dir: Path, doc_type: str) -> Optional[Dict[str, object]]:
    path = text_artifact_path(run_dir, doc_type)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:  # noqa: BLE001
        return None


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def upsert_text_artifact(
    run_dir: Path,
    doc_type: str,
    source_file: Optional[str] = None,
    raw_text: Optional[str] = None,
    detected_language: Optional[str] = None,
    language_confidence: Optional[float] = None,
    translated_text: Optional[str] = None,
    active: Optional[str] = None,
    ocr_engine: Optional[str] = None,
    translation_engine: Optional[str] = None,
    translation_warning: Optional[str] = None,
    translation_check: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    normalized = normalize_doc_type(doc_type)
    if not normalized:
        raise ValueError("doc_type must be 'g28' or 'passport'")

    path = text_artifact_path(run_dir, normalized)
    existing = read_text_artifact(run_dir, normalized) or {}

    language = dict(existing.get("language") or {})
    if detected_language is not None:
        language["detected"] = detected_language
    if language_confidence is not None:
        language["confidence"] = float(language_confidence)
    language.setdefault("detected", "unknown")
    language.setdefault("confidence", 0.0)

    text = dict(existing.get("text") or {})
    if raw_text is not None:
        text["raw"] = raw_text
    if translated_text is not None:
        text["translated_en"] = translated_text
    if active is not None:
        if active not in {"raw", "translated_en"}:
            raise ValueError("active must be 'raw' or 'translated_en'")
        text["active"] = active
    text.setdefault("raw", "")
    text.setdefault("translated_en", None)
    text.setdefault("active", "raw")

    meta = dict(existing.get("meta") or {})
    if "created_at" not in meta:
        meta["created_at"] = _now_iso()
    if ocr_engine and not meta.get("ocr_engine"):
        meta["ocr_engine"] = ocr_engine
    if translation_engine is not None:
        meta["translation_engine"] = translation_engine
    if translation_warning is not None:
        if translation_warning:
            meta["translation_warning"] = translation_warning
        else:
            meta.pop("translation_warning", None)
    if translation_check is not None:
        meta["translation_check"] = translation_check

    payload = {
        "doc_type": normalized,
        "source_file": source_file or existing.get("source_file") or "unknown",
        "language": {
            "detected": language.get("detected", "unknown"),
            "confidence": float(language.get("confidence", 0.0)),
        },
        "text": {
            "raw": text.get("raw", ""),
            "translated_en": text.get("translated_en"),
            "active": text.get("active", "raw"),
        },
        "meta": {
            "ocr_engine": meta.get("ocr_engine", ocr_engine or "tesseract"),
            "translation_engine": meta.get("translation_engine") or translation_engine or "none",
            "created_at": meta.get("created_at", _now_iso()),
            **{k: v for k, v in meta.items() if k not in {"ocr_engine", "translation_engine", "created_at"}},
        },
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))
    return payload


def _plain_label(label: str) -> bool:
    if _REGEX_META.search(label):
        return False
    if re.search(r"\\d", label):
        return False
    stripped = label.strip()
    return len(stripped) >= 3 and re.search(r"[A-Za-z]", stripped)


def _g28_label_phrases() -> Tuple[str, ...]:
    phrases = set()
    for spec in iter_fields():
        if not spec.key.startswith("g28."):
            continue
        for hint in spec.label_hints:
            if _plain_label(hint):
                phrases.add(hint.strip())
    return tuple(sorted(phrases))


G28_LABEL_PHRASES = _g28_label_phrases()


def _count_lines(text: str) -> int:
    return len([line for line in text.splitlines() if line.strip()])


def g28_label_match_count(text: str) -> int:
    if not text:
        return 0
    lowered = text.lower()
    return sum(1 for phrase in G28_LABEL_PHRASES if phrase.lower() in lowered)


def looks_like_g28_text(text: str) -> bool:
    if not text:
        return False
    label_matches = g28_label_match_count(text)
    if label_matches < MIN_G28_LABEL_MATCHES:
        return False
    lowered = text.lower()
    signature_hits = (
        "law firm" in lowered
        or "bar number" in lowered
        or "licensing authority" in lowered
        or "notice of appearance" in lowered
        or "information about attorney" in lowered
    )
    return signature_hits


def translation_structure_check(raw_text: str, translated_text: str, doc_type: str) -> Tuple[Optional[str], Dict[str, object]]:
    raw_lines = _count_lines(raw_text)
    translated_lines = _count_lines(translated_text)
    ratio = translated_lines / max(1, raw_lines)
    details: Dict[str, object] = {
        "raw_lines": raw_lines,
        "translated_lines": translated_lines,
        "line_ratio": round(ratio, 3),
        "min_ratio": MIN_LINE_RATIO,
        "max_ratio": MAX_LINE_RATIO,
    }
    warnings = []
    if ratio < MIN_LINE_RATIO or ratio > MAX_LINE_RATIO:
        warnings.append("Line breaks changed significantly; structure may be degraded.")

    if doc_type == "g28":
        translated_lower = translated_text.lower()
        label_matches = sum(1 for phrase in G28_LABEL_PHRASES if phrase.lower() in translated_lower)
        details["label_matches"] = label_matches
        details["label_threshold"] = MIN_G28_LABEL_MATCHES
        if label_matches < MIN_G28_LABEL_MATCHES:
            warnings.append("Expected English form labels were not preserved.")

    warning_text = " ".join(warnings) if warnings else None
    return warning_text, details
