from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

from ..field_registry import G28_LABEL_PATTERNS, get_field_spec
from .label_noise import is_placeholder_value, looks_like_label_value
from .normalize import normalize_country, normalize_email, normalize_name, normalize_phone

LOGGER = logging.getLogger(__name__)


LABEL_PATTERNS = G28_LABEL_PATTERNS

# G-28 boilerplate that should never be treated as a firm/organization value.
LAW_FIRM_NOISE_RE = re.compile(
    r"\b(accredited representative|representative of the following|qualified nonprofit)\b",
    re.IGNORECASE,
)

EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
ZIP_RE = re.compile(r"\b\d{5}(-\d{4})?\b")
STATE_RE = re.compile(r"\b[A-Z]{2}\b")

BOILERPLATE_CUTOFF_PATTERNS = [
    r"need extra space",
    r"use the space provided",
    r"provided in part",
    r"additional information",
    r"select only one box",
    r"subject to any order",
    r"disbarring",
    r"restricting me in the practice",
    r"appearance as an attorney",
    r"accredited representative",
    r"who previously filed",
    r"at his or her request",
    r"in accordance with",
    r"requirements in",
    r"member in good standing",
]


@dataclass
class G28Extraction:
    fields: Dict[str, Optional[str]]
    evidence: Dict[str, str]
    candidates: Dict[str, List[str]]
    label_presence: Dict[str, bool]


def _lines(text: str) -> List[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]

ATTORNEY_START_PATTERNS = [
    r"Part\\s*1",
    r"Information About Attorney",
    r"Name of Attorney",
    r"Address of Attorney",
    r"Contact Information of Attorney",
]

ATTORNEY_STOP_PATTERNS = [
    r"Part\\s*3",
    r"Notice of Appearance",
    r"Client's Contact Information",
    r"Information About Client",
]

CLIENT_START_PATTERNS = [
    r"Part\\s*3",
    r"Notice of Appearance",
    r"Client's Contact Information",
    r"Information About Client",
]

CLIENT_STOP_PATTERNS = [
    r"Part\\s*4",
    r"Client's Consent",
]


def _looks_like_label(line: str) -> bool:
    return looks_like_label_value(line)


def _is_law_firm_noise(value: str) -> bool:
    if not value:
        return False
    return bool(LAW_FIRM_NOISE_RE.search(value))


def _is_numeric_label_pattern(pattern: str) -> bool:
    if not re.search(r"\d", pattern):
        return False
    return not re.search(r"[A-Za-z]{2,}", pattern)


def _value_label_patterns(patterns: List[str]) -> List[str]:
    filtered = [pattern for pattern in patterns if not _is_numeric_label_pattern(pattern)]
    return filtered or patterns


def _is_name_candidate(value: str) -> bool:
    if not value:
        return False
    if looks_like_label_value(value):
        return False
    return bool(re.search(r"[A-Za-z]{2,}", value))


def _strip_leading_punct(value: str) -> str:
    return re.sub(r"^[\s:\-|()\[\]\{\}]+", "", value).strip()


