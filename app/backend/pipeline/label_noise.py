from __future__ import annotations

import re
from typing import Iterable, Optional


PLACEHOLDER_VALUES = {
    "n/a",
    "na",
    "none",
    "not applicable",
    "not available",
    "unknown",
    "nil",
    "-",
}

LABEL_NOISE_PHRASES = [
    "uscis online account number",
    "online account number",
    "account number",
    "receipt number",
    "alien registration number",
    "a-number",
    "if applicable",
    "if any",
    "ifapplicable",
    "ifany",
    "email address",
    "address if any",
    "street number and name",
    "street number",
    "number and name",
    "city or town",
    "zip code",
    "postal code",
    "usps zip code lookup",
    "family name",
    "given name",
    "middle name",
    "last name",
    "first name",
    "law firm name",
    "name of law firm",
    "organization name",
    "licensing authority",
    "bar number",
    "bar no",
    "daytime phone",
    "phone number",
    "mobile phone",
    "mobile number",
    "mobile telephone",
    "country",
    "state",
    "street",
    "address",
    "city",
    "town",
    "email",
    "phone",
    "telephone",
    "apt",
    "ste",
    "suite",
    "flr",
    "fir",
    "floor",
    "unit",
]

LABEL_NOISE_WORDS = {
    token
    for phrase in LABEL_NOISE_PHRASES
    for token in phrase.split()
}


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def is_placeholder_value(value: Optional[str]) -> bool:
    if not value:
        return False
    normalized = _normalize(value)
    if not normalized:
        return True
    collapsed = normalized.replace(" ", "")
    return normalized in PLACEHOLDER_VALUES or collapsed in PLACEHOLDER_VALUES


def _tokens_subset(value_tokens: Iterable[str], hint_tokens: Iterable[str]) -> bool:
    value_set = {token for token in value_tokens if token}
    hint_set = {token for token in hint_tokens if token}
    if not value_set:
        return False
    return value_set.issubset(hint_set)


def looks_like_label_value(value: Optional[str], label_hints: Optional[Iterable[str]] = None) -> bool:
    if value is None:
        return False
    raw = str(value).strip()
    if not raw:
        return True
    if is_placeholder_value(raw):
        return True
    normalized = _normalize(raw)
    if not normalized:
        return True

    if "if any" in normalized or "if applicable" in normalized:
        return True

    for phrase in LABEL_NOISE_PHRASES:
        if phrase in normalized:
            phrase_len = len(phrase.split())
            if normalized == phrase:
                return True
            if phrase_len >= 2 and len(normalized.split()) <= 4:
                return True

    if label_hints:
        for hint in label_hints:
            hint_norm = _normalize(hint)
            if not hint_norm:
                continue
            if normalized == hint_norm:
                return True
            hint_tokens = hint_norm.split()
            value_tokens = normalized.split()
            if _tokens_subset(value_tokens, hint_tokens) and len(value_tokens) <= len(hint_tokens) + 1:
                return True

    if re.fullmatch(r"[^A-Za-z0-9]+", raw):
        return True

    tokens = normalized.split()
    if tokens and len(tokens) <= 4 and all(token in LABEL_NOISE_WORDS for token in tokens):
        return True

    return False
