from __future__ import annotations

import hashlib
from typing import Sequence

import math
import structlog

logger = structlog.get_logger(__name__)


class Embedder:
    def __init__(self, model_name: str = "paraphrase-multilingual-mpnet-base-v2", batch_size: int = 32) -> None:
        self.model_name = model_name
        self.batch_size = batch_size
        self._cache: dict[str, list[float]] = {}
        self._model = None

    def _lazy_model(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RuntimeError("sentence-transformers is required for embeddings") from exc
            logger.info("loading_embedding_model", model=self.model_name)
            self._model = SentenceTransformer(self.model_name)
        return self._model

    @staticmethod
    def _normalize(vector: Sequence[float]) -> list[float]:
        arr = [float(v) for v in vector]
        norm = math.sqrt(sum(v * v for v in arr))
        if norm == 0:
            raise ValueError("Embedding norm is zero")
        return [v / norm for v in arr]

    @staticmethod
    def hash_text(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def embed_texts(self, texts: list[str]) -> list[tuple[str, list[float]]]:
        model = self._lazy_model()
        hashes = [self.hash_text(text) for text in texts]
        out: list[tuple[str, list[float]]] = []
        missing_ix = [i for i, h in enumerate(hashes) if h not in self._cache]
        if missing_ix:
            missing_texts = [texts[i] for i in missing_ix]
            vectors = model.encode(missing_texts, batch_size=self.batch_size)
            for pos, vec in zip(missing_ix, vectors):
                h = hashes[pos]
                self._cache[h] = self._normalize(vec)
        for h in hashes:
            out.append((h, self._cache[h]))
        return out
