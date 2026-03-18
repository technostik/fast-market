from __future__ import annotations

import hashlib
import logging
import math
from typing import Sequence

from common import structlog

logger = structlog.get_logger(__name__)


class Embedder:
    def __init__(
        self,
        model_name: str = "paraphrase-multilingual-mpnet-base-v2",
        batch_size: int = 32,
        server_url: str | None = None,
    ) -> None:
        from common.core.config import load_config

        try:
            config = load_config()
        except FileNotFoundError:
            config = {}

        embeddings_cfg = config.get("embeddings", {}) if isinstance(config, dict) else {}
        if not isinstance(embeddings_cfg, dict):
            embeddings_cfg = {}

        legacy_batch = config.get("embed_batch_size", batch_size) if isinstance(config, dict) else batch_size
        resolved_model = embeddings_cfg.get("model", model_name)
        resolved_batch_size = int(embeddings_cfg.get("batch_size", legacy_batch))
        port = int(embeddings_cfg.get("server_port", 8765))

        self.model_name = str(resolved_model)
        self.batch_size = resolved_batch_size
        self._cache: dict[str, list[float]] = {}
        self._model = None

        self.server_url = server_url or f"http://127.0.0.1:{port}"
        self._use_server = self._check_server_available()

        if self._use_server:
            logger.info("embedder_using_server", url=self.server_url, model=self.model_name)
        else:
            logger.info("embedder_using_local_model", model=self.model_name)

    def _check_server_available(self) -> bool:
        try:
            import httpx

            resp = httpx.get(f"{self.server_url}/health", timeout=1.0)
            if resp.status_code != 200:
                return False
            health = resp.json()
            if health.get("model") == self.model_name and health.get("model_loaded"):
                return True
            logger.warning(
                "server_model_mismatch",
                expected=self.model_name,
                actual=health.get("model"),
            )
        except Exception:
            return False
        return False

    def _lazy_model(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RuntimeError("sentence-transformers is required for embeddings") from exc
            logging.getLogger(__name__).info("loading_embedding_model model=%s", self.model_name)
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
        hashes = [self.hash_text(text) for text in texts]
        out: list[tuple[str, list[float]]] = []
        missing_ix = [i for i, h in enumerate(hashes) if h not in self._cache]
        if missing_ix:
            missing_texts = [texts[i] for i in missing_ix]
            if self._use_server:
                vectors = self._embed_via_server(missing_texts)
            else:
                vectors = self._embed_via_local_model(missing_texts)
            for pos, (_, vec) in zip(missing_ix, vectors):
                h = hashes[pos]
                self._cache[h] = vec
        for h in hashes:
            out.append((h, self._cache[h]))
        return out

    def _embed_via_server(self, texts: list[str]) -> list[tuple[str, list[float]]]:
        import httpx

        try:
            resp = httpx.post(
                f"{self.server_url}/embed",
                json={"texts": texts, "batch_size": self.batch_size},
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            embeddings = data.get("embeddings")
            if not isinstance(embeddings, list):
                raise ValueError("Invalid server response: missing embeddings")
            return [(str(h), [float(v) for v in vec]) for h, vec in embeddings]
        except Exception as exc:
            logger.error("server_request_failed", error=str(exc))
            logger.info("falling_back_to_local_model")
            self._use_server = False
            return self._embed_via_local_model(texts)

    def _embed_via_local_model(self, texts: list[str]) -> list[tuple[str, list[float]]]:
        model = self._lazy_model()
        vectors = model.encode(texts, batch_size=self.batch_size)
        result: list[tuple[str, list[float]]] = []
        for text, vec in zip(texts, vectors):
            result.append((self.hash_text(text), self._normalize(vec)))
        return result
