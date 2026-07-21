from typing import Protocol, Sequence


class EmbeddingProvider(Protocol):
    model_name: str
    dimension: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class SentenceTransformerEmbeddingProvider:
    dimension = 384

    def __init__(self, model_name: str) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "Sentence Transformers is not installed; install the backend embeddings extra"
            ) from exc
        self.model_name = model_name
        self._model = SentenceTransformer(model_name, device="cpu")

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = self._model.encode(
            list(texts),
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        result = [vector.tolist() for vector in vectors]
        if any(len(vector) != self.dimension for vector in result):
            raise RuntimeError("The configured embedding model does not produce 384 dimensions")
        return result
