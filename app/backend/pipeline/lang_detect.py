from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from langdetect import DetectorFactory, LangDetectException, detect_langs


DetectorFactory.seed = 0


LANGUAGE_LABELS: Dict[str, str] = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "pt": "Portuguese",
    "it": "Italian",
    "nl": "Dutch",
    "sv": "Swedish",
    "no": "Norwegian",
    "da": "Danish",
    "fi": "Finnish",
    "pl": "Polish",
    "cs": "Czech",
    "tr": "Turkish",
    "ru": "Russian",
    "uk": "Ukrainian",
    "ar": "Arabic",
    "he": "Hebrew",
    "hi": "Hindi",
    "zh-cn": "Chinese (Simplified)",
    "zh-tw": "Chinese (Traditional)",
    "ja": "Japanese",
    "ko": "Korean",
}


@dataclass(frozen=True)
class LanguageDetectionResult:
    language: str
    confidence: float


def detect_language(text: str, max_chars: int = 4000) -> LanguageDetectionResult:
    if not text or not text.strip():
        return LanguageDetectionResult(language="unknown", confidence=0.0)
    sample = text.strip()[:max_chars]
    try:
        candidates = detect_langs(sample)
    except LangDetectException:
        return LanguageDetectionResult(language="unknown", confidence=0.0)
    if not candidates:
        return LanguageDetectionResult(language="unknown", confidence=0.0)
    top = candidates[0]
    return LanguageDetectionResult(language=top.lang, confidence=float(top.prob))


def language_name(code: str) -> str:
    if not code:
        return "Unknown"
    return LANGUAGE_LABELS.get(code.lower(), code)


def is_english(code: str, confidence: float, threshold: float) -> bool:
    return code == "en" and confidence >= threshold
