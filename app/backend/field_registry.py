from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional


@dataclass(frozen=True)
class AutofillSpec:
    labels: List[str]
    order: int


@dataclass(frozen=True)
class FieldSpec:
    key: str
    group: str
    field_type: str
    required: bool
    label: str
    label_hints: List[str] = field(default_factory=list)
    autofill: Optional[AutofillSpec] = None
    validate: bool = False
    human_required: bool = False
    human_required_reason: Optional[str] = None


FIELDS: List[FieldSpec] = [
    # Passport
    FieldSpec(
        key="passport.given_names",
        group="passport",
        field_type="name",
        required=True,
        label="Passport given names",
        label_hints=["Given Names", "First Name"],
        validate=True,
        autofill=AutofillSpec(labels=["1.b. First Name(s)", "Given Name", "First Name"], order=31),
    ),
    FieldSpec(
        key="passport.surname",
        group="passport",
        field_type="name",
        required=True,
        label="Passport surname",
        label_hints=["Surname", "Last Name"],
        validate=True,
        autofill=AutofillSpec(labels=["1.a. Last Name", "Family Name", "Last Name"], order=30),
    ),
    FieldSpec(
        key="passport.full_name",
        group="passport",
        field_type="name",
        required=False,
        label="Passport full name",
    ),
    FieldSpec(
        key="passport.date_of_birth",
        group="passport",
        field_type="date_past",
        required=True,
        label="Date of birth",
        label_hints=["Date of Birth", "DOB"],
        validate=True,
        autofill=AutofillSpec(labels=["5.a. Date of Birth", "Date of Birth", "DOB"], order=33),
    ),
    FieldSpec(
        key="passport.place_of_birth",
        group="passport",
        field_type="text",
        required=False,
        label="Place of birth",
        label_hints=["Place of Birth"],
        autofill=AutofillSpec(labels=["5.b. Place of Birth", "Place of Birth"], order=37),
    ),
    FieldSpec(
        key="passport.nationality",
        group="passport",
        field_type="text",
        required=False,
        label="Nationality",
        label_hints=["Nationality"],
        autofill=AutofillSpec(labels=["4. Nationality", "Nationality"], order=36),
    ),
    FieldSpec(
        key="passport.country_of_issue",
        group="passport",
        field_type="text",
        required=False,
        label="Country of issue",
        label_hints=["Country of Issue", "Issuing Country"],
        autofill=AutofillSpec(labels=["3. Country of Issue", "Country of Issue"], order=35),
    ),
    FieldSpec(
        key="passport.passport_number",
        group="passport",
        field_type="passport_number",
        required=True,
        label="Passport number",
        label_hints=["Passport Number", "Passport No"],
        validate=True,
        autofill=AutofillSpec(labels=["2. Passport Number", "Passport Number"], order=34),
    ),
    FieldSpec(
        key="passport.date_of_issue",
        group="passport",
        field_type="date_past",
        required=False,
        label="Date of issue",
        label_hints=["Date of Issue"],
        autofill=AutofillSpec(labels=["7.a. Date of Issue", "Date of Issue"], order=38),
    ),
    FieldSpec(
        key="passport.date_of_expiration",
        group="passport",
        field_type="date_future",
        required=True,
        label="Date of expiration",
        label_hints=["Date of Expiry", "Expiration", "Expiry"],
        validate=True,
        autofill=AutofillSpec(labels=["7.b. Date of Expiration", "Date of Expiry", "Expiration"], order=39),
    ),
    FieldSpec(
        key="passport.sex",
        group="passport",
        field_type="sex",
        required=False,
        label="Sex",
        label_hints=["Sex"],
        validate=True,
        autofill=AutofillSpec(labels=["6. Sex", "Sex"], order=32),
    ),
    # G-28 Attorney
    FieldSpec(
        key="g28.attorney.online_account_number",
        group="g28.attorney",
        field_type="text",
        required=False,
        label="Online account number",
        label_hints=["Online Account Number"],
        autofill=AutofillSpec(labels=["1. Online Account Number (if any)", "Online Account Number"], order=0),
    ),
    FieldSpec(
        key="g28.attorney.family_name",
        group="g28.attorney",
        field_type="name",
        required=True,
        label="Attorney family name",
        label_hints=["Family Name", "Last Name", r"2\s*\.?a", r"2a\.?"],
        validate=True,
        autofill=AutofillSpec(
            labels=["2.a. Family Name (Last Name)", "2.a. Family Name", "Family Name", "Last Name"],
            order=1,
        ),
    ),
    FieldSpec(
        key="g28.attorney.given_name",
        group="g28.attorney",
        field_type="name",
        required=True,
        label="Attorney given name",
        label_hints=["Given Name", "First Name", r"2\s*\.?b", r"2b\.?"],
        validate=True,
        autofill=AutofillSpec(
            labels=["2.b. Given Name (First Name)", "2.b. Given Name", "Given Name", "First Name"],
            order=2,
        ),
    ),
    FieldSpec(
        key="g28.attorney.middle_name",
        group="g28.attorney",
        field_type="name",
        required=False,
        label="Attorney middle name",
        label_hints=["Middle Name", r"2\s*\.?c", r"2c\.?"],
        autofill=AutofillSpec(labels=["2.c. Middle Name", "Middle Name"], order=3),
    ),
    FieldSpec(
        key="g28.attorney.full_name",
        group="g28.attorney",
        field_type="name",
        required=False,
        label="Attorney full name",
    ),
    FieldSpec(
        key="g28.attorney.law_firm_name",
        group="g28.attorney",
        field_type="text",
        required=False,
        label="Law firm name",
        label_hints=["Law Firm", "Organization Name", "Name of Law Firm"],
        autofill=AutofillSpec(
            labels=[
                "1.d. Name of Law Firm or Organization (if applicable)",
                "Name of Law Firm or Organization",
                "Law Firm",
                "Organization Name",
            ],
            order=4,
        ),
    ),
    FieldSpec(
        key="g28.attorney.licensing_authority",
        group="g28.attorney",
        field_type="text",
        required=False,
        label="Licensing authority",
        label_hints=["Licensing Authority", "State Bar"],
        validate=True,
        autofill=AutofillSpec(labels=["Licensing Authority"], order=14),
    ),
    FieldSpec(
        key="g28.attorney.bar_number",
        group="g28.attorney",
        field_type="text",
        required=False,
        label="Bar number",
        label_hints=["Bar Number", "Bar\s*#", "Bar No", r"1\s*\.?b", r"1b\.?"],
        validate=True,
        autofill=AutofillSpec(labels=["1.b. Bar Number (if applicable)", "Bar Number"], order=15),
    ),
    FieldSpec(
        key="g28.attorney.eligibility.attorney_eligible",
        group="g28.attorney.eligibility",
        field_type="checkbox",
        required=False,
        label="Eligible to practice law and in good standing",
        human_required=True,
        human_required_reason="Human attestation required; do not autofill.",
    ),
    FieldSpec(
        key="g28.attorney.eligibility.subject_to_orders_no",
        group="g28.attorney.eligibility",
        field_type="checkbox",
        required=False,
        label="Not subject to any order restricting practice",
        human_required=True,
        human_required_reason="Human attestation required; do not autofill.",
    ),
    FieldSpec(
        key="g28.attorney.eligibility.subject_to_orders_yes",
        group="g28.attorney.eligibility",
        field_type="checkbox",
        required=False,
        label="Subject to order restricting practice",
        human_required=True,
        human_required_reason="Human attestation required; do not autofill.",
    ),
    FieldSpec(
        key="g28.attorney.eligibility.accredited_representative",
        group="g28.attorney.eligibility",
        field_type="checkbox",
        required=False,
        label="Accredited representative",
        human_required=True,
        human_required_reason="Human attestation required; do not autofill.",
    ),
    FieldSpec(
        key="g28.attorney.eligibility.recognized_organization_name",
        group="g28.attorney.eligibility",
        field_type="text",
        required=False,
        label="Recognized organization name",
        human_required=True,
        human_required_reason="Human attestation required; do not autofill.",
    ),
    FieldSpec(
        key="g28.attorney.eligibility.accreditation_date",
        group="g28.attorney.eligibility",
        field_type="date_past",
        required=False,
        label="Accreditation date",
        human_required=True,
        human_required_reason="Human attestation required; do not autofill.",
    ),
    FieldSpec(
        key="g28.attorney.eligibility.associated_with",
        group="g28.attorney.eligibility",
        field_type="checkbox",
        required=False,
        label="Associated with previously filed G-28",
        human_required=True,
        human_required_reason="Human attestation required; do not autofill.",
    ),
    FieldSpec(
        key="g28.attorney.eligibility.associated_with_name",
        group="g28.attorney.eligibility",
        field_type="text",
        required=False,
        label="Name of previously filed attorney/representative",
        human_required=True,
        human_required_reason="Human attestation required; do not autofill.",
    ),
    FieldSpec(
        key="g28.attorney.eligibility.law_student",
        group="g28.attorney.eligibility",
        field_type="checkbox",
        required=False,
        label="Law student or graduate under supervision",
        human_required=True,
        human_required_reason="Human attestation required; do not autofill.",
    ),
    FieldSpec(
        key="g28.attorney.eligibility.law_student_name",
        group="g28.attorney.eligibility",
        field_type="text",
        required=False,
        label="Name of law student or graduate",
        human_required=True,
        human_required_reason="Human attestation required; do not autofill.",
    ),
    FieldSpec(
        key="g28.attorney.email",
        group="g28.attorney",
        field_type="email",
        required=True,
        label="Attorney email",
        label_hints=["Email", "Email Address", r"6\s*\.?"],
        validate=True,
        autofill=AutofillSpec(labels=["6. Email Address (if any)", "Email Address", "Email"], order=13),
    ),
    FieldSpec(
        key="g28.attorney.phone_daytime",
        group="g28.attorney",
        field_type="phone",
        required=False,
        label="Attorney daytime phone",
        label_hints=["Daytime Phone", "Phone Number", "Daytime Telephone", r"4\s*\.?"],
        validate=True,
        autofill=AutofillSpec(labels=["4. Daytime Telephone Number", "Daytime Phone Number", "Phone"], order=11),
    ),
    FieldSpec(
        key="g28.attorney.phone_mobile",
        group="g28.attorney",
        field_type="phone",
        required=False,
        label="Attorney mobile phone",
        label_hints=["Mobile Phone", "Mobile Number", "Cell", "Mobile Telephone", r"5\s*\.?"],
        validate=True,
        autofill=AutofillSpec(
            labels=["5. Mobile Telephone Number (if any)", "Mobile Phone Number", "Mobile"],
            order=12,
        ),
    ),
    FieldSpec(
        key="g28.attorney.address.street",
        group="g28.attorney",
        field_type="text",
        required=True,
        label="Attorney street",
        label_hints=["Street", "Number and Name", "Street Number", r"3\s*\.?a", r"3a\.?"],
        validate=True,
        autofill=AutofillSpec(labels=["3.a. Street Number and Name", "Street Number and Name", "Street"], order=5),
    ),
    FieldSpec(
        key="g28.attorney.address.unit",
        group="g28.attorney",
        field_type="text",
        required=False,
        label="Attorney unit",
        label_hints=[r"\bApt\b", r"\bSte\b", r"\bSuite\b", r"\bFlr\b", r"3\s*\.?b", r"3b\.?"],
        autofill=AutofillSpec(labels=["Apt.", "Ste.", "Flr.", "Apt", "Suite", "Apt./Ste./Flr."], order=6),
    ),
    FieldSpec(
        key="g28.attorney.address.city",
        group="g28.attorney",
        field_type="text",
        required=True,
        label="Attorney city",
        label_hints=["City", "Town", r"3\s*\.?c", r"3c\.?"],
        validate=True,
        autofill=AutofillSpec(labels=["3.c. City", "City or Town", "City"], order=7),
    ),
    FieldSpec(
        key="g28.attorney.address.state",
        group="g28.attorney",
        field_type="state",
        required=True,
        label="Attorney state",
        label_hints=["State", r"3\s*\.?d", r"3d\.?"],
        validate=True,
        autofill=AutofillSpec(labels=["3.d. State", "State"], order=8),
    ),
    FieldSpec(
        key="g28.attorney.address.zip",
        group="g28.attorney",
        field_type="zip",
        required=True,
        label="Attorney ZIP",
        label_hints=["ZIP", "Postal", "Postal Code", r"3\s*\.?e", r"3e\.?"],
        validate=True,
        autofill=AutofillSpec(labels=["3.e. ZIP Code", "ZIP Code", "Postal"], order=9),
    ),
    FieldSpec(
        key="g28.attorney.address.country",
        group="g28.attorney",
        field_type="text",
        required=False,
        label="Attorney country",
        label_hints=["Country", r"3\s*\.?h", r"3h\.?"],
        autofill=AutofillSpec(labels=["3.f. Country", "Country"], order=10),
    ),
    # G-28 Client
    FieldSpec(
        key="g28.client.family_name",
        group="g28.client",
        field_type="name",
        required=False,
        label="Client family name",
        label_hints=[
            "Family Name",
            "Last Name",
            "Client.*Family Name",
            "Applicant.*Family Name",
            "Petitioner.*Family Name",
            r"6\s*\.?a",
            r"6a\.?",
        ],
    ),
    FieldSpec(
        key="g28.client.given_name",
        group="g28.client",
        field_type="name",
        required=False,
        label="Client given name",
        label_hints=[
            "Given Name",
            "First Name",
            "Client.*Given Name",
            "Applicant.*Given Name",
            "Petitioner.*Given Name",
            r"6\s*\.?b",
            r"6b\.?",
        ],
    ),
    FieldSpec(
        key="g28.client.middle_name",
        group="g28.client",
        field_type="name",
        required=False,
        label="Client middle name",
        label_hints=[
            "Middle Name",
            "Client.*Middle Name",
            "Applicant.*Middle Name",
            r"6\s*\.?c",
            r"6c\.?",
        ],
    ),
    FieldSpec(
        key="g28.client.full_name",
        group="g28.client",
        field_type="name",
        required=False,
        label="Client full name",
    ),
    FieldSpec(
        key="g28.client.email",
        group="g28.client",
        field_type="email",
        required=False,
        label="Client email",
        label_hints=["Email", "Email Address", "Client.*Email", "Applicant.*Email", r"12\s*\.?", r"12\.?"],
    ),
    FieldSpec(
        key="g28.client.phone",
        group="g28.client",
        field_type="phone",
        required=False,
        label="Client phone",
        label_hints=["Daytime Telephone", "Phone", "Client.*Phone", "Applicant.*Phone", r"10\s*\.?", r"10\.?"],
    ),
    FieldSpec(
        key="g28.client.address.street",
        group="g28.client",
        field_type="text",
        required=False,
        label="Client street",
        label_hints=["Street", "Street Number", "Client.*Street", "Applicant.*Street", r"13\s*\.?a", r"13a\.?"],
    ),
    FieldSpec(
        key="g28.client.address.unit",
        group="g28.client",
        field_type="text",
        required=False,
        label="Client unit",
        label_hints=[r"\bApt\b", r"\bSte\b", r"\bSuite\b", r"\bFlr\b", r"13\s*\.?b", r"13b\.?"],
    ),
    FieldSpec(
        key="g28.client.address.city",
        group="g28.client",
        field_type="text",
        required=False,
        label="Client city",
        label_hints=["City", "Town", "Client.*City", "Applicant.*City", r"13\s*\.?c", r"13c\.?"],
    ),
    FieldSpec(
        key="g28.client.address.state",
        group="g28.client",
        field_type="state",
        required=False,
        label="Client state",
        label_hints=["State", "Client.*State", "Applicant.*State", r"13\s*\.?d", r"13d\.?"],
    ),
    FieldSpec(
        key="g28.client.address.zip",
        group="g28.client",
        field_type="zip",
        required=False,
        label="Client ZIP",
        label_hints=["ZIP", "Postal", "Postal Code", "Client.*ZIP", "Applicant.*ZIP", r"13\s*\.?e", r"13e\.?"],
    ),
    FieldSpec(
        key="g28.client.address.country",
        group="g28.client",
        field_type="text",
        required=False,
        label="Client country",
        label_hints=["Country", "Client.*Country", "Applicant.*Country", r"13\s*\.?h", r"13h\.?"],
    ),
    # G-28 Consent / Signatures
    FieldSpec(
        key="g28.consent.send_notices_to_attorney",
        group="g28.consent",
        field_type="checkbox",
        required=False,
        label="Request notices to be sent to attorney",
        human_required=True,
        human_required_reason="Client consent required; do not autofill.",
    ),
    FieldSpec(
        key="g28.consent.send_documents_to_attorney",
        group="g28.consent",
        field_type="checkbox",
        required=False,
        label="Request documents be sent to attorney",
        human_required=True,
        human_required_reason="Client consent required; do not autofill.",
    ),
    FieldSpec(
        key="g28.consent.send_documents_to_client",
        group="g28.consent",
        field_type="checkbox",
        required=False,
        label="Request documents be sent to client",
        human_required=True,
        human_required_reason="Client consent required; do not autofill.",
    ),
    FieldSpec(
        key="g28.consent.client_signature_date",
        group="g28.consent",
        field_type="date_past",
        required=True,
        label="Client signature date",
        human_required=True,
        human_required_reason="Signature date must be provided by the client.",
    ),
    FieldSpec(
        key="g28.consent.attorney_signature_date",
        group="g28.consent",
        field_type="date_past",
        required=True,
        label="Attorney signature date",
        human_required=True,
        human_required_reason="Signature date must be provided by the attorney.",
    ),
]


