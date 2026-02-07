from __future__ import annotations

from backend.pipeline.passport import parse_mrz_td3


def test_passport_mrz_parser() -> None:
    lines = [
        "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<",
        "L898902C36UTO7408122F1204159ZE184226B<<<<<10",
    ]
    result = parse_mrz_td3(lines)
    assert result is not None
    fields = result.fields
    assert fields["surname"] == "Eriksson"
    assert fields["given_names"] == "Anna Maria"
    assert fields["passport_number"] == "L898902C3"
    assert fields["date_of_birth"] == "1974-08-12"
    assert fields["date_of_expiration"] == "2012-04-15"
    assert fields["sex"] == "F"
