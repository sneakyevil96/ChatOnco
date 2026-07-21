import csv
import io
import re
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.project_config import FaqRetrievalConfig
from app.services.faq_embeddings import EmbeddingProvider
from app.services.faq_import import FaqImportValidationError, parse_boolean
from app.services.faq_retrieval import FaqRetrievalOutcome, retrieve_approved_faq


EXPECTED_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+@[1-9][0-9]*$")


@dataclass(frozen=True, slots=True)
class FaqEvaluationItem:
    question_ro: str
    expected: str
    high_risk: bool


@dataclass(frozen=True, slots=True)
class FaqEvaluationMetrics:
    total: int
    automatically_answered: int
    correct_automatic_answers: int
    incorrect_automatic_answers: int
    escalated: int
    high_risk_incorrect_automatic_answers: int

    @property
    def precision(self) -> float:
        if self.automatically_answered == 0:
            return 1.0
        return self.correct_automatic_answers / self.automatically_answered

    @property
    def incorrect_automatic_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.incorrect_automatic_answers / self.total

    @property
    def automatic_coverage(self) -> float:
        if self.total == 0:
            return 0.0
        return self.automatically_answered / self.total

    @property
    def meets_safety_targets(self) -> bool:
        return (
            self.precision >= 0.99
            and self.incorrect_automatic_rate < 0.01
            and self.high_risk_incorrect_automatic_answers == 0
        )


def parse_evaluation_csv(content: bytes) -> tuple[FaqEvaluationItem, ...]:
    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise FaqImportValidationError(["evaluation CSV must be UTF-8 encoded"]) from exc
    reader = csv.DictReader(io.StringIO(decoded))
    expected_columns = {"question_ro", "expected", "high_risk"}
    if set(reader.fieldnames or []) != expected_columns:
        raise FaqImportValidationError(
            ["evaluation CSV columns must be question_ro, expected, high_risk"]
        )
    errors: list[str] = []
    items: list[FaqEvaluationItem] = []
    for row_number, row in enumerate(reader, start=2):
        question = (row.get("question_ro") or "").strip()
        expected = (row.get("expected") or "").strip()
        if not question:
            errors.append(f"row {row_number}: question_ro is required")
        if expected != "ESCALATE" and not EXPECTED_LABEL_PATTERN.fullmatch(expected):
            errors.append(
                f"row {row_number}: expected must be ESCALATE or logical_key@version"
            )
        high_risk = parse_boolean(
            row.get("high_risk") or "",
            "high_risk",
            row_number,
            errors,
        )
        items.append(
            FaqEvaluationItem(
                question_ro=question,
                expected=expected,
                high_risk=high_risk,
            )
        )
    if not items:
        errors.append("the evaluation file contains no items")
    if errors:
        raise FaqImportValidationError(errors)
    return tuple(items)


async def evaluate_faq_retrieval(
    database: AsyncSession,
    *,
    project_id: str,
    items: tuple[FaqEvaluationItem, ...],
    configuration: FaqRetrievalConfig,
    embedding_provider: EmbeddingProvider | None,
) -> FaqEvaluationMetrics:
    automatically_answered = 0
    correct = 0
    incorrect = 0
    escalated = 0
    high_risk_incorrect = 0
    for item in items:
        result = await retrieve_approved_faq(
            database,
            project_id=project_id,
            question=item.question_ro,
            configuration=configuration,
            embedding_provider=embedding_provider,
        )
        if result.outcome == FaqRetrievalOutcome.ESCALATE:
            escalated += 1
            continue
        automatically_answered += 1
        if result.faq_label == item.expected:
            correct += 1
        else:
            incorrect += 1
            if item.high_risk:
                high_risk_incorrect += 1
    return FaqEvaluationMetrics(
        total=len(items),
        automatically_answered=automatically_answered,
        correct_automatic_answers=correct,
        incorrect_automatic_answers=incorrect,
        escalated=escalated,
        high_risk_incorrect_automatic_answers=high_risk_incorrect,
    )
