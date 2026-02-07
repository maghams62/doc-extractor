# G-28 Doc Extractor + Autofill
Upload a passport + G-28, extract structured fields with evidence, autofill the target form, and validate.

## Quickstart

### Prereqs
- Python 3.11 (repo venv is 3.11) + pip
- Node.js 18+ (Vite 5)
- Tesseract OCR and Poppler (required for OCR + PDF rendering)
- Playwright browsers (required for autofill)
- OpenAI API key if you enable translation/LLM validation/LLM extraction

### Environment
Create a `.env` file in the repo root (same level as this README).
```bash
# .env (repo root)
# Enable optional LLM features (translation/LLM validation/LLM extraction).
ENABLE_LLM=1
OPENAI_API_KEY=your_key_here

# Optional: use a non-OpenAI endpoint or override defaults.
# LLM_API_KEY=your_key_here
# LLM_ENDPOINT=https://api.openai.com/v1/chat/completions
# LLM_MODEL=gpt-4o-mini
# LLM_TIMEOUT=30

# Optional: autofill target + behavior.
# ALMA_FORM_URL=https://mendrika-alma.github.io/form-submission/
# ALMA_AUTOFILL_HEADLESS=false
# ALMA_AUTOFILL_SLOW_MO_MS=0
# ALMA_AUTOFILL_KEEP_OPEN_MS=-1
```

Optional frontend override:
```bash
# app/frontend/.env
VITE_API_BASE=http://localhost:8000
```

### Run backend
```bash
cd app/backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install
PYTHONPATH=.. uvicorn backend.main:app --reload
```

### Run frontend
```bash
cd app/frontend
npm install
npm run dev
```

### Open the app
Visit http://localhost:5173 (API defaults to http://localhost:8000).

## How it works (user flow)
1. Upload documents (passport + G-28 + supporting docs).
2. The app detects whether translation is needed.
3. If non-English, translate to English first.
4. Extract structured fields with evidence + confidence.
5. Run the pre-autofill review gate (rules + optional LLM checks).
6. Resolve blocking fields and approve the canonical snapshot.
7. Autofill the target form using canonical fields.
8. Validate filled values and review the status report table (heuristic + LLM).

## Pipeline diagram
```mermaid
flowchart TD
  A[User uploads docs] --> B{Non-English?}
  B -- Yes --> C[Translate to English]
  B -- No --> D[Extract fields]
  C --> D[Extract fields]
  D --> E["Review gate (rules + optional LLM)"]
  E --> F{Blocking issues?}
  F -- Yes --> G[Human corrections / confirm]
  F -- No --> H[Approve canonical fields]
  G --> H[Approve canonical fields]
  H --> I[Autofill form]
  I --> J["Validation report (heuristic + LLM)"]
  J --> K[Final confirmation + export]
```

## Deeper docs
- docs/README.md
- docs/architecture.md
- docs/data-models.md
- docs/extractor.md
- docs/autofill.md
- docs/validation.md
- docs/conflict-resolution.md
- docs/patterns-and-directory.md
