from __future__ import annotations

import logging
from pathlib import Path
from typing import List

import numpy as np
from pdf2image import convert_from_path
from PIL import Image, ImageOps

LOGGER = logging.getLogger(__name__)


SUPPORTED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}


def load_document(path: Path) -> List[Image.Image]:
    """Load a PDF or image file and return a list of PIL images."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        LOGGER.info("Rendering PDF %s to images", path)
        pages = convert_from_path(str(path), dpi=300)
        return pages
    if suffix in SUPPORTED_IMAGE_EXTS:
        LOGGER.info("Loading image %s", path)
        image = Image.open(path)
        # Normalize orientation/mode so OCR sees consistent pixels.
        image = ImageOps.exif_transpose(image)
        if image.mode not in {"RGB", "L"}:
            image = image.convert("RGB")
        return [image]
    raise ValueError(f"Unsupported file type: {suffix}")


def preprocess_image(image: Image.Image) -> Image.Image:
    """Normalize image for OCR with grayscale + gentle thresholding when it helps."""
    # Preserve orientation metadata on image uploads.
    image = ImageOps.exif_transpose(image)
    gray = ImageOps.grayscale(image)
    gray = ImageOps.autocontrast(gray)
    # Resize small images for better OCR fidelity.
    if gray.width < 1000:
        scale = 1000 / gray.width
        gray = gray.resize((int(gray.width * scale), int(gray.height * scale)))
    np_img = np.array(gray)
    # Simple adaptive thresholding.
    thresh = (np_img > np.mean(np_img)).astype(np.uint8) * 255
    # If thresholding wipes most of the text, keep the grayscale image instead.
    black_ratio = float((thresh == 0).sum()) / float(thresh.size) if thresh.size else 0.0
    if black_ratio < 0.01 or black_ratio > 0.99:
        return gray
    return Image.fromarray(thresh)
