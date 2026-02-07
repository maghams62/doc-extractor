# E2E pipeline hardening (Feb 2026)

## What was broken
- Autofill “success” was inferred from planned attempts; DOM readback wasn’t authoritative for all input types.
- Post-autofill validation invoked the LLM on every field, including green fields.
- Suggestions could appear without clear evidence or conflict context.
- There was no single per-run artifact proving coverage for every field.

## What changed
- Added `e2e_coverage_report.json` per run and a reusable coverage builder.
- Autofill now records per-field attempts, selector used, DOM readback, PASS/FAIL/SKIP, and failure reason codes.
- DOM readback handles text, textarea, select, radio, and date inputs with normalization.
- Post-autofill validation runs deterministic checks for every field, gates LLM calls, and emits human-in-loop reasons/categories.
- Suggestion policy tightened: evidence-grounded only; “merge” only on explicit conflict.
- New backend script for a golden-path fixture run with optional smoke mode.
- E2E Playwright tests now assert coverage + readback for canonical fixtures.

## How to run the E2E test locally
1. Start backend and frontend (same as current E2E setup).
2. Run Playwright E2E:
   - `cd app/e2e/playwright`
   - `npx playwright test e2e_golden_path.spec.ts`
3. Optional golden-path script (fixtures + optional smoke):
   - `python app/backend/scripts/run_e2e_coverage.py --passport app/backend/tests/fixtures/synthetic_passport_mrz_realistic.png --g28 app/backend/tests/fixtures/Example_G-28.pdf`
   - Add `--smoke` to also hit the configured real form URL.

## Known limitations
- Translation validation and evidence normalization are still limited to English.
- Real-form smoke runs can still fail if the live form changes its DOM structure.
