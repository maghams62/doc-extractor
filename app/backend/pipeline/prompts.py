from __future__ import annotations

import json
from typing import Dict, List


FIELD_VALIDATION_PROMPT = """
You are a strict field validator for passport + USCIS G-28 data.
Goal: provide concise proof that autofill is correct. Return JSON only. Do not wrap in markdown.

Return this exact shape:
{
  "results": [
    {
      "field": "g28.attorney.email",
      "verdict": "GREEN|AMBER|RED",
      "score": 0.0-1.0,
      "reason": "short, rule-based explanation tied to evidence",
      "suggested_value": null OR "string",
      "suggested_value_reason": "why this suggestion (cite evidence or normalization)",
      "evidence": "verbatim snippet from provided evidence OR 'not found'",
      "requires_human_input": true/false
    }
  ]
}

Inputs include deterministic_status + deterministic_reason_codes. Treat deterministic rules as authoritative.
Each field may include human_required and human_required_reason; when human_required is true, do not try to validate
or suggest a value.

Rules:
- Never invent personal data.
- Only suggest values explicitly present in evidence, or trivial normalization of it
  (e.g., remove spaces around "@", normalize phone punctuation).
- Only suggest a different value when the evidence clearly shows the correct value
  (label-capture fixes) or when resolving an explicit conflict between sources.
- Do not propose merge values unless a conflict between credible sources is explicit.
- If evidence does not contain a value, set suggested_value = null,
  evidence = "not found", requires_human_input = true.
- If human_required is true, set verdict = AMBER, requires_human_input = true,
  suggested_value = null, and reason should mention the human_required_reason.
- When suggesting a value, suggested_value_reason MUST reference the evidence snippet or
  describe the exact normalization performed.
- If extracted_value is label/placeholder (e.g., "City or Town", "Email Address (if any)"),
  verdict MUST be RED and suggested_value should be null unless evidence shows the real value.
- If deterministic_status is RED, verdict must be RED or AMBER (never GREEN).
- If deterministic_status is GREEN, verdict can be GREEN or AMBER only (downgrade is rare).
- If deterministic_status is GREEN, suggested_value must be null unless verdict is AMBER.
- If deterministic_status indicates optional empty + presence absent, verdict should be GREEN.
- Prefer citing deterministic_reason_codes in the reason when they explain the verdict.
- Keep reasons short and grounded in evidence; no extra commentary.

Score rubric:
- 0.90-1.00: clear evidence + correct format.
- 0.60-0.89: evidence present, needs normalization.
- 0.30-0.59: ambiguous or partial evidence.
- 0.00-0.29: missing, label capture, or contradictory.

Examples:
Input field:
  field: passport.date_of_birth
  extracted_value: "1870-01-01"
  deterministic_status: "red"
  deterministic_reason_codes: ["date_past", "age_out_of_range"]
  evidence: "Date of Birth: 1870-01-01"
Output:
  {{"field":"passport.date_of_birth","verdict":"RED","score":0.08,
    "reason":"DOB implies age >150 years; likely incorrect",
    "suggested_value":null,
    "suggested_value_reason":"No reliable alternative in evidence",
    "evidence":"Date of Birth: 1870-01-01","requires_human_input":true}}

Input field:
  field: passport.date_of_birth
  extracted_value: "01/02/03"
  deterministic_status: "amber"
  deterministic_reason_codes: ["date_format_ambiguous"]
  evidence: "DOB 01/02/03"
Output:
  {{"field":"passport.date_of_birth","verdict":"AMBER","score":0.45,
    "reason":"Ambiguous date format; clarify day/month order",
    "suggested_value":null,
    "suggested_value_reason":"Ambiguous; needs confirmation",
    "evidence":"DOB 01/02/03","requires_human_input":true}}

Input field:
  field: g28.attorney.email
  extracted_value: "immigration @tryalma.ai"
  deterministic_status: "amber"
  deterministic_reason_codes: ["email_normalize"]
  evidence: "Email Address (if any) immigration @tryalma.ai"
Output:
  {{"field":"g28.attorney.email","verdict":"GREEN","score":0.92,
    "reason":"Email found with extra spaces; normalize formatting",
    "suggested_value":"immigration@tryalma.ai",
    "suggested_value_reason":"Remove spaces around @",
    "evidence":"immigration @tryalma.ai","requires_human_input":false}}

Input field:
  field: g28.attorney.address.state
  extracted_value: "94301"
  deterministic_status: "red"
  deterministic_reason_codes: ["state_format", "zip_state_swap"]
  evidence: "State | CA 3.e. ZIP Code | 94301"
Output:
  {{"field":"g28.attorney.address.state","verdict":"RED","score":0.30,
    "reason":"State/ZIP appear swapped; state should be CA",
    "suggested_value":"CA",
    "suggested_value_reason":"Evidence shows State | CA",
    "evidence":"State | CA 3.e. ZIP Code | 94301","requires_human_input":false}}

Input field:
  field: g28.attorney.address.city
  extracted_value: "City or Town"
  deterministic_status: "red"
  deterministic_reason_codes: ["label_noise"]
  evidence: "City or Town | Perth"
Output:
  {{"field":"g28.attorney.address.city","verdict":"RED","score":0.20,
    "reason":"Value is a label, not a city",
    "suggested_value":"Perth",
    "suggested_value_reason":"Evidence shows the city after the label",
    "evidence":"City or Town | Perth","requires_human_input":false}}

Input field:
  field: g28.attorney.phone_daytime
  extracted_value: "555-12AB"
  deterministic_status: "red"
  deterministic_reason_codes: ["phone_format"]
  evidence: "Daytime Phone: 555-12AB"
Output:
  {{"field":"g28.attorney.phone_daytime","verdict":"RED","score":0.15,
    "reason":"Phone number contains letters and is too short",
    "suggested_value":null,
    "suggested_value_reason":"No valid phone number in evidence",
    "evidence":"Daytime Phone: 555-12AB","requires_human_input":true}}

Input field:
  field: g28.attorney.bar_number
  extracted_value: "if applicable"
  deterministic_status: "red"
  deterministic_reason_codes: ["bar_number_label"]
  evidence: "Bar Number (if applicable)"
Output:
  {{"field":"g28.attorney.bar_number","verdict":"RED","score":0.10,
    "reason":"Value is label/placeholder text, not a bar number",
    "suggested_value":null,
    "suggested_value_reason":"No bar number in evidence",
    "evidence":"Bar Number (if applicable)","requires_human_input":true}}

Input field:
  field: g28.attorney.licensing_authority
  extracted_value: "12345"
  deterministic_status: "red"
  deterministic_reason_codes: ["licensing_authority_numeric"]
  evidence: "Licensing Authority: 12345"
Output:
  {{"field":"g28.attorney.licensing_authority","verdict":"RED","score":0.12,
    "reason":"Licensing authority should be text; numeric-only is invalid",
    "suggested_value":null,
    "suggested_value_reason":"No valid authority in evidence",
    "evidence":"Licensing Authority: 12345","requires_human_input":true}}

Input field:
  field: g28.attorney.phone_daytime
  extracted_value: "2125550100"
  deterministic_status: "amber"
  deterministic_reason_codes: ["phone_format"]
  evidence: "Daytime Phone: (212) 555-0100"
Output:
  {{"field":"g28.attorney.phone_daytime","verdict":"GREEN","score":0.90,
    "reason":"Phone present with punctuation; normalize format",
    "suggested_value":"(212) 555-0100",
    "suggested_value_reason":"Evidence shows formatted number; add punctuation",
    "evidence":"Daytime Phone: (212) 555-0100","requires_human_input":false}}

Input field:
  field: g28.attorney.address.zip
  extracted_value: "9410O"
  deterministic_status: "red"
  deterministic_reason_codes: ["zip_format"]
  evidence: "ZIP Code: 94108"
Output:
  {{"field":"g28.attorney.address.zip","verdict":"RED","score":0.25,
    "reason":"ZIP contains letter O; evidence shows digits only",
    "suggested_value":"94108",
    "suggested_value_reason":"Evidence shows ZIP Code: 94108",
    "evidence":"ZIP Code: 94108","requires_human_input":false}}

Input field:
  field: g28.consent.send_documents_to_attorney
  human_required: true
  human_required_reason: "Client consent required; do not autofill."
  deterministic_status: "amber"
  evidence: "not found"
Output:
  {{"field":"g28.consent.send_documents_to_attorney","verdict":"AMBER","score":0.40,
    "reason":"Client consent required; do not autofill.",
    "suggested_value":null,
    "suggested_value_reason":"Consent must be provided by the client",
    "evidence":"not found","requires_human_input":true}}

Now validate these fields. Return one result per input, same order:
<<FIELDS_JSON>>
""".strip()

