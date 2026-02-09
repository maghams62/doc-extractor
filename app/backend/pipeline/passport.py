from __future__ import annotations

import datetime as dt
import logging
import re
from difflib import SequenceMatcher
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, Iterable, List, Optional, Tuple

from .ocr import OCRResult
from .label_noise import looks_like_label_value
from .normalize import (
    normalize_country,
    normalize_date,
    normalize_passport_number,
    normalize_sex,
    normalize_name,
)
from ..field_registry import iter_fields

LOGGER = logging.getLogger(__name__)


# MRZ OCR often includes a stray character; allow slight overrun and require filler "<".
MRZ_LINE_RE = re.compile(r"^(?=.*<)[A-Z0-9<]{30,46}$")
MRZ_CANDIDATE_RE = re.compile(r"[A-Z0-9<]{30,46}")
SMALL_NOISE_TOKENS = {"no", "nr", "id", "ap", "pg"}
NAME_PARTICLES = {"of", "de", "du", "la", "le", "del", "d", "da", "dos", "das"}
LABEL_STOPWORDS = {
    "date",
    "of",
    "de",
    "la",
    "le",
    "du",
    "del",
    "d",
    "da",
    "dos",
    "das",
    "des",
    "fecha",
}
DATE_CANDIDATE_PATTERNS = [
    re.compile(r"\b\d{1,2}\s*[A-Za-z]{3,9}\s*\d{2,4}\b"),
    re.compile(r"\b[A-Za-z]{3,9}\s*\d{1,2},?\s*\d{2,4}\b"),
    re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b"),
    re.compile(r"\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b"),
]
PLACE_OF_BIRTH_LABEL_RE = re.compile(
    r"(place\W*of\W*birth|birth\W*place|lieu\W*de\W*naissance|lugar\W*de\W*nacimiento)",
    re.IGNORECASE,
)
NATIONALITY_LABEL_RE = re.compile(r"(nationality|nationalite|nacionalidad)", re.IGNORECASE)
COUNTRY_ISSUE_LABEL_RE = re.compile(
    r"(country\W*of\W*issue|issuing\W*country|pays\W*de\W*delivrance|pais\W*de\W*expedicion|autorite|autoridad)",
    re.IGNORECASE,
)
PLACE_OF_ISSUE_LABEL_RE = re.compile(
    r"(place\W*of\W*issue|lieu\W*de\W*delivrance|lugar\W*de\W*expedicion)",
    re.IGNORECASE,
)
DATE_OF_BIRTH_LABEL_RE = re.compile(
    r"(date\W*of\W*birth|date\W*de\W*naissance|fecha\W*de\W*nacimiento)",
    re.IGNORECASE,
)
DATE_OF_ISSUE_LABEL_RE = re.compile(
    r"(date\W*of\W*issue|date\W*of\W*issuance|date\W*de\W*delivrance|fecha\W*de\W*expedicion)",
    re.IGNORECASE,
)
DATE_OF_EXPIRATION_LABEL_RE = re.compile(
    r"(date\W*of\W*expir|date\W*d['’]?expiration|fecha\W*de\W*caducidad)",
    re.IGNORECASE,
)


@lru_cache
def _passport_specs() -> Tuple[object, ...]:
    return tuple(spec for spec in iter_fields() if spec.key.startswith("passport."))


@lru_cache
def _passport_label_tokens() -> frozenset[str]:
    tokens: set[str] = set()
    for spec in _passport_specs():
        labels: Iterable[str] = [spec.label, *spec.label_hints] if spec.label_hints else [spec.label]
        for label in labels:
            if not label:
                continue
            tokens.update(token.lower() for token in re.findall(r"[A-Za-z]+", label))
    return frozenset(tokens)


@lru_cache
def _name_stop_re() -> Optional[re.Pattern]:
    tokens = sorted(_passport_label_tokens(), key=len, reverse=True)
    if not tokens:
        return None
    pattern = r"\b(" + "|".join(re.escape(token) for token in tokens) + r")\b"
    return re.compile(pattern, re.IGNORECASE)


def _looks_like_regex(value: str) -> bool:
    return bool(re.search(r"[\\\[\]\(\)\?\+\{\}\|]", value))


def _compile_label_pattern(label: str) -> Optional[re.Pattern]:
    if not label:
        return None
    cleaned = label.strip()
    if cleaned.lower().startswith("passport "):
        cleaned = cleaned[len("passport ") :]
    if _looks_like_regex(cleaned):
        try:
            return re.compile(cleaned, re.IGNORECASE)
        except re.error:
            pass
    tokens = re.findall(r"[A-Za-z0-9]+", cleaned)
    if not tokens:
        return None
    pattern = r"\b" + r"\W*".join(re.escape(token) for token in tokens) + r"\b"
    return re.compile(pattern, re.IGNORECASE)


