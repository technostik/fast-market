from __future__ import annotations

import base64
import json as _json
import os
import subprocess
import tempfile
from pathlib import Path

import click

GROQ_MODEL = "whisper-large-v3-turbo"
CLOUDFLARE_MODEL = "@cf/openai/whisper-large-v3-turbo"

ENGINES = ("auto", "local", "groq", "cloudflare", "modal")


def _load_env() -> None:
    """Best-effort load of repo .env so GROQ/CLOUDFLARE keys work out of the box."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    # sound-cli/commands/transcribe/analysis.py -> 3 levels up = repo root (fast-market)
    candidates = [
        Path(__file__).resolve().parents[3] / ".env",
        Path.cwd() / ".env",
    ]
    for env_path in candidates:
        try:
            if env_path.exists():
                load_dotenv(env_path, override=False)
        except Exception:
            pass


def _require_ffmpeg() -> str:
    import shutil

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise click.ClickException("ffmpeg not found in PATH — required to extract audio.")
    return ffmpeg


def _device() -> str:
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _extract_audio(src: str, dst: str, sr: int = 16000) -> None:
    ffmpeg = _require_ffmpeg()
    subprocess.run(
        [ffmpeg, "-y", "-i", src, "-vn", "-ac", "1", "-ar", str(sr), "-b:a", "64k", dst],
        check=True,
        capture_output=True,
    )


def _probe_duration(path: str) -> float | None:
    import shutil

    if not shutil.which("ffprobe"):
        return None
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", path],
            text=True,
        )
        return float(_json.loads(out)["format"]["duration"])
    except Exception:
        return None


def cloudflare_credentials(config: dict | None = None) -> tuple[str, str]:
    """Return (account_id, api_token) from env first, then sound config fallback."""
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
    api_token = os.environ.get("CLOUDFLARE_API_TOKEN", "")
    if account_id and api_token:
        return account_id, api_token
    cfg = (config or {}).get("transcribe", {}) if isinstance(config, dict) else {}
    cf = cfg.get("cloudflare", {}) if isinstance(cfg, dict) else {}
    if isinstance(cf, dict):
        account_id = account_id or str(cf.get("account_id", "") or "")
        api_token = api_token or str(cf.get("api_token", "") or "")
    return account_id, api_token


def resolve_engine(requested: str, config: dict | None = None) -> str:
    """Resolve 'auto' to groq > cloudflare > local. Explicit values pass through."""
    _load_env()
    if requested != "auto":
        return requested
    if os.environ.get("GROQ_API_KEY", ""):
        return "groq"
    account_id, api_token = cloudflare_credentials(config)
    if account_id and api_token:
        return "cloudflare"
    return "local"


# ── Local (faster-whisper) ────────────────────────────────────────────────────


def transcribe_local(path: str, model_size: str, language: str) -> dict:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise click.ClickException(
            "faster-whisper not installed (required for --engine local). "
            "Install with: pip install 'sound-agent[transcribe]'"
        ) from exc

    device = _device()
    compute_type = "float16" if device == "cuda" else "int8"
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    lang = None if language in ("auto", "", None) else language
    segments_iter, info = model.transcribe(path, language=lang)
    segments = [
        {"start": float(seg.start), "end": float(seg.end), "text": (seg.text or "").strip()}
        for seg in segments_iter
        if (seg.text or "").strip()
    ]
    detected = getattr(info, "language", "en") or "en"
    text = " ".join(s["text"] for s in segments).strip()
    return {"language": detected, "text": text, "segments": segments}


# ── Groq (hosted whisper-large-v3-turbo) ──────────────────────────────────────


def transcribe_groq(path: str, language: str, model: str = GROQ_MODEL) -> dict:
    import requests

    _load_env()
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        raise click.ClickException(
            "GROQ_API_KEY environment variable not set (required for --engine groq)."
        )

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as _tmp:
        tmp_audio = _tmp.name
    try:
        _extract_audio(path, tmp_audio)
        form_data = [
            ("model", model),
            ("response_format", "verbose_json"),
            ("timestamp_granularities[]", "segment"),
        ]
        if language and language != "auto":
            form_data.append(("language", language))
        with open(tmp_audio, "rb") as f:
            resp = requests.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": (os.path.basename(tmp_audio), f, "audio/mpeg")},
                data=form_data,
                timeout=300,
            )
        resp.raise_for_status()
        result = resp.json()
    except requests.exceptions.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 0
        body = (exc.response.text if exc.response is not None else "")[:500]
        raise click.ClickException(f"Groq API error HTTP {status}: {body}") from exc
    finally:
        try:
            os.unlink(tmp_audio)
        except Exception:
            pass

    raw_segments = result.get("segments", [])
    segments = [
        {
            "start": float(seg["start"]),
            "end": float(seg["end"]),
            "text": str(seg.get("text", "")).strip(),
        }
        for seg in raw_segments
        if str(seg.get("text", "")).strip()
    ]
    text = str(result.get("text", "") or "").strip()
    if not text and segments:
        text = " ".join(s["text"] for s in segments).strip()
    return {
        "language": result.get("language", language if language != "auto" else "en"),
        "text": text,
        "segments": segments,
    }


# ── Cloudflare Workers AI (@cf/openai/whisper-large-v3-turbo) ────────────────


def transcribe_cloudflare(
    path: str,
    language: str,
    account_id: str,
    api_token: str,
    model: str = CLOUDFLARE_MODEL,
) -> dict:
    import requests

    if not account_id or not api_token:
        raise click.ClickException(
            "Cloudflare credentials missing (required for --engine cloudflare). "
            "Set CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN in the environment or .env, "
            "or transcribe.cloudflare.{account_id,api_token} in sound config."
        )

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as _tmp:
        tmp_audio = _tmp.name
    try:
        _extract_audio(path, tmp_audio)
        audio_b64 = base64.b64encode(Path(tmp_audio).read_bytes()).decode("ascii")
        payload: dict = {"audio": audio_b64, "task": "transcribe"}
        if language and language != "auto":
            payload["language"] = language
        url = (
            f"https://api.cloudflare.com/client/v4/accounts/"
            f"{account_id}/ai/run/{model}"
        )
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {api_token}"},
            json=payload,
            timeout=300,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 0
        body = (exc.response.text if exc.response is not None else "")[:500]
        raise click.ClickException(f"Cloudflare API error HTTP {status}: {body}") from exc
    finally:
        try:
            os.unlink(tmp_audio)
        except Exception:
            pass

    if not data.get("success"):
        raise click.ClickException(f"Cloudflare API returned failure: {data.get('errors', [])}")
    result = data.get("result", {}) or {}
    text = str(result.get("text", "") or "").strip()
    words = result.get("words", []) or []
    if words:
        segments = [
            {
                "start": float(w.get("start", 0.0)),
                "end": float(w.get("end", 0.0)),
                "text": str(w.get("word", "") or w.get("text", "")).strip(),
            }
            for w in words
            if str(w.get("word", "") or w.get("text", "")).strip()
        ]
    else:
        duration = _probe_duration(path)
        segments = (
            [{"start": 0.0, "end": duration, "text": text}]
            if text and duration
            else ([{"start": 0.0, "end": 0.0, "text": text}] if text else [])
        )
    return {"language": language if language != "auto" else "en", "text": text, "segments": segments}


# ── Formatting ────────────────────────────────────────────────────────────────


def _fmt_srt_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds % 1) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(segments: list[dict]) -> str:
    lines: list[str] = []
    for i, seg in enumerate(segments, 1):
        lines.append(str(i))
        lines.append(f"{_fmt_srt_time(seg['start'])} --> {_fmt_srt_time(seg['end'])}")
        lines.append(str(seg["text"]).strip())
        lines.append("")
    return "\n".join(lines).strip() + ("\n" if lines else "")
