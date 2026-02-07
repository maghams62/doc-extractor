from __future__ import annotations

from typing import Dict, Optional

from ..field_registry import iter_fields


def _is_empty(value: Optional[object]) -> bool:
    if value is None:
        return True
    return str(value).strip() == ""


def _is_conflict(entry: Dict) -> bool:
    if not isinstance(entry, dict):
        return False
    issue_type = str(entry.get("issue_type") or "")
    if issue_type == "CONFLICT":
        return True
    codes = entry.get("deterministic_codes") or []
    if isinstance(codes, list) and "conflict_sources" in codes:
        return True
    if str(entry.get("human_reason_category") or "") == "CONFLICT_SOURCES":
        return True
    return False


def summarize_review(fields_report: Dict[str, Dict], doc_status: Optional[Dict[str, Dict[str, object]]] = None) -> Dict[str, object]:
    summary = {
        "blocking": 0,
        "needs_review": 0,
        "auto_approved": 0,
        "optional_missing": 0,
        "required_missing": 0,
        "conflicts": 0,
        "total": 0,
        "blocking_fields": [],
        "review_fields": [],
        "auto_fields": [],
    }

    skipped_prefixes = set()
    if isinstance(doc_status, dict):
        for group, meta in doc_status.items():
            status = str((meta or {}).get("status", "")).lower()
            if status in {"absent", "mismatch"}:
                skipped_prefixes.add(f"{group}.")

    for spec in iter_fields():
        path = spec.key
        if any(path.startswith(prefix) for prefix in skipped_prefixes):
            continue
        entry = fields_report.get(path, {}) if isinstance(fields_report, dict) else {}
        required = bool(spec.required)
        value = entry.get("dom_readback_value")
        if value is None:
            value = entry.get("extracted_value")
        value_missing = _is_empty(value)

        conflict = _is_conflict(entry)
        if conflict:
            summary["needs_review"] += 1
            summary["review_fields"].append(path)
            summary["conflicts"] += 1
        else:
            summary["auto_approved"] += 1
            summary["auto_fields"].append(path)

        if not required and value_missing:
            summary["optional_missing"] += 1
        if required and value_missing:
            summary["required_missing"] += 1
        summary["total"] += 1

    summary["ready_for_autofill"] = summary["conflicts"] == 0
    summary["skipped_groups"] = sorted(prefix.rstrip(".") for prefix in skipped_prefixes)
    return summary
