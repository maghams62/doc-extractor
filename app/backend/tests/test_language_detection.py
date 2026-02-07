from backend.pipeline.lang_detect import detect_language


def test_language_detection_english() -> None:
    text = (
        "This is a sample English document used to verify language detection. "
        "It contains multiple sentences and should be detected as English. "
        "The quick brown fox jumps over the lazy dog. "
        "Please ensure the detector returns English."
    )
    result = detect_language(text)
    assert result.language == "en"
    assert result.confidence > 0.5


def test_language_detection_non_english() -> None:
    text = (
        "Este documento está escrito en español y contiene varias oraciones. "
        "El objetivo es verificar que el detector no lo clasifique como inglés. "
        "La traducción automática debe funcionar correctamente."
    )
    result = detect_language(text)
    assert result.language != "en"
    assert result.confidence > 0.3
