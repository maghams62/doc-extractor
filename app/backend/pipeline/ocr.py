from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List

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


def ocr_image(image: Image.Image, lang: str | None = None) -> OCRResult:
    """Run OCR on a single image and return text + word boxes."""
    try:
        data = pytesseract.image_to_data(image, output_type=Output.DICT, lang=lang)
    except pytesseract.TesseractError:
        if lang:
            LOGGER.warning("OCR language %s failed; retrying default OCR.", lang)
            data = pytesseract.image_to_data(image, output_type=Output.DICT)
        else:
            raise
    words: List[OCRWord] = []
    for i, text in enumerate(data.get("text", [])):
        if not text or not text.strip():
            continue
        conf_raw = data.get("conf", ["0"])[i]
        try:
            conf = float(conf_raw) / 100.0
        except ValueError:
            conf = 0.0
        words.append(
            OCRWord(
                text=text.strip(),
                conf=conf,
                left=int(data["left"][i]),
                top=int(data["top"][i]),
                width=int(data["width"][i]),
                height=int(data["height"][i]),
            )
        )
    try:
        text = pytesseract.image_to_string(image, lang=lang)
    except pytesseract.TesseractError:
        if lang:
            text = pytesseract.image_to_string(image)
        else:
            raise
    LOGGER.debug("OCR extracted %d words", len(words))
    return OCRResult(text=text, words=words)


def ocr_mrz_text(image: Image.Image) -> str:
    """Run OCR optimized for MRZ (uppercase + digits + <)."""
    config = "--psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<"
    return pytesseract.image_to_string(image, config=config)
