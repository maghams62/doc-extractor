from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .ocr import OCRResult
from .normalize import normalize_date, normalize_passport_number, normalize_sex, normalize_name

LOGGER = logging.getLogger(__name__)


MRZ_LINE_RE = re.compile(r"^[A-Z0-9<]{30,44}$")


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
    for raw in text.splitlines():
        line = _normalize_mrz_line(raw)
        if MRZ_LINE_RE.match(line):
            lines.append(line)
    # MRZ TD3 is two lines of 44 chars. Keep last two to bias towards bottom of page.
    if len(lines) >= 2:
        return lines[-2:]
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
    name_parts = names_raw.split("<<")
    surname = name_parts[0].replace("<", " ").strip() or None
    given_names = " ".join(name_parts[1:]).replace("<", " ").strip() or None

    passport_number = line2[0:9].replace("<", "") or None
    passport_cd = line2[9:10]
    nationality = line2[10:13].replace("<", "") or None
    dob_raw = line2[13:19]
    dob_cd = line2[19:20]
    sex = line2[20:21]
    expiry_raw = line2[21:27]
    expiry_cd = line2[27:28]

    checks_ok = {
        "passport_number": _valid_check_digit(line2[0:9], passport_cd),
        "date_of_birth": _valid_check_digit(dob_raw, dob_cd),
        "date_of_expiration": _valid_check_digit(expiry_raw, expiry_cd),
    }

    fields = {
        "given_names": normalize_name(given_names),
        "surname": normalize_name(surname),
        "full_name": normalize_name(" ".join([p for p in [given_names, surname] if p])),
        "nationality": nationality,
        "country_of_issue": issuing_country or None,
        "passport_number": passport_number,
        "date_of_birth": normalize_date(dob_raw, year_first=False),
        "date_of_expiration": normalize_date(expiry_raw, year_first=False),
        "sex": normalize_sex(sex),
        "_mrz_checks": str(checks_ok),
        "_document_code": document_code,
    }
    return MRZResult(fields=fields, raw_lines=[line1, line2])


def extract_passport_heuristics(text: str) -> HeuristicResult:
    fields: Dict[str, Optional[str]] = {}
    evidence: Dict[str, str] = {}

    def capture(pattern: str, key: str, normalizer=None) -> None:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            return
        raw = match.group(2) if match.lastindex and match.lastindex >= 2 else match.group(1)
        value = raw.strip() if raw else None
        if normalizer:
            value = normalizer(value)
        if value:
            fields[key] = value
            evidence[key] = match.group(0)

    # Passport number heuristic.
    passport_match = re.search(r"\b([A-Z0-9]{7,9})\b", text)
    if passport_match:
        fields["passport_number"] = normalize_passport_number(passport_match.group(1))
        evidence["passport_number"] = passport_match.group(0)

    capture(r"(Date of Birth|DOB)\s*[:\-]?\s*([0-9A-Z/\-]{6,10})", "date_of_birth", normalize_date)
    capture(r"(Expiry|Expiration|Date of Expiry)\s*[:\-]?\s*([0-9A-Z/\-]{6,10})", "date_of_expiration", normalize_date)
    capture(r"Nationality\s*[:\-]?\s*([A-Z]{3})", "nationality", lambda v: v.upper() if v else v)
    capture(r"(Surname|Last Name)\s*[:\-]?\s*(.+)", "surname", normalize_name)
    capture(r"(Given Names|First Name)\s*[:\-]?\s*(.+)", "given_names", normalize_name)

    if fields.get("given_names") or fields.get("surname"):
        fields["full_name"] = normalize_name(
            " ".join([p for p in [fields.get("given_names"), fields.get("surname")] if p])
        )
        evidence["full_name"] = evidence.get("given_names") or evidence.get("surname", "")

    sex_match = re.search(r"\bSex\s*[:\-]?\s*([MFxX])\b", text)
    if sex_match:
        fields["sex"] = normalize_sex(sex_match.group(1))
        evidence["sex"] = sex_match.group(0)

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
