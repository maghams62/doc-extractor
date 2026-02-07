from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class PassportData(BaseModel):
    given_names: Optional[str] = None
    surname: Optional[str] = None
    full_name: Optional[str] = None
    date_of_birth: Optional[str] = None
    place_of_birth: Optional[str] = None
    nationality: Optional[str] = None
    country_of_issue: Optional[str] = None
    passport_number: Optional[str] = None
    date_of_issue: Optional[str] = None
    date_of_expiration: Optional[str] = None
    sex: Optional[str] = None


class Address(BaseModel):
    street: Optional[str] = None
    unit: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    country: Optional[str] = None


class EligibilityData(BaseModel):
    attorney_eligible: Optional[str] = None
    subject_to_orders_no: Optional[str] = None
    subject_to_orders_yes: Optional[str] = None
    accredited_representative: Optional[str] = None
    recognized_organization_name: Optional[str] = None
    accreditation_date: Optional[str] = None
    associated_with: Optional[str] = None
    associated_with_name: Optional[str] = None
    law_student: Optional[str] = None
    law_student_name: Optional[str] = None


class AttorneyData(BaseModel):
    online_account_number: Optional[str] = None
    family_name: Optional[str] = None
    given_name: Optional[str] = None
    middle_name: Optional[str] = None
    full_name: Optional[str] = None
    law_firm_name: Optional[str] = None
    licensing_authority: Optional[str] = None
    bar_number: Optional[str] = None
    email: Optional[str] = None
    phone_daytime: Optional[str] = None
    phone_mobile: Optional[str] = None
    address: Address = Field(default_factory=Address)
    eligibility: EligibilityData = Field(default_factory=EligibilityData)


class ClientData(BaseModel):
    family_name: Optional[str] = None
    given_name: Optional[str] = None
    middle_name: Optional[str] = None
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Address = Field(default_factory=Address)


class ConsentData(BaseModel):
    send_notices_to_attorney: Optional[str] = None
    send_documents_to_attorney: Optional[str] = None
    send_documents_to_client: Optional[str] = None
    client_signature_date: Optional[str] = None
    attorney_signature_date: Optional[str] = None


class G28Data(BaseModel):
    attorney: AttorneyData = Field(default_factory=AttorneyData)
    client: ClientData = Field(default_factory=ClientData)
    consent: ConsentData = Field(default_factory=ConsentData)


class SuggestionOption(BaseModel):
    value: str
    reason: Optional[str] = None
    source: str
    confidence: Optional[float] = None
    evidence: Optional[str] = None
    requires_confirmation: bool = False


class WarningItem(BaseModel):
    code: str
    message: str
    field: Optional[str] = None


class LLMVerificationIssue(BaseModel):
    field: Optional[str] = None
    severity: str = "warning"
    message: str
    evidence: Optional[str] = None


class LLMVerification(BaseModel):
    issues: List[LLMVerificationIssue] = Field(default_factory=list)
    suggestions: Dict[str, List[SuggestionOption]] = Field(default_factory=dict)
    summary: Optional[str] = None
    error: Optional[str] = None


class ResolvedField(BaseModel):
    key: str
    value: Optional[str] = None
    status: str = "unknown"
    confidence: float = 0.0
    source: str = "UNKNOWN"
    locked: bool = False
    requires_human_input: bool = False
    reason: Optional[str] = None
    deterministic_validation: Optional[Dict[str, object]] = None
    llm_validation: Optional[Dict[str, object]] = None
    suggestions: List[SuggestionOption] = Field(default_factory=list)
    last_validated_at: Optional[str] = None
    version: int = 0


class MetaData(BaseModel):
    sources: Dict[str, str] = Field(default_factory=dict)
    confidence: Dict[str, float] = Field(default_factory=dict)
    status: Dict[str, str] = Field(default_factory=dict)
    evidence: Dict[str, str] = Field(default_factory=dict)
    suggestions: Dict[str, List[SuggestionOption]] = Field(default_factory=dict)
    presence: Dict[str, str] = Field(default_factory=dict)
    conflicts: Dict[str, Dict[str, Optional[str]]] = Field(default_factory=dict)
    warnings: List[WarningItem] = Field(default_factory=list)
    llm_verification: Optional[LLMVerification] = None
    resolved_fields: Dict[str, ResolvedField] = Field(default_factory=dict)
    review_summary: Dict[str, object] = Field(default_factory=dict)
    canonical_approved_at: Optional[str] = None
    documents: Dict[str, Dict[str, object]] = Field(default_factory=dict)


class ExtractionResult(BaseModel):
    passport: PassportData = Field(default_factory=PassportData)
    g28: G28Data = Field(default_factory=G28Data)
    meta: MetaData = Field(default_factory=MetaData)


class ValidationIssue(BaseModel):
    field: str
    severity: str
    rule: str
    message: str
    current_value: Optional[str] = None
    suggestion: Optional[str] = None
    source: Optional[str] = None


class ValidationReport(BaseModel):
    ok: bool
    issues: List[ValidationIssue] = Field(default_factory=list)
    score: float = 0.0
    llm_used: bool = False
    llm_error: Optional[str] = None


def empty_result() -> ExtractionResult:
    return ExtractionResult()
