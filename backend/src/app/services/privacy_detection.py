import re

from app.services.faq_normalization import normalize_romanian_question


CNP_PATTERN = re.compile(r"(?<!\d)([1-9]\d{12})(?!\d)")
CNP_WEIGHTS = "279146358279"
SENSITIVE_PHRASES = (
    "bilet de externare",
    "buletin de analize",
    "document medical",
    "rezultat medical",
    "rezultate medicale",
    "scrisoare medicala",
)


def _valid_cnp(candidate: str) -> bool:
    checksum = sum(int(digit) * int(weight) for digit, weight in zip(candidate[:12], CNP_WEIGHTS))
    expected = checksum % 11
    if expected == 10:
        expected = 1
    return expected == int(candidate[-1])


def contains_obvious_sensitive_content(text: str) -> bool:
    if any(_valid_cnp(match.group(1)) for match in CNP_PATTERN.finditer(text)):
        return True
    normalized = normalize_romanian_question(text)
    return any(phrase in normalized for phrase in SENSITIVE_PHRASES)