def _label_patterns_for(spec) -> List[re.Pattern]:
    patterns: List[re.Pattern] = []
    labels: List[str] = []
    if spec.label:
        labels.append(spec.label)
    if spec.label_hints:
        labels.extend(spec.label_hints)
    for label in labels:
        pattern = _compile_label_pattern(label)
        if pattern:
            patterns.append(pattern)
    return patterns


def _normalizer_for(spec):
    if spec.field_type in {"date", "date_past", "date_future"}:
        return normalize_date
    if spec.field_type == "passport_number":
        return normalize_passport_number
    if spec.field_type == "sex":
        return normalize_sex
    if spec.field_type == "name":
        return normalize_passport_name
    if spec.key in {"passport.nationality", "passport.country_of_issue"}:
        return normalize_country
    if spec.field_type == "text":
        return normalize_name
    return None


def _label_token_set(spec) -> frozenset[str]:
    tokens: set[str] = set()
    labels: List[str] = []
    if spec.label:
        labels.append(spec.label)
    if spec.label_hints:
        labels.extend(spec.label_hints)
    for label in labels:
        if not label:
            continue
        for token in re.findall(r"[A-Za-z]+", label.lower()):
            if token in SMALL_NOISE_TOKENS:
                continue
            tokens.add(token)
    return frozenset(tokens)


def _label_like_value(spec, value: str) -> bool:
    if looks_like_label_value(value, spec.label_hints):
        return True
    key = str(getattr(spec, "key", ""))
    if key.endswith("place_of_birth") and PLACE_OF_BIRTH_LABEL_RE.search(value):
        return True
    if key.endswith("nationality") and NATIONALITY_LABEL_RE.search(value):
        return True
    if key.endswith("country_of_issue") and COUNTRY_ISSUE_LABEL_RE.search(value):
        return True
    return False


def _passport_text_value_ok(spec, value: str, line: str, is_same_line: bool) -> bool:
    if _label_like_value(spec, value):
        return False
    key = str(getattr(spec, "key", ""))
    if key.endswith("place_of_birth"):
        if re.search(r"\d", value):
            return False
        return _looks_like_location(value)
    if key.endswith("country_of_issue"):
        if re.search(r"\d", value):
            return False
        if is_same_line and PLACE_OF_ISSUE_LABEL_RE.search(line) and not COUNTRY_ISSUE_LABEL_RE.search(line):
            return False
        if len(re.findall(r"[A-Za-z]", value)) < 2:
            return False
        return True
    if key.endswith("nationality"):
        if re.search(r"\d", value):
            return False
        if len(re.findall(r"[A-Za-z]", value)) < 3:
            return False
        return True
    return True


def _line_tokens(line: str) -> List[str]:
    return [token.lower() for token in re.findall(r"[A-Za-z]+", line)]


def _fuzzy_token_eq(a: str, b: str) -> bool:
    if a == b:
        return True
    if len(a) < 3 or len(b) < 3:
        return False
    if a in b or b in a:
        return min(len(a), len(b)) >= 4
    if len(a) >= 4 and len(b) >= 4:
        return SequenceMatcher(None, a, b).ratio() >= 0.8
    return False


def _fuzzy_label_match(label_tokens: frozenset[str], line: str) -> bool:
    if not label_tokens:
        return False
    line_tokens = _line_tokens(line)
    if not line_tokens:
        return False
    distinctives = [token for token in label_tokens if token not in LABEL_STOPWORDS]
    if distinctives and not any(_fuzzy_token_eq(token, lt) for token in distinctives for lt in line_tokens):
        return False
    matches = 0
    for token in label_tokens:
        if any(_fuzzy_token_eq(token, lt) for lt in line_tokens):
            matches += 1
    if matches == 0:
        return False
    required = 1 if len(label_tokens) <= 2 else 2
    # Avoid mapping "place of birth" to "date of birth" lines.
    if "place" in label_tokens and "date" in line_tokens:
        if not any(_fuzzy_token_eq("place", lt) for lt in line_tokens):
            return False
    return matches >= required


def _normalize_date_any(raw: str) -> Optional[str]:
    normalized = normalize_date(raw, year_first=True)
    if normalized:
        return normalized
    return normalize_date(raw, year_first=False)


def _normalize_mrz_date(raw: str, *, field: str) -> Optional[str]:
    if not raw:
        return None
    cleaned = raw.strip()
    if re.fullmatch(r"\d{6}", cleaned):
        year = int(cleaned[0:2])
        month = int(cleaned[2:4])
        day = int(cleaned[4:6])
        candidates = []
        for century in (2000, 1900):
            try:
                candidates.append(dt.date(century + year, month, day))
            except ValueError:
                continue
        if not candidates:
            return None
        if field == "expiry":
            today = dt.date.today()
            future = [c for c in candidates if c >= today]
            chosen = min(future) if future else max(candidates)
            return chosen.isoformat()
    return normalize_date(cleaned, year_first=False)


