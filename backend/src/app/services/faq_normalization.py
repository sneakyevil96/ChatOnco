import re
import unicodedata


ROMANIAN_DIACRITIC_TRANSLATION = str.maketrans(
    {
        "ă": "a",
        "â": "a",
        "î": "i",
        "ș": "s",
        "ş": "s",
        "ț": "t",
        "ţ": "t",
    }
)


def normalize_romanian_question(question: str) -> str:
    normalized = unicodedata.normalize("NFKC", question).casefold().strip()
    normalized = normalized.translate(ROMANIAN_DIACRITIC_TRANSLATION)
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())
