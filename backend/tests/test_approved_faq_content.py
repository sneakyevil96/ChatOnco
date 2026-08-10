from pathlib import Path

from app.services.faq_import import parse_faq_csv
from app.services.faq_normalization import normalize_romanian_question


APPROVED_ONCODIR_FAQ = (
    Path(__file__).parents[1] / "content" / "approved" / "ONCODIR" / "faq-v1.csv"
)
SOURCE_REVIEW_REFERENCE = (
    "ONCODIR LIP-01 Chatbot Knowledge Base.docx "
    "SHA256:BFFCF7822D7EC83766384B3DD74B5383181302E6A7FB92EB2D9BF8E62269C8C3"
)


def test_approved_oncodir_faq_v1_is_valid_and_unambiguous() -> None:
    rows = parse_faq_csv(APPROVED_ONCODIR_FAQ.read_bytes())

    assert len(rows) == 55
    assert len({row.logical_key for row in rows}) == 55
    assert all(row.version_number == 1 for row in rows)
    assert all(row.administrative_reviewer_reference == SOURCE_REVIEW_REFERENCE for row in rows)
    assert sum(row.requires_clinical_review for row in rows) == 9
    assert all(
        row.clinical_reviewer_reference == SOURCE_REVIEW_REFERENCE
        for row in rows
        if row.requires_clinical_review
    )

    normalized_questions = [
        normalize_romanian_question(question)
        for row in rows
        for question in row.alternative_questions_ro
    ]
    assert len(normalized_questions) == 66
    assert len(normalized_questions) == len(set(normalized_questions))

    by_key = {row.logical_key: row for row in rows}
    assert by_key["project_what_is_oncodir"].approved_answer_ro.startswith(
        "ONCODIR este un proiect european"
    )
    assert by_key["contact_unknown_answer"].approved_answer_ro.endswith("de la BEIA.")
    assert by_key["technical_password_changed_still_login"].alternative_questions_ro == (
        "Am schimbat parola și tot pot sa ma conectez.",
    )
