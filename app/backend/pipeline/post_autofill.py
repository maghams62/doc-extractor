from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import requests

from ..field_registry import get_field_spec, iter_fields
from ..schemas import ExtractionResult, ResolvedField, SuggestionOption
from .label_noise import is_placeholder_value
from .prompts import (
    FIELD_VALIDATION_PROMPT,
    FIELD_VALIDATION_PROMPT_FAST,
    build_field_validation_prompt,
)
from .rules import validate_field


DEFAULT_OPENAI_ENDPOINT = "https://api.openai.com/v1/chat/completions"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


def _load_dotenv() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    candidates = [repo_root / ".env", Path.cwd() / ".env"]
    for env_path in candidates:
        if not env_path.exists():
            continue
        try:
            for line in env_path.read_text().splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                key, value = stripped.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
        except Exception:  # noqa: BLE001
            continue
        break


def _resolve_llm_config() -> Tuple[Optional[str], Optional[str], str, float]:
    _load_dotenv()
    endpoint = os.getenv("LLM_ENDPOINT")
    api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    model = (
        os.getenv("LLM_MODEL")
        or os.getenv("OPENAI_MODEL")
        or DEFAULT_OPENAI_MODEL
    ).strip()
    if not endpoint and os.getenv("OPENAI_API_KEY"):
        endpoint = DEFAULT_OPENAI_ENDPOINT
    timeout = float(os.getenv("LLM_TIMEOUT", "30"))
    return endpoint, api_key, model, timeout


def _llm_enabled() -> bool:
    _load_dotenv()
    raw = os.getenv("ENABLE_LLM")
    if raw is None:
        return True
    return raw.strip().lower() in {"1", "true", "yes"}


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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _values_equal(a: Optional[str], b: Optional[str]) -> bool:
    if a is None and b is None:
        return True
    return str(a or "").strip() == str(b or "").strip()


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


def _is_empty(value: Optional[str]) -> bool:
    return value is None or str(value).strip() == ""


def _deterministic_verdict(status: str) -> str:
    normalized = _normalize_status(status) or "unknown"
    if normalized == "green":
        return "VERIFIED"
    if normalized == "amber":
        return "NEEDS_REVIEW"
    if normalized == "red":
        return "MISSING_OR_INCORRECT"
    return "NEEDS_REVIEW"


def _normalize_llm_text(value: Optional[str], limit: int) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _read_env_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None:
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        return default
    return value if value > 0 else default


def _locked_by_user_or_ai(existing: Optional[ResolvedField]) -> bool:
    if not existing or not existing.locked:
        return False
    source = str(existing.source or "").upper()
    return source in {"USER", "AI"}


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def _resolve_prompt_style(contexts: List[Dict]) -> str:
    raw = os.getenv("LLM_VALIDATE_PROMPT_STYLE", "fast").strip().lower()
    if raw in {"fast", "full"}:
        return raw
    if raw == "auto":
        threshold = _read_env_int("LLM_VALIDATE_FAST_THRESHOLD", 20)
        return "fast" if len(contexts) > threshold else "full"
    return "fast"


def _llm_validate_scope() -> str:
    raw = os.getenv("LLM_VALIDATE_SCOPE", "smart").strip().lower()
    if raw in {"all", "smart", "issues", "issues_only", "required_only"}:
        return raw
    return "smart"


def _estimate_prompt_tokens(contexts: List[Dict], prompt_style: str) -> int:
    template = FIELD_VALIDATION_PROMPT_FAST if prompt_style == "fast" else FIELD_VALIDATION_PROMPT
    payload = json.dumps(contexts, ensure_ascii=True, separators=(",", ":"))
    output_tokens = _read_env_int("LLM_VALIDATE_OUTPUT_TOKENS_PER_FIELD", 40) * len(contexts)
    return _estimate_tokens(template) + _estimate_tokens(payload) + output_tokens


