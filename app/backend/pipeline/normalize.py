from __future__ import annotations

import datetime as dt
import re
from typing import Optional

from dateutil import parser


CURRENT_YEAR = dt.date.today().year
COUNTRY_ALIASES = {
    "USA": "United States",
    "U.S.A.": "United States",
    "US": "United States",
    "U.S.": "United States",
    "UNITED STATES OF AMERICA": "United States",
    "UNITED STATES": "United States",
}


def normalize_name(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    cleaned = re.sub(r"\s+", " ", value.strip())
    return cleaned.title()


def normalize_sex(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    v = value.strip().upper()
    if v in {"M", "F", "X"}:
        return v
    return None


def normalize_phone(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"{digits[0:3]}-{digits[3:6]}-{digits[6:10]}"
    return value.strip()


def normalize_email(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return value.strip().lower()


def normalize_country(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    cleaned = re.sub(r"\s+", " ", value.strip())
    key = cleaned.upper()
    return COUNTRY_ALIASES.get(key, cleaned.title())


def normalize_full_name(given: Optional[str], middle: Optional[str], family: Optional[str]) -> Optional[str]:
    parts = [p for p in [given, middle, family] if p]
    if not parts:
        return None
    return normalize_name(" ".join(parts))


def normalize_passport_number(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return re.sub(r"\s+", "", value.strip()).upper()


def normalize_date(value: Optional[str], year_first: bool = True) -> Optional[str]:
    if not value:
        return None
    raw = value.strip()
    # MRZ YYMMDD
    if re.fullmatch(r"\d{6}", raw) and not year_first:
        year = int(raw[0:2])
        month = int(raw[2:4])
        day = int(raw[4:6])
        century = 2000 if year <= (CURRENT_YEAR % 100) else 1900
        try:
            return dt.date(century + year, month, day).isoformat()
        except ValueError:
            return None
    try:
        parsed = parser.parse(raw, dayfirst=not year_first, yearfirst=year_first)
        parsed_date = parsed.date()
        year_match = re.search(r"\b(\d{3})\b", raw)
        if year_match and parsed_date.year < 1900:
            year_raw = int(year_match.group(1))
            candidates = []
            if year_raw < 100:
                candidates.extend([2000 + year_raw, 1900 + year_raw])
            else:
                candidates.extend([year_raw * 10 + digit for digit in range(10)])
            viable = []
            for year in candidates:
                if 1900 <= year <= CURRENT_YEAR + 20:
                    try:
                        viable.append(dt.date(year, parsed_date.month, parsed_date.day))
                    except ValueError:
                        continue
            if viable:
                best = min(viable, key=lambda d: abs(d.year - CURRENT_YEAR))
                return best.isoformat()
        return parsed_date.isoformat()
    except (ValueError, OverflowError):
        return None