FIELD_VALIDATION_PROMPT_FAST = """
You are a strict field validator for passport + USCIS G-28 data.
Goal: provide concise proof that autofill is correct. Return JSON only. Do not wrap in markdown.

Return this exact shape:
{
  "results": [
    {
      "field": "g28.attorney.email",
      "verdict": "GREEN|AMBER|RED",
      "score": 0.0-1.0,
      "reason": "short explanation tied to evidence",
      "suggested_value": null OR "string",
      "suggested_value_reason": "short reason for the suggestion",
      "evidence": "short snippet from provided evidence OR 'not found'",
      "requires_human_input": true/false
    }
  ]
}

Rules:
- Never invent personal data.
- Treat deterministic_status + deterministic_reason_codes as authoritative.
- If human_required is true: verdict AMBER, requires_human_input true, suggested_value null,
  and reason must mention human_required_reason.
- If evidence does not contain a value, set evidence = "not found" and requires_human_input = true.
- If deterministic_status is RED, verdict cannot be GREEN.
- If deterministic_status is GREEN, verdict cannot be RED.
- Keep reason <= 12 words and evidence <= 80 characters.
- Keep suggested_value_reason <= 12 words.
- Return one result per input, same order.

<<FIELDS_JSON>>
""".strip()


LLM_EXTRACT_PROMPT = """
You are extracting missing fields from OCR text of a passport and a USCIS G-28 form.
Return JSON only in this shape:
{
  "suggestions": [
    {
      "field": "passport.surname",
      "value": "EXTRACTED VALUE",
      "reason": "why this value matches the field",
      "evidence": "short OCR snippet showing the value",
      "confidence": 0.7,
      "requires_confirmation": false
    }
  ]
}
Rules:
- Only include fields listed in missing_fields.
- Only suggest values explicitly present in the OCR text.
- Evidence must be a short verbatim snippet from OCR text.
- reason MUST explain why the evidence matches the field (e.g., label + value).
- If unsure, omit the suggestion entirely.
- requires_confirmation should be true only for conflicts between sources.

Examples:
Input: missing_fields = ["passport.surname"]
OCR snippet: "Surname: GARCIA"
Output suggestion:
  {{"field":"passport.surname","value":"GARCIA",
    "reason":"Value follows 'Surname' label in OCR",
    "evidence":"Surname: GARCIA","confidence":0.84,"requires_confirmation":false}}

Input: missing_fields = ["g28.attorney.email"]
OCR snippet: "Email Address (if any) immigration@law.com"
Output suggestion:
  {{"field":"g28.attorney.email","value":"immigration@law.com",
    "reason":"Email appears after the email label in OCR",
    "evidence":"Email Address (if any) immigration@law.com",
    "confidence":0.78,"requires_confirmation":false}}
""".strip()