def _extract_date_candidates(lines: List[str]) -> List[Dict[str, object]]:
    candidates: List[Dict[str, object]] = []
    seen = set()
    for idx, line in enumerate(lines):
        for pattern in DATE_CANDIDATE_PATTERNS:
            for match in pattern.finditer(line):
                raw = match.group(0)
                normalized = _normalize_date_any(raw)
                if not normalized:
                    continue
                key = (normalized, idx, match.start())
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(
                    {
                        "iso": normalized,
                        "idx": idx,
                        "pos": match.start(),
                        "line": line,
                        "prev": lines[idx - 1] if idx > 0 else "",
                        "raw": raw,
                    }
                )
    return candidates


def _looks_like_location(line: str) -> bool:
    if not line:
        return False
    if re.search(r"\d", line):
        return False
    if re.fullmatch(r"[^A-Za-z]+", line):
        return False
    letters = re.findall(r"[A-Za-z]", line)
    if len(letters) < 4:
        return False
    tokens = _line_tokens(line)
    label_tokens = {
        "date",
        "birth",
        "place",
        "issue",
        "expiry",
        "expiration",
        "passport",
        "sex",
        "nationality",
        "nationalite",
        "nacionalidad",
        "authority",
        "autorite",
        "autoridad",
        "naissance",
        "nacimiento",
        "lieu",
        "lugar",
    }
    if any(token in label_tokens for token in tokens):
        return False
    if PLACE_OF_BIRTH_LABEL_RE.search(line):
        return False
    return True


def _score_candidate(
    spec,
    raw: str,
    same_line: bool,
    line: str,
    label_tokens: frozenset[str],
) -> float:
    score = 0.4 if same_line else 0.25
    line_tokens = {token.lower() for token in re.findall(r"[A-Za-z]+", line)}
    overlap = len(label_tokens & line_tokens)
    if overlap:
        score += min(0.2, overlap * 0.05)
    raw_clean = raw.strip()
    if not raw_clean:
        return 0.0

    if spec.field_type == "passport_number":
        digits = sum(ch.isdigit() for ch in raw_clean)
        alnum = all(ch.isalnum() for ch in raw_clean)
        if digits >= 6:
            score += 0.25
        if len(raw_clean) == 9:
            score += 0.2
        if alnum:
            score += 0.05
    elif spec.field_type in {"date", "date_past", "date_future"}:
        if normalize_date(raw_clean):
            score += 0.3
        else:
            score -= 0.1
    elif spec.field_type == "sex":
        if raw_clean.upper() in {"M", "F", "X"}:
            score += 0.3
        else:
            score -= 0.1
    elif spec.field_type == "name":
        letters = re.findall(r"[A-Za-z]+", raw_clean)
        if letters:
            score += 0.1
        if len(raw_clean) > 48:
            score -= 0.2
    else:
        if re.search(r"[A-Za-z0-9]", raw_clean):
            score += 0.05
        if normalize_date(raw_clean):
            score -= 0.25
    return score


def _extract_mrz_chunks(line: str) -> Optional[List[str]]:
    """Return two MRZ lines from a long OCR line, if present."""
    if len(line) >= 88:
        tail = line[-88:]
        if "<" in tail:
            return [tail[:44], tail[44:88]]
    chunks = [chunk for chunk in MRZ_CANDIDATE_RE.findall(line) if "<" in chunk]
    if len(chunks) >= 2:
        return chunks[-2:]
    return None


def _best_mrz_line1(line: str) -> str:
    if len(line) <= 44:
        return line
    if "P<" in line:
        start = line.index("P<")
        candidate = line[start : start + 44]
        if len(candidate) >= 40:
            return candidate
    return line[:44]


def _best_mrz_line2(line: str) -> str:
    if len(line) <= 44:
        return line
    best_line = line[:44]
    best_score = -1.0
    for idx in range(0, len(line) - 43):
        candidate = line[idx : idx + 44]
        if "<" not in candidate:
            continue
        score = 0.0
        if _valid_check_digit(candidate[0:9], candidate[9:10]):
            score += 2.0
        if _valid_check_digit(candidate[13:19], candidate[19:20]):
            score += 1.5
        if _valid_check_digit(candidate[21:27], candidate[27:28]):
            score += 1.5
        if re.fullmatch(r"[A-Z]{3}", candidate[10:13]):
            score += 0.5
        if candidate[20:21] in {"M", "F", "X"}:
            score += 0.25
        if score > best_score:
            best_score = score
            best_line = candidate
    return best_line


def _trim_at_stop(value: str) -> str:
    stop_re = _name_stop_re()
    if stop_re:
        match = stop_re.search(value)
        if match:
            return value[: match.start()].strip()
    return value.strip()


def _split_particles(token: str) -> List[str]:
    lower = token.lower()
    if lower.startswith("dela") and len(token) > 4:
        return ["de", "la", token[4:]]
    if lower.startswith("delas") and len(token) > 5:
        return ["de", "las", token[5:]]
    if lower.startswith("delos") and len(token) > 5:
        return ["de", "los", token[5:]]
    return [token]


