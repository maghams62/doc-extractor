# GAP Report

| Requirement | Current status | Evidence | Fix applied | Remaining risk |
| --- | --- | --- | --- | --- |
| PDF + image supported | PASS | `app/backend/pipeline/ingest.py:17` (PDF + image branches), `app/backend/tests/test_ingest_pdf_to_images.py`, `app/backend/tests/test_extract_endpoint_variants.py` | Added local fixture to keep tests offline (`app/backend/tests/fixtures/Example_G-28.pdf`) | Requires Poppler + Tesseract installed (`README.md:22`) |
| MRZ + OCR fallback | PASS | MRZ parse + OCR fallback in `app/backend/pipeline/passport.py:100`, validated by `app/backend/tests/test_passport_mrz_parser.py` and `app/backend/tests/test_extract_endpoint_variants.py` | None (existing logic) | OCR quality can still affect fallback accuracy |
| LLM-based validation (optional) | PASS (configurable) | `app/backend/pipeline/validate.py` + `/validate` endpoint, toggled in UI | Added LLM hook via `LLM_ENDPOINT` + UI toggle | Requires LLM endpoint + key to be configured |
| LLM extraction fallback (optional) | PASS (configurable) | `app/backend/pipeline/llm_extract.py` + `/extract` options | Added UI toggle for LLM extraction fallback | Requires LLM endpoint + key to be configured |
| Handles missing fields | PASS | Warnings for missing fields in `app/backend/main.py:92` and `app/backend/main.py:128`, checked in `app/backend/tests/test_g28_extraction_sample.py` | None (existing logic) | Warnings are surfaced, but UI does not enforce manual correction |
| Passports from various countries | PASS (TD3 MRZ) | MRZ parser reads issuing country + nationality in `app/backend/pipeline/passport.py:62` and is not hardcoded to a single country | None | Only TD3 MRZ is supported; TD1/TD2 and non-MRZ passports are not handled |
| No submit or sign | PASS | Submit guard in `app/backend/automation/fill_form.py:170` and `app/backend/tests/test_playwright_autofill_no_submit.py` | None | If the target form changes label text drastically, guard may not trigger |
| Tolerates minor formatting variations | PASS (limited) | G-28 label heuristics in `app/backend/pipeline/g28.py:16` and fuzzy label matching in `app/backend/automation/fill_form.py:101` | Added validator + LLM hook for recovery | Large layout/label changes can still reduce match quality |
| Minimal setup | PASS | Setup steps in `README.md:12` | Updated README to call out required system deps + smoke script | Requires Poppler/Tesseract/Playwright installs |
| Clear artifact outputs for reviewer | PASS | Artifacts documented in `README.md:92` and surfaced in UI `app/frontend/src/App.jsx:238` | UI now shows trace + run folder + run log paths with copy buttons | Reviewer still needs local filesystem access for artifacts |
| Local web interface | PASS | React UI upload + extract + autofill in `app/frontend/src/App.jsx:148` | Enhanced UI with confidence bars + source chips | None |

## Wow Factor Review
- Confidence as chips/bars: PASS (`app/frontend/src/App.jsx:190`, `app/frontend/src/styles.css:163`)
- Source attribution visible per field: PASS (`app/frontend/src/App.jsx:219`)
- Evidence snippet per field: PASS (`app/frontend/src/App.jsx:228`)
- Autofill summary with filled/skipped + reasons: PASS (`app/frontend/src/App.jsx:238`)
- Trace/run folder/run log paths surfaced with copy: PASS (`app/frontend/src/App.jsx:258`)
- Run log includes extraction/autofill summaries: PASS (`app/backend/main.py:156`, `app/backend/automation/fill_form.py:196`)
- Pipeline tracker + animation: PASS (`app/frontend/src/App.jsx:172`, `app/frontend/src/styles.css:127`)
- Validation report + suggestions: PASS (`app/frontend/src/App.jsx:478`, `app/backend/pipeline/validate.py`)