def _auto_batch_size(contexts: List[Dict], prompt_style: str) -> int:
    if not contexts:
        return 0
    est_tokens = _estimate_prompt_tokens(contexts, prompt_style)
    target_tokens = _read_env_int("LLM_VALIDATE_TARGET_TOKENS", 3500)
    if est_tokens <= target_tokens:
        return 0
    per_item = max(1, est_tokens // len(contexts))
    batch = max(5, min(len(contexts), target_tokens // per_item))
    return batch if batch < len(contexts) else 0


def _resolve_batch_size(contexts: List[Dict], prompt_style: Optional[str] = None) -> int:
    raw = os.getenv("LLM_VALIDATE_BATCH_SIZE", "auto").strip().lower()
    style = prompt_style or _resolve_prompt_style(contexts)
    if raw in {"", "auto"}:
        return _auto_batch_size(contexts, style)
    try:
        batch_size = int(raw)
    except ValueError:
        batch_size = 0
    if batch_size <= 0:
        return _auto_batch_size(contexts, style)
    return batch_size


def _allow_placeholder(spec) -> bool:
    if not spec or spec.required:
        return False
    if spec.key.endswith("address.unit"):
        return True
    if "phone" in spec.key:
        return True
    return False


def _deterministic_reason(issue_type: str, detail: Optional[str] = None) -> str:
    base = {
        "OK": "Looks valid.",
        "EMPTY_REQUIRED": "Expected in document but extraction likely failed.",
        "EMPTY_OPTIONAL": "Optional field left empty.",
        "EMPTY_OPTIONAL_PRESENT": "Label present but optional field missing.",
        "INVALID_FORMAT": "Value format looks invalid.",
        "SUSPECT_LABEL_CAPTURE": "Looks like a label or header, not a value.",
        "CONFLICT": "Conflicts with other address fields.",
        "AUTOFILL_FAILED": "Autofill failed to set this field.",
        "NOT_PRESENT_IN_DOC": "Not found in document; needs human input.",
        "HUMAN_REQUIRED": "Human consent required; do not autofill.",
    }.get(issue_type, "Needs review.")
    if detail:
        return f"{base} {detail}"
    return base


def _human_reason_payload(
    *,
    spec,
    presence: str,
    conflict: bool,
    issue_type: str,
    failure_reason: Optional[str],
    deterministic_codes: List[str],
    value_missing: bool,
) -> Dict[str, object]:
    payload = {
        "requires_human_input": False,
        "human_reason": "",
        "human_reason_category": "OPTIONAL_EMPTY",
        "human_action": "",
    }
    if conflict:
        payload.update(
            {
                "requires_human_input": True,
                "human_reason": "Conflict between credible sources; user confirmation required.",
                "human_reason_category": "CONFLICT_SOURCES",
                "human_action": "Confirm which source is correct.",
            }
        )
        return payload
    if failure_reason:
        if spec.required:
            payload.update(
                {
                    "requires_human_input": True,
                    "human_reason": f"Autofill failed: {failure_reason}.",
                    "human_reason_category": "AUTOFILL_FAILED",
                    "human_action": "Enter manually or update the form selector mapping.",
                }
            )
        else:
            payload.update(
                {
                    "requires_human_input": False,
                    "human_reason": "Optional field autofill failed.",
                    "human_reason_category": "OPTIONAL_EMPTY",
                    "human_action": "Enter manually if needed.",
                }
            )
        return payload
    if value_missing:
        if spec.required:
            if presence == "present":
                reason = "Label found but value missing in extraction."
            elif presence == "absent":
                reason = "Value not found in the document."
            else:
                reason = "Value missing from extraction."
            payload.update(
                {
                    "requires_human_input": True,
                    "human_reason": reason,
                    "human_reason_category": "MISSING_NOT_FOUND",
                    "human_action": "Enter manually or re-upload a clearer document.",
                }
            )
        else:
            payload.update(
                {
                    "requires_human_input": False,
                    "human_reason": "Optional field left blank.",
                    "human_reason_category": "OPTIONAL_EMPTY",
                    "human_action": "No action required.",
                }
            )
        return payload
    if issue_type == "SUSPECT_LABEL_CAPTURE":
        payload.update(
            {
                "requires_human_input": True,
                "human_reason": "Captured value looks like a label, not a real value.",
                "human_reason_category": "MISSING_NOT_FOUND",
                "human_action": "Enter the correct value manually.",
            }
        )
        return payload
    if issue_type == "INVALID_FORMAT":
        if "date_format" in deterministic_codes:
            payload.update(
                {
                    "requires_human_input": True,
                    "human_reason": "Ambiguous date format; cannot normalize safely.",
                    "human_reason_category": "AMBIGUOUS_EVIDENCE",
                    "human_action": "Confirm the correct date format.",
                }
            )
        else:
            payload.update(
                {
                    "requires_human_input": True,
                    "human_reason": "Value format looks invalid.",
                    "human_reason_category": "INVALID_FORMAT",
                    "human_action": "Correct the value manually.",
                }
            )
        return payload
    return payload


def _should_invoke_llm(
    *,
    spec,
    deterministic_status: str,
    conflict: bool,
    failure_reason: Optional[str],
    presence: str,
    value_missing: bool,
    attempted: bool,
) -> bool:
    scope = _llm_validate_scope()
    if scope == "all":
        return True
    if scope in {"issues", "issues_only"}:
        return bool(conflict or failure_reason or deterministic_status in {"amber", "red"})
    if scope == "required_only":
        return bool(spec.required and not value_missing)

    # Some OCR-prone fields are worth validating even when deterministic rules pass.
    high_risk_fields = {"passport.place_of_birth"}
    if spec.key in high_risk_fields and not value_missing:
        return True

    # Smart default: skip clear non-issues, focus on autofilled + risky fields.
    if bool(getattr(spec, "human_required", False)):
        return False
    if value_missing and not spec.required and presence == "absent" and not attempted:
        return False
    if conflict or failure_reason or deterministic_status in {"amber", "red"}:
        return True
    if attempted:
        return True
    if spec.required and not value_missing:
        return True

    high_risk_types = {
        "name",
        "date_past",
        "date_future",
        "passport_number",
        "email",
        "phone",
        "state",
        "zip",
        "sex",
    }
    return bool(not value_missing and spec.field_type in high_risk_types)


def _normalize_status(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    lowered = str(value).strip().lower()
    if lowered in {"green", "amber", "red"}:
        return lowered
    return None


def _final_status(deterministic_status: str, llm_verdict: Optional[str]) -> str:
    det = _normalize_status(deterministic_status) or "unknown"
    llm = _normalize_status(llm_verdict)
    if det == "red":
        return "red"
    if det == "amber":
        if llm == "green":
            return "green"
        if llm == "red":
            return "red"
        return "amber"
    if det == "green":
        if llm in {"amber", "red"}:
            return "amber"
        return "green"
    return llm or det


def _suggestion_grounded(suggested_value: str, evidence: str) -> bool:
    if not suggested_value or not evidence:
        return False
    if suggested_value.lower() in evidence.lower():
        return True
    normalized_ev = re.sub(r"\s+", "", evidence).lower()
    normalized_val = re.sub(r"\s+", "", suggested_value).lower()
    if normalized_val and normalized_val in normalized_ev:
        return True
    ev_alnum = re.sub(r"[^a-z0-9]", "", evidence.lower())
    val_alnum = re.sub(r"[^a-z0-9]", "", suggested_value.lower())
    return bool(val_alnum) and val_alnum in ev_alnum


def _trivial_normalization(a: Optional[str], b: Optional[str]) -> bool:
    if not a or not b:
        return False
    a_norm = re.sub(r"[^a-z0-9]", "", str(a).lower())
    b_norm = re.sub(r"[^a-z0-9]", "", str(b).lower())
    return bool(a_norm) and a_norm == b_norm


def _chunk_contexts(contexts: List[Dict], batch_size: int) -> List[List[Dict]]:
    if batch_size <= 0:
        return [contexts]
    return [contexts[i : i + batch_size] for i in range(0, len(contexts), batch_size)]


def _call_llm_validation(contexts: List[Dict]) -> Tuple[List[Dict], Optional[str]]:
    if not _llm_enabled():
        return [], "LLM disabled (ENABLE_LLM is not set)"
    endpoint, api_key, model, timeout = _resolve_llm_config()
    if not endpoint:
        return [], "LLM endpoint not configured"
    if not api_key:
        return [], "LLM API key not configured"

    prompt_style = _resolve_prompt_style(contexts)
    prompt = build_field_validation_prompt(contexts, fast=(prompt_style == "fast"))
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Return JSON only. Do not wrap in markdown."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
    }
    try:
        resp = requests.post(endpoint, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        parsed = json.loads(content)
    except Exception as exc:  # noqa: BLE001
        return [], f"LLM validation failed: {exc}"

    if isinstance(parsed, dict):
        parsed = parsed.get("results") or parsed.get("fields") or []
    if not isinstance(parsed, list):
        return [], "LLM validation returned non-list JSON"
    return parsed, None


def validate_post_autofill(
    result: ExtractionResult,
    autofill_report: Dict,
    passport_text: str,
    g28_text: str,
    use_llm: bool = True,
    llm_client: Optional[Callable[[List[Dict]], Tuple[List[Dict], Optional[str]]]] = None,
) -> Tuple[Dict, Optional[str], ExtractionResult]:
    payload = result.model_dump()
    autofill_field_results = autofill_report.get("field_results", {}) or {}
    attempted_fields = set(autofill_report.get("attempted_fields", []) or [])
    filled_fields = set(autofill_report.get("filled_fields", []) or [])
    fill_failures = autofill_report.get("fill_failures", {}) or {}
    dom_readback = autofill_report.get("dom_readback", {}) or {}
    existing_resolved = result.meta.resolved_fields or {}
    conflict_fields = set((result.meta.conflicts or {}).keys())
    warning_conflicts = {
        warning.field
        for warning in result.meta.warnings
        if warning.code == "conflict" and warning.field
    }
    conflict_fields.update(warning_conflicts)

    fields_report: Dict[str, Dict] = {}
    contexts: List[Dict] = []
    llm_invoked: Dict[str, bool] = {}
    now_iso = _now_iso()
    label_limit = _read_env_int("LLM_LABEL_MAX_CHARS", 80)
    value_limit = _read_env_int("LLM_VALUE_MAX_CHARS", 120)
    evidence_limit = _read_env_int("LLM_EVIDENCE_MAX_CHARS", 320)
    reason_limit = _read_env_int("LLM_REASON_MAX_CHARS", 160)

    for spec in iter_fields():
        path = spec.key
        existing = existing_resolved.get(path)
        locked_by_user_or_ai = _locked_by_user_or_ai(existing)
        extracted_value = _get_value(payload, path)
        resolved_override_value = _resolved_override_value(result, path)
        entry = autofill_field_results.get(path) if isinstance(autofill_field_results, dict) else None
        dom_value = None
        selector_used = None
        autofill_result = None
        failure_reason = None
        attempted = False
        available_options = None
        if isinstance(entry, dict):
            dom_value = entry.get("dom_readback_value")
            selector_used = entry.get("selector_used")
            autofill_result = entry.get("result")
            failure_reason = entry.get("failure_reason") or fill_failures.get(path)
            attempted = bool(entry.get("attempted", False))
            available_options = entry.get("available_options")
        else:
            dom_value = dom_readback.get(path)
            failure_reason = fill_failures.get(path)
            attempted = path in attempted_fields or path in filled_fields
        if not autofill_result:
            if failure_reason:
                autofill_result = "FAIL"
            elif attempted:
                autofill_result = "PASS"
            else:
                autofill_result = "SKIP"
        presence = result.meta.presence.get(path, "unknown")

        value = dom_value if dom_value is not None else extracted_value
        value = str(value).strip() if value is not None else ""
        value_missing = _is_empty(value)
        conflict = path in conflict_fields

        if locked_by_user_or_ai:
            deterministic_status = existing.status or "green"
            deterministic_verdict = _deterministic_verdict(deterministic_status)
            human_category = "OPTIONAL_EMPTY"
            human_reason = existing.reason or "Locked by user."
            requires_human = bool(existing.requires_human_input)
            if requires_human:
                human_category = "MISSING_NOT_FOUND"
            fields_report[path] = {
                "field": path,
                "status": deterministic_status,
                "deterministic_status": deterministic_status,
                "deterministic_verdict": deterministic_verdict,
                "issue_type": "OK",
                "deterministic_reason": human_reason,
                "deterministic_codes": [],
                "deterministic_validation": {
                    "status": deterministic_status,
                    "verdict": deterministic_verdict,
                    "reason_codes": [],
                    "reason": human_reason,
                },
                "llm_validation": None,
                "extracted_value": extracted_value,
                "resolved_override_value": resolved_override_value,
                "dom_readback_value": dom_value,
                "attempted_autofill": attempted,
                "autofill_result": autofill_result,
                "autofill_failure": failure_reason,
                "autofill_selector_used": selector_used,
                "autofill_available_options": available_options,
                "locked": True,
                "requires_human_input": requires_human,
                "human_reason": human_reason,
                "human_reason_category": human_category,
                "human_action": "No action required." if not requires_human else "Confirm or enter manually.",
                "llm_validation_invoked": False,
            }
            continue

        issue_type = "OK"
        status = "green"
        deterministic_codes: List[str] = []
        deterministic_reason = ""

        human_required = bool(getattr(spec, "human_required", False))
        human_required_reason = getattr(spec, "human_required_reason", None) or _deterministic_reason("HUMAN_REQUIRED")
        failure_reason_for_rules = failure_reason if autofill_result == "FAIL" else None
        skip_rules = False

        if human_required and value_missing:
            status = "amber"
            issue_type = "HUMAN_REQUIRED"
            deterministic_codes.append("human_required")
            deterministic_reason = human_required_reason
            skip_rules = True

        if not skip_rules:
            if failure_reason_for_rules:
                status = "red" if spec.required else "amber"
                issue_type = "AUTOFILL_FAILED"
                deterministic_codes.append(f"autofill_{failure_reason_for_rules}")
                deterministic_reason = _deterministic_reason(issue_type, failure_reason_for_rules)
            elif value_missing:
                deterministic_codes.append("empty")
                if spec.required:
                    status = "red"
                    issue_type = "NOT_PRESENT_IN_DOC" if presence == "absent" else "EMPTY_REQUIRED"
                    deterministic_reason = _deterministic_reason(issue_type)
                else:
                    if presence == "present":
                        status = "amber"
                        issue_type = "EMPTY_OPTIONAL_PRESENT"
                        deterministic_reason = _deterministic_reason(issue_type)
                    else:
                        status = "green"
                        issue_type = "EMPTY_OPTIONAL"
                        deterministic_reason = _deterministic_reason(issue_type)
            else:
                allow_placeholder = _allow_placeholder(spec)
                if allow_placeholder and is_placeholder_value(value):
                    status = "amber"
                    issue_type = "EMPTY_OPTIONAL"
                    deterministic_codes.append("placeholder_ok")
                    deterministic_reason = _deterministic_reason(issue_type)
                else:
                    rule_result = validate_field(
                        path,
                        spec.field_type,
                        value,
                        spec.label_hints,
                        context={"country": _get_value(payload, path.replace("zip", "country"))},
                        allow_placeholder=allow_placeholder,
                    )
                    if not rule_result.is_valid:
                        status = "red"
                        if any(code in {"label_noise", "address_label", "email_label", "phone_label"} for code in rule_result.reasons):
                            issue_type = "SUSPECT_LABEL_CAPTURE"
                        else:
                            issue_type = "INVALID_FORMAT"
                    else:
                        if any(
                            code in {"state_non_standard", "postal_ok", "unit_placeholder", "account_number_unverified"}
                            for code in rule_result.reasons
                        ):
                            status = "amber"
                        else:
                            status = "green"
                    deterministic_codes.extend(rule_result.reasons)
                    deterministic_reason = _deterministic_reason(issue_type)

            if conflict:
                deterministic_codes.append("conflict_sources")
                if status == "green":
                    status = "amber"
                    issue_type = "CONFLICT"
                    deterministic_reason = _deterministic_reason(issue_type)

        deterministic_status = status
        deterministic_reason = deterministic_reason or _deterministic_reason(issue_type)
        deterministic_verdict = _deterministic_verdict(deterministic_status)
        if human_required and value_missing:
            human_payload = {
                "requires_human_input": True,
                "human_reason": human_required_reason,
                "human_reason_category": "HUMAN_CONSENT",
                "human_action": "Complete manually in the form.",
            }
        else:
            human_payload = _human_reason_payload(
                spec=spec,
                presence=presence,
                conflict=conflict,
                issue_type=issue_type,
                failure_reason=failure_reason_for_rules,
                deterministic_codes=deterministic_codes,
                value_missing=value_missing,
            )
        fields_report[path] = {
            "field": path,
            "status": status,
            "deterministic_status": deterministic_status,
            "deterministic_verdict": deterministic_verdict,
            "issue_type": issue_type,
            "deterministic_reason": deterministic_reason,
            "deterministic_codes": deterministic_codes,
            "deterministic_validation": {
                "status": deterministic_status,
                "issue_type": issue_type,
                "verdict": deterministic_verdict,
                "reason_codes": deterministic_codes,
                "reason": deterministic_reason,
            },
            "llm_validation": None,
            "extracted_value": extracted_value,
            "resolved_override_value": resolved_override_value,
            "dom_readback_value": dom_value,
            "attempted_autofill": attempted,
            "autofill_result": autofill_result,
            "autofill_failure": failure_reason,
            "autofill_selector_used": selector_used,
            "autofill_available_options": available_options,
            "locked": bool(existing.locked) if existing else False,
            "requires_human_input": human_payload["requires_human_input"],
            "human_reason": human_payload["human_reason"],
            "human_reason_category": human_payload["human_reason_category"],
            "human_action": human_payload["human_action"],
            "llm_validation_invoked": False,
        }

        evidence = result.meta.evidence.get(path) or ""
        llm_needed = _should_invoke_llm(
            spec=spec,
            deterministic_status=deterministic_status,
            conflict=conflict,
            failure_reason=failure_reason_for_rules,
            presence=presence,
            value_missing=value_missing,
            attempted=attempted,
        )
        if locked_by_user_or_ai:
            llm_invoked[path] = False
        else:
            llm_invoked[path] = bool(use_llm and llm_needed)
        if use_llm and llm_needed and not locked_by_user_or_ai:
            label_text = _normalize_llm_text(spec.label, label_limit)
            extracted_text = _normalize_llm_text(extracted_value, value_limit)
            dom_text = _normalize_llm_text(dom_value, value_limit)
            evidence_text = _normalize_llm_text(evidence or "not found", evidence_limit)
            deterministic_reason_text = _normalize_llm_text(deterministic_reason, reason_limit)
            human_reason_text = _normalize_llm_text(
                human_required_reason if human_required else "",
                reason_limit,
            )
            contexts.append(
                {
                    "field": path,
                    "label": label_text,
                    "expected_type": spec.field_type,
                    "extracted_value": extracted_text,
                    "dom_readback_value": dom_text,
                    "evidence": evidence_text,
                    "presence": presence,
                    "deterministic_status": deterministic_status,
                    "deterministic_reason_codes": deterministic_codes,
                    "deterministic_reason": deterministic_reason_text,
                    "deterministic_issue_type": issue_type,
                    "human_required": human_required,
                    "human_required_reason": human_reason_text,
                }
            )

    # Cross-field consistency checks (country vs US state/ZIP).
    attorney_addr = result.g28.attorney.address
    if attorney_addr.state and attorney_addr.zip and attorney_addr.country:
        if (
            len(attorney_addr.state.strip()) == 2
            and attorney_addr.zip.strip().isdigit()
            and attorney_addr.country.strip().lower() not in {"united states", "usa", "us"}
        ):
            path = "g28.attorney.address.country"
            if path in fields_report:
                entry = fields_report[path]
                entry["status"] = "amber"
                entry["deterministic_status"] = "amber"
                entry["issue_type"] = "CONFLICT"
                entry["deterministic_reason"] = _deterministic_reason("CONFLICT")
                entry["deterministic_codes"].append("country_conflict")
                entry["deterministic_verdict"] = _deterministic_verdict("amber")
                entry["deterministic_validation"] = {
                    "status": "amber",
                    "issue_type": "CONFLICT",
                    "verdict": entry["deterministic_verdict"],
                    "reason_codes": entry["deterministic_codes"],
                    "reason": entry["deterministic_reason"],
                }
                entry["requires_human_input"] = True
                entry["human_reason_category"] = "CONFLICT_SOURCES"
                entry["human_reason"] = "Conflict between country and state/ZIP."
                entry["human_action"] = "Confirm the correct country."

    llm_used = False
    llm_error = None
    llm_results: Dict[str, Dict] = {}
    if use_llm and contexts:
        llm_used = True
        llm_call = llm_client or _call_llm_validation
        prompt_style = _resolve_prompt_style(contexts)
        batch_size = _resolve_batch_size(contexts, prompt_style)
        errors = []
        for batch in _chunk_contexts(contexts, batch_size):
            llm_payload, error = llm_call(batch)
            if error:
                errors.append(error)
                continue
            if isinstance(llm_payload, list):
                for item in llm_payload:
                    if not isinstance(item, dict):
                        continue
                    field = item.get("field")
                    if not field:
                        continue
                    llm_results[field] = item
        if errors:
            unique = []
            for err in errors:
                if err not in unique:
                    unique.append(err)
            llm_error = "; ".join(unique)

    updated = result.model_copy(deep=True)

    for path, entry in fields_report.items():
        entry["llm_validation_invoked"] = bool(llm_invoked.get(path, False))
        llm_entry = llm_results.get(path)
        if llm_entry:
            deterministic_status = entry.get("deterministic_status", entry.get("status", "unknown"))
            issue_type = entry.get("issue_type", "OK")
            deterministic_codes = entry.get("deterministic_codes", [])
            verdict = _normalize_status(llm_entry.get("verdict")) or ""
            score = llm_entry.get("score")
            reason = llm_entry.get("reason") or ""
            suggested_value = llm_entry.get("suggested_value")
            suggested_reason = llm_entry.get("suggested_value_reason") or ""
            evidence = llm_entry.get("evidence") or "not found"
            requires_human = bool(llm_entry.get("requires_human_input", False))

            if verdict:
                final_status = _final_status(deterministic_status, verdict)
                entry["status"] = final_status
                entry["llm_verdict"] = verdict
                entry["llm_reason"] = reason
                entry["llm_score"] = score
                entry["llm_requires_human_input"] = requires_human
                entry["llm_evidence"] = evidence
                entry["llm_validation"] = {
                    "verdict": verdict,
                    "score": score,
                    "reason": reason,
                    "evidence": evidence,
                    "suggested_value": suggested_value,
                    "requires_human_input": requires_human,
                }

            suggestion_allowed = bool(suggested_value and evidence and evidence != "not found")
            if deterministic_status == "green":
                suggestion_allowed = False
            if suggestion_allowed and not _suggestion_grounded(str(suggested_value), str(evidence)):
                suggestion_allowed = False
            if suggestion_allowed:
                conflict = path in conflict_fields
                conflict_values = result.meta.conflicts.get(path) if conflict else None
                if _trivial_normalization(entry.get("extracted_value"), suggested_value):
                    suggestion_allowed = True
                elif issue_type in {
                    "SUSPECT_LABEL_CAPTURE",
                    "INVALID_FORMAT",
                    "EMPTY_REQUIRED",
                    "EMPTY_OPTIONAL_PRESENT",
                    "NOT_PRESENT_IN_DOC",
                }:
                    suggestion_allowed = True
                elif conflict and conflict_values:
                    suggestion_allowed = str(suggested_value) in {
                        str(conflict_values.get("passport_value") or ""),
                        str(conflict_values.get("g28_value") or ""),
                    }
                else:
                    suggestion_allowed = False

            if suggestion_allowed:
                updated.meta.suggestions.setdefault(path, []).append(
                    SuggestionOption(
                        value=str(suggested_value),
                        reason=suggested_reason or reason or "LLM suggestion",
                        source="LLM",
                        confidence=float(score) if isinstance(score, (int, float)) else None,
                        evidence=str(evidence),
                        requires_confirmation=requires_human or entry.get("status") in {"amber", "red"} or (path in conflict_fields),
                    )
                )

        updated.meta.status[path] = entry["status"]

    resolved_fields: Dict[str, ResolvedField] = {}
    for path, entry in fields_report.items():
        existing = existing_resolved.get(path)
        if _locked_by_user_or_ai(existing):
            resolved_fields[path] = existing.model_copy(update={"last_validated_at": now_iso})
            continue

        value = entry.get("dom_readback_value")
        if value is None:
            value = entry.get("extracted_value")
        value = str(value).strip() if value is not None else None
        status = entry.get("status", "unknown")
        reason = entry.get("human_reason") or entry.get("llm_reason") or entry.get("deterministic_reason") or ""
        requires_human = bool(entry.get("requires_human_input", False))
        source = updated.meta.sources.get(path, "UNKNOWN")
        confidence = updated.meta.confidence.get(path, 0.0)
        suggestions = updated.meta.suggestions.get(path, [])
        version = (existing.version if existing else 0) + 1
        locked = bool(existing.locked) if existing else False
        if source.upper() == "USER":
            locked = True
        resolved_fields[path] = ResolvedField(
            key=path,
            value=value,
            status=status,
            confidence=confidence,
            source=source,
            locked=locked,
            requires_human_input=requires_human,
            reason=reason,
            deterministic_validation=entry.get("deterministic_validation"),
            llm_validation=entry.get("llm_validation"),
            suggestions=suggestions,
            last_validated_at=now_iso,
            version=version,
        )

    updated.meta.resolved_fields = resolved_fields

    summary = {
        "llm_used": llm_used,
        "llm_error": llm_error,
        "fields": fields_report,
    }
    return summary, llm_error, updated
