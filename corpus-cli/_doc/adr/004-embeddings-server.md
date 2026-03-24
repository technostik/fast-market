Create a persistent embedding server that runs in a separate process to avoid repeated model loading, while maintaining backward compatibility with the existing `Embedder` interface.

## Architecture Overview
````
┌─────────────────────────────────────────────────────────────┐
│ Current (slow): Load model on every CLI invocation          │
│ corpus search → load model → embed → unload                 │
│ corpus sync   → load model → embed → unload                 │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ New (fast): Persistent server with loaded model             │
│ corpus embed-server start → load model once → keep running  │
│ corpus search → HTTP request to server → instant response   │
│ corpus sync   → HTTP request to server → instant response   │
│ corpus embed-server stop  → shutdown gracefully             │
└─────────────────────────────────────────────────────────────┘
````

## Requirements

### 1. Transparent Interface
- `core/embedder.py` `Embedder` class **public interface MUST NOT change**
- All existing code continues to work without modification
- Auto-detection: if server is running, use it; otherwise fall back to local model

### 2. Server Management Command
- `corpus embed-server start` — launch server in background
- `corpus embed-server stop` — graceful shutdown
- `corpus embed-server status` — health check
- `corpus embed-server restart` — stop + start

### 3. Model Configuration
- Model name configurable via `config.yaml`: `embeddings.model`
- Default: `paraphrase-multilingual-mpnet-base-v2`
- Batch size configurable: `embeddings.batch_size`
- Server port configurable: `embeddings.server_port` (default: 8765)

### 4. Testing Compatibility
- Tests must work with or without server
- `conftest.py` auto-starts server for test session if real embeddings needed
- `DummyEmbedder` bypasses server entirely (fast unit tests)

### 5. Process Management
- Server runs as daemon process
- PID file for tracking: `~/.cache/fast-market/corpus/embedding-server.pid`
- Graceful shutdown on SIGTERM
- Auto-cleanup on crash

## Implementation

### Step 1: Create Embedding Server

Create `core/embedding_server.py`:
````python
"""Persistent embedding server to avoid repeated model loading.

Run as a background process:
    corpus embed-server start

The server loads the sentence-transformers model once and keeps it in memory,
serving embedding requests over HTTP. This eliminates the ~5-10s model load
time on every CLI invocation.
"""

from __future__ import annotations

import json
import logging
import signal
import sys
from pathlib import Path

import structlog
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logger = structlog.get_logger(__name__)


class EmbedRequest(BaseModel):
    texts: list[str]
    batch_size: int = 32


class EmbedResponse(BaseModel):
    embeddings: list[tuple[str, list[float]]]  # [(hash, vector), ...]


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
    
    def _setup_routes(self):
        @self.app.post("/embed", response_model=EmbedResponse)
        def embed(req: EmbedRequest) -> EmbedResponse:
            if self._model is None:
                raise HTTPException(status_code=503, detail="Model not loaded")
            
            from core.embedder import Embedder
            
            # Use static methods for normalization and hashing
            embeddings = []
            vectors = self._model.encode(req.texts, batch_size=req.batch_size)
            
            for text, vector in zip(req.texts, vectors):
                text_hash = Embedder.hash_text(text)
                normalized = Embedder._normalize(vector)
                embeddings.append((text_hash, normalized))
            
            return EmbedResponse(embeddings=embeddings)
        
        @self.app.get("/health")
        def health():
            return {
                "status": "ok",
                "model": self.model_name,
                "model_loaded": self._model is not None,
            }
        
        @self.app.post("/shutdown")
        def shutdown():
            logger.info("shutdown_requested")
            import os
            os.kill(os.getpid(), signal.SIGTERM)
            return {"status": "shutting down"}
    
    def _setup_signal_handlers(self):
        def handle_shutdown(signum, frame):
            logger.info("shutdown_signal_received", signal=signum)
            sys.exit(0)
        
        signal.signal(signal.SIGTERM, handle_shutdown)
        signal.signal(signal.SIGINT, handle_shutdown)
    
    def load_model(self):
        """Load the sentence-transformers model into memory."""
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is required for embedding server. "
                "Install with: pip install 'corpus-agent[ml]'"
            ) from exc
        
        logger.info("loading_model", model=self.model_name)
        self._model = SentenceTransformer(self.model_name)
        logger.info("model_loaded", model=self.model_name)
    
    def run(self):
        """Start the server (blocking)."""
        import uvicorn
        
        logger.info("starting_server", host=self.host, port=self.port, model=self.model_name)
        
        uvicorn.run(
            self.app,
            host=self.host,
            port=self.port,
            log_level="warning",  # Quiet unless errors
            access_log=False,
        )