FIELD_REGISTRY: Dict[str, FieldSpec] = {field.key: field for field in FIELDS}
FIELD_ORDER: List[str] = [field.key for field in FIELDS]


def iter_fields() -> Iterable[FieldSpec]:
    return FIELDS


def iter_validation_fields() -> Iterable[FieldSpec]:
    return [field for field in FIELDS if field.validate]


def iter_autofill_fields() -> Iterable[FieldSpec]:
    return [field for field in FIELDS if field.autofill]


def get_field_spec(key: str) -> Optional[FieldSpec]:
    return FIELD_REGISTRY.get(key)


def get_field_label(key: str) -> str:
    spec = FIELD_REGISTRY.get(key)
    return spec.label if spec else key


def field_registry_payload() -> Dict[str, object]:
    return {
        "fields": [
            {
                "key": field.key,
                "group": field.group,
                "type": field.field_type,
                "required": field.required,
                "label": field.label,
                "human_required": field.human_required,
                "human_required_reason": field.human_required_reason,
                "autofill": bool(field.autofill),
            }
            for field in FIELDS
        ],
        "order": FIELD_ORDER,
    }


G28_LABEL_PATTERNS: Dict[str, List[str]] = {
    field.key: list(field.label_hints)
    for field in FIELDS
    if field.key.startswith("g28.") and field.label_hints
}
