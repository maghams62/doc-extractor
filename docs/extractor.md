# Extractor pipeline

```mermaid
flowchart TD
  A[Upload] --> B[Preprocess + OCR]
  B --> C[Language detect]
  C --> D{Translate?}
  D -- Yes --> E[LLM translation]
  D -- No --> F[Extract fields]
  E --> F[Extract fields]
  F --> G[Rule checks (all fields)]
  G --> H[LLM checks (flagged only)]
  H --> I[Review gate + canonical fields]
  I --> J[ExtractionResult]
```

## Key ideas / patterns
- Evidence-backed extraction: every field can carry evidence text in `meta.evidence`.
- Confidence scoring: MRZ > OCR > LLM (see base scores in `confidence.py`).
- Rejects pattern: label noise + placeholder values are rejected or downgraded.
- Human-in-the-loop gates: conflicts, low confidence, or missing required fields set `requires_human_input`.
- Two-tier checks: rules run on all fields; LLM checks only on flagged fields.
- Canonical fields: user-approved snapshot before autofill.

## Where in code
- Ingestion + OCR: `app/backend/pipeline/ingest.py`, `app/backend/pipeline/ocr.py`
- Passport parsing + MRZ: `app/backend/pipeline/passport.py`
- G-28 extraction: `app/backend/pipeline/g28.py`
- Language detection + translation: `app/backend/pipeline/lang_detect.py`, `app/backend/pipeline/translate.py`
- Confidence/evidence tracking: `app/backend/pipeline/confidence.py`
- Label noise + rejects: `app/backend/pipeline/label_noise.py`
- Orchestration endpoint: `app/backend/main.py` (`/extract`)

## Failure modes
- OCR noise from low-contrast scans or skewed pages.
- Partial scans missing the MRZ block or key G-28 fields.
- Wrong doc type uploaded (e.g., a non-G-28 form).
- Translation drift when structure is not preserved.

## Testing
- Backend tests: `app/backend/tests/`
- Sample fixture PDFs: `app/backend/tests/fixtures/`
- Run: `cd app/backend && PYTHONPATH=.. pytest -q`

## JSON example
```json
{
  "passport": { "given_names": "ANA", "surname": "GARCIA" },
  "g28": { "attorney": { "family_name": "LEE" } },
  "meta": {
    "sources": { "passport.surname": "MRZ" },
    "confidence": { "passport.surname": 0.95 },
    "evidence": { "passport.surname": "MRZ: GARCIA" },
    "warnings": []
  }
}
```
