from __future__ import annotations

import logging
import re
import time
from collections import Counter
from datetime import datetime
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from playwright.sync_api import sync_playwright

from ..field_registry import iter_autofill_fields
from ..config import CONFIG, resolve_form_url
from ..pipeline.normalize import normalize_date

LOGGER = logging.getLogger(__name__)

OPEN_BROWSER_SESSIONS: List[Dict[str, object]] = []


@dataclass
class FieldCandidate:
    label: str
    locator_query: str


TARGET_FIELDS = [
    {
        "path": field.key,
        "labels": field.autofill.labels,
        "required": field.required,
        "field_type": field.field_type,
    }
    for field in sorted(
        iter_autofill_fields(),
        key=lambda spec: spec.autofill.order if spec.autofill else 0,
    )
]


def _normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def _append_run_log(run_dir: Path, message: str) -> None:
    timestamp = datetime.utcnow().isoformat()
    with (run_dir / "run.log").open("a") as f:
        f.write(f"[{timestamp}] {message}\n")


def _value_empty(value: Optional[str]) -> bool:
    return value is None or str(value).strip() == ""


def _truncate(value: Optional[str], limit: int = 120) -> str:
    if value is None:
        return ""
    text = str(value)
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _is_submit_like(text: str) -> bool:
    return bool(re.search(r"(submit|sign|confirm)", text, re.IGNORECASE))


def _normalize_compare(value: Optional[str]) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    return re.sub(r"\s+", "", text)


