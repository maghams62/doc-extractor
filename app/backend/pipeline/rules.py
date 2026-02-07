from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Iterable, List, Optional

from dateutil import parser

from .label_noise import is_placeholder_value, looks_like_label_value
from .normalize import (
    normalize_country,
    normalize_date,
    normalize_email,
    normalize_name,
    normalize_passport_number,
    normalize_phone,
    normalize_sex,
)


RE_EMAIL = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.IGNORECASE)
RE_PASSPORT = re.compile(r"^[A-Z0-9]{7,9}$")
RE_ZIP_US = re.compile(r"^\d{5}(-\d{4})?$")
RE_POSTAL_GENERIC = re.compile(r"^[A-Za-z0-9 -]{3,10}$")

US_STATES = {
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "LA",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NJ",
    "NM",
    "NY",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "WA",
    "WV",
    "WI",
    "WY",
}

HEADER_TOKENS = [
    "form g-28",
    "notice of entry of appearance",
    "department of homeland security",
    "u.s. citizenship and immigration services",
    "uscis",
    "dhs",
    "attorney or accredited representative",
]


@dataclass
class RuleResult:
    is_valid: bool
    reasons: List[str]
    normalized: Optional[str] = None
    confidence_delta: float = 0.0


def _normalize_label_hint(pattern: str) -> str:
    cleaned = pattern.replace("\\s", " ")
    cleaned = re.sub(r"[\\^$.|?*+()\\[\\]{}]", " ", cleaned)
    cleaned = cleaned.replace("_", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip().lower()


def looks_like_label_or_header(value: str, label_hints: Optional[Iterable[str]] = None) -> bool:
    if looks_like_label_value(value, label_hints):
        return True
    lowered = value.lower()
    return any(token in lowered for token in HEADER_TOKENS)


def _alpha_ratio(value: str) -> float:
    letters = sum(1 for ch in value if ch.isalpha())
    total = sum(1 for ch in value if ch.isalnum())
    if total == 0:
        return 0.0
    return letters / total


def _parse_date(value: str) -> Optional[date]:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def validate_name(value: str, label_hints: Optional[Iterable[str]] = None) -> RuleResult:
    if looks_like_label_or_header(value, label_hints):
        return RuleResult(False, ["label_noise"], None, -0.3)
    if re.fullmatch(r"[^A-Za-z0-9]+", value):
        return RuleResult(False, ["name_length"], None, -0.3)
    if re.search(r"\d", value):
        return RuleResult(False, ["name_numeric"], None, -0.2)
    if len(value.strip()) < 2:
        return RuleResult(False, ["name_length"], None, -0.2)
    if len(value.split()) > 6:
        return RuleResult(False, ["name_word_count"], None, -0.1)
    if _alpha_ratio(value) < 0.5:
        return RuleResult(False, ["name_format"], None, -0.2)
    normalized = normalize_name(value)
    if normalized and normalized != value:
        return RuleResult(True, ["name_normalize"], normalized, 0.05)
    return RuleResult(True, ["name_ok"], None, 0.0)


def validate_email(value: str, label_hints: Optional[Iterable[str]] = None) -> RuleResult:
    if looks_like_label_or_header(value, label_hints):
        return RuleResult(False, ["email_label"], None, -0.3)
    cleaned = re.sub(r"\s+", "", value)
    normalized = normalize_email(cleaned)
    if normalized and RE_EMAIL.match(normalized):
        if normalized != value:
            return RuleResult(True, ["email_normalize"], normalized, 0.05)
        return RuleResult(True, ["email_ok"], None, 0.0)
    return RuleResult(False, ["email_format"], None, -0.2)


def validate_phone(value: str, label_hints: Optional[Iterable[str]] = None) -> RuleResult:
    if looks_like_label_or_header(value, label_hints):
        return RuleResult(False, ["phone_label"], None, -0.3)
    digits = re.sub(r"\D", "", value)
    if len(digits) < 7 or len(digits) > 15:
        normalized = normalize_phone(value)
        return RuleResult(False, ["phone_format"], normalized if normalized != value else None, -0.2)
    normalized = normalize_phone(value)
    if normalized and normalized != value:
        return RuleResult(True, ["phone_normalize"], normalized, 0.05)
    return RuleResult(True, ["phone_ok"], None, 0.0)


def validate_passport_number(value: str) -> RuleResult:
    normalized = normalize_passport_number(value)
    if not normalized or not RE_PASSPORT.match(normalized):
        return RuleResult(False, ["passport_format"], normalized, -0.2)
    if normalized != value:
        return RuleResult(True, ["passport_normalize"], normalized, 0.05)
    return RuleResult(True, ["passport_ok"], None, 0.0)


def validate_sex(value: str) -> RuleResult:
    normalized = normalize_sex(value)
    if not normalized:
        return RuleResult(False, ["sex_value"], None, -0.2)
    if normalized != value:
        return RuleResult(True, ["sex_normalize"], normalized, 0.05)
    return RuleResult(True, ["sex_ok"], None, 0.0)


def validate_state(value: str) -> RuleResult:
    raw = value.strip().upper()
    if re.search(r"\d", raw) or len(raw) < 2:
        return RuleResult(False, ["state_format"], None, -0.2)
    if len(raw) == 2:
        return RuleResult(True, ["state_ok"], raw if raw != value else None, 0.0)
    if len(raw) <= 30 and raw.isalpha():
        return RuleResult(True, ["state_non_standard"], normalize_name(value), -0.1)
    return RuleResult(False, ["state_format"], None, -0.2)


def validate_zip(value: str, country: Optional[str] = None) -> RuleResult:
    raw = value.strip()
    if RE_ZIP_US.match(raw):
        return RuleResult(True, ["zip_ok"], None, 0.0)
    if country and country.strip().lower() not in {"united states", "usa", "us"}:
        if RE_POSTAL_GENERIC.match(raw):
            return RuleResult(True, ["postal_ok"], None, -0.1)
    return RuleResult(False, ["zip_format"], None, -0.2)


def validate_date(value: str, field_type: str) -> RuleResult:
    parsed = _parse_date(value)
    normalized = None
    if not parsed:
        normalized = normalize_date(value)
        if normalized:
            parsed = _parse_date(normalized)
    if not parsed:
        return RuleResult(False, ["date_format"], normalized, -0.2)
    today = date.today()
    if field_type == "date_past" and parsed > today:
        return RuleResult(False, ["date_future"], normalized or value, -0.2)
    if field_type == "date_future" and parsed < today:
        return RuleResult(False, ["date_past"], normalized or value, -0.2)
    if normalized and normalized != value:
        return RuleResult(True, ["date_normalize"], normalized, 0.05)
    return RuleResult(True, ["date_ok"], None, 0.0)


def validate_address_street(value: str, label_hints: Optional[Iterable[str]] = None) -> RuleResult:
    if looks_like_label_or_header(value, label_hints):
        return RuleResult(False, ["address_label"], None, -0.3)
    if not re.search(r"\d", value) or not re.search(r"[A-Za-z]{2,}", value):
        return RuleResult(False, ["address_street_format"], None, -0.2)
    return RuleResult(True, ["address_street_ok"], None, 0.0)


def validate_address_unit(value: str, label_hints: Optional[Iterable[str]] = None, allow_placeholder: bool = False) -> RuleResult:
    if allow_placeholder and is_placeholder_value(value):
        return RuleResult(True, ["unit_placeholder"], value.strip(), -0.05)
    if looks_like_label_or_header(value, label_hints):
        return RuleResult(False, ["address_label"], None, -0.3)
    if re.search(r"\b(apt|ste|suite|flr|floor|unit|#)\b", value, re.IGNORECASE):
        return RuleResult(True, ["address_unit_ok"], None, 0.0)
    if re.search(r"\d", value):
        return RuleResult(True, ["address_unit_ok"], None, 0.0)
    return RuleResult(False, ["address_unit_format"], None, -0.1)


def validate_address_city(value: str, label_hints: Optional[Iterable[str]] = None) -> RuleResult:
    if looks_like_label_or_header(value, label_hints):
        return RuleResult(False, ["address_label"], None, -0.3)
    if re.search(r"\d", value) or not re.search(r"[A-Za-z]{2,}", value):
        return RuleResult(False, ["address_city_format"], None, -0.2)
    return RuleResult(True, ["address_city_ok"], None, 0.0)


def validate_address_country(value: str, label_hints: Optional[Iterable[str]] = None) -> RuleResult:
    if looks_like_label_or_header(value, label_hints):
        return RuleResult(False, ["address_label"], None, -0.3)
    if re.search(r"\d", value) or not re.search(r"[A-Za-z]{2,}", value):
        return RuleResult(False, ["address_country_format"], None, -0.2)
    normalized = normalize_country(value)
    if normalized and normalized != value:
        return RuleResult(True, ["country_normalize"], normalized, 0.05)
    return RuleResult(True, ["address_country_ok"], None, 0.0)


def validate_online_account_number(value: str, label_hints: Optional[Iterable[str]] = None) -> RuleResult:
    if looks_like_label_or_header(value, label_hints):
        return RuleResult(False, ["label_noise"], None, -0.3)
    raw = value.strip()
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return RuleResult(False, ["account_number_missing_digits"], None, -0.2)
    if re.search(r"[A-Za-z]", raw):
        return RuleResult(True, ["account_number_unverified"], None, -0.1)
    if len(digits) < 8 or len(digits) > 15:
        return RuleResult(True, ["account_number_unverified"], None, -0.1)
    if digits != raw:
        return RuleResult(True, ["account_number_normalize"], digits, 0.02)
    return RuleResult(True, ["account_number_ok"], None, 0.0)


def validate_field(
    path: str,
    field_type: str,
    value: str,
    label_hints: Optional[Iterable[str]] = None,
    context: Optional[dict] = None,
    allow_placeholder: bool = False,
) -> RuleResult:
    if value is None:
        return RuleResult(False, ["empty"], None, -0.2)
    value = str(value).strip()
    if not value:
        return RuleResult(False, ["empty"], None, -0.2)
    if path.endswith("address.street"):
        return validate_address_street(value, label_hints)
    if path.endswith("address.unit"):
        return validate_address_unit(value, label_hints, allow_placeholder=allow_placeholder)
    if path.endswith("address.city"):
        return validate_address_city(value, label_hints)
    if path.endswith("address.state"):
        return validate_state(value)
    if path.endswith("address.zip"):
        country = None
        if context:
            country = context.get("country")
        return validate_zip(value, country=country)
    if path.endswith("address.country"):
        return validate_address_country(value, label_hints)
    if path.endswith("online_account_number"):
        return validate_online_account_number(value, label_hints)
    if field_type == "name":
        return validate_name(value, label_hints)
    if field_type == "email":
        return validate_email(value, label_hints)
    if field_type == "phone":
        return validate_phone(value, label_hints)
    if field_type == "passport_number":
        return validate_passport_number(value)
    if field_type == "sex":
        return validate_sex(value)
    if field_type in {"date_past", "date_future"}:
        return validate_date(value, field_type)
    if field_type == "zip":
        return validate_zip(value, country=(context or {}).get("country"))
    if field_type == "state":
        return validate_state(value)
    if looks_like_label_or_header(value, label_hints):
        return RuleResult(False, ["label_noise"], None, -0.3)
    return RuleResult(True, ["text_ok"], None, 0.0)
