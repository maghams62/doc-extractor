# System architecture

```mermaid
flowchart TD
  A[Ingestion] --> B[Preprocess + OCR]
  B --> C[Language detect]
  C --> D{Translate?}
  D -- Yes --> E[LLM translation]
  D -- No --> F[Extraction]
  E --> F[Extraction]
  F --> G[Review gate (rules + optional LLM)]
  G --> H[Canonical snapshot approval]
  H --> I[Autofill]
  I --> J[Validation report (heuristic + LLM)]
  J --> K[Output artifacts]
```

## Components
- Frontend UI: upload, review, and trigger actions.
- Backend API: orchestrates pipeline stages and writes artifacts.
- Extractor modules: OCR, MRZ parsing, G-28 heuristics, confidence scoring.
- Autofill module: Playwright-driven form discovery and filling.
- Validation module: deterministic rules + optional LLM checks.
- Review gate: pre-autofill rules + optional LLM checks; produces canonical fields.
- Storage: per-run artifacts in `app/backend/runs/<run_id>/` (inputs, JSON outputs, traces).

## Execution modes
- Happy path: English docs + strong confidence -> extract -> autofill -> validate -> done.
- Review path: low confidence/conflicts/missing fields -> human edits -> canonical approval -> autofill -> validate -> done.

## Where in code
- API endpoints and run orchestration: `app/backend/main.py`
- Review gate + canonical approval: `app/backend/main.py` (`/review`, `/approve_canonical`)
- Extraction and translation pipeline: `app/backend/pipeline/`
- Autofill automation and trace capture: `app/backend/automation/fill_form.py`
- Frontend UI flow: `app/frontend/src/App.jsx`

## JSON example
```json
{
  "run_id": "20260206_203720_ca734637",
  "extraction": { "passport": { "passport_number": "X1234567" } },
  "autofill": { "filled_fields": ["passport.passport_number"] },
  "post_autofill_validation": { "ok": true, "issues": [] },
  "summary": { "green": 12, "amber": 2, "red": 0 }
}
```