def main():
    """Entry point for running server directly."""
    import argparse
    
    from core.config import load_config
    
    parser = argparse.ArgumentParser(description="Corpus embedding server")
    parser.add_argument("--model", help="Model name (overrides config)")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, help="Bind port (overrides config)")
    args = parser.parse_args()
    
    # Load config
    config = load_config()
    embeddings_cfg = config.get("embeddings", {})
    
    model_name = args.model or embeddings_cfg.get("model", "paraphrase-multilingual-mpnet-base-v2")
    port = args.port or embeddings_cfg.get("server_port", 8765)
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)-8s] %(message)s",
        stream=sys.stderr,
    )
    
    # Start server
    server = EmbeddingServer(model_name, host=args.host, port=port)
    server.load_model()
    server.run()


if __name__ == "__main__":
    main()
````

### Step 2: Update Embedder Class (Transparent Client)

Modify `core/embedder.py` to auto-detect and use server:
````python
from __future__ import annotations

import hashlib
import logging
import math
from typing import Sequence

logger = logging.getLogger(__name__)


class Embedder:
    """Embedding client with transparent server fallback.
    
    Auto-detects if embedding server is running:
    - If server available: send HTTP requests (fast, no model load)
    - If server unavailable: load model locally (slow, backward compatible)
    
    Public interface unchanged — all existing code continues to work.
    """
    
    def __init__(
        self, 
        model_name: str = "paraphrase-multilingual-mpnet-base-v2", 
        batch_size: int = 32,
        server_url: str | None = None,
    ) -> None:
        self.model_name = model_name
        self.batch_size = batch_size
        self._cache: dict[str, list[float]] = {}
        self._model = None
        
        # Auto-detect server or use provided URL
        if server_url is None:
            from core.config import load_config
            config = load_config()
            embeddings_cfg = config.get("embeddings", {})
            port = embeddings_cfg.get("server_port", 8765)
            server_url = f"http://127.0.0.1:{port}"
        
        self.server_url = server_url
        self._use_server = self._check_server_available()
        
        if self._use_server:
            logger.info("embedder_using_server", url=self.server_url)
        else:
            logger.info("embedder_using_local_model", model=self.model_name)
    
    def _check_server_available(self) -> bool:
        """Check if embedding server is running and healthy."""
        try:
            import httpx
            resp = httpx.get(f"{self.server_url}/health", timeout=1.0)
            if resp.status_code == 200:
                health = resp.json()
                # Verify server has correct model loaded
                if health.get("model") == self.model_name and health.get("model_loaded"):
                    return True
                logger.warning(
                    "server_model_mismatch",
                    expected=self.model_name,
                    actual=health.get("model"),
                )
        except Exception:
            # Server not running or not reachable
            pass
        return False
    
    def _lazy_model(self):
        """Load local model only if server not available."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RuntimeError("sentence-transformers is required for embeddings") from exc
            logger.info("loading_embedding_model model=%s", self.model_name)
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
        """Embed texts using server if available, otherwise local model.
        
        Returns: [(hash, normalized_vector), ...]
        """
        hashes = [self.hash_text(text) for text in texts]
        out: list[tuple[str, list[float]]] = []
        
        # Check cache first
        missing_ix = [i for i, h in enumerate(hashes) if h not in self._cache]
        
        if not missing_ix:
            # All cached
            return [(h, self._cache[h]) for h in hashes]
        
        missing_texts = [texts[i] for i in missing_ix]
        
        # Embed missing texts
        if self._use_server:
            vectors = self._embed_via_server(missing_texts)
        else:
            vectors = self._embed_via_local_model(missing_texts)
        
        # Update cache
        for pos, (text_hash, vec) in zip(missing_ix, vectors):
            self._cache[hashes[pos]] = vec
        
        # Return all (from cache)
        return [(h, self._cache[h]) for h in hashes]
    
    def _embed_via_server(self, texts: list[str]) -> list[tuple[str, list[float]]]:
        """Send embedding request to server."""
        import httpx
        
        try:
            resp = httpx.post(
                f"{self.server_url}/embed",
                json={"texts": texts, "batch_size": self.batch_size},
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["embeddings"]
        except Exception as exc:
            logger.error("server_request_failed", error=str(exc))
            # Fallback to local model
            logger.info("falling_back_to_local_model")
            self._use_server = False
            return self._embed_via_local_model(texts)
    
    def _embed_via_local_model(self, texts: list[str]) -> list[tuple[str, list[float]]]:
        """Embed using locally loaded model."""
        model = self._lazy_model()
        vectors = model.encode(texts, batch_size=self.batch_size)
        
        result = []
        for text, vec in zip(texts, vectors):
            text_hash = self.hash_text(text)
            normalized = self._normalize(vec)
            result.append((text_hash, normalized))
        
        return result
````

### Step 3: Create Server Management Command

Create `commands/embed_server/`:
````
commands/embed_server/
├── __init__.py
├── AGENTS.md
└── register.py
````

**`commands/embed_server/register.py`:**
````python
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import click

from commands.base import CommandManifest
from core.paths import get_tool_cache_dir


def _pid_file() -> Path:
    """Path to PID file for embedding server."""
    return get_tool_cache_dir("corpus") / "embedding-server.pid"


def _is_running() -> tuple[bool, int | None]:
    """Check if server is running.
    
    Returns: (is_running, pid)
    """
    pid_file = _pid_file()
    if not pid_file.exists():
        return False, None
    
    try:
        pid = int(pid_file.read_text().strip())
    except (ValueError, OSError):
        return False, None
    
    # Check if process exists
    try:
        os.kill(pid, 0)  # Signal 0 just checks existence
        return True, pid
    except ProcessLookupError:
        # PID file exists but process is dead
        pid_file.unlink()
        return False, None


def _check_health(port: int, timeout: float = 2.0) -> bool:
    """Check if server is healthy via HTTP."""
    try:
        import httpx
        resp = httpx.get(f"http://127.0.0.1:{port}/health", timeout=timeout)
        return resp.status_code == 200
    except Exception:
        return False


def register(plugin_manifests: dict) -> CommandManifest:
    @click.group("embed-server")
    def embed_server_group():
        """Manage the persistent embedding server."""
        pass
    
    @embed_server_group.command("start")
    @click.option("--model", help="Model name (overrides config)")
    @click.option("--port", type=int, help="Server port (overrides config)")
    @click.pass_context
    def start_cmd(ctx, model, port):
        """Start the embedding server in background."""
        from core.config import load_config
        
        is_running, pid = _is_running()
        if is_running:
            click.echo(f"Embedding server already running (PID {pid})")
            return
        
        # Load config
        config = load_config()
        embeddings_cfg = config.get("embeddings", {})
        model_name = model or embeddings_cfg.get("model", "paraphrase-multilingual-mpnet-base-v2")
        server_port = port or embeddings_cfg.get("server_port", 8765)
        
        # Build command
        cmd = [
            sys.executable, "-m", "core.embedding_server",
            "--model", model_name,
            "--port", str(server_port),
        ]
        
        # Start in background
        click.echo(f"Starting embedding server (model: {model_name}, port: {server_port})...")
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # Detach from parent
        )
        
        # Write PID file
        _pid_file().write_text(str(process.pid))
        
        # Wait for health check
        click.echo("Waiting for server to be ready...", nl=False)
        for _ in range(30):  # 30 second timeout
            time.sleep(1)
            if _check_health(server_port):
                click.echo(" ✓")
                click.echo(f"Embedding server started successfully (PID {process.pid})")
                return
            click.echo(".", nl=False)
        
        click.echo(" ✗")
        click.echo("Server failed to start within 30 seconds", err=True)
        sys.exit(1)
    
    @embed_server_group.command("stop")
    def stop_cmd():
        """Stop the embedding server gracefully."""
        is_running, pid = _is_running()
        if not is_running:
            click.echo("Embedding server is not running")
            return
        
        click.echo(f"Stopping embedding server (PID {pid})...")
        
        try:
            # Try graceful shutdown via HTTP first
            import httpx
            from core.config import load_config
            
            config = load_config()
            port = config.get("embeddings", {}).get("server_port", 8765)
            
            try:
                httpx.post(f"http://127.0.0.1:{port}/shutdown", timeout=2.0)
            except Exception:
                pass
            
            # Wait for graceful shutdown
            time.sleep(2)
            
            # Check if still running
            try:
                os.kill(pid, 0)
                # Still running, send SIGTERM
                os.kill(pid, signal.SIGTERM)
                time.sleep(2)
            except ProcessLookupError:
                pass
            
            # Force kill if still alive
            try:
                os.kill(pid, 0)
                os.kill(pid, signal.SIGKILL)
                click.echo("Server forcefully terminated")
            except ProcessLookupError:
                click.echo("Server stopped successfully")
            
        except Exception as exc:
            click.echo(f"Error stopping server: {exc}", err=True)
            sys.exit(1)
        finally:
            # Clean up PID file
            _pid_file().unlink(missing_ok=True)
    
    @embed_server_group.command("status")
    def status_cmd():
        """Check embedding server status."""
        from core.config import load_config
        
        is_running, pid = _is_running()
        
        config = load_config()
        embeddings_cfg = config.get("embeddings", {})
        port = embeddings_cfg.get("server_port", 8765)
        model = embeddings_cfg.get("model", "paraphrase-multilingual-mpnet-base-v2")
        
        if not is_running:
            click.echo("Status: NOT RUNNING")
            click.echo(f"Expected: {model} on port {port}")
            return
        
        click.echo(f"Status: RUNNING (PID {pid})")
        
        # Check health
        if _check_health(port):
            import httpx
            resp = httpx.get(f"http://127.0.0.1:{port}/health")
            health = resp.json()
            click.echo(f"Health: OK")
            click.echo(f"Model: {health['model']}")
            click.echo(f"Port: {port}")
        else:
            click.echo("Health: UNREACHABLE (process exists but not responding)")
    
    @embed_server_group.command("restart")
    @click.pass_context
    def restart_cmd(ctx):
        """Restart the embedding server."""
        ctx.invoke(stop_cmd)
        time.sleep(1)
        ctx.invoke(start_cmd)
    
    return CommandManifest(
        name="embed-server",
        click_command=embed_server_group,
    )
````

**`commands/embed_server/AGENTS.md`:**
````markdown
# commands/embed-server/

Manages the persistent embedding server daemon process.

## Purpose
Start/stop a background server that keeps the sentence-transformers model loaded,
eliminating the ~5-10s model load time on every CLI invocation.

## Commands
- `corpus embed-server start` — Launch server in background
- `corpus embed-server stop` — Graceful shutdown
- `corpus embed-server status` — Health check
- `corpus embed-server restart` — Stop + start

## How It Works
1. Server loads model once on startup
2. All `corpus` commands send HTTP requests to server
3. Model stays in memory until server is stopped
4. Transparent fallback to local model if server unavailable

## Configuration
Add to `~/.local/share/fast-market/config/corpus.yaml`:
```yaml
embeddings:
  model: paraphrase-multilingual-mpnet-base-v2
  server_port: 8765
  batch_size: 32
```

## Process Management
- PID file: `~/.cache/fast-market/corpus/embedding-server.pid`
- Server runs as detached daemon
- Graceful shutdown on SIGTERM/SIGINT
- Auto-cleanup on crash (stale PID removal)

## Usage Examples
```bash
# Start server
corpus embed-server start

# Check if running
corpus embed-server status

# Now all commands use the server (fast!)
corpus sync --source youtube --limit 10
corpus search "topic"

# Stop server
corpus embed-server stop
```

## Backward Compatibility
- If server not running, Embedder falls back to local model
- All existing code works without changes
- Tests work with or without server
````

### Step 4: Update Configuration Schema

Document in `README.md` and example configs:
````yaml
embeddings:
  # Model name (any sentence-transformers compatible model)
  model: paraphrase-multilingual-mpnet-base-v2
  
  # Embedding server port (default: 8765)
  server_port: 8765
  
  # Batch size for encoding (default: 32)
  batch_size: 32
````

### Step 5: Update Tests

Modify `tests/conftest.py`:
````python
import pytest
import subprocess
import time
from pathlib import Path


# Session-scoped server management
_server_process = None


def _start_test_server():
    """Start embedding server for test session."""
    global _server_process
    
    # Check if we should use real embeddings
    import os
    if os.environ.get("USE_DUMMY_EMBEDDER", "1") == "1":
        return  # Skip server, use DummyEmbedder
    
    import sys
    from core.paths import get_tool_cache_dir
    
    port = 18765  # Different port for tests
    pid_file = get_tool_cache_dir("corpus") / "embedding-server-test.pid"
    
    # Clean up stale PID
    if pid_file.exists():
        pid_file.unlink()
    
    cmd = [
        sys.executable, "-m", "core.embedding_server",
        "--model", "paraphrase-MiniLM-L3-v2",  # Smaller model for tests
        "--port", str(port),
    ]
    
    _server_process = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    
    pid_file.write_text(str(_server_process.pid))
    
    # Wait for server
    import httpx
    for _ in range(30):
        try:
            resp = httpx.get(f"http://127.0.0.1:{port}/health", timeout=1.0)
            if resp.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(1)
    
    raise RuntimeError("Test embedding server failed to start")


def _stop_test_server():
    """Stop test embedding server."""
    global _server_process
    
    if _server_process is None:
        return
    
    try:
        _server_process.terminate()
        _server_process.wait(timeout=5)
    except Exception:
        _server_process.kill()
    
    from core.paths import get_tool_cache_dir
    pid_file = get_tool_cache_dir("corpus") / "embedding-server-test.pid"
    pid_file.unlink(missing_ok=True)


@pytest.fixture(scope="session", autouse=True)
def embedding_server():
    """Auto-start/stop embedding server for test session."""
    _start_test_server()
    yield
    _stop_test_server()


# Existing fixtures...

@pytest.fixture
def embedder() -> DummyEmbedder:
    """Fast dummy embedder for unit tests (bypasses server)."""
    return DummyEmbedder()


@pytest.fixture
def config_dict(tmp_path: Path, vault: Path) -> dict:
    """Add embeddings config."""
    return {
        "db_path": str(tmp_path / "test.db"),
        "embed_batch_size": 2,
        "embeddings": {
            "model": "paraphrase-MiniLM-L3-v2",
            "server_port": 18765,  # Test port
            "batch_size": 2,
        },
        "obsidian": {"vault_path": str(vault)},
        "youtube": {"channel_id": "UC_fake", "client_secret_path": ""},
    }
````

### Step 6: Add httpx Dependency

Update `pyproject.toml`:
````toml
[project]
dependencies = [
  "click>=8.1",
  "fastapi>=0.115",
  "uvicorn>=0.30",
  "structlog>=24.2",
  "pyyaml>=6.0",
  "httpx>=0.27",  # NEW: for embedding server client
]
````

### Step 7: Update pyproject.toml Packages
````toml
[tool.setuptools]
packages = [
  # ... existing ...
  "commands.embed_server",
]
````

### Step 8: Add Tests

Create `tests/test_embed_server.py`:
````python
from __future__ import annotations

import time

from click.testing import CliRunner

from cli.main import main


def test_embed_server_lifecycle(tmp_path, monkeypatch):
    """Test start/stop/status/restart commands."""
    # Use test-specific port and PID file
    from core.paths import get_tool_cache_dir
    
    monkeypatch.setenv("USE_DUMMY_EMBEDDER", "0")  # Use real server
    
    runner = CliRunner()
    
    # Status when not running
    result = runner.invoke(main, ["embed-server", "status"])
    assert "NOT RUNNING" in result.output
    
    # Start server
    result = runner.invoke(main, ["embed-server", "start", "--port", "28765"])
    assert result.exit_code == 0
    assert "started successfully" in result.output.lower()
    
    # Status when running
    result = runner.invoke(main, ["embed-server", "status"])
    assert "RUNNING" in result.output
    assert "Health: OK" in result.output
    
    # Stop server
    result = runner.invoke(main, ["embed-server", "stop"])
    assert result.exit_code == 0
    
    time.sleep(1)
    
    # Status after stop
    result = runner.invoke(main, ["embed-server", "status"])
    assert "NOT RUNNING" in result.output


def test_embedder_uses_server(mock_env, monkeypatch):
    """Test that Embedder uses server when available."""
    monkeypatch.setenv("USE_DUMMY_EMBEDDER", "0")
    
    from core.embedder import Embedder
    
    # Start server
    runner = CliRunner()
    runner.invoke(main, ["embed-server", "start", "--port", "28765"])
    
    time.sleep(2)
    
    # Create embedder (should detect server)
    embedder = Embedder(server_url="http://127.0.0.1:28765")
    assert embedder._use_server is True
    
    # Embed texts
    results = embedder.embed_texts(["hello", "world"])
    assert len(results) == 2
    assert all(len(vec) > 0 for _, vec in results)
    
    # Stop server
    runner.invoke(main, ["embed-server", "stop"])


def test_embedder_fallback_without_server(mock_env, monkeypatch):
    """Test that Embedder falls back to local model when server unavailable."""
    monkeypatch.setenv("USE_DUMMY_EMBEDDER", "1")  # Use dummy
    
    from core.embedder import Embedder
    
    # Embedder with unreachable server
    embedder = Embedder(server_url="http://127.0.0.1:99999")
    assert embedder._use_server is False
    
    # Should still work via local model
    results = embedder.embed_texts(["test"])
    assert len(results) == 1
````

## Critical Implementation Rules

### 1. Backward Compatibility
- ✅ **DO** keep `Embedder.embed_texts()` signature unchanged
- ✅ **DO** auto-detect server and fall back gracefully
- ✅ **DO** ensure all existing tests pass
- ❌ **DON'T** require server for basic functionality

### 2. Process Management
- ✅ **DO** use PID file for tracking
- ✅ **DO** handle stale PID cleanup
- ✅ **DO** graceful shutdown (SIGTERM before SIGKILL)
- ❌ **DON'T** leave zombie processes

### 3. Testing
- ✅ **DO** use `DummyEmbedder` for fast unit tests
- ✅ **DO** auto-start server for integration tests if needed
- ✅ **DO** clean up server on test session end
- ❌ **DON'T** require server for CI/CD tests (use dummy)

### 4. Error Handling
- ✅ **DO** fail loudly on server errors
- ✅ **DO** log server usage with structlog
- ✅ **DO** provide clear error messages
- ❌ **DON'T** silently fall back without logging

### 5. Configuration
- ✅ **DO** use existing config system
- ✅ **DO** provide sensible defaults
- ✅ **DO** validate model compatibility
- ❌ **DON'T** hardcode ports or paths

## Documentation Updates

### README.md

Add section:
````markdown
## Performance: Embedding Server

To avoid repeated model loading (5-10s each time), start a persistent embedding server:
```bash
# Start server (loads model once)
corpus embed-server start

# All commands now use the server (fast!)
corpus sync --source youtube --limit 50
corpus search "topic"

# Check server status
corpus embed-server status

# Stop when done
corpus embed-server stop
```

Configure in `corpus.yaml`:
```yaml
embeddings:
  model: paraphrase-multilingual-mpnet-base-v2  # Any sentence-transformers model
  server_port: 8765
  batch_size: 32
```

**Backward compatible**: If server not running, commands fall back to loading model locally.
````

## Testing Checklist

- [ ] `corpus embed-server start` launches server
- [ ] `corpus embed-server status` shows health
- [ ] `corpus embed-server stop` gracefully shuts down
- [ ] `corpus embed-server restart` works
- [ ] `Embedder` auto-detects server
- [ ] `Embedder` falls back to local model if server unavailable
- [ ] All existing tests pass with `DummyEmbedder`
- [ ] Integration tests work with real server
- [ ] Server survives parent process exit (daemon)
- [ ] Stale PID files are cleaned up
- [ ] Model mismatch is detected and logged
- [ ] Multiple sequential commands reuse server (fast)
- [ ] Config changes (model, port) are respected

## Follow Project Golden Rules

- **DRY**: Reuse `Embedder._normalize()` and `hash_text()` in server
- **KISS**: Simple HTTP API, simple process management
- **CODE IS LAW**: Server implementation documents the protocol
- **FAIL LOUDLY**: Server startup errors are clear
- **Modularity**: Server can be deleted without breaking core
- **Observability**: Log server usage, fallback decisions
- **Provability**: Tests verify server lifecycle and fallback

## Success Criteria

1. ✅ First `corpus sync` takes ~10s (model load)
2. ✅ Subsequent commands take <1s (server request)
3. ✅ All existing code works without changes
4. ✅ Tests run fast with `DummyEmbedder`
5. ✅ Integration tests use real server automatically
6. ✅ Server survives CLI invocations
7. ✅ Graceful degradation when server unavailable

Implement following the project's architectural patterns from `.doc/skills/HOW_TO_ADD_A_COMMAND.md` and maintain backward compatibility with all existing code.
