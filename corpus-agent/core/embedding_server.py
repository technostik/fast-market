"""Persistent embedding server to avoid repeated model loading."""

from __future__ import annotations

import logging
import os
import signal
import sys

import structlog
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logger = structlog.get_logger(__name__)


class EmbedRequest(BaseModel):
    texts: list[str]
    batch_size: int = 32


class EmbedResponse(BaseModel):
    embeddings: list[tuple[str, list[float]]]


class EmbeddingServer:
    """FastAPI server that keeps sentence-transformers model loaded."""

    def __init__(self, model_name: str, host: str = "127.0.0.1", port: int = 8765):
        self.model_name = model_name
        self.host = host
        self.port = port
        self.app = FastAPI(title="Corpus Embedding Server")
        self._model = None
        self._setup_routes()
        self._setup_signal_handlers()

    def _setup_routes(self) -> None:
        @self.app.post("/embed", response_model=EmbedResponse)
        def embed(req: EmbedRequest) -> EmbedResponse:
            if self._model is None:
                raise HTTPException(status_code=503, detail="Model not loaded")

            from core.embedder import Embedder

            vectors = self._model.encode(req.texts, batch_size=req.batch_size)
            embeddings: list[tuple[str, list[float]]] = []
            for text, vector in zip(req.texts, vectors):
                embeddings.append((Embedder.hash_text(text), Embedder._normalize(vector)))
            return EmbedResponse(embeddings=embeddings)

        @self.app.get("/health")
        def health() -> dict[str, object]:
            return {
                "status": "ok",
                "model": self.model_name,
                "model_loaded": self._model is not None,
            }

        @self.app.post("/shutdown")
        def shutdown() -> dict[str, str]:
            logger.info("shutdown_requested")
            os.kill(os.getpid(), signal.SIGTERM)
            return {"status": "shutting_down"}

    def _setup_signal_handlers(self) -> None:
        def handle_shutdown(signum, frame):
            logger.info("shutdown_signal_received", signal=signum)
            sys.exit(0)

        signal.signal(signal.SIGTERM, handle_shutdown)
        signal.signal(signal.SIGINT, handle_shutdown)

    def load_model(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is required for embedding server. Install with: pip install 'corpus-agent[ml]'"
            ) from exc

        logger.info("loading_model", model=self.model_name)
        self._model = SentenceTransformer(self.model_name)
        logger.info("model_loaded", model=self.model_name)

    def run(self) -> None:
        import uvicorn

        logger.info("starting_server", host=self.host, port=self.port, model=self.model_name)
        uvicorn.run(self.app, host=self.host, port=self.port, log_level="warning", access_log=False)


def main() -> None:
    import argparse

    from common.core.config import load_config

    parser = argparse.ArgumentParser(description="Corpus embedding server")
    parser.add_argument("--model", help="Model name override")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, help="Port override")
    args = parser.parse_args()

    config = load_config()
    embeddings_cfg = config.get("embeddings", {})
    if not isinstance(embeddings_cfg, dict):
        embeddings_cfg = {}

    model_name = str(args.model or embeddings_cfg.get("model", "paraphrase-multilingual-mpnet-base-v2"))
    port = int(args.port or embeddings_cfg.get("server_port", 8765))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)-8s] %(message)s",
        stream=sys.stderr,
    )

    server = EmbeddingServer(model_name=model_name, host=args.host, port=port)
    server.load_model()
    server.run()


if __name__ == "__main__":
    main()
