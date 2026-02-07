# QA Report

## Orientation & diagnosis (current pipeline)
- `ingest.py` renders PDFs/images into PIL images and applies basic grayscale + thresholding for OCR.
- `ocr.py` uses Tesseract to produce full text plus word boxes.
- `passport.py` detects MRZ lines; if found, parses TD3 into normalized fields; otherwise runs label-based heuristics.
- `g28.py` scans OCR text for label/value pairs and applies normalization; captures label presence for missing-vs-absent classification.
- `confidence.py` sets source-based baselines, adds value-quality boosts, and stores sources/confidence/evidence in meta.
- `normalize.py` standardizes names, dates, phones, emails, countries, and derives full names from parts.
- `llm_extract.py` (optional, gated by `ENABLE_LLM=1`) fills only missing fields in canonical schema.
- `validate.py` runs typed validation, adjusts confidence/status, detects conflicts, and attaches suggestions.
- `main.py` orchestrates tiered extraction, logs warnings, and exposes `/extract`, `/validate`, `/autofill`, `/run_all`.
- `App.jsx` flattens canonical schema, shows per-field status/confidence, and applies suggestions.

## Root causes of the “attorney name everywhere” issue
1. **Naive label parsing in G‑28 OCR**: the old `_find_value_after_label` routinely captured label fragments (e.g., “(Last Name)”) when OCR split labels across lines. This produced label text instead of actual values.
2. **Non‑canonical schema**: the earlier flat `g28.attorney_*` schema had no dedicated client namespace, causing unrelated fields to be presented as attorney values in the UI.
3. **No label‑presence checks**: missing fields were treated as extracted/valid without distinguishing true absence vs extraction failure.

## Key changes implemented
- Introduced canonical schema with nested `g28.attorney` and `g28.client`, and expanded meta (`sources`, `confidence`, `status`, `suggestions`, `warnings`).
- Added normalization helpers (emails, countries, passport numbers, full-name derivation) and applied them consistently.
- Implemented tiered extraction:
  - Passport: MRZ → OCR heuristics → optional LLM fill for missing fields.
  - G‑28: OCR heuristics → optional LLM fill → label‑presence classification for missing vs absent.
- Replaced fake confidence with source baselines + validation‑based adjustments and conflict downgrades.
- Added validation workflow that sets traffic‑light statuses and suggestion lists, with optional LLM validation.
- Updated UI to display traffic‑light status chips and apply single/bulk suggestions.
- Added synthetic fixtures for edge cases and expanded backend + UI tests.

## How to run tests
Backend:
```bash
cd app/backend
PYTHONPATH=.. pytest -q
```
Frontend (Playwright):
```bash
cd app/frontend
npm install
npx playwright install
npm test
```

## Test cases implemented
- `test_schema_shape.py`
  - Canonical schema keys + meta structure present; confidence bounds enforced.
- `test_canonical_keys.py`
  - Ensures no legacy flat attorney keys at the top level of `g28`.
- `test_validation_status.py`
  - Missing-vs-absent classification, confidence caps, MRZ green confidence, USER override.
- `test_synthetic_fixtures.py`
  - Synthetic passport/G‑28 fixtures exercise OCR and missing‑warning behavior.
- `test_extract_endpoint_variants.py`
  - `/extract` for passport-only, g28-only, both; validates schema + MRZ warnings.
- `test_validate_endpoint.py`
  - `/validate` returns updated result + suggestions for missing required fields.
- `test_playwright_autofill_no_submit.py`, `test_playwright_fill.py`, `test_repeatability.py`
  - End‑to‑end autofill behaviors and repeatability.
- `app/frontend/tests/ui.spec.js`
  - Validate workflow shows suggestions and applies them in the UI.

## Results
- Backend: `pytest -q` → **20 passed**
- Frontend: `npm test` → **1 passed**

## Known limitations / next improvements
- OCR quality still drives extraction accuracy; more robust layout-aware parsing would reduce misses.
- Playwright browser downloads are required for UI tests in new environments.
- LLM validation/extraction is gated by `ENABLE_LLM=1` and requires keys; current prompts are conservative by design.
