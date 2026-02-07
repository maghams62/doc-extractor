from __future__ import annotations

from backend.pipeline.ingest import load_document, SUPPORTED_IMAGE_EXTS


def test_ingest_pdf_to_images(sample_g28_path) -> None:
    pages = load_document(sample_g28_path)
    assert len(pages) >= 1
    first = pages[0]
    assert first.width > 0
    assert first.height > 0


def test_supported_image_exts_include_jpg() -> None:
    assert ".jpg" in SUPPORTED_IMAGE_EXTS
    assert ".jpeg" in SUPPORTED_IMAGE_EXTS
