from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

from .confidence import add_suggestion, base_confidence_for_source
from .label_noise import is_placeholder_value, looks_like_label_value
from .prompts import build_llm_validate_prompt
from .rules import RE_ZIP_US, RuleResult, validate_field
from ..field_registry import iter_validation_fields
from ..schemas import ExtractionResult, ValidationIssue, ValidationReport

LOGGER = logging.getLogger(__name__)


MRZ_LINE_RE = re.compile(r"^(?=.*<)[A-Z0-9<]{30,46}$")
DEFAULT_OPENAI_ENDPOINT = "https://api.openai.com/v1/chat/completions"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


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


def _llm_enabled() -> bool:
    _load_dotenv()
    return os.getenv("ENABLE_LLM", "").strip().lower() in {"1", "true", "yes"}


def _field_specific_invalid(path: str, value: str, payload: Dict) -> Tuple[bool, Optional[str], str]:
    stripped = value.strip()
    if path.endswith("licensing_authority"):
        if re.fullmatch(r"\d+", stripped):
            return True, None, "licensing_authority_numeric"
    if path.endswith("bar_number") and looks_like_label_value(value):
        return True, None, "bar_number_label"
    if path.endswith("law_firm_name") and looks_like_label_value(value):
        return True, None, "law_firm_label"
    if path.endswith("email") and looks_like_label_value(value):
        return True, None, "email_label"
    if "phone" in path and looks_like_label_value(value):
        return True, None, "phone_label"
    if path.endswith(("family_name", "given_name", "middle_name")) and looks_like_label_value(value):
        return True, None, "name_label"
    if path.endswith(("address.street", "address.unit", "address.city", "address.state", "address.zip", "address.country")):
        if looks_like_label_value(value):
            return True, None, "address_label"
    return False, None, "field_ok"


def _compute_check_digit(value: str) -> str:
    weights = [7, 3, 1]
    total = 0
    for i, char in enumerate(value):
        if char.isdigit():
            v = int(char)
        elif char == "<":
            v = 0
        else:
            v = ord(char) - 55
        total += v * weights[i % 3]
    return str(total % 10)


def _valid_check_digit(value: str, check_digit: str) -> bool:
    if not check_digit or check_digit == "<":
        return False
    return _compute_check_digit(value) == check_digit


def _normalize_mrz_line(raw: str) -> str:
    line = raw.strip().replace(" ", "").upper()
    return "".join(ch for ch in line if ch.isalnum() or ch == "<")


def _extract_mrz_lines(evidence: str) -> List[str]:
    if not evidence:
        return []
    lines = []
    for raw in evidence.splitlines():
        line = _normalize_mrz_line(raw)
        if MRZ_LINE_RE.match(line):
            lines.append(line)
    if len(lines) >= 2:
        return lines[-2:]
    return []


def _mrz_check_results(lines: List[str]) -> Optional[Dict[str, bool]]:
    if len(lines) < 2:
        return None
    line1, line2 = lines[0], lines[1]
    if len(line1) < 44 or len(line2) < 44:
        return None
    return {
        "passport_number": _valid_check_digit(line2[0:9], line2[9:10]),
        "date_of_birth": _valid_check_digit(line2[13:19], line2[19:20]),
        "date_of_expiration": _valid_check_digit(line2[21:27], line2[27:28]),
    }


def _rule_result(path: str, field_type: str, value: str, label_hints: List[str], payload: Dict) -> RuleResult:
    context = {}
    if field_type == "zip":
        country_path = path.replace("zip", "country")
        context["country"] = _get_value(payload, country_path) or ""
    return validate_field(path, field_type, value, label_hints, context=context)


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
    timeout = float(os.getenv("LLM_TIMEOUT", "20"))
    return endpoint, api_key, model, timeout


def _build_llm_prompt(payload: Dict, issues: List[ValidationIssue]) -> str:
    issues_payload = [
        {"field": issue.field, "severity": issue.severity, "message": issue.message}
        for issue in issues
    ]
    return build_llm_validate_prompt(payload, issues_payload)


