import pytest

pytest.importorskip("argon2")

from app.security.passwords import PasswordPolicyError, hash_password, verify_password


def test_passwords_are_hashed_with_argon2id() -> None:
    encoded = hash_password("Synthetic-Secure-Password-2026")

    assert encoded.startswith("$argon2id$")
    assert verify_password(encoded, "Synthetic-Secure-Password-2026") is True
    assert verify_password(encoded, "Incorrect-password") is False


@pytest.mark.parametrize(
    "password",
    ["short", "password1234", "aaaaaaaaaaaa", "123456789012"],
)
def test_weak_passwords_are_rejected(password: str) -> None:
    with pytest.raises(PasswordPolicyError):
        hash_password(password)