def _normalize_for_input_type(value: Optional[str], input_type: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if input_type == "date":
        normalized = normalize_date(raw)
        return normalized or raw
    return raw


def _should_check_checkbox(value: Optional[str]) -> bool:
    if value is None:
        return False
    text = str(value).strip().lower()
    if not text:
        return False
    return text not in {"false", "no", "0", "off", "n"}


def _parse_unit_value(value: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if value is None:
        return None, None
    raw = str(value).strip()
    if not raw:
        return None, None
    text = raw.lower()
    unit_type = None
    if re.search(r"\bapt\b|\bapartment\b", text):
        unit_type = "apt"
    elif re.search(r"\bste\b|\bsuite\b", text):
        unit_type = "ste"
    elif re.search(r"\bflr\b|\bfloor\b", text):
        unit_type = "flr"
    unit_number = re.sub(r"(?i)\\b(apt|apartment|ste|suite|flr|floor|unit)\\b", "", raw)
    unit_number = re.sub(r"[#]", " ", unit_number)
    unit_number = re.sub(r"\\s+", " ", unit_number).strip()
    if not unit_number:
        unit_number = None
    return unit_type, unit_number


def _fill_unit_fields(page, run_dir: Path, value: Optional[str]) -> Dict[str, object]:
    unit_type, unit_number = _parse_unit_value(value)
    fallback_type = unit_type or "apt"
    number_value = unit_number or (str(value).strip() if value is not None else "")
    attempted = False
    filled = False
    selector_used: List[str] = []
    failure_reason = None
    readback_value: Optional[str] = None
    input_type = None

    # Prefer checkbox selection when available (matches the hosted GitHub form).
    checkbox_locator = page.locator(
        f"input[type='checkbox']#{fallback_type}, input[type='checkbox'][value='{fallback_type}']"
    )
    if checkbox_locator.count() > 0:
        attempted = True
        input_type = "checkbox"
        try:
            checkbox_locator.first.check()
            filled = True
            selector_used.append(f"#{fallback_type}")
            readback_value = fallback_type
        except Exception as exc:  # noqa: BLE001
            failure_reason = f"checkbox_error:{exc}"
    else:
        # Some fixtures model unit selection as text inputs (apt/ste/flr).
        unit_input_locator = page.locator(
            f"input[type='text']#{fallback_type}, input[type='text'][name='{fallback_type}']"
        )
        if unit_input_locator.count() > 0 and number_value:
            attempted = True
            input_type = "text"
            try:
                unit_input_locator.first.fill(number_value)
                filled = True
                selector_used.append(f"#{fallback_type}")
                try:
                    readback_value = unit_input_locator.first.input_value(timeout=2000)
                except Exception:  # noqa: BLE001
                    readback_value = number_value
            except Exception as exc:  # noqa: BLE001
                failure_reason = f"unit_fill_error:{exc}"

    # Fill unit number field when present (GitHub form uses apt-number).
    if number_value:
        apt_number_locator = page.locator(
            "input[type='text']#apt-number, input[type='text'][name='apt-number']"
        )
        if apt_number_locator.count() > 0:
            attempted = True
            input_type = "text"
            try:
                apt_number_locator.first.fill(number_value)
                filled = True
                selector_used.append("#apt-number")
                try:
                    readback_value = apt_number_locator.first.input_value(timeout=2000)
                except Exception:  # noqa: BLE001
                    readback_value = number_value
            except Exception as exc:  # noqa: BLE001
                failure_reason = f"unit_number_error:{exc}"

    if not filled and not failure_reason:
        failure_reason = "selector_not_found"

    return {
        "attempted": attempted,
        "filled": filled,
        "selector_used": ", ".join(selector_used) if selector_used else None,
        "dom_readback_value": readback_value,
        "input_type": input_type,
        "failure_reason": failure_reason,
    }


def _get_radio_group(locator):
    return locator.evaluate(
        """(el) => {
            const all = Array.from(document.querySelectorAll('input[type="radio"]'));
            const name = el.getAttribute('name');
            const group = name ? all.filter((r) => r.getAttribute('name') === name) : [el];
            const options = group.map((radio) => {
              const id = radio.id || '';
              let label = '';
              if (id) {
                const labelEl = document.querySelector(`label[for="${id}"]`);
                if (labelEl && labelEl.innerText) label = labelEl.innerText.trim();
              }
              if (!label) {
                const parentLabel = radio.closest('label');
                if (parentLabel && parentLabel.innerText) label = parentLabel.innerText.trim();
              }
              return { value: radio.value || '', label };
            });
            const selected = group.find((radio) => radio.checked);
            let selectedLabel = '';
            if (selected) {
              const id = selected.id || '';
              if (id) {
                const labelEl = document.querySelector(`label[for="${id}"]`);
                if (labelEl && labelEl.innerText) selectedLabel = labelEl.innerText.trim();
              }
              if (!selectedLabel) {
                const parentLabel = selected.closest('label');
                if (parentLabel && parentLabel.innerText) selectedLabel = parentLabel.innerText.trim();
              }
            }
            return {
              options,
              selected: selected ? { value: selected.value || '', label: selectedLabel } : null,
            };
        }"""
    )


def _select_radio(locator, value: str) -> Tuple[bool, str, List[Dict[str, str]], Optional[Dict[str, str]]]:
    try:
        data = locator.evaluate(
            """(el, raw) => {
                const normalize = (s) => (s || '').toLowerCase().replace(/[^a-z0-9]+/g, '').trim();
                const target = normalize(raw);
                const all = Array.from(document.querySelectorAll('input[type="radio"]'));
                const name = el.getAttribute('name');
                const group = name ? all.filter((r) => r.getAttribute('name') === name) : [el];
                const options = group.map((radio) => {
                  const id = radio.id || '';
                  let label = '';
                  if (id) {
                    const labelEl = document.querySelector(`label[for="${id}"]`);
                    if (labelEl && labelEl.innerText) label = labelEl.innerText.trim();
                  }
                  if (!label) {
                    const parentLabel = radio.closest('label');
                    if (parentLabel && parentLabel.innerText) label = parentLabel.innerText.trim();
                  }
                  return { value: radio.value || '', label };
                });
                let match = null;
                for (const radio of group) {
                  const option = options.find((opt) => opt.value === (radio.value || '')) || { value: radio.value || '', label: '' };
                  const valueKey = normalize(option.value);
                  const labelKey = normalize(option.label);
                  if (target && (valueKey === target || labelKey === target)) {
                    match = { radio, option };
                    break;
                  }
                  if (target && target.length <= 2 && labelKey.startsWith(target)) {
                    match = { radio, option };
                    break;
                  }
                }
                if (!match) {
                  return { ok: false, reason: 'no_radio_match', options };
                }
                match.radio.click();
                return { ok: true, reason: 'matched_radio', options, selected: match.option };
            }""",
            value,
        )
        if not isinstance(data, dict):
            return False, "no_radio_match", [], None
        return (
            bool(data.get("ok")),
            str(data.get("reason") or ""),
            data.get("options") or [],
            data.get("selected"),
        )
    except Exception:  # noqa: BLE001
        return False, "radio_select_error", [], None


def _readback_value(locator) -> Tuple[Optional[str], Dict[str, object]]:
    details: Dict[str, object] = {}
    try:
        tag = locator.evaluate("el => el.tagName.toLowerCase()")
    except Exception:  # noqa: BLE001
        return None, details
    if tag == "select":
        try:
            selected = locator.evaluate(
                """el => {
                    const opt = el.selectedOptions && el.selectedOptions.length ? el.selectedOptions[0] : null;
                    if (!opt) return null;
                    return { value: opt.value || '', label: opt.label || '' };
                }"""
            )
        except Exception:  # noqa: BLE001
            selected = None
        details["input_type"] = "select"
        details["selected_option"] = selected
        if isinstance(selected, dict):
            return selected.get("value") or selected.get("label") or None, details
        return None, details
    if tag == "textarea":
        details["input_type"] = "textarea"
        try:
            return locator.input_value(timeout=2000), details
        except Exception:  # noqa: BLE001
            return None, details
    if tag == "input":
        input_type = (locator.get_attribute("type") or "").lower()
        details["input_type"] = input_type or "text"
        if input_type == "radio":
            try:
                data = _get_radio_group(locator)
            except Exception:  # noqa: BLE001
                data = {}
            selected = data.get("selected") if isinstance(data, dict) else None
            details["selected_option"] = selected
            if isinstance(selected, dict):
                return selected.get("value") or selected.get("label") or None, details
            return None, details
        if input_type == "checkbox":
            try:
                checked = locator.is_checked()
            except Exception:  # noqa: BLE001
                checked = False
            details["checked"] = checked
            return "checked" if checked else None, details
        try:
            raw = locator.input_value(timeout=2000)
        except Exception:  # noqa: BLE001
            raw = None
        normalized = _normalize_for_input_type(raw, input_type)
        details["normalized"] = normalized
        return normalized if normalized is not None else raw, details
    return None, details


def _matches_expected(expected: Optional[str], readback_value: Optional[str], details: Dict[str, object]) -> bool:
    input_type = details.get("input_type")
    if input_type == "checkbox":
        return _should_check_checkbox(expected) == bool(details.get("checked"))
    if _value_empty(expected) or _value_empty(readback_value):
        return False
    expected_norm = _normalize_compare(_normalize_for_input_type(expected, input_type))
    if input_type in {"select", "radio"}:
        selected = details.get("selected_option") if isinstance(details.get("selected_option"), dict) else {}
        candidates = [readback_value, selected.get("value"), selected.get("label")]
        for candidate in candidates:
            if _normalize_compare(candidate) == expected_norm:
                return True
        return False
    actual_norm = _normalize_compare(_normalize_for_input_type(readback_value, input_type))
    return expected_norm == actual_norm


def _failure_result(required: bool, reason: str) -> str:
    optional_skip_reasons = {
        "selector_not_found",
        "no_match",
        "no_select_match",
        "no_radio_match",
        "duplicate_target",
        "checkbox_value_false",
    }
    if not required and reason in optional_skip_reasons:
        return "SKIP"
    return "FAIL"
def _is_fillable(locator) -> Tuple[bool, str]:
    tag = locator.evaluate("el => el.tagName.toLowerCase()")
    if tag == "button":
        return False, "submit_guard"
    if tag == "select":
        return True, ""
    if tag == "textarea":
        return True, ""
    if tag == "input":
        input_type = (locator.get_attribute("type") or "").lower()
        if input_type in {"submit", "button", "image"}:
            return False, "submit_guard"
        return True, ""
    return False, "unsupported_input"


def _rank_candidates(candidates: List[FieldCandidate], labels: List[str]) -> List[Tuple[float, FieldCandidate]]:
    scored: List[Tuple[float, FieldCandidate]] = []
    for candidate in candidates:
        best = 0.0
        for label in labels:
            score = _similarity(label, candidate.label)
            if score > best:
                best = score
        scored.append((best, candidate))
    scored.sort(key=lambda item: (-item[0], item[1].label.lower(), item[1].locator_query))
    return scored

def _collect_candidates(page) -> List[FieldCandidate]:
    candidates: List[FieldCandidate] = []

    labels = page.locator("label")
    for i in range(labels.count()):
        label = labels.nth(i)
        text = label.text_content() or ""
        text = text.strip()
        if not text:
            continue
        for_attr = label.get_attribute("for")
        if for_attr:
            candidates.append(FieldCandidate(label=text, locator_query=f"#{for_attr}"))
            continue
        # Try input/select inside label.
        input_locator = label.locator("input, select, textarea")
        if input_locator.count() > 0:
            candidates.append(FieldCandidate(label=text, locator_query=f"label:has-text('{text}') >> input, label:has-text('{text}') >> select, label:has-text('{text}') >> textarea"))

    # Fallback to placeholder/name.
    inputs = page.locator("input, select, textarea")
    for i in range(inputs.count()):
        input_el = inputs.nth(i)
        placeholder = input_el.get_attribute("placeholder") or ""
        name = input_el.get_attribute("name") or ""
        label = placeholder or name
        if label:
            candidates.append(FieldCandidate(label=label, locator_query=f"xpath=(//input|//select|//textarea)[{i+1}]"))

    return candidates


def _scan_form_fields(page) -> List[Dict[str, object]]:
    try:
        fields = page.evaluate(
            """() => {
            const nodes = Array.from(document.querySelectorAll('input, select, textarea'));
            const results = [];
            const radioGroups = new Map();

            const getLabel = (el) => {
              const id = el.getAttribute('id');
              if (id) {
                const label = document.querySelector(`label[for="${id}"]`);
                if (label && label.innerText) return label.innerText.trim();
              }
              const parentLabel = el.closest('label');
              if (parentLabel && parentLabel.innerText) return parentLabel.innerText.trim();
              const fieldset = el.closest('fieldset');
              if (fieldset) {
                const legend = fieldset.querySelector('legend');
                if (legend && legend.innerText) return legend.innerText.trim();
              }
              return '';
            };

            const isRequired = (el) => {
              if (el.required) return true;
              const ariaRequired = el.getAttribute('aria-required');
              if (ariaRequired && ariaRequired.toLowerCase() === 'true') return true;
              return false;
            };

            nodes.forEach((el, index) => {
              const tag = el.tagName.toLowerCase();
              const type = tag === 'input' ? (el.getAttribute('type') || 'text').toLowerCase() : tag;
              if (['submit', 'button', 'image', 'hidden', 'reset'].includes(type)) return;
              const name = el.getAttribute('name') || '';
              const id = el.getAttribute('id') || '';
              const required = isRequired(el);
              if (tag === 'input' && type === 'radio') {
                const key = name || id || `radio_${index}`;
                const entry = radioGroups.get(key) || {
                  tag,
                  type,
                  name,
                  id,
                  label: getLabel(el),
                  required: false,
                  selected_value: '',
                  selected_label: '',
                };
                entry.required = entry.required || required;
                if (el.checked) {
                  entry.selected_value = el.value || '';
                  entry.selected_label = getLabel(el) || entry.selected_label;
                }
                radioGroups.set(key, entry);
                return;
              }
              if (tag === 'input' && type === 'checkbox') {
                results.push({
                  tag,
                  type,
                  name,
                  id,
                  label: getLabel(el),
                  required,
                  value: el.checked ? 'checked' : '',
                  checked: Boolean(el.checked),
                });
                return;
              }
              let value = '';
              if (tag === 'select') {
                value = el.value || '';
              } else if (tag === 'textarea') {
                value = el.value || '';
              } else if (tag === 'input') {
                value = el.value || '';
              }
              results.push({
                tag,
                type,
                name,
                id,
                label: getLabel(el),
                required,
                value,
              });
            });

            for (const entry of radioGroups.values()) {
              results.push({
                tag: entry.tag,
                type: entry.type,
                name: entry.name,
                id: entry.id,
                label: entry.label || entry.selected_label || '',
                required: entry.required,
                value: entry.selected_value || '',
              });
            }

            return results;
          }"""
        )
    except Exception:  # noqa: BLE001
        return []
    return fields if isinstance(fields, list) else []


def _field_label_candidates(field: Dict[str, object]) -> List[str]:
    candidates = []
    for key in ("label", "name", "id"):
        value = field.get(key)
        if isinstance(value, str) and value.strip():
            candidates.append(value.strip())
    return candidates


def _match_target_path(field: Dict[str, object]) -> Tuple[Optional[str], float]:
    best_score = 0.0
    best_path: Optional[str] = None
    candidates = _field_label_candidates(field)
    if not candidates:
        return None, 0.0
    for target in TARGET_FIELDS:
        for candidate in candidates:
            for label in target.get("labels") or []:
                score = _similarity(label, candidate)
                if score > best_score:
                    best_score = score
                    best_path = target.get("path")
    return best_path, best_score


def _field_filled(field: Dict[str, object]) -> bool:
    field_type = str(field.get("type") or "").lower()
    if field_type == "checkbox":
        return bool(field.get("checked")) or str(field.get("value") or "") == "checked"
    value = field.get("value")
    return not _value_empty(value)


def _build_form_completeness(
    form_fields: List[Dict[str, object]],
    payload: Dict,
    field_results: Optional[Dict[str, Dict[str, object]]] = None,
) -> Dict[str, object]:
    required_not_filled: List[Dict[str, object]] = []
    optional_not_filled: List[Dict[str, object]] = []
    unmapped_required: List[Dict[str, object]] = []
    unmapped_optional: List[Dict[str, object]] = []
    mapped: Dict[str, Dict[str, object]] = {}

    field_results = field_results or {}
    non_applicable_reasons = {
        "selector_not_found",
        "no_match",
    }
    unmapped_failure_reasons = {
        "unsupported_input",
        "checkbox_input",
        "submit_guard",
    }

    for target in TARGET_FIELDS:
        path = target.get("path")
        if not path:
            continue
        required = bool(target.get("required"))
        fill_entry = field_results.get(path) if isinstance(field_results, dict) else None
        result = (fill_entry or {}).get("result")
        failure_reason = (fill_entry or {}).get("failure_reason") or ""
        filled = result == "PASS"
        canonical_value = _get_payload_value(payload, path)
        canonical_missing = _value_empty(canonical_value)
        issue = None

        is_unmapped = failure_reason in (non_applicable_reasons | unmapped_failure_reasons)
        if not filled:
            if failure_reason in unmapped_failure_reasons:
                entry = {
                    "label": path,
                    "type": (fill_entry or {}).get("input_type"),
                    "required": required,
                    "mapped_path": None,
                    "issue": "UNMAPPED_REQUIRED" if required else "UNMAPPED_OPTIONAL",
                }
                if required:
                    unmapped_required.append(entry)
                else:
                    unmapped_optional.append(entry)
            elif canonical_missing:
                if required:
                    issue = "CANONICAL_MISSING"
                    required_not_filled.append(
                        {
                            "label": path,
                            "type": (fill_entry or {}).get("input_type"),
                            "required": required,
                            "mapped_path": path,
                            "issue": issue,
                        }
                    )
            else:
                issue = "AUTOFILL_MISSED"
                entry = {
                    "label": path,
                    "type": (fill_entry or {}).get("input_type"),
                    "required": required,
                    "mapped_path": path,
                    "issue": issue,
                }
                if required:
                    required_not_filled.append(entry)
                else:
                    optional_not_filled.append(entry)

        mapped[path] = {
            "required": None if is_unmapped else required,
            "filled": None if is_unmapped else filled,
            "issue": None if is_unmapped else issue,
            "canonical_missing": canonical_missing,
            "unmapped": is_unmapped,
        }

    for field in form_fields:
        required = bool(field.get("required"))
        filled = _field_filled(field)
        mapped_path, score = _match_target_path(field)
        if mapped_path and score >= 0.9:
            continue
        if not filled:
            entry = {
                "label": field.get("label") or field.get("name") or field.get("id") or "Unmapped field",
                "type": field.get("type"),
                "required": required,
                "mapped_path": None,
                "issue": "UNMAPPED_REQUIRED" if required else "UNMAPPED_OPTIONAL",
            }
            if required:
                unmapped_required.append(entry)
            else:
                unmapped_optional.append(entry)

    counts = {
        "required_not_filled": len(required_not_filled),
        "optional_not_filled": len(optional_not_filled),
        "unmapped_required": len(unmapped_required),
        "unmapped_optional": len(unmapped_optional),
    }
    return {
        "required_not_filled": required_not_filled,
        "optional_not_filled": optional_not_filled,
        "unmapped_required": unmapped_required,
        "unmapped_optional": unmapped_optional,
        "mapped": mapped,
        "counts": counts,
    }


def _resolved_override(payload: Dict, path: str) -> Optional[str]:
    meta = payload.get("meta") if isinstance(payload, dict) else None
    if not isinstance(meta, dict):
        return None
    resolved = meta.get("resolved_fields", {})
    if not isinstance(resolved, dict):
        return None
    entry = resolved.get(path)
    if not isinstance(entry, dict):
        return None
    source = str(entry.get("source") or "").upper()
    value = entry.get("value")
    if value is None or str(value).strip() == "":
        return None
    if source in {"USER", "AI"}:
        return value
    return None


def _get_payload_value(payload: Dict, path: str) -> Optional[str]:
    override = _resolved_override(payload, path)
    if override is not None:
        return override
    parts = path.split(".")
    value = payload
    for part in parts:
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _get_select_options(locator) -> List[Dict[str, str]]:
    try:
        return locator.evaluate(
            """el => Array.from(el.options).map(o => ({value: o.value, label: o.label}))"""
        )
    except Exception:  # noqa: BLE001
        return []


def _abbrev(label: str) -> str:
    parts = re.split(r"[^A-Za-z]+", label.strip())
    return "".join([p[0] for p in parts if p]).upper()


def _select_option(locator, value: str, options: Optional[List[Dict[str, str]]] = None) -> Tuple[bool, str]:
    options = options or _get_select_options(locator)
    if not options:
        return False, "no_select_options"
    raw = value.strip()
    if not raw:
        return False, "empty_value"

    def match_key(field: str) -> Optional[str]:
        for opt in options:
            if opt.get(field, "").strip().lower() == raw.lower():
                return opt.get(field, "")
        return None

    matched_value = match_key("value")
    if matched_value is not None:
        locator.select_option(value=matched_value, timeout=2000)
        return True, "matched_value"

    matched_label = match_key("label")
    if matched_label is not None:
        locator.select_option(label=matched_label, timeout=2000)
        return True, "matched_label"

    if len(raw) <= 3:
        for opt in options:
            if _abbrev(opt.get("label", "")) == raw.upper():
                locator.select_option(label=opt.get("label", ""), timeout=2000)
                return True, "matched_abbrev"

    # Fuzzy match on labels if input is longer.
    best_label = ""
    best_score = 0.0
    for opt in options:
        label = opt.get("label", "")
        score = _similarity(raw, label)
        if score > best_score:
            best_score = score
            best_label = label
    if best_score >= 0.82 and best_label:
        locator.select_option(label=best_label, timeout=2000)
        return True, f"matched_fuzzy:{best_score:.2f}"

    return False, "no_select_match"


def _fill_locator(locator, value: str) -> None:
    tag = locator.evaluate("el => el.tagName.toLowerCase()")
    if tag == "button":
        raise ValueError("submit_guard")
    if tag == "select":
        ok, reason = _select_option(locator, value)
        if not ok:
            raise ValueError(reason)
        return
    if tag == "input":
        input_type = (locator.get_attribute("type") or "").lower()
        if input_type in {"submit", "button", "image"}:
            raise ValueError("submit_guard")
        if input_type in {"checkbox"}:
            raise ValueError("checkbox_input")
        if input_type == "radio":
            ok, reason, _, _ = _select_radio(locator, value)
            if not ok:
                raise ValueError(reason)
            return
    locator.fill(value)


def fill_form(
    payload: Dict,
    run_dir: Path,
    form_url: Optional[str] = None,
    headless: Optional[bool] = None,
    slow_mo_ms: Optional[int] = None,
    keep_open_ms: Optional[int] = None,
) -> Dict:
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_path = run_dir / "trace.zip"
    start_time = time.perf_counter()

    autofill_cfg = CONFIG.autofill
    headless = autofill_cfg.headless if headless is None else headless
    slow_mo_ms = autofill_cfg.slow_mo_ms if slow_mo_ms is None else slow_mo_ms
    keep_open_ms = autofill_cfg.keep_open_ms if keep_open_ms is None else keep_open_ms
    keep_open = keep_open_ms < 0 and not headless

    filled_fields: List[str] = []
    attempted_fields: List[str] = []
    fill_failures: Dict[str, str] = {}
    dom_readback: Dict[str, Optional[str]] = {}
    field_results: Dict[str, Dict[str, object]] = {}
    used_queries = set()
    final_url = ""
    form_fields: List[Dict[str, object]] = []
    target_url = resolve_form_url(form_url)
    _append_run_log(
        run_dir,
        "Autofill start. "
        f"Form URL: {target_url} | headless={headless} | slow_mo_ms={slow_mo_ms} | keep_open_ms={keep_open_ms}",
    )

    def _run(playwright):
        nonlocal final_url
        browser = playwright.chromium.launch(headless=headless, slow_mo=slow_mo_ms)
        context = browser.new_context()
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = context.new_page()
        try:
            page.set_default_timeout(15000)
            page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:  # noqa: BLE001
                pass

            candidates = _collect_candidates(page)
            _append_run_log(run_dir, f"Candidate fields discovered: {len(candidates)}")
            # Stable order for deterministic matching.
            candidates = sorted(candidates, key=lambda c: (c.label.lower(), c.locator_query))
            form_fields.extend(_scan_form_fields(page))
            _append_run_log(run_dir, f"Form fields scanned: {len(form_fields)}")

            for target in TARGET_FIELDS:
                path = target["path"]
                required = bool(target.get("required"))
                value = _get_payload_value(payload, path)
                _append_run_log(
                    run_dir,
                    f"Target {path} value='{_truncate(value)}'",
                )
                if _value_empty(value):
                    field_results[path] = {
                        "attempted": False,
                        "selector_used": None,
                        "dom_readback_value": None,
                        "result": "SKIP",
                        "failure_reason": "no_value",
                    }
                    _append_run_log(run_dir, f"Skip {path}: no_value")
                    continue

                if path.endswith("address.unit"):
                    unit_result = _fill_unit_fields(page, run_dir, value)
                    attempted = bool(unit_result.get("attempted"))
                    filled = bool(unit_result.get("filled"))
                    failure_reason = unit_result.get("failure_reason") or "fill_error"
                    result = "PASS" if filled else _failure_result(required, str(failure_reason))
                    field_results[path] = {
                        "attempted": attempted,
                        "selector_used": unit_result.get("selector_used"),
                        "dom_readback_value": unit_result.get("dom_readback_value"),
                        "input_type": unit_result.get("input_type"),
                        "result": result,
                        "failure_reason": None if filled else failure_reason,
                    }
                    if attempted:
                        attempted_fields.append(path)
                    if filled:
                        filled_fields.append(path)
                    if unit_result.get("dom_readback_value") is not None:
                        dom_readback[path] = unit_result.get("dom_readback_value")
                    if result == "FAIL":
                        fill_failures[path] = str(failure_reason)
                    continue
                ranked = _rank_candidates(candidates, target["labels"])
                if not ranked or ranked[0][0] < 0.6:
                    reason = "selector_not_found"
                    result = _failure_result(required, reason)
                    field_results[path] = {
                        "attempted": False,
                        "selector_used": None,
                        "dom_readback_value": None,
                        "result": result,
                        "failure_reason": reason,
                    }
                    if result == "FAIL":
                        fill_failures[path] = reason
                    _append_run_log(run_dir, f"Skip {path}: {reason}")
                    continue
                top_candidates = ranked[:5]
                for idx, (score, candidate) in enumerate(top_candidates, start=1):
                    _append_run_log(
                        run_dir,
                        f"Candidate {idx} score={score:.2f} label='{_truncate(candidate.label)}' "
                        f"locator='{candidate.locator_query}'",
                    )
                filled = False
                attempted = False
                last_reason = "no_match"
                readback_value: Optional[str] = None
                readback_details: Dict[str, object] = {}
                selector_used: Optional[str] = None
                available_options: Optional[List[Dict[str, str]]] = None
                input_type: Optional[str] = None
                for score, candidate in ranked:
                    if score < 0.6:
                        break
                    if _is_submit_like(candidate.label):
                        last_reason = "submit_guard"
                        continue
                    if candidate.locator_query in used_queries:
                        last_reason = "duplicate_target"
                        continue
                    locator = page.locator(candidate.locator_query).first
                    tag = locator.evaluate("el => el.tagName.toLowerCase()")
                    if tag == "input":
                        input_type = (locator.get_attribute("type") or "").lower()
                        _append_run_log(
                            run_dir,
                            f"Candidate tag=input type={input_type} locator={candidate.locator_query}",
                        )
                    else:
                        input_type = tag
                        _append_run_log(
                            run_dir,
                            f"Candidate tag={tag} locator={candidate.locator_query}",
                        )
                    normalized_value = _normalize_for_input_type(value, input_type)
                    value_for_fill = normalized_value if normalized_value is not None else str(value)
                    is_fillable, reason = _is_fillable(locator)
                    if not is_fillable:
                        last_reason = reason or "unsupported_input"
                        _append_run_log(
                            run_dir,
                            f"Skip candidate for {path}: {last_reason} ({candidate.locator_query})",
                        )
                        continue
                    if tag == "select":
                        options = _get_select_options(locator)
                        available_options = options
                        if options:
                            preview = ", ".join(
                                [f"{opt.get('label','')}[{opt.get('value','')}]" for opt in options[:8]]
                            )
                            _append_run_log(
                                run_dir,
                                f"Select options ({len(options)}): {preview}",
                            )
                    try:
                        if tag == "select":
                            attempted = True
                            ok, reason = _select_option(locator, value_for_fill, options)
                            if not ok:
                                last_reason = reason
                                _append_run_log(
                                    run_dir,
                                    f"Select mismatch for {path} on {candidate.locator_query}: {reason}",
                                )
                                continue
                        elif tag == "input" and input_type == "radio":
                            attempted = True
                            ok, reason, radio_options, _ = _select_radio(locator, value_for_fill)
                            available_options = radio_options or available_options
                            if not ok:
                                last_reason = reason or "no_radio_match"
                                _append_run_log(
                                    run_dir,
                                    f"Radio mismatch for {path} on {candidate.locator_query}: {last_reason}",
                                )
                                continue
                        elif tag == "input" and input_type == "checkbox":
                            if not _should_check_checkbox(value_for_fill):
                                last_reason = "checkbox_value_false"
                                _append_run_log(
                                    run_dir,
                                    f"Skip checkbox for {path}: {last_reason}",
                                )
                                continue
                            attempted = True
                            locator.check()
                        else:
                            locator.fill(value_for_fill)
                            attempted = True
                        selector_used = candidate.locator_query
                        _append_run_log(
                            run_dir,
                            f"Filled {path} via {candidate.locator_query}",
                        )
                        readback_value, readback_details = _readback_value(locator)
                        if readback_value is None or _value_empty(readback_value):
                            last_reason = "post_fill_empty"
                            _append_run_log(
                                run_dir,
                                f"Post-fill check failed for {path} (empty)",
                            )
                            continue
                        if not _matches_expected(value_for_fill, readback_value, readback_details):
                            last_reason = "readback_mismatch"
                            _append_run_log(
                                run_dir,
                                f"Post-fill check failed for {path} (mismatch)",
                            )
                            continue
                        used_queries.add(candidate.locator_query)
                        filled = True
                        break
                    except ValueError as exc:
                        if str(exc) == "submit_guard":
                            last_reason = "submit_guard"
                        elif str(exc) == "checkbox_input":
                            last_reason = "checkbox_input"
                        elif str(exc).startswith("no_select"):
                            last_reason = str(exc)
                        elif str(exc).startswith("matched_") is False and str(exc) in {
                            "empty_value",
                            "no_select_match",
                        }:
                            last_reason = str(exc)
                        else:
                            last_reason = "fill_error"
                        _append_run_log(
                            run_dir,
                            f"Fill error for {path} on {candidate.locator_query}: {last_reason}",
                        )
                    except Exception as exc:  # noqa: BLE001
                        LOGGER.warning("Failed to fill %s: %s", path, exc)
                        last_reason = "fill_error"
                        _append_run_log(
                            run_dir,
                            f"Fill exception for {path} on {candidate.locator_query}: {exc}",
                        )

                if attempted:
                    attempted_fields.append(path)
                dom_readback[path] = readback_value
                if filled:
                    filled_fields.append(path)
                    field_results[path] = {
                        "attempted": True,
                        "selector_used": selector_used,
                        "dom_readback_value": readback_value,
                        "input_type": readback_details.get("input_type") or input_type,
                        "result": "PASS",
                        "failure_reason": None,
                        "selected_option": readback_details.get("selected_option"),
                        "available_options": available_options,
                    }
                    continue
                if last_reason == "no_match":
                    last_reason = "selector_not_found"
                result = _failure_result(required, last_reason)
                field_results[path] = {
                    "attempted": attempted,
                    "selector_used": selector_used,
                    "dom_readback_value": readback_value,
                    "input_type": readback_details.get("input_type") or input_type,
                    "result": result,
                    "failure_reason": last_reason,
                    "selected_option": readback_details.get("selected_option"),
                    "available_options": available_options,
                }
                if result == "FAIL":
                    fill_failures[path] = last_reason
                _append_run_log(run_dir, f"Skip {path}: {last_reason}")

            final_url = page.url
            if keep_open_ms > 0 and not headless:
                _append_run_log(run_dir, f"Keeping browser open for {keep_open_ms}ms")
                try:
                    page.wait_for_timeout(keep_open_ms)
                except Exception as exc:  # noqa: BLE001
                    _append_run_log(run_dir, f"Keep-open interrupted: {exc}")
        finally:
            try:
                context.tracing.stop(path=str(trace_path))
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Trace capture failed: %s", exc)
            if not keep_open:
                context.close()
                browser.close()
        return browser, context, page

    if keep_open:
        playwright = sync_playwright().start()
        browser, context, page = _run(playwright)
        OPEN_BROWSER_SESSIONS.append(
            {
                "run_dir": str(run_dir),
                "browser": browser,
                "context": context,
                "page": page,
                "playwright": playwright,
            }
        )
        _append_run_log(run_dir, "Browser kept open for manual consent (keep_open_ms<0)")
    else:
        with sync_playwright() as playwright:
            _run(playwright)

    if fill_failures:
        reason_counts = Counter(fill_failures.values())
        _append_run_log(run_dir, f"Skipped reasons: {dict(reason_counts)}")
    _append_run_log(
        run_dir,
        f"Autofill complete. Attempted {len(attempted_fields)}; Filled {len(filled_fields)}; "
        f"Failures {len(fill_failures)}; Trace: {trace_path}",
    )

    duration_ms = int((time.perf_counter() - start_time) * 1000)
    _append_run_log(run_dir, f"Autofill runtime: {duration_ms}ms")

    return {
        "filled_fields": filled_fields,
        "attempted_fields": attempted_fields,
        "fill_failures": fill_failures,
        "dom_readback": dom_readback,
        "field_results": field_results,
        "form_completeness": _build_form_completeness(form_fields, payload, field_results),
        "duration_ms": duration_ms,
        "trace_path": str(trace_path),
        "final_url": final_url,
        "form_url": target_url,
        "browser_kept_open": keep_open,
    }