def _call_llm(prompt: str) -> Tuple[List[ValidationIssue], Dict[str, str], Optional[str]]:
    if not _llm_enabled():
        return [], {}, "LLM disabled (ENABLE_LLM is not set)"
    endpoint, api_key, model, timeout = _resolve_llm_config()
    if not endpoint:
        return [], {}, "LLM endpoint not configured"
    if not api_key:
        return [], {}, "LLM API key not configured"

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Return JSON only. Do not wrap in markdown."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }

    try:
        resp = requests.post(endpoint, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        parsed = json.loads(content)
    except Exception as exc:  # noqa: BLE001
        return [], {}, f"LLM request failed: {exc}"

    issues: List[ValidationIssue] = []
    suggestions: Dict[str, str] = {}
    if isinstance(parsed, dict):
        for issue in parsed.get("issues", []) or []:
            if not isinstance(issue, dict):
                continue
            issues.append(
                ValidationIssue(
                    field=issue.get("field", ""),
                    severity=issue.get("severity", "warning"),
                    rule=issue.get("rule", "llm_validation"),
                    message=issue.get("message", "LLM validation issue."),
                    current_value=_get_value(payload, issue.get("field", "")),
                    suggestion=issue.get("suggestion"),
                    source="llm",
                )
            )
        for key, value in (parsed.get("suggestions") or {}).items():
            if isinstance(value, (str, int, float)):
                suggestions[key] = str(value)
    return issues, suggestions, None


def validate_and_annotate(result: ExtractionResult, use_llm: bool = False) -> ValidationReport:
    payload = result.model_dump()
    issues: List[ValidationIssue] = []
    conflicts = {w.field for w in result.meta.warnings if w.code == "conflict" and w.field}
    mrz_checks = None
    if result.meta.presence.get("passport.mrz") == "present":
        for key in [
            "passport.passport_number",
            "passport.date_of_birth",
            "passport.date_of_expiration",
        ]:
            evidence = result.meta.evidence.get(key, "")
            lines = _extract_mrz_lines(evidence)
            if lines:
                mrz_checks = _mrz_check_results(lines)
                break
    mrz_check_map = {
        "passport.passport_number": "passport_number",
        "passport.date_of_birth": "date_of_birth",
        "passport.date_of_expiration": "date_of_expiration",
    }

    validated_paths: set[str] = set()
    # Validate required + typed fields.
    for spec in iter_validation_fields():
        path = spec.key
        validated_paths.add(path)
        value = _get_value(payload, path)
        required = spec.required
        label = spec.label or path
        presence = result.meta.presence.get(path, "unknown")
        source = result.meta.sources.get(path, "")

        if not value:
            if required:
                result.meta.status[path] = "red"
                issues.append(
                    ValidationIssue(
                        field=path,
                        severity="error",
                        rule="required_missing",
                        message=(
                            f"{label} is missing."
                            if presence == "present"
                            else f"{label} is missing; presence {presence}."
                        ),
                        current_value=value,
                        source="heuristic",
                    )
                )
                add_suggestion(result, path, "", "Missing value; verify in document", "heuristic", 0.0)
            else:
                result.meta.status[path] = "yellow"
            result.meta.confidence[path] = min(result.meta.confidence.get(path, 0.0), 0.0)
            continue

        if is_placeholder_value(value):
            if required:
                result.meta.status[path] = "red"
                base_conf = base_confidence_for_source(source)
                result.meta.confidence[path] = min(base_conf, 0.3)
                issues.append(
                    ValidationIssue(
                        field=path,
                        severity="error",
                        rule="placeholder_value",
                        message=f"{label} is missing.",
                        current_value=value,
                        source="heuristic",
                    )
                )
            else:
                result.meta.status[path] = "yellow"
                base_conf = base_confidence_for_source(source)
                result.meta.confidence[path] = min(base_conf, 0.55)
                issues.append(
                    ValidationIssue(
                        field=path,
                        severity="warning",
                        rule="placeholder_value",
                        message=f"{label} is marked as not applicable.",
                        current_value=value,
                        source="heuristic",
                    )
                )
            continue

        rule_result = _rule_result(path, spec.field_type, value, spec.label_hints, payload)
        rule_name = rule_result.reasons[0] if rule_result.reasons else "invalid"
        if any(
            reason in {"label_noise", "email_label", "phone_label", "address_label"}
            for reason in rule_result.reasons
        ):
            rule_name = "label_noise"
        suggestion = rule_result.normalized
        if not rule_result.is_valid:
            result.meta.status[path] = "red"
            base_conf = base_confidence_for_source(source)
            result.meta.confidence[path] = min(base_conf, 0.3)
            issues.append(
                ValidationIssue(
                    field=path,
                    severity="error",
                    rule=rule_name,
                    message=f"{label} looks invalid.",
                    current_value=value,
                    source="heuristic",
                )
            )
            if suggestion:
                add_suggestion(result, path, suggestion, "Heuristic normalization", "heuristic", 0.6)
            continue

        field_invalid, field_suggestion, field_rule = _field_specific_invalid(path, value, payload)
        if field_invalid:
            result.meta.status[path] = "red"
            base_conf = base_confidence_for_source(source)
            result.meta.confidence[path] = min(base_conf, 0.3)
            issues.append(
                ValidationIssue(
                    field=path,
                    severity="error",
                    rule=field_rule,
                    message=f"{label} looks invalid.",
                    current_value=value,
                    source="heuristic",
                )
            )
            if field_suggestion:
                add_suggestion(result, path, field_suggestion, "Heuristic normalization", "heuristic", 0.6)
            continue

        if (
            mrz_checks
            and path in mrz_check_map
            and source == "MRZ"
            and mrz_checks.get(mrz_check_map[path]) is False
        ):
            result.meta.status[path] = "red"
            result.meta.confidence[path] = min(base_confidence_for_source(source), 0.2)
            issues.append(
                ValidationIssue(
                    field=path,
                    severity="error",
                    rule="mrz_check_digit",
                    message=f"{label} fails MRZ check digit validation.",
                    current_value=value,
                    source="heuristic",
                )
            )
            continue

        # Valid value.
        base_conf = base_confidence_for_source(source)
        if source == "USER":
            bumped = 1.0
        else:
            bumped = min(base_conf + 0.1 + rule_result.confidence_delta, 0.95)
        result.meta.confidence[path] = bumped
        result.meta.status[path] = "green" if bumped >= 0.85 else "yellow"
        if path in conflicts and source != "MRZ":
            result.meta.status[path] = "yellow"
            result.meta.confidence[path] = min(result.meta.confidence.get(path, bumped), 0.7)
        if suggestion:
            add_suggestion(result, path, suggestion, "Heuristic normalization", "heuristic", 0.7)
            issues.append(
                ValidationIssue(
                    field=path,
                    severity="info",
                    rule=rule_name,
                    message=f"{label} can be normalized.",
                    current_value=value,
                    suggestion=suggestion,
                    source="heuristic",
                )
            )

    # Ensure statuses for any other extracted fields not covered above.
    for path, source in result.meta.sources.items():
        if path not in validated_paths:
            result.meta.confidence[path] = base_confidence_for_source(source)
        if path in result.meta.status:
            continue
        conf = result.meta.confidence.get(path, 0.0)
        result.meta.status[path] = "green" if conf >= 0.85 else "yellow" if conf >= 0.55 else "red"

    # Cross-field sanity checks.
    attorney_addr = result.g28.attorney.address
    if attorney_addr.zip and attorney_addr.state and attorney_addr.country:
        zip_ok = RE_ZIP_US.match(attorney_addr.zip.strip()) is not None
        state_ok = len(attorney_addr.state.strip()) == 2
        if zip_ok and state_ok and attorney_addr.country.strip().lower() not in {"united states", "usa", "us"}:
            path = "g28.attorney.address.country"
            issues.append(
                ValidationIssue(
                    field=path,
                    severity="warning",
                    rule="country_conflict",
                    message="Country conflicts with US state/ZIP.",
                    current_value=attorney_addr.country,
                    source="heuristic",
                )
            )
            result.meta.status[path] = "yellow"
            add_suggestion(result, path, "United States", "US state/ZIP detected", "heuristic", 0.6)

    llm_used = False
    llm_error = None
    if use_llm:
        llm_prompt = _build_llm_prompt(payload, issues)
        llm_issues, llm_suggestions, llm_error = _call_llm(llm_prompt)
        if llm_issues or llm_suggestions:
            llm_used = True
            issues.extend(llm_issues)
            for path, value in llm_suggestions.items():
                evidence = result.meta.evidence.get(path)
                if not evidence:
                    continue
                requires_confirmation = path in conflicts
                add_suggestion(
                    result,
                    path,
                    value,
                    "LLM suggestion",
                    "LLM",
                    0.7,
                    evidence,
                    requires_confirmation,
                )

    # Compute a simple score.
    score = 1.0
    for issue in issues:
        if issue.severity == "error":
            score -= 0.15
        elif issue.severity == "warning":
            score -= 0.05
        else:
            score -= 0.02
    score = max(0.0, min(1.0, score))

    ok = not any(issue.severity == "error" for issue in issues)
    report = ValidationReport(
        ok=ok,
        issues=issues,
        score=score,
        llm_used=llm_used,
        llm_error=llm_error,
    )
    if llm_error:
        LOGGER.warning("LLM validation skipped: %s", llm_error)
    return report


def validate_payload(payload: Dict, use_llm: bool = False) -> ValidationReport:
    result = ExtractionResult.model_validate(payload)
    return validate_and_annotate(result, use_llm=use_llm)