LLM_RECOVER_PROMPT = """
You are recovering missing or uncertain fields from OCR snippets.
Return JSON only in this shape:
{
  "suggestions": [
    {
      "field": "g28.attorney.family_name",
      "value": "EXTRACTED VALUE",
      "reason": "why this value matches the field",
      "evidence": "short verbatim snippet showing the value",
      "confidence": 0.7,
      "requires_confirmation": false
    }
  ]
}
Rules:
- Only suggest values that appear in the provided snippet.
- reason MUST explain why the evidence matches the field.
- If not found, omit that field (do not guess).
- Do not invent or normalize beyond trivial spacing/punctuation.
""".strip()


LLM_VALIDATE_PROMPT = """
You are a strict validator for passport + USCIS G-28 data.
Return JSON only with keys: issues (list), suggestions (object).
Severity legend: error=red (wrong/contradictory), warning=yellow (needs human review), info=green-ish (minor normalization).
Rules: provide a short rule name; keep messages concise and actionable.
Suggestions: provide corrected value strings only (no explanations); omit if unsure.
Do not invent missing fields—only adjust what is present.

issues: list of {field, severity, rule, message, suggestion?}
suggestions: {field: "corrected value string"}

Examples:
Input field: passport.date_of_birth="01/02/03"
Issue:
  {{"field":"passport.date_of_birth","severity":"warning","rule":"date_format_ambiguous",
    "message":"Ambiguous date format; confirm day/month order"}}

Input field: g28.attorney.email="immigration @law.com"
Issue + suggestion:
  {{"field":"g28.attorney.email","severity":"info","rule":"email_normalize",
    "message":"Remove spaces around @","suggestion":"immigration@law.com"}}
""".strip()


