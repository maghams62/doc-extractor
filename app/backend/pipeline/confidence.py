from __future__ import annotations

import re
from typing import Dict, Optional

from ..schemas import ExtractionResult, SuggestionOption


def _set_nested_attr(obj, path: str, value):
    parts = path.split(".")
    target = obj
    for part in parts[:-1]:
        target = getattr(target, part)
    setattr(target, parts[-1], value)


def _base_confidence_for_source(source: str, match_quality: str = "exact") -> float:
    source_key = source.upper()
    if source_key == "MRZ":
        return 0.95
    if source_key == "LLM":
        return 0.7
    if source_key == "AI":
        return 0.7
    if source_key == "USER":
        return 1.0
    if source_key == "VALIDATOR":
        return 0.85
    if source_key in {"MERGE", "PASSPORT"}:
        return 0.85
    # OCR baseline depends on match quality.
    if source_key == "OCR":
        return 0.6 if match_quality == "fuzzy" else 0.75
    return 0.7


def base_confidence_for_source(source: str, match_quality: str = "exact") -> float:
    return _base_confidence_for_source(source, match_quality=match_quality)


def _value_quality_score(value: Optional[str], evidence: Optional[str] = None) -> float:
    """Return a bounded quality bonus (0-0.15) based on content richness.

    Heuristics:
    - longer strings slightly increase confidence (up to +0.1)
    - alphanumeric balance adds a small boost (up to +0.03)
    - having surrounding evidence text adds +0.02
    """

    if not value:
        return 0.0
    text = str(value).strip()
    length_bonus = min(len(text) / 32, 1.0) * 0.1

    has_alpha = bool(re.search(r"[A-Za-z]", text))
    has_digit = bool(re.search(r"\d", text))
    balance_bonus = 0.0
    if has_alpha:
        balance_bonus += 0.015
    if has_digit:
        balance_bonus += 0.015

    evidence_bonus = 0.02 if evidence else 0.0
    return length_bonus + balance_bonus + evidence_bonus


def estimate_confidence(
    source: str,
    value: Optional[str],
    evidence: Optional[str] = None,
    match_quality: str = "exact",
) -> float:
    """Estimate a confidence score with simple, deterministic heuristics."""
    base = _base_confidence_for_source(source, match_quality=match_quality)
    if source.upper() == "USER":
        return 1.0
    score = base + _value_quality_score(value, evidence)
    return round(max(0.0, min(0.99, score)), 2)


def set_field(
    result: ExtractionResult,
    path: str,
    value: Optional[str],
    source: str,
    confidence: Optional[float],
    evidence: Optional[str] = None,
    match_quality: str = "exact",
) -> None:
    if value is None:
        return
    _set_nested_attr(result, path, value)
    result.meta.sources[path] = source
    result.meta.confidence[path] = confidence if confidence is not None else estimate_confidence(
        source, value, evidence, match_quality=match_quality
    )
    if path not in result.meta.status:
        result.meta.status[path] = "unknown"
    if evidence:
        result.meta.evidence[path] = evidence


def apply_fields(
    result: ExtractionResult,
    fields: Dict[str, Optional[str]],
    source: str,
    confidence: Optional[float],
    evidence: Optional[str] = None,
    match_quality: str = "exact",
) -> None:
    for key, value in fields.items():
        if key.startswith("_"):
            continue
        set_field(result, key, value, source, confidence, evidence, match_quality=match_quality)


def add_suggestion(
    result: ExtractionResult,
    path: str,
    value: str,
    reason: Optional[str],
    source: str,
    confidence: Optional[float] = None,
    evidence: Optional[str] = None,
    requires_confirmation: bool = False,
) -> None:
    if path not in result.meta.suggestions:
        result.meta.suggestions[path] = []
    for existing in result.meta.suggestions[path]:
        if existing.value == value and existing.source == source:
            return
    result.meta.suggestions[path].append(
        SuggestionOption(
            value=value,
            reason=reason,
            source=source,
            confidence=confidence,
            evidence=evidence,
            requires_confirmation=requires_confirmation,
        )
    )
