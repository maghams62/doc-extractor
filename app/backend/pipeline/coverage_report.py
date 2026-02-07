from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional

from ..field_registry import iter_fields
from ..schemas import ExtractionResult


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


def _resolved_override_value(result: ExtractionResult, path: str) -> Optional[str]:
    entry = (result.meta.resolved_fields or {}).get(path)
    if not entry:
        return None
    source = str(entry.source or "").upper()
    value = entry.value
    if value is None or str(value).strip() == "":
        return None
    if source in {"USER", "AI"}:
        return str(value)
    return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_e2e_coverage_report(
    *,
    run_id: str,
    result: ExtractionResult,
    autofill_report: Dict,
    validation_report: Dict,
) -> Dict[str, object]:
    payload = result.model_dump()
    field_results = autofill_report.get("field_results", {}) or {}
    attempted_fields = set(autofill_report.get("attempted_fields", []) or [])
    filled_fields = set(autofill_report.get("filled_fields", []) or [])
    fill_failures = autofill_report.get("fill_failures", {}) or {}
    dom_readback = autofill_report.get("dom_readback", {}) or {}

    validation_fields = validation_report.get("fields", {}) if isinstance(validation_report, dict) else {}

    fields = []
    for spec in iter_fields():
        path = spec.key
        extracted_value = _get_value(payload, path)
        resolved_override_value = _resolved_override_value(result, path)
        autofill_entry = field_results.get(path) if isinstance(field_results, dict) else None

        attempted = False
        selector_used = None
        dom_value = None
        autofill_result = None
        failure_reason = None
        if isinstance(autofill_entry, dict):
            attempted = bool(autofill_entry.get("attempted", False))
            selector_used = autofill_entry.get("selector_used")
            dom_value = autofill_entry.get("dom_readback_value")
            autofill_result = autofill_entry.get("result")
            failure_reason = autofill_entry.get("failure_reason")
        else:
            attempted = path in attempted_fields or path in filled_fields
            dom_value = dom_readback.get(path)
            failure_reason = fill_failures.get(path)

        value_present = False
        if resolved_override_value and str(resolved_override_value).strip():
            value_present = True
        if extracted_value and str(extracted_value).strip():
            value_present = True

        if not spec.autofill:
            attempted = False
            selector_used = None
            autofill_result = "SKIP"
            failure_reason = "no_autofill_spec"
        elif not value_present and not attempted:
            autofill_result = "SKIP"
            failure_reason = failure_reason or "no_value"
        else:
            if not autofill_result:
                if failure_reason:
                    autofill_result = "FAIL"
                elif attempted:
                    autofill_result = "PASS"
                else:
                    autofill_result = "SKIP"

        validation_entry = validation_fields.get(path, {}) if isinstance(validation_fields, dict) else {}
        deterministic_validation = validation_entry.get("deterministic_validation", {}) or {}
        deterministic_verdict = (
            deterministic_validation.get("verdict")
            or validation_entry.get("deterministic_verdict")
            or "NEEDS_REVIEW"
        )
        deterministic_reason_codes = (
            deterministic_validation.get("reason_codes")
            or validation_entry.get("deterministic_codes")
            or []
        )
        llm_validation = validation_entry.get("llm_validation") or {}
        llm_invoked = bool(validation_entry.get("llm_validation_invoked")) or bool(llm_validation)
        llm_verdict = llm_validation.get("verdict") or validation_entry.get("llm_verdict")
        llm_score = llm_validation.get("score") or validation_entry.get("llm_score")
        llm_reason = llm_validation.get("reason") or validation_entry.get("llm_reason")
        requires_human_input = bool(validation_entry.get("requires_human_input", False))
        human_reason_category = validation_entry.get("human_reason_category") or "OPTIONAL_EMPTY"

        fields.append(
            {
                "field": path,
                "extracted_value": extracted_value,
                "resolved_override_value": resolved_override_value,
                "autofill_attempted": attempted,
                "autofill_selector_used": selector_used,
                "dom_readback_value": dom_value,
                "autofill_result": autofill_result,
                "autofill_failure_reason_code": failure_reason,
                "deterministic_validation_verdict": deterministic_verdict,
                "deterministic_reason_codes": deterministic_reason_codes,
                "llm_validation_invoked": llm_invoked,
                "llm_verdict": llm_verdict,
                "llm_score": llm_score,
                "llm_reason": llm_reason,
                "requires_human_input": requires_human_input,
                "human_reason_category": human_reason_category,
            }
        )

    return {
        "run_id": run_id,
        "generated_at": _now_iso(),
        "fields": fields,
    }
