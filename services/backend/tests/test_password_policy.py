from __future__ import annotations

import pytest

from app.user_auth import _password


def test_password_contract_strips_only_outer_whitespace() -> None:
    assert _password("  password  ") == "password"
    assert _password(" pass word ") == "pass word"


@pytest.mark.parametrize("password", [None, 123, "", "       ", "short7"])
def test_password_contract_rejects_non_strings_empty_and_short_values(password) -> None:
    with pytest.raises(ValueError):
        _password(password)


def test_password_contract_accepts_8_to_256_normalized_characters() -> None:
    assert len(_password("x" * 8)) == 8
    assert len(_password("x" * 256)) == 256
    with pytest.raises(ValueError, match="at least 8"):
        _password(" x " * 2)
    with pytest.raises(ValueError, match="exceeds 256"):
        _password("x" * 257)