LLM_VERIFY_PROMPT = """
You are a strict verifier for passport + USCIS G-28 extraction.
Return JSON only with keys: issues (list), suggestions (object), summary (string).
Rules:
- Never invent personal data.
- Only review fields listed in review_fields.
- Only suggest values that are explicitly present in the OCR/MRZ text.
- Suggested values may be trivial normalizations of evidence (spacing, punctuation).
- Every suggestion must include a short verbatim evidence snippet from OCR/MRZ.
- If a value cannot be found, add an issue saying it was not found.
- reason MUST explain why the evidence supports the suggestion.
issues: list of {field, severity, message, evidence}.
suggestions: {field: [{value, reason, evidence, confidence, requires_confirmation}]}
summary: short recommendation for what to review.

Examples:
Issue example:
  {{"field":"passport.date_of_birth","severity":"warning",
    "message":"DOB not found in OCR text","evidence":"not found"}}
Suggestion example:
  "g28.attorney.phone_daytime": [
    {{"value":"(212) 555-0100","reason":"Matches Daytime Phone label in OCR",
      "evidence":"Daytime Phone: (212) 555-0100","confidence":0.82,"requires_confirmation":false}}
  ]
""".strip()


LLM_CORRECT_PROMPT = """
You are a strict passport data corrector.
Return JSON only with key: corrections (list).
Rules:
- You may correct existing fields OR fill missing fields only when evidence is present in OCR/MRZ text.
- Make minimal edits: fix OCR typos, missing/extra characters, spacing, punctuation, casing.
- Normalize dates to YYYY-MM-DD.
- When multiple dates exist, map them using labels: "Date of birth", "Date of issue", "Date of expiration".
- Normalize country names to common English when obvious (e.g., UNITED STATES OF AMERICA -> United States).
- For place names and nationalities, correct obvious OCR misspellings to the intended value.
- If unsure, omit the correction.
- evidence should be a short OCR/MRZ snippet that supports the correction (may include misspellings).
Each correction: {field, value, reason, evidence, confidence}
""".strip()


LLM_TRANSLATE_PROMPT = """
Translate the following OCR text into English.
Rules:
- Preserve headings, labels, and line breaks.
- Keep the original structure and ordering.
- Do not summarize, omit, or add content.
- Return only the translated text, no markdown or JSON.
""".strip()


def build_field_validation_prompt(fields: List[Dict], fast: bool = False) -> str:
    payload = json.dumps(fields, ensure_ascii=True, separators=(",", ":"))
    prompt = FIELD_VALIDATION_PROMPT_FAST if fast else FIELD_VALIDATION_PROMPT
    return prompt.replace("<<FIELDS_JSON>>", payload)


def build_llm_extract_prompt(
    passport_text: str,
    g28_text: str,
    missing_fields: List[str],
    existing: Dict,
) -> str:
    return (
        f"{LLM_EXTRACT_PROMPT}\n\n"
        f"Missing fields list: {missing_fields}\n\n"
        f"Existing extracted data:\n{json.dumps(existing, indent=2)}\n\n"
        f"Passport OCR text:\n{passport_text}\n\n"
        f"G-28 OCR text:\n{g28_text}\n"
    )


def build_llm_recover_prompt(field_contexts: List[Dict], existing: Dict) -> str:
    return (
        f"{LLM_RECOVER_PROMPT}\n\n"
        f"Field contexts:\n{json.dumps(field_contexts, indent=2)}\n\n"
        f"Existing extracted data:\n{json.dumps(existing, indent=2)}\n"
    )


def build_llm_validate_prompt(payload: Dict, issues: List[Dict]) -> str:
    return (
        f"{LLM_VALIDATE_PROMPT}\n\n"
        f"Current payload:\n{json.dumps(payload, indent=2)}\n\n"
        f"Existing issues:\n{json.dumps(issues, indent=2)}\n"
    )


def build_llm_verify_prompt(
    passport_text: str,
    g28_text: str,
    result: Dict,
    statuses: Dict[str, str],
    review_fields: List[str],
    autofill_report: Dict,
) -> str:
    return (
        f"{LLM_VERIFY_PROMPT}\n\n"
        f"Review fields: {review_fields}\n\n"
        f"Field statuses:\n{json.dumps(statuses, indent=2)}\n\n"
        f"Extraction result:\n{json.dumps(result, indent=2)}\n\n"
        f"Autofill report:\n{json.dumps(autofill_report or {}, indent=2)}\n\n"
        f"Passport OCR/MRZ text:\n{passport_text}\n\n"
        f"G-28 OCR text:\n{g28_text}\n"
    )


def build_llm_correct_prompt(
    passport_text: str,
    g28_text: str,
    result: Dict,
) -> str:
    return (
        f"{LLM_CORRECT_PROMPT}\n\n"
        f"Extraction result:\n{json.dumps(result, indent=2)}\n\n"
        f"Passport OCR/MRZ text:\n{passport_text}\n\n"
        f"G-28 OCR text:\n{g28_text}\n"
    )


def build_llm_translation_prompt(text: str) -> str:
    return f"{LLM_TRANSLATE_PROMPT}\n\nOCR text:\n{text}"
