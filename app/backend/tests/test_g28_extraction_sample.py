from __future__ import annotations

from backend.main import extract_documents


def test_g28_extraction_sample(sample_g28_path) -> None:
    result = extract_documents(passport_path=None, g28_path=sample_g28_path)

    attorney = result.g28.attorney
    client = result.g28.client

    assert attorney.family_name == "Messi"
    assert attorney.given_name == "Kaka"
    assert attorney.middle_name is None
    assert attorney.full_name == "Kaka Messi"
    assert attorney.licensing_authority == "State Bar of California"
    assert attorney.bar_number == "12083456"
    assert attorney.email == "immigration @tryalma.ai"
    assert attorney.phone_mobile == "N/A"
    assert attorney.address.street == "545 Bryant Street"
    assert attorney.address.unit == "N/A"
    assert attorney.address.city == "Palo Alto"
    assert attorney.address.state == "CA"
    assert attorney.address.zip == "94301"
    assert attorney.address.country == "United States"

    assert client.family_name == "Jonas"
    assert client.given_name == "Joe"
    assert client.middle_name is None
    assert client.email == "b.smith_00 @test.ai"
    assert client.phone == "614-545-3434"
    assert client.address.street == "16 Anytown Street"
    assert client.address.unit is None
    assert client.address.city == "Perth"
    assert client.address.state == "WA"
    assert client.address.zip == "6000"
    assert client.address.country == "Australia"
