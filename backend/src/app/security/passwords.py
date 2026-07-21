import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from argon2.low_level import Type


class PasswordPolicyError(ValueError):
    pass


COMMON_PASSWORDS = {
    "123456789012",
    "administrator",
    "letmeinletmein",
    "parolaparola",
    "password1234",
    "qwertyqwerty",
}

PASSWORD_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=65_536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)

# Used to reduce account-enumeration timing differences for unknown emails.
DUMMY_PASSWORD_HASH = PASSWORD_HASHER.hash("not-a-real-user-password")


def validate_password(password: str) -> None:
    if len(password) < 12:
        raise PasswordPolicyError("Parola trebuie să conțină cel puțin 12 caractere.")
    normalized = password.casefold().strip()
    if normalized in COMMON_PASSWORDS:
        raise PasswordPolicyError("Parola este prea frecvent utilizată.")
    if len(set(normalized)) <= 2:
        raise PasswordPolicyError("Parola este prea simplă.")
    if normalized in "0123456789abcdefghijklmnopqrstuvwxyz":
        raise PasswordPolicyError("Parola este prea simplă.")


def hash_password(password: str) -> str:
    validate_password(password)
    return PASSWORD_HASHER.hash(password)


def verify_password(password_hash: str, candidate: str) -> bool:
    try:
        return PASSWORD_HASHER.verify(password_hash, candidate)
    except (InvalidHashError, VerifyMismatchError):
        return False


def verify_unknown_account_password(candidate: str) -> None:
    verify_password(DUMMY_PASSWORD_HASH, candidate)


def generate_temporary_password() -> str:
    return f"Tmp-{secrets.token_urlsafe(16)}"