def _strip_trailing_junk(value: str) -> str:
    cleaned = re.sub(r"[\s\-|,:;()\[\].]+$", "", value).strip()
    cleaned = re.sub(r"\b[IVX]{1,3}$", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"[\s\-|,:;()\[\].]+$", "", cleaned).strip()
    cleaned = re.sub(r"\b\d+\s*\.\s*[a-z]\b\.?$", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned


def _allow_placeholder_value(spec) -> bool:
    if not spec or spec.required:
        return False
    return False


def _looks_like_online_account_number(value: str) -> bool:
    if not value:
        return False
    text = value.strip()
    if not text:
        return False
    if re.search(r"[A-Za-z]", text):
        return False
    if re.search(r"[^0-9\s-]", text):
        return False
    digits = re.sub(r"\D", "", text)
    return 8 <= len(digits) <= 15


def _has_valid_phone_digits(value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return len(digits) >= 10


def _section_slice(
    lines: List[str],
    start_patterns: List[str],
    stop_patterns: List[str],
) -> List[str]:
    if not lines:
        return []
    start_idx = None
    for idx, line in enumerate(lines):
        if any(re.search(pattern, line, re.IGNORECASE) for pattern in start_patterns):
            start_idx = idx
            break
    if start_idx is None:
        for idx, line in enumerate(lines):
            if any(re.search(pattern, line, re.IGNORECASE) for pattern in stop_patterns):
                return lines[:idx]
        return []
    end_idx = len(lines)
    for idx in range(start_idx + 1, len(lines)):
        if any(re.search(pattern, lines[idx], re.IGNORECASE) for pattern in stop_patterns):
            end_idx = idx
            break
    return lines[start_idx:end_idx]


def _find_label_indices(lines: List[str], patterns: List[str]) -> List[int]:
    indices = []
    for idx, line in enumerate(lines):
        if any(re.search(pattern, line, re.IGNORECASE) for pattern in patterns):
            indices.append(idx)
    return indices


def _client_section_start(lines: List[str]) -> Optional[int]:
    client_markers = [
        r"\b6\s*\.\s*a(?![A-Za-z])",
        r"\b6\s*\.\s*b(?![A-Za-z])",
        r"\b6\s*\.\s*c(?![A-Za-z])",
        r"\b10\s*\.",
        r"\b11\s*\.",
        r"\b12\s*\.",
        r"\b13\s*\.\s*a(?![A-Za-z])",
        r"\b13\s*\.\s*b(?![A-Za-z])",
        r"\b13\s*\.\s*c(?![A-Za-z])",
        r"\b13\s*\.\s*d(?![A-Za-z])",
        r"\b13\s*\.\s*e(?![A-Za-z])",
        r"\b13\s*\.\s*h(?![A-Za-z])",
        r"This appearance relates to immigration matters",
        r"U\\.S\\. Citizenship and Immigration Services",
        r"U\\.S\\. Customs and Border Protection",
        r"Receipt Number",
        r"I enter my appearance as an attorney or accredited",
        r"Client's Contact Information",
        r"Information About Client",
    ]
    for idx, line in enumerate(lines):
        if any(re.search(pattern, line, re.IGNORECASE) for pattern in client_markers):
            return idx
    return None


def _next_value_lines(lines: List[str], start_idx: int, limit: int = 6) -> List[str]:
    values = []
    for offset in range(1, limit + 1):
        idx = start_idx + offset
        if idx >= len(lines):
            break
        candidate = lines[idx].strip()
        if not candidate or _looks_like_label(candidate):
            continue
        if len(candidate) < 2 or not re.search(r"[A-Za-z]{2,}", candidate):
            continue
        values.append(candidate)
        if len(values) >= 3:
            break
    return values


def _extract_name_block(
    lines: List[str],
    family_patterns: List[str],
    given_patterns: List[str],
    middle_patterns: List[str],
    prefix: str,
) -> Dict[str, str]:
    family_value_patterns = _value_label_patterns(family_patterns)
    given_value_patterns = _value_label_patterns(given_patterns)
    middle_value_patterns = _value_label_patterns(middle_patterns)
    family_numeric_patterns = [pattern for pattern in family_patterns if _is_numeric_label_pattern(pattern)]
    given_numeric_patterns = [pattern for pattern in given_patterns if _is_numeric_label_pattern(pattern)]
    middle_numeric_patterns = [pattern for pattern in middle_patterns if _is_numeric_label_pattern(pattern)]
    family_idx = _find_label_indices(lines, family_value_patterns)
    given_idx = _find_label_indices(lines, given_value_patterns)
    middle_idx = _find_label_indices(lines, middle_value_patterns)
    family_numeric_idx = _find_label_indices(lines, family_numeric_patterns) if family_numeric_patterns else []
    given_numeric_idx = _find_label_indices(lines, given_numeric_patterns) if given_numeric_patterns else []
    middle_numeric_idx = _find_label_indices(lines, middle_numeric_patterns) if middle_numeric_patterns else []
    if not family_idx and not given_idx and not middle_idx and not family_numeric_idx and not given_numeric_idx and not middle_numeric_idx:
        return {}
    all_label_indices = sorted(
        set(
            family_idx
            + given_idx
            + middle_idx
            + family_numeric_idx
            + given_numeric_idx
            + middle_numeric_idx
        )
    )

    def value_for_label(patterns: List[str], path: str) -> Optional[str]:
        value_patterns = _value_label_patterns(patterns)
        numeric_patterns = [pattern for pattern in patterns if _is_numeric_label_pattern(pattern)]
        for idx, line in enumerate(lines):
            if not any(re.search(pattern, line, re.IGNORECASE) for pattern in (value_patterns + numeric_patterns)):
                continue
            for pattern in value_patterns:
                if not re.search(pattern, line, re.IGNORECASE):
                    continue
                inline = _extract_inline_value(line, pattern, path=path)
                if inline and _is_name_candidate(inline):
                    return inline
            for pattern in numeric_patterns:
                if not re.search(pattern, line, re.IGNORECASE):
                    continue
                inline = _extract_inline_value(line, pattern, path=path)
                if inline and _is_name_candidate(inline):
                    return inline
            next_label = None
            for later in all_label_indices:
                if later > idx:
                    next_label = later
                    break
            stop_at = next_label if next_label is not None else min(len(lines), idx + 6)
            for j in range(idx + 1, min(len(lines), stop_at)):
                candidate = lines[j].strip()
                if not candidate or _looks_like_label(candidate):
                    continue
                if _is_name_candidate(candidate):
                    return candidate
        return None

    family = value_for_label(family_patterns, f"{prefix}.family_name")
    given = value_for_label(given_patterns, f"{prefix}.given_name")
    middle = value_for_label(middle_patterns, f"{prefix}.middle_name")
    if family or given:
        out: Dict[str, str] = {}
        if family:
            out["family_name"] = family
        if given:
            out["given_name"] = given
        if middle:
            out["middle_name"] = middle
        return out

    last_label = max(all_label_indices)
    values = [value for value in _next_value_lines(lines, last_label, limit=6) if _is_name_candidate(value)]
    if not values:
        return {}
    out: Dict[str, str] = {}
    if len(values) >= 1:
        out["family_name"] = values[0]
    if len(values) >= 2:
        out["given_name"] = values[1]
    if len(values) >= 3:
        out["middle_name"] = values[2]
    return out


def _extract_state_zip(line: str) -> Tuple[Optional[str], Optional[str]]:
    state = None
    zip_code = None
    state_match = re.search(r"\b([A-Z]{2})\b", line)
    if state_match:
        state = state_match.group(1)
    zip_match = re.search(r"\b\d{5}(-\d{4})?\b", line)
    if zip_match:
        zip_code = zip_match.group(0)
    return state, zip_code


def _is_strong_label_pattern(pattern: str) -> bool:
    if _is_numeric_label_pattern(pattern):
        return False
    if re.search(r"\d", pattern) and re.search(r"[A-Za-z]", pattern):
        return True
    cleaned = pattern.replace("\\s", " ")
    cleaned = re.sub(r"[\\^$.|?*+()\\[\\]{}]", " ", cleaned)
    cleaned = cleaned.replace("_", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return False
    return len(cleaned.split()) >= 2


@lru_cache(maxsize=None)
def _other_label_patterns(path: str) -> Tuple[str, ...]:
    patterns: List[str] = []
    for other_path, hints in LABEL_PATTERNS.items():
        if other_path == path:
            continue
        for hint in hints:
            if _is_strong_label_pattern(hint):
                patterns.append(hint)
    return tuple(patterns)


def _truncate_on_patterns(value: str, patterns: Tuple[str, ...]) -> str:
    earliest = None
    for pattern in patterns:
        match = re.search(pattern, value, re.IGNORECASE)
        if not match:
            continue
        if earliest is None or match.start() < earliest:
            earliest = match.start()
    if earliest is not None and earliest > 0:
        return value[:earliest].strip()
    return value


def _strip_boilerplate(value: str) -> str:
    earliest = None
    for pattern in BOILERPLATE_CUTOFF_PATTERNS:
        match = re.search(pattern, value, re.IGNORECASE)
        if not match:
            continue
        if earliest is None or match.start() < earliest:
            earliest = match.start()
    if earliest is not None and earliest > 0:
        return value[:earliest].strip()
    return value


def _coerce_inline_value(path: Optional[str], value: str) -> Optional[str]:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    if "|" in raw:
        segments = [seg.strip() for seg in raw.split("|") if seg.strip()]
        for segment in segments:
            if _looks_like_label(segment):
                continue
            raw = segment
            break
    if path and path.endswith("email"):
        match = EMAIL_RE.search(raw)
        if match:
            return match.group(0)
    if path and "phone" in path:
        match = re.search(
            r"(\+?1[\s\-\.]*)?(\(?\d{3}\)?[\s\-\.]*)\d{3}[\s\-\.]\d{4}",
            raw,
        )
        if match:
            return match.group(0)
        digits = re.sub(r"\D", "", raw)
        if len(digits) >= 10:
            return digits[:10]
    cleaned = _strip_boilerplate(raw)
    if path:
        cleaned = _truncate_on_patterns(cleaned, _other_label_patterns(path))
    cleaned = _strip_trailing_junk(cleaned)
    if not cleaned:
        return None
    if path and any(path.endswith(suffix) for suffix in ["family_name", "given_name", "middle_name"]):
        cleaned = re.sub(r"^[\s\.-]*\d+\s*\.?\s*[a-z]?\s*\.?\s*", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"\([^)]*\)", "", cleaned).strip()
        cleaned = re.sub(
            r"\b(first|given|middle|last|family)\s+name\b",
            "",
            cleaned,
            flags=re.IGNORECASE,
        ).strip()
        cleaned = _strip_leading_punct(cleaned)
        cleaned = re.sub(r"^[.]+\s*", "", cleaned).strip()
        if not cleaned:
            return None
    if path and path.endswith("address.street"):
        cleaned = re.sub(r"^[\s\.-]*\d+\s*\.?\s*[a-z]?\s*\.?\s*", "", cleaned, flags=re.IGNORECASE).strip()
        for _ in range(2):
            cleaned = re.sub(
                r"^[\s\.-]*(street|stree|stree number|street number|street number and name|number and name|number)\b[:\s-]*",
                "",
                cleaned,
                flags=re.IGNORECASE,
            ).strip()
        if not cleaned:
            return None
    if path and path.endswith("licensing_authority"):
        match = re.search(r"(State Bar[^,;\n]*)", cleaned, re.IGNORECASE)
        if match:
            cleaned = match.group(1).strip()
    if path and path.endswith("bar_number"):
        digit_match = re.search(r"\d{4,}", cleaned)
        if digit_match:
            return digit_match.group(0)
    if path and path.endswith("zip"):
        zip_match = ZIP_RE.search(cleaned)
        if zip_match:
            return zip_match.group(0)
    if path and path.endswith("state"):
        state_match = STATE_RE.search(cleaned.upper())
        if state_match:
            return state_match.group(0)
    if path and path.endswith("address.unit"):
        if is_placeholder_value(cleaned):
            return cleaned
    return cleaned


def _extract_address_block(lines: List[str], prefix: str) -> Dict[str, str]:
    street_patterns = LABEL_PATTERNS.get(f"{prefix}.address.street", [])
    unit_patterns = LABEL_PATTERNS.get(f"{prefix}.address.unit", [])
    city_patterns = LABEL_PATTERNS.get(f"{prefix}.address.city", [])
    state_patterns = LABEL_PATTERNS.get(f"{prefix}.address.state", [])
    zip_patterns = LABEL_PATTERNS.get(f"{prefix}.address.zip", [])
    country_patterns = LABEL_PATTERNS.get(f"{prefix}.address.country", [])

    start_idx = None
    for idx, line in enumerate(lines):
        if any(re.search(pattern, line, re.IGNORECASE) for pattern in street_patterns):
            start_idx = idx
            break
    if start_idx is None:
        return {}
    end_idx = min(len(lines), start_idx + 14)
    for idx in range(start_idx + 1, min(len(lines), start_idx + 14)):
        if any(re.search(pattern, lines[idx], re.IGNORECASE) for pattern in country_patterns):
            end_idx = min(len(lines), idx + 3)
            break

    block = lines[start_idx:end_idx]
    extracted: Dict[str, str] = {}

    def capture_inline(
        line: str,
        patterns: List[str],
        allow_placeholder: bool = False,
        path: Optional[str] = None,
    ) -> Optional[str]:
        for pattern in _value_label_patterns(patterns):
            value = _extract_inline_value(
                line,
                pattern,
                allow_placeholder=allow_placeholder,
                path=path,
            )
            if value:
                return value
        return None

    def is_street_candidate(value: str) -> bool:
        if looks_like_label_value(value):
            return False
        if re.match(r"^\s*\d+\s*\.?\s*[a-z]\b", value, re.IGNORECASE):
            return False
        if not re.search(r"\d", value):
            return False
        if not re.search(r"[A-Za-z]{2,}", value):
            return False
        if any(
            re.search(pattern, value, re.IGNORECASE)
            for pattern in (unit_patterns + city_patterns + state_patterns + zip_patterns + country_patterns)
        ):
            return False
        return True

    def is_unit_candidate(value: str) -> bool:
        if is_placeholder_value(value):
            return True
        return bool(re.search(r"\b(apt|ste|suite|flr|floor|unit)\b", value, re.IGNORECASE))

    def is_city_candidate(value: str) -> bool:
        if looks_like_label_value(value):
            return False
        if re.search(r"\d", value):
            return False
        if any(re.search(pattern, value, re.IGNORECASE) for pattern in (state_patterns + zip_patterns)):
            return False
        return bool(re.search(r"[A-Za-z]{2,}", value))

    def is_country_candidate(value: str) -> bool:
        if looks_like_label_value(value):
            return False
        return bool(re.search(r"[A-Za-z]{2,}", value))

    def next_candidate(idx: int, limit: int, predicate) -> Optional[str]:
        for offset in range(1, limit + 1):
            if idx + offset >= len(block):
                break
            candidate = block[idx + offset].strip()
            if not candidate:
                continue
            if _looks_like_label(candidate):
                continue
            if predicate(candidate):
                return candidate
        return None

    for idx, line in enumerate(block):
        if any(re.search(pattern, line, re.IGNORECASE) for pattern in street_patterns):
            if f"{prefix}.address.street" in extracted:
                continue
            value = capture_inline(line, street_patterns, path=f"{prefix}.address.street")
            if not value:
                for pattern in street_patterns:
                    if not _is_numeric_label_pattern(pattern):
                        continue
                    value = _extract_inline_value(
                        line,
                        pattern,
                        path=f"{prefix}.address.street",
                    )
                    if value:
                        break
            if not value:
                value = next_candidate(idx, limit=4, predicate=is_street_candidate)
            if value:
                value = re.sub(r"^and\s+name\b", "", value, flags=re.IGNORECASE).strip()
                if not value:
                    value = None
            if value:
                extracted[f"{prefix}.address.street"] = value
        if any(re.search(pattern, line, re.IGNORECASE) for pattern in unit_patterns):
            if f"{prefix}.address.unit" in extracted:
                continue
            value = capture_inline(
                line,
                unit_patterns,
                allow_placeholder=True,
                path=f"{prefix}.address.unit",
            )
            if not value:
                value = next_candidate(idx, limit=3, predicate=is_unit_candidate)
            if value:
                extracted[f"{prefix}.address.unit"] = value
        if any(re.search(pattern, line, re.IGNORECASE) for pattern in city_patterns):
            if f"{prefix}.address.city" in extracted:
                continue
            value = capture_inline(line, city_patterns, path=f"{prefix}.address.city")
            if not value:
                value = next_candidate(idx, limit=3, predicate=is_city_candidate)
            if value:
                extracted[f"{prefix}.address.city"] = value
        if any(re.search(pattern, line, re.IGNORECASE) for pattern in state_patterns):
            if f"{prefix}.address.state" not in extracted or f"{prefix}.address.zip" not in extracted:
                state, zip_code = _extract_state_zip(line)
                if state and f"{prefix}.address.state" not in extracted:
                    extracted[f"{prefix}.address.state"] = state
                if zip_code and f"{prefix}.address.zip" not in extracted:
                    extracted[f"{prefix}.address.zip"] = zip_code
        if any(re.search(pattern, line, re.IGNORECASE) for pattern in zip_patterns):
            if f"{prefix}.address.zip" in extracted:
                continue
            value = capture_inline(line, zip_patterns, path=f"{prefix}.address.zip")
            if value and value.upper() != "N/A":
                extracted[f"{prefix}.address.zip"] = value
        if any(re.search(pattern, line, re.IGNORECASE) for pattern in country_patterns):
            if f"{prefix}.address.country" in extracted:
                continue
            value = capture_inline(line, country_patterns, path=f"{prefix}.address.country")
            if not value:
                value = next_candidate(idx, limit=3, predicate=is_country_candidate)
            if value:
                extracted[f"{prefix}.address.country"] = value

    if f"{prefix}.address.zip" not in extracted:
        for line in block:
            if re.fullmatch(r"\d{4,6}", line.strip()):
                extracted[f"{prefix}.address.zip"] = line.strip()
                break
    return extracted


def _score_candidate(path: str, value: str) -> int:
    text = value.strip()
    if not text:
        return -10
    if looks_like_label_value(text):
        return -5
    score = 0
    if path.endswith("email"):
        score += 4 if re.search(r"@", text) else -3
    if "phone" in path:
        digits = re.sub(r"\D", "", text)
        score += 2 if len(digits) >= 7 else -2
    if path.endswith("address.street"):
        score += 3 if re.search(r"\d", text) else -2
    if path.endswith("zip"):
        score += 3 if re.fullmatch(r"\d{4,6}(-\d{4})?", text.replace(" ", "")) else -1
    if path.endswith("state"):
        score += 3 if re.fullmatch(r"[A-Za-z]{2}", text.strip()) else -2
    if path.endswith("bar_number"):
        digits = re.sub(r"\D", "", text)
        if digits:
            score += 4 if len(digits) >= 4 else 1
            if digits == text:
                score += 3
        if re.search(r"[A-Za-z]", text):
            score -= 3
    if path.endswith("online_account_number"):
        digits = re.sub(r"\D", "", text)
        if re.search(r"[A-Za-z]", text):
            score -= 4
        if len(digits) >= 8:
            score += 4
        else:
            score -= 2
        if re.search(r"[^0-9\s-]", text):
            score -= 3
    if path.endswith("licensing_authority"):
        score += 1 if re.search(r"[A-Za-z]", text) else -2
    if any(path.endswith(suffix) for suffix in ["family_name", "given_name", "middle_name"]):
        score += 2 if re.search(r"[A-Za-z]{2,}", text) else -2
    score += min(len(text) // 8, 2)
    return score

def _extract_inline_value(
    line: str,
    pattern: str,
    allow_placeholder: bool = False,
    path: Optional[str] = None,
) -> Optional[str]:
    match = re.search(pattern, line, re.IGNORECASE)
    if not match:
        return None
    tail = line[match.end():]
    tail = re.sub(r"^[\s:\-|]+", "", tail).strip()
    if "|" in tail:
        segments = [seg.strip() for seg in tail.split("|") if seg.strip()]
        for segment in segments:
            if _looks_like_label(segment):
                if allow_placeholder and is_placeholder_value(segment):
                    tail = segment
                    break
                continue
            tail = segment
            break
        else:
            if segments:
                tail = segments[0]
    if not tail:
        return None
    if _looks_like_label(tail):
        if not (allow_placeholder and is_placeholder_value(tail)):
            return None
    tail = _strip_leading_punct(tail)
    tail = _coerce_inline_value(path, tail) if tail else None
    return tail if tail else None


def _find_value_after_label(lines: List[str], label_patterns: List[str]) -> Optional[str]:
    for idx, line in enumerate(lines):
        for pattern in label_patterns:
            if re.search(pattern, line, re.IGNORECASE):
                inline = _extract_inline_value(line, pattern)
                if inline:
                    return inline
                for offset in range(1, 4):
                    if idx + offset >= len(lines):
                        break
                    candidate = lines[idx + offset].strip()
                    if not candidate or _looks_like_label(candidate):
                        continue
                    return candidate
    return None


def _find_email(text: str) -> Optional[str]:
    match = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", text, re.IGNORECASE)
    return match.group(0) if match else None


def _find_phone(text: str) -> Optional[str]:
    match = re.search(r"(\+?1[\s\-\.]*)?(\(?\d{3}\)?[\s\-\.]*)\d{3}[\s\-\.]\d{4}", text)
    return match.group(0) if match else None


def extract_g28_fields(text: str) -> G28Extraction:
    lines = _lines(text)
    attorney_lines = _section_slice(lines, ATTORNEY_START_PATTERNS, ATTORNEY_STOP_PATTERNS)
    client_lines = _section_slice(lines, CLIENT_START_PATTERNS, CLIENT_STOP_PATTERNS)
    client_start_idx = _client_section_start(lines)
    if client_start_idx is not None:
        attorney_lines = lines[:client_start_idx]
        client_lines = lines[client_start_idx:]
    if not attorney_lines:
        attorney_lines = lines

    candidates: Dict[str, List[str]] = {}
    evidence: Dict[str, str] = {}
    label_presence: Dict[str, bool] = {path: False for path in LABEL_PATTERNS}

    def add_candidate(
        path: str,
        value: Optional[str],
        source_line: Optional[str],
        label_patterns: Optional[List[str]] = None,
    ) -> None:
        if not value:
            return
        if "phone" in path and "@" in str(value):
            return
        if path.endswith("online_account_number") and not _looks_like_online_account_number(str(value)):
            return
        if "phone" in path:
            if is_placeholder_value(str(value)):
                return
            if not _has_valid_phone_digits(str(value)):
                return
        if path.endswith("address.unit") and is_placeholder_value(str(value)):
            return
        if path.endswith("law_firm_name") and _is_law_firm_noise(str(value)):
            return
        spec = get_field_spec(path)
        allow_placeholder = _allow_placeholder_value(spec)
        if looks_like_label_value(value, label_patterns):
            if not (allow_placeholder and is_placeholder_value(value)):
                return
        candidates.setdefault(path, []).append(value)
        if path not in evidence and source_line:
            evidence[path] = source_line

    def scan_field(path: str, label_patterns: List[str], lines_scope: List[str]) -> None:
        seen = set()
        spec = get_field_spec(path)
        allow_placeholder = _allow_placeholder_value(spec)
        value_patterns = _value_label_patterns(label_patterns)
        for idx, line in enumerate(lines_scope):
            if any(re.search(pattern, line, re.IGNORECASE) for pattern in label_patterns):
                label_presence[path] = True
            if ".address." in path:
                continue
            if path.endswith("phone_daytime") and re.search(r"mobile", line, re.IGNORECASE):
                continue
            if path.endswith("phone_mobile") and re.search(r"daytime", line, re.IGNORECASE):
                continue
            for pattern in value_patterns:
                if not re.search(pattern, line, re.IGNORECASE):
                    continue
                inline = _extract_inline_value(
                    line,
                    pattern,
                    allow_placeholder=allow_placeholder,
                    path=path,
                )
                if inline:
                    if inline not in seen:
                        add_candidate(path, inline, line, label_patterns)
                        seen.add(inline)
                if not inline:
                    for offset in range(1, 4):
                        if idx + offset >= len(lines_scope):
                            break
                        candidate = lines_scope[idx + offset].strip()
                        if not candidate:
                            continue
                        if _looks_like_label(candidate):
                            if allow_placeholder and is_placeholder_value(candidate):
                                if candidate not in seen:
                                    add_candidate(path, candidate, candidate, label_patterns)
                                    seen.add(candidate)
                            break
                        cleaned_candidate = _coerce_inline_value(path, candidate) or candidate
                        if cleaned_candidate in seen:
                            continue
                        add_candidate(path, cleaned_candidate, candidate, label_patterns)
                        seen.add(cleaned_candidate)

    for path, patterns in LABEL_PATTERNS.items():
        scope = attorney_lines if path.startswith("g28.attorney.") else client_lines
        scan_field(path, patterns, scope)

    attorney_name_block = _extract_name_block(
        attorney_lines,
        LABEL_PATTERNS.get("g28.attorney.family_name", []),
        LABEL_PATTERNS.get("g28.attorney.given_name", []),
        LABEL_PATTERNS.get("g28.attorney.middle_name", []),
        "g28.attorney",
    )
    if attorney_name_block:
        for key in ["family_name", "given_name", "middle_name"]:
            path = f"g28.attorney.{key}"
            if key in attorney_name_block:
                value = attorney_name_block[key]
                candidates[path] = [value]
                if path not in evidence:
                    evidence[path] = value
            else:
                candidates.pop(path, None)

    client_name_block = _extract_name_block(
        client_lines,
        LABEL_PATTERNS.get("g28.client.family_name", []),
        LABEL_PATTERNS.get("g28.client.given_name", []),
        LABEL_PATTERNS.get("g28.client.middle_name", []),
        "g28.client",
    )
    if client_name_block:
        for key in ["family_name", "given_name", "middle_name"]:
            path = f"g28.client.{key}"
            if key in client_name_block:
                value = client_name_block[key]
                candidates[path] = [value]
                if path not in evidence:
                    evidence[path] = value
            else:
                candidates.pop(path, None)

    attorney_address_block = _extract_address_block(attorney_lines, "g28.attorney")
    for path, value in attorney_address_block.items():
        add_candidate(path, value, value, LABEL_PATTERNS.get(path, []))

    client_address_block = _extract_address_block(client_lines, "g28.client")
    for path, value in client_address_block.items():
        add_candidate(path, value, value, LABEL_PATTERNS.get(path, []))

    attorney_email = _find_email("\n".join(attorney_lines))
    if attorney_email:
        add_candidate("g28.attorney.email", attorney_email, attorney_email)
    client_email = _find_email("\n".join(client_lines))
    if client_email:
        add_candidate("g28.client.email", client_email, client_email)

    attorney_phone = _find_phone("\n".join(attorney_lines))
    if attorney_phone:
        add_candidate("g28.attorney.phone_daytime", attorney_phone, attorney_phone)
    client_phone = _find_phone("\n".join(client_lines))
    if client_phone:
        add_candidate("g28.client.phone", client_phone, client_phone)

    def choose_best(path: str, values: List[str]) -> Optional[str]:
        if not values:
            return None
        scored = []
        for value in values:
            scored.append((_score_candidate(path, value), len(value), value))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return scored[0][2]

    fields: Dict[str, Optional[str]] = {}
    for path, values in candidates.items():
        choice = choose_best(path, values)
        if not choice:
            continue
        if path.endswith("email"):
            choice = normalize_email(choice)
        elif "phone" in path:
            choice = normalize_phone(choice)
        elif path.endswith("country"):
            choice = normalize_country(choice)
        elif path.endswith("state"):
            choice = choice.strip().upper() if choice else choice
        elif path.endswith("bar_number"):
            choice = re.sub(r"\s+", "", choice)
        elif any(path.endswith(suffix) for suffix in ["family_name", "given_name", "middle_name"]):
            choice = normalize_name(choice)
        fields[path] = choice

    LOGGER.debug("G-28 raw candidates: %s", candidates)
    LOGGER.debug("G-28 normalized fields: %s", fields)

    return G28Extraction(fields=fields, evidence=evidence, candidates=candidates, label_presence=label_presence)
