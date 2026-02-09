from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

import pytesseract
from pytesseract import Output

from PIL import Image

LOGGER = logging.getLogger(__name__)


@dataclass
class OCRWord:
    text: str
    conf: float
    left: int
    top: int
    width: int
    height: int


@dataclass
class OCRResult:
    text: str
    words: List[OCRWord]


def _ocr_score(words: List[OCRWord]) -> float:
    if not words:
        return 0.0
    confs = [w.conf for w in words if w.conf > 0]
    avg_conf = sum(confs) / len(confs) if confs else 0.0
    # Favor higher confidence with a small boost for more recognized tokens.
    return avg_conf + min(len(words), 120) * 0.0025


def _run_tesseract(
    image: Image.Image, lang: Optional[str], config: Optional[str]
) -> OCRResult:
    safe_config = config or ""
    try:
        data = pytesseract.image_to_data(
            image, output_type=Output.DICT, lang=lang, config=safe_config
        )
        text = pytesseract.image_to_string(image, lang=lang, config=safe_config)
    except pytesseract.TesseractError:
        if lang:
            LOGGER.warning("OCR language %s failed; retrying default OCR.", lang)
            data = pytesseract.image_to_data(image, output_type=Output.DICT, config=safe_config)
            text = pytesseract.image_to_string(image, config=safe_config)
        else:
            raise
    words: List[OCRWord] = []
    for i, token in enumerate(data.get("text", [])):
        if not token or not token.strip():
            continue
        conf_raw = data.get("conf", ["0"])[i]
        try:
            conf = float(conf_raw) / 100.0
        except ValueError:
            conf = 0.0
        words.append(
            OCRWord(
                text=token.strip(),
                conf=conf,
                left=int(data["left"][i]),
                top=int(data["top"][i]),
                width=int(data["width"][i]),
                height=int(data["height"][i]),
            )
        )
    return OCRResult(text=text, words=words)


def ocr_image(image: Image.Image, lang: str | None = None) -> OCRResult:
    """Run OCR on a single image and return text + word boxes."""
    # Start with default settings; fall back to a few common layouts if confidence is low.
    base = _run_tesseract(image, lang, None)
    base_score = _ocr_score(base.words)
    if base_score >= 0.45 and len(base.words) >= 5:
        LOGGER.debug("OCR extracted %d words", len(base.words))
        return base

    candidates: List[Tuple[OCRResult, float]] = [(base, base_score)]
    for config in ("--psm 6", "--psm 4", "--psm 11"):
        result = _run_tesseract(image, lang, config)
        candidates.append((result, _ocr_score(result.words)))
    best = max(candidates, key=lambda item: item[1])[0]
    LOGGER.debug("OCR extracted %d words (best of %d runs)", len(best.words), len(candidates))
    return best


def ocr_mrz_text(image: Image.Image) -> str:
    """Run OCR optimized for MRZ (uppercase + digits + <)."""
    base_config = (
        "-c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789< "
        "-c load_system_dawg=0 -c load_freq_dawg=0"
    )
    configs = [f"--psm 6 {base_config}", f"--psm 7 {base_config}"]

    def score(text: str) -> int:
        normalized = re.sub(r"[^A-Z0-9<\n]+", "", text.upper())
        candidates = re.findall(r"[A-Z0-9<]{30,}", normalized.replace("\n", ""))
        if not candidates:
            return 0
        return max(len(c) for c in candidates) + len(candidates) * 5

    best_text = ""
    best_score = -1
    for config in configs:
        text = pytesseract.image_to_string(image, config=config)
        text_score = score(text)
        if text_score > best_score:
            best_text = text
            best_score = text_score
    return best_text