def normalize_passport_name(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    raw = value.replace("|", " ")
    raw = re.sub(r"\b(page|pg)\s*\d+\b", " ", raw, flags=re.IGNORECASE)
    tokens = re.findall(r"[A-Za-z][A-Za-z'\-]*", raw)
    if not tokens:
        return None
    noise_tokens = _passport_label_tokens()
    filtered: List[str] = []
    for token in tokens:
        lower = token.lower()
        if lower in SMALL_NOISE_TOKENS:
            continue
        if lower in noise_tokens and lower not in NAME_PARTICLES:
            continue
        if len(token) < 2 and lower not in NAME_PARTICLES:
            continue
        filtered.extend(_split_particles(token))
    if not filtered:
        return None
    if len(filtered) > 4:
        filtered = filtered[-4:]
    return normalize_name(" ".join(filtered))


@dataclass
class MRZResult:
    fields: Dict[str, Optional[str]]
    raw_lines: List[str]


@dataclass
class HeuristicResult:
    fields: Dict[str, Optional[str]]
    evidence: Dict[str, str]


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


def extract_mrz_lines(text: str) -> List[str]:
    lines = []
    long_lines: List[str] = []
    for raw in text.splitlines():
        line = _normalize_mrz_line(raw)
        if MRZ_LINE_RE.match(line):
            lines.append(line)
        elif len(line) >= 44:
            long_lines.append(line)
    # MRZ TD3 is two lines of 44 chars. Keep last two to bias towards bottom of page.
    if len(lines) >= 2:
        return lines[-2:]
    # Fallback: try to recover two 44-char lines from a concatenated OCR line.
    for line in reversed(long_lines):
        chunks = _extract_mrz_chunks(line)
        if chunks:
            return chunks
    # Final fallback: attempt on normalized full text (useful when OCR drops newlines).
    normalized = _normalize_mrz_line(text)
    chunks = _extract_mrz_chunks(normalized)
    if chunks:
        return chunks
    return []


def extract_mrz_from_text(text: str) -> Optional[MRZResult]:
    lines = extract_mrz_lines(text)
    if not lines:
        return None
    return parse_mrz_td3(lines)


def parse_mrz_td3(lines: List[str]) -> Optional[MRZResult]:
    if len(lines) < 2:
        return None
    line1, line2 = lines[0], lines[1]
    line1 = _best_mrz_line1(line1)
    line2 = _best_mrz_line2(line2)
    if len(line1) < 44:
        line1 = line1.ljust(44, "<")
    if len(line2) < 44:
        line2 = line2.ljust(44, "<")
    if len(line1) < 44 or len(line2) < 44:
        return None
    if len(line1) > 44:
        line1 = line1[:44]
    if len(line2) > 44:
        line2 = line2[:44]

    document_code = line1[0:2]
    issuing_country = line1[2:5].replace("<", "")
    names_raw = line1[5:44]

    passport_number = line2[0:9].replace("<", "") or None
    passport_cd = line2[9:10]
    nationality = line2[10:13].replace("<", "") or None
    dob_raw = line2[13:19]
    dob_cd = line2[19:20]
    sex = line2[20:21]
    expiry_raw = line2[21:27]
    expiry_cd = line2[27:28]

    # If the issuing country looks wrong compared to nationality, the MRZ line may be missing the country code.
    if nationality and issuing_country and issuing_country != nationality:
        pre = line1.split("<<", 1)[0]
        if pre.startswith("P<"):
            pre = pre[2:]
        if len(pre) >= 5 and not pre.startswith(nationality):
            issuing_country = nationality
            names_raw = line1[2:44]
    if nationality and (not issuing_country or len(issuing_country) < 3):
        issuing_country = nationality

    name_parts = names_raw.split("<<")
    surname = name_parts[0].replace("<", " ").strip() or None
    given_names = " ".join(name_parts[1:]).replace("<", " ").strip() or None

    checks_ok = {
        "passport_number": _valid_check_digit(line2[0:9], passport_cd),
        "date_of_birth": _valid_check_digit(dob_raw, dob_cd),
        "date_of_expiration": _valid_check_digit(expiry_raw, expiry_cd),
    }

    normalized_given = normalize_passport_name(given_names)
    normalized_surname = normalize_passport_name(surname)
    fields = {
        "given_names": normalized_given,
        "surname": normalized_surname,
        "full_name": normalize_name(" ".join([p for p in [normalized_given, normalized_surname] if p])),
        "nationality": nationality,
        "country_of_issue": issuing_country or None,
        "passport_number": passport_number,
        "date_of_birth": _normalize_mrz_date(dob_raw, field="birth"),
        "date_of_expiration": _normalize_mrz_date(expiry_raw, field="expiry"),
        "sex": normalize_sex(sex),
        "_mrz_checks": str(checks_ok),
        "_document_code": document_code,
    }
    return MRZResult(fields=fields, raw_lines=[line1, line2])


def extract_passport_heuristics(text: str) -> HeuristicResult:
    fields: Dict[str, Optional[str]] = {}
    evidence: Dict[str, str] = {}
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    def extract_from_lines(
        label_re: re.Pattern,
        value_re: Optional[re.Pattern],
        trim_stops: bool,
    ) -> Tuple[Optional[str], Optional[str]]:
        for idx, line in enumerate(lines):
            if not label_re.search(line):
                continue
            candidate = label_re.sub("", line).strip(" :-")
            if not candidate and idx + 1 < len(lines):
                candidate = lines[idx + 1].strip()
            if candidate and trim_stops:
                candidate = _trim_at_stop(candidate)
            if value_re and candidate:
                match = value_re.search(candidate)
                if match:
                    candidate = match.group(1) if match.groups() else match.group(0)
            return candidate or None, line
        return None, None

    for spec in _passport_specs():
        short_key = spec.key.split(".", 1)[1]
        if fields.get(short_key):
            continue
        patterns = _label_patterns_for(spec)
        if not patterns:
            continue
        normalizer = _normalizer_for(spec)
        value_pattern = None
        trim_stops = spec.field_type == "name"
        if spec.field_type == "sex":
            value_pattern = re.compile(r"\b([MFX])\b", re.IGNORECASE)
        elif spec.field_type == "passport_number":
            value_pattern = re.compile(r"\b[A-Z0-9]{7,9}\b")
        label_tokens = _label_token_set(spec)
        best_value: Optional[str] = None
        best_score = -1.0
        best_evidence = ""

        for pattern in patterns:
            for idx, line in enumerate(lines):
                if not pattern.search(line):
                    continue
                candidates: List[Tuple[str, bool]] = []
                same_line = pattern.sub("", line).strip(" :-")
                if same_line:
                    candidates.append((same_line, True))
                if idx + 1 < len(lines):
                    candidates.append((lines[idx + 1], False))
                for raw_value, is_same in candidates:
                    value = _trim_at_stop(raw_value) if trim_stops else raw_value
                    if value_pattern:
                        match = value_pattern.search(value)
                        if not match:
                            continue
                        value = match.group(1) if match.groups() else match.group(0)
                    if not _passport_text_value_ok(spec, value, line, is_same):
                        continue
                    if _label_like_value(spec, value):
                        continue
                    score = _score_candidate(spec, value, is_same, line, label_tokens)
                    if score <= best_score:
                        continue
                    normalized = normalizer(value) if normalizer else value
                    if not normalized:
                        continue
                    best_score = score
                    best_value = normalized
                    best_evidence = line

        if best_value is None and label_tokens:
            for idx, line in enumerate(lines):
                if not _fuzzy_label_match(label_tokens, line):
                    continue
                candidates: List[Tuple[str, bool]] = []
                if idx + 1 < len(lines):
                    candidates.append((lines[idx + 1], False))
                else:
                    candidates.append((line, True))
                for raw_value, is_same in candidates:
                    value = _trim_at_stop(raw_value) if trim_stops else raw_value
                    if value_pattern:
                        match = value_pattern.search(value)
                        if not match:
                            continue
                        value = match.group(1) if match.groups() else match.group(0)
                    if not _passport_text_value_ok(spec, value, line, is_same):
                        continue
                    if _label_like_value(spec, value):
                        continue
                    score = _score_candidate(spec, value, is_same, line, label_tokens)
                    if score <= best_score:
                        continue
                    normalized = normalizer(value) if normalizer else value
                    if not normalized:
                        continue
                    best_score = score
                    best_value = normalized
                    best_evidence = line

        if best_value is not None:
            fields[short_key] = best_value
            evidence[short_key] = best_evidence or ""

    if not fields.get("passport_number"):
        candidates: List[str] = []
        for line in lines:
            for match in re.findall(r"\b[A-Z0-9]{7,9}\b", line.upper()):
                if not re.search(r"\d", match):
                    continue
                candidates.append(match)
        if candidates:
            candidates.sort(key=lambda value: (sum(ch.isdigit() for ch in value), len(value)), reverse=True)
            fields["passport_number"] = normalize_passport_number(candidates[0])
            evidence["passport_number"] = candidates[0]

    if fields.get("given_names") or fields.get("surname"):
        fields["full_name"] = normalize_name(
            " ".join([p for p in [fields.get("given_names"), fields.get("surname")] if p])
        )
        evidence["full_name"] = evidence.get("given_names") or evidence.get("surname", "")

    if not fields.get("place_of_birth") and lines:
        place_spec = next((spec for spec in _passport_specs() if spec.key.endswith("place_of_birth")), None)
        place_label_hints: List[str] = []
        if place_spec:
            if place_spec.label:
                place_label_hints.append(place_spec.label)
            if place_spec.label_hints:
                place_label_hints.extend(place_spec.label_hints)

        def _set_place_from_line(candidate_line: str, ev_line: str) -> bool:
            if PLACE_OF_BIRTH_LABEL_RE.search(candidate_line):
                return False
            if looks_like_label_value(candidate_line, place_label_hints):
                return False
            if not _looks_like_location(candidate_line):
                return False
            normalized = normalize_name(candidate_line)
            if not normalized:
                return False
            fields["place_of_birth"] = normalized
            # Use the value line as evidence so downstream LLM checks see the actual place text.
            evidence["place_of_birth"] = candidate_line
            return True

        # Try to find a "place of birth" label line even if it is OCR-noisy.
        for idx, line in enumerate(lines):
            if re.search(r"\bbirth\b", line, re.IGNORECASE) and not re.search(r"\bdate\b", line, re.IGNORECASE):
                if idx + 1 < len(lines) and _looks_like_location(lines[idx + 1]):
                    if _set_place_from_line(lines[idx + 1], line):
                        break

        # If still missing, use the first location-like line after DOB evidence.
        if not fields.get("place_of_birth") and evidence.get("date_of_birth"):
            try:
                dob_idx = next(i for i, line in enumerate(lines) if evidence["date_of_birth"] in line)
            except StopIteration:
                dob_idx = -1
            if dob_idx >= 0:
                for line in lines[dob_idx + 1 : dob_idx + 6]:
                    if _looks_like_location(line):
                        if _set_place_from_line(line, line):
                            break

    # Fallback: pick best dates from all detected date-like strings when labels are garbled.
    missing_date_keys = [key for key in ("date_of_birth", "date_of_issue", "date_of_expiration") if not fields.get(key)]
    if missing_date_keys:
        candidates = _extract_date_candidates(lines)
        if candidates:
            today = dt.date.today()

            def date_obj(iso: str) -> Optional[dt.date]:
                try:
                    return dt.date.fromisoformat(iso)
                except ValueError:
                    return None

            def pick_by_label(label_tokens: frozenset[str], pool: Optional[List[Dict[str, object]]] = None) -> Optional[Dict[str, object]]:
                best = None
                best_score = 0.0
                for cand in pool or candidates:
                    score = 0.0
                    if _fuzzy_label_match(label_tokens, str(cand["line"])):
                        score += 1.0
                    if cand.get("prev") and _fuzzy_label_match(label_tokens, str(cand["prev"])):
                        score += 0.7
                    if score > best_score:
                        best = cand
                        best_score = score
                return best

            def remove_candidate(chosen: Dict[str, object]) -> None:
                try:
                    candidates.remove(chosen)
                except ValueError:
                    pass

            dob_tokens = _label_token_set(next(spec for spec in _passport_specs() if spec.key.endswith("date_of_birth")))
            issue_tokens = _label_token_set(next(spec for spec in _passport_specs() if spec.key.endswith("date_of_issue")))
            exp_tokens = _label_token_set(next(spec for spec in _passport_specs() if spec.key.endswith("date_of_expiration")))
            non_dob_candidates = [
                cand
                for cand in candidates
                if not _fuzzy_label_match(dob_tokens, str(cand["line"]))
                and not (cand.get("prev") and _fuzzy_label_match(dob_tokens, str(cand["prev"])))
            ]

            if "date_of_birth" in missing_date_keys and candidates:
                chosen = pick_by_label(dob_tokens)
                if not chosen:
                    past = [c for c in candidates if date_obj(str(c["iso"])) and date_obj(str(c["iso"])) <= today]
                    chosen = min(past, key=lambda c: date_obj(str(c["iso"]))) if past else None
                if chosen:
                    fields["date_of_birth"] = str(chosen["iso"])
                    evidence["date_of_birth"] = str(chosen["line"])
                    remove_candidate(chosen)

            if "date_of_expiration" in missing_date_keys and candidates:
                chosen = pick_by_label(exp_tokens, non_dob_candidates)
                if not chosen:
                    future = [
                        c
                        for c in non_dob_candidates
                        if date_obj(str(c["iso"])) and date_obj(str(c["iso"])) >= today
                    ]
                    chosen = max(future, key=lambda c: date_obj(str(c["iso"]))) if future else None
                if not chosen and non_dob_candidates:
                    chosen = max(non_dob_candidates, key=lambda c: date_obj(str(c["iso"])) or dt.date.min)
                if chosen:
                    fields["date_of_expiration"] = str(chosen["iso"])
                    evidence["date_of_expiration"] = str(chosen["line"])
                    remove_candidate(chosen)

            if "date_of_issue" in missing_date_keys and candidates:
                chosen = pick_by_label(issue_tokens, non_dob_candidates)
                if not chosen:
                    dob_obj = date_obj(fields.get("date_of_birth", "")) if fields.get("date_of_birth") else None
                    exp_obj = date_obj(fields.get("date_of_expiration", "")) if fields.get("date_of_expiration") else None
                    between = [
                        c
                        for c in non_dob_candidates
                        if date_obj(str(c["iso"]))
                        and (dob_obj is None or date_obj(str(c["iso"])) >= dob_obj)
                        and (exp_obj is None or date_obj(str(c["iso"])) <= exp_obj)
                        and date_obj(str(c["iso"])) <= today
                    ]
                    if between:
                        chosen = max(between, key=lambda c: date_obj(str(c["iso"])))
                if not chosen:
                    past = [
                        c
                        for c in non_dob_candidates
                        if date_obj(str(c["iso"])) and date_obj(str(c["iso"])) <= today
                    ]
                    if past:
                        chosen = max(past, key=lambda c: date_obj(str(c["iso"])))
                if chosen:
                    fields["date_of_issue"] = str(chosen["iso"])
                    evidence["date_of_issue"] = str(chosen["line"])
                    remove_candidate(chosen)

    # Label-anchored OCR override: pick dates near their label lines (DOB -> issue -> expiration).
    if lines:
        dob_tokens = _label_token_set(next(spec for spec in _passport_specs() if spec.key.endswith("date_of_birth")))
        issue_tokens = _label_token_set(next(spec for spec in _passport_specs() if spec.key.endswith("date_of_issue")))
        exp_tokens = _label_token_set(next(spec for spec in _passport_specs() if spec.key.endswith("date_of_expiration")))

        def _find_label_idx(tokens: frozenset[str], label_re: re.Pattern) -> Optional[int]:
            for idx, line in enumerate(lines):
                if label_re.search(line) or _fuzzy_label_match(tokens, line):
                    return idx
            return None

        def _first_date_from_idx(start_idx: Optional[int], skip_isos: set[str]) -> Optional[Tuple[str, str]]:
            if start_idx is None:
                return None
            for idx in range(start_idx, min(len(lines), start_idx + 4)):
                line = lines[idx]
                for pattern in DATE_CANDIDATE_PATTERNS:
                    for match in pattern.finditer(line):
                        normalized = _normalize_date_any(match.group(0))
                        if not normalized:
                            continue
                        if normalized in skip_isos:
                            continue
                        return normalized, line
            return None

        dob_idx = _find_label_idx(dob_tokens, DATE_OF_BIRTH_LABEL_RE)
        issue_idx = _find_label_idx(issue_tokens, DATE_OF_ISSUE_LABEL_RE)
        exp_idx = _find_label_idx(exp_tokens, DATE_OF_EXPIRATION_LABEL_RE)

        dob_iso = fields.get("date_of_birth")
        issue_iso = fields.get("date_of_issue")
        exp_iso = fields.get("date_of_expiration")

        dob_pick = _first_date_from_idx(dob_idx, set()) if dob_idx is not None else None
        if dob_pick:
            dob_val, dob_line = dob_pick
            if dob_val and dob_val != dob_iso:
                fields["date_of_birth"] = dob_val
                evidence["date_of_birth"] = dob_line
                dob_iso = dob_val

        issue_pick = _first_date_from_idx(issue_idx, {str(dob_iso or "")}) if issue_idx is not None else None
        if issue_pick:
            issue_val, issue_line = issue_pick
            if issue_val and issue_val != issue_iso:
                fields["date_of_issue"] = issue_val
                evidence["date_of_issue"] = issue_line
                issue_iso = issue_val

        exp_skip = {str(dob_iso or ""), str(issue_iso or "")}
        exp_pick = _first_date_from_idx(exp_idx, exp_skip) if exp_idx is not None else None
        if exp_pick:
            exp_val, exp_line = exp_pick
            if exp_val and exp_val != exp_iso:
                fields["date_of_expiration"] = exp_val
                evidence["date_of_expiration"] = exp_line
                exp_iso = exp_val

    # Final fallback: use document order to assign DOB -> issue -> expiration when dates are ambiguous.
    if lines:
        candidates = _extract_date_candidates(lines)
        if candidates:
            ordered = sorted(candidates, key=lambda c: (int(c.get("idx", 0)), int(c.get("pos", 0))))

            def _cand_for_iso(iso: Optional[str]) -> Optional[Dict[str, object]]:
                if not iso:
                    return None
                for cand in ordered:
                    if str(cand.get("iso")) == str(iso):
                        return cand
                return None

            def _after(ref: Dict[str, object], skip_isos: set[str]) -> Optional[Dict[str, object]]:
                ref_key = (int(ref.get("idx", 0)), int(ref.get("pos", 0)))
                for cand in ordered:
                    cand_key = (int(cand.get("idx", 0)), int(cand.get("pos", 0)))
                    if cand_key <= ref_key:
                        continue
                    iso = str(cand.get("iso") or "")
                    if iso and iso in skip_isos:
                        continue
                    return cand
                return None

            def _set_date(key: str, cand: Optional[Dict[str, object]]) -> None:
                if not cand:
                    return
                fields[key] = str(cand.get("iso"))
                evidence[key] = str(cand.get("line") or "")

            dob_iso = fields.get("date_of_birth")
            issue_iso = fields.get("date_of_issue")
            exp_iso = fields.get("date_of_expiration")
            dob_cand = _cand_for_iso(dob_iso)
            issue_cand = _cand_for_iso(issue_iso)
            exp_cand = _cand_for_iso(exp_iso)

            dob_tokens = _label_token_set(next(spec for spec in _passport_specs() if spec.key.endswith("date_of_birth")))

            def _dob_labeled(cand: Dict[str, object]) -> bool:
                return _fuzzy_label_match(dob_tokens, str(cand.get("line", ""))) or (
                    cand.get("prev") and _fuzzy_label_match(dob_tokens, str(cand.get("prev", "")))
                )

            doc_dob_cand = next((cand for cand in ordered if _dob_labeled(cand)), None) or (ordered[0] if ordered else None)
            doc_dob_iso = str(doc_dob_cand.get("iso")) if doc_dob_cand else None

            issue_label_present = any(DATE_OF_ISSUE_LABEL_RE.search(line) for line in lines)
            exp_label_present = any(DATE_OF_EXPIRATION_LABEL_RE.search(line) for line in lines)
            issue_label_ok = bool(issue_iso) and issue_label_present
            exp_label_ok = bool(exp_iso) and exp_label_present

            # If DOB is missing, use the DOB-labeled candidate (or first in order).
            if not dob_iso and doc_dob_cand:
                dob_iso = doc_dob_iso
                _set_date("date_of_birth", doc_dob_cand)

            anchor_cand = doc_dob_cand or dob_cand
            if anchor_cand:
                anchor_key = (int(anchor_cand.get("idx", 0)), int(anchor_cand.get("pos", 0)))
                issue_key = (
                    (int(issue_cand.get("idx", 0)), int(issue_cand.get("pos", 0))) if issue_cand else None
                )
                exp_key = (
                    (int(exp_cand.get("idx", 0)), int(exp_cand.get("pos", 0))) if exp_cand else None
                )

                needs_issue = (
                    not issue_iso
                    or (doc_dob_iso and issue_iso == doc_dob_iso)
                    or issue_cand is None
                    or (issue_key is not None and issue_key <= anchor_key)
                )
                if issue_label_ok:
                    needs_issue = False
                if needs_issue:
                    next_issue = _after(anchor_cand, {str(doc_dob_iso or "")})
                    if next_issue:
                        issue_cand = next_issue
                        issue_iso = str(next_issue.get("iso"))
                        _set_date("date_of_issue", next_issue)

                ref_cand = issue_cand or anchor_cand
                ref_key = (int(ref_cand.get("idx", 0)), int(ref_cand.get("pos", 0)))
                needs_exp = (
                    not exp_iso
                    or exp_iso in {str(doc_dob_iso or ""), str(issue_iso or "")}
                    or exp_cand is None
                    or (exp_key is not None and exp_key <= ref_key)
                )
                if exp_label_ok:
                    needs_exp = False
                if needs_exp:
                    next_exp = _after(ref_cand, {str(doc_dob_iso or ""), str(issue_iso or "")})
                    if next_exp:
                        _set_date("date_of_expiration", next_exp)
            elif len(ordered) >= 3:
                # No DOB anchor; fall back to first three dates in order.
                if not dob_iso:
                    _set_date("date_of_birth", ordered[0])
                    dob_iso = str(ordered[0].get("iso"))
                if not issue_iso or issue_iso == dob_iso:
                    _set_date("date_of_issue", ordered[1])
                    issue_iso = str(ordered[1].get("iso"))
                if not exp_iso or exp_iso in {dob_iso, issue_iso}:
                    _set_date("date_of_expiration", ordered[2])

    # Sanity guardrails: issue date should not equal expiration, and should be between DOB and expiration.
    if fields.get("date_of_issue"):
        issue = fields.get("date_of_issue")
        exp = fields.get("date_of_expiration")
        dob = fields.get("date_of_birth")
        try:
            issue_date = dt.date.fromisoformat(issue) if issue else None
            exp_date = dt.date.fromisoformat(exp) if exp else None
            dob_date = dt.date.fromisoformat(dob) if dob else None
        except ValueError:
            issue_date = exp_date = dob_date = None
        if issue_date and exp_date and issue_date == exp_date:
            fields.pop("date_of_issue", None)
            evidence.pop("date_of_issue", None)
        elif issue_date and exp_date and issue_date > exp_date:
            fields.pop("date_of_issue", None)
            evidence.pop("date_of_issue", None)
        elif issue_date and dob_date and issue_date < dob_date:
            fields.pop("date_of_issue", None)
            evidence.pop("date_of_issue", None)

    return HeuristicResult(fields=fields, evidence=evidence)


def extract_passport_fields(ocr_result: OCRResult) -> Dict[str, Optional[str]]:
    text = ocr_result.text
    lines = extract_mrz_lines(text)
    if lines:
        mrz = parse_mrz_td3(lines)
        if mrz:
            LOGGER.info("MRZ detected with passport number %s", mrz.fields.get("passport_number"))
            return {**mrz.fields, "_mrz_raw": "\n".join(mrz.raw_lines)}

    LOGGER.info("MRZ not found. Falling back to OCR heuristics.")
    heuristics = extract_passport_heuristics(text)
    return heuristics.fields
