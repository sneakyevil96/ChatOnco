import argparse
import asyncio
import json
from pathlib import Path
from typing import Sequence

from app.core.project_config import FaqRetrievalConfig, ProjectCatalog, ProjectId
from app.core.settings import get_settings
from app.db.session import create_database_engine, create_session_factory
from app.services.faq_embeddings import (
    EmbeddingProvider,
    SentenceTransformerEmbeddingProvider,
)
from app.services.faq_evaluation import evaluate_faq_retrieval, parse_evaluation_csv


class CachingEmbeddingProvider:
    def __init__(self, delegate: EmbeddingProvider) -> None:
        self._delegate = delegate
        self.model_name = delegate.model_name
        self.dimension = delegate.dimension
        self._cache: dict[str, list[float]] = {}

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        missing = [text for text in texts if text not in self._cache]
        if missing:
            for text, vector in zip(missing, self._delegate.embed(missing), strict=True):
                self._cache[text] = vector
        return [self._cache[text] for text in texts]


def parse_candidates(value: str | None, label: str) -> list[float] | None:
    if value is None:
        return None
    try:
        candidates = [float(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as exc:
        raise ValueError(f"{label} must be a comma-separated list of numbers") from exc
    if not candidates:
        raise ValueError(f"{label} must not be empty")
    return candidates


async def run_evaluation(
    project_id: ProjectId,
    path: Path,
    thresholds: list[float] | None,
    gaps: list[float] | None,
) -> None:
    settings = get_settings()
    project = ProjectCatalog.load(settings.project_config_dir).get(project_id)
    items = parse_evaluation_csv(path.read_bytes())
    if (thresholds is None) != (gaps is None):
        raise ValueError("threshold and score-gap candidates must be supplied together")

    configurations: list[FaqRetrievalConfig]
    embedder: EmbeddingProvider | None = None
    if thresholds is not None and gaps is not None:
        configurations = [
            FaqRetrievalConfig(
                embedding_model=project.faq_retrieval.embedding_model,
                semantic_enabled=True,
                semantic_threshold=threshold,
                minimum_score_gap=gap,
            )
            for threshold in thresholds
            for gap in gaps
        ]
        embedder = CachingEmbeddingProvider(
            SentenceTransformerEmbeddingProvider(project.faq_retrieval.embedding_model)
        )
    else:
        configurations = [project.faq_retrieval]
        if project.faq_retrieval.semantic_enabled:
            embedder = CachingEmbeddingProvider(
                SentenceTransformerEmbeddingProvider(project.faq_retrieval.embedding_model)
            )

    engine = create_database_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    reports: list[dict] = []
    try:
        async with session_factory() as database:
            for configuration in configurations:
                metrics = await evaluate_faq_retrieval(
                    database,
                    project_id=project_id.value,
                    items=items,
                    configuration=configuration,
                    embedding_provider=embedder,
                )
                reports.append(
                    {
                        "semantic_threshold": configuration.semantic_threshold,
                        "minimum_score_gap": configuration.minimum_score_gap,
                        "total": metrics.total,
                        "automatically_answered": metrics.automatically_answered,
                        "correct_automatic_answers": metrics.correct_automatic_answers,
                        "incorrect_automatic_answers": metrics.incorrect_automatic_answers,
                        "escalated": metrics.escalated,
                        "precision": metrics.precision,
                        "incorrect_automatic_rate": metrics.incorrect_automatic_rate,
                        "automatic_coverage": metrics.automatic_coverage,
                        "high_risk_incorrect_automatic_answers": (
                            metrics.high_risk_incorrect_automatic_answers
                        ),
                        "meets_safety_targets": metrics.meets_safety_targets,
                    }
                )
    finally:
        await engine.dispose()
    qualifying = [report for report in reports if report["meets_safety_targets"]]
    recommended = max(qualifying, key=lambda report: report["automatic_coverage"], default=None)
    print(json.dumps({"project_id": project_id.value, "reports": reports, "recommended": recommended}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate FAQ retrieval using reviewed Romanian labels."
    )
    parser.add_argument("--project", required=True, choices=[item.value for item in ProjectId])
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument(
        "--thresholds",
        help="Explicit comma-separated semantic-score candidates; no defaults are assumed.",
    )
    parser.add_argument(
        "--score-gaps",
        help="Explicit comma-separated best-versus-second-best gap candidates.",
    )
    arguments = parser.parse_args()
    asyncio.run(
        run_evaluation(
            ProjectId(arguments.project),
            arguments.file,
            parse_candidates(arguments.thresholds, "thresholds"),
            parse_candidates(arguments.score_gaps, "score gaps"),
        )
    )


if __name__ == "__main__":
    main()
