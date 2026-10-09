from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

MODEL_CACHE_TTL_SECS = 24 * 3600

PLATFORM_MODELS_URL = "https://api.fal.ai/v1/models"


@dataclass
class FalModel:
    """One curated fal.ai video model with text- and image-to-video endpoints."""

    alias: str
    label: str
    text_endpoint: str
    image_endpoint: str
    default_duration: int = 5
    supports_audio: bool = True
    free_tier_note: str = ""
    # True when fal offers free daily generations for this model in the
    # web sandbox/playground. Sandbox-free is NOT API-free: API calls are
    # pay-per-use, and the Platform API exposes no free-quota counter, so
    # this flag only powers `--list-models --free-only` curation.
    sandbox_free: bool = False


#: Curated fallback chain, sandbox-free models first.
#: Endpoint IDs verified against GET api.fal.ai/v1/models (Oct 2026).
#: fal.ai exposes no "remaining free generations" counter, so `auto`
#: selection = first endpoint in this list that does not fail with a
#: quota/billing error (see fal.is_quota_error). The model actually used
#: is always echoed to stderr.
MODEL_CATALOG: list[FalModel] = [
    FalModel(
        alias="minimax",
        label="MiniMax H3 Max (768p, native audio, up to 15s)",
        text_endpoint="minimax/h3-max/text-to-video",
        image_endpoint="minimax/h3-max/image-to-video",
        default_duration=5,
        supports_audio=True,
        free_tier_note="5 free generations/day via fal sandbox (playground); API calls are pay-per-use",
        sandbox_free=True,
    ),
    FalModel(
        alias="flux",
        label="FLUX 3 draft (720p draft render with audio; preview quality)",
        text_endpoint="blackforestlabs/flux-3/text-to-video/draft",
        image_endpoint="blackforestlabs/flux-3/image-to-video/draft",
        default_duration=5,
        supports_audio=True,
        free_tier_note="5 free generations/day via fal sandbox (playground); API calls are pay-per-use",
        sandbox_free=True,
    ),
    FalModel(
        alias="kling",
        label="Kling v3 Standard (720p, native audio)",
        text_endpoint="fal-ai/kling-video/v3/standard/text-to-video",
        image_endpoint="fal-ai/kling-video/v3/standard/image-to-video",
        default_duration=5,
        supports_audio=True,
        free_tier_note="pay-per-use",
    ),
    FalModel(
        alias="ltx",
        label="LTX 2.3 22B (fast tier)",
        text_endpoint="fal-ai/ltx-2.3-22b/text-to-video",
        image_endpoint="fal-ai/ltx-2.3-22b/image-to-video",
        default_duration=5,
        supports_audio=False,
        free_tier_note="pay-per-use, cheap/fast",
    ),
]


def get_aliases() -> list[str]:
    return [m.alias for m in MODEL_CATALOG]


def free_models() -> list[FalModel]:
    """Curated models with a free daily sandbox allowance."""
    return [m for m in MODEL_CATALOG if m.sandbox_free]


def resolve_candidate_endpoints(model: str, has_image: bool) -> list[str]:
    """Resolve `--model` to an ordered list of endpoint IDs to try.

    - ``"auto"`` → every catalog endpoint in order (text or image variant).
    - ``"<alias>"`` → that catalog entry's text or image endpoint.
    - anything containing ``"/"`` → treated as a literal endpoint ID (custom).
    """
    if model == "auto":
        return [
            m.image_endpoint if has_image else m.text_endpoint
            for m in MODEL_CATALOG
        ]
    for m in MODEL_CATALOG:
        if model == m.alias:
            return [m.image_endpoint if has_image else m.text_endpoint]
    if "/" in model:
        return [model]
    raise ValueError(
        f"Unknown model {model!r}. Use 'auto', one of {get_aliases()}, "
        "or a full fal endpoint ID containing '/'."
    )


def build_payload(
    prompt: str,
    *,
    image_url: str | None = None,
    duration: int | None = None,
    aspect_ratio: str | None = None,
    seed: int | None = None,
    negative_prompt: str | None = None,
    extra: dict | None = None,
) -> dict:
    """Build a minimal cross-model request payload.

    Only widely-accepted keys are sent; model-specific tuning goes through
    the ``--set KEY=VALUE`` passthrough (``extra``), which wins on conflict.
    """
    payload: dict = {"prompt": prompt}
    if image_url:
        payload["image_url"] = image_url
    if duration is not None:
        payload["duration"] = duration
    if aspect_ratio is not None:
        payload["aspect_ratio"] = aspect_ratio
    if seed is not None:
        payload["seed"] = seed
    if negative_prompt:
        payload["negative_prompt"] = negative_prompt
    if extra:
        payload.update(extra)
    return payload


def parse_set_option(values: tuple[str, ...]) -> dict:
    """Parse repeated ``--set KEY=VALUE`` options with light type coercion."""
    extra: dict = {}
    for item in values:
        if "=" not in item:
            raise ValueError(
                f"Invalid --set value {item!r}: expected KEY=VALUE"
            )
        key, raw = item.split("=", 1)
        key = key.strip()
        raw = raw.strip()
        if not key:
            raise ValueError(f"Invalid --set value {item!r}: empty key")
        extra[key] = _coerce_scalar(raw)
    return extra


def _coerce_scalar(raw: str):
    lowered = raw.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


def _cache_path() -> Path:
    return Path.home() / ".cache" / "fast-market" / "video" / "fal_models.json"


def _read_cache(max_age_secs: int = MODEL_CACHE_TTL_SECS) -> list[dict] | None:
    path = _cache_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    fetched_at = raw.get("fetched_at", 0)
    if time.time() - fetched_at > max_age_secs:
        return None
    models = raw.get("models")
    return models if isinstance(models, list) else None


def _write_cache(models: list[dict]) -> Path:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"fetched_at": time.time(), "models": models}, indent=2
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def fetch_models(
    *,
    api_key: str | None = None,
    category: str = "text-to-video",
    limit: int = 50,
    force_refresh: bool = False,
) -> tuple[list[dict], bool]:
    """Auto-discover fal.ai video models via the Platform Models API.

    Returns ``(models, from_cache)``. Raises ``RuntimeError`` on HTTP/API
    failure. Auth is optional (higher rate limits with a key).
    """
    import requests

    if not force_refresh:
        cached = _read_cache()
        if cached is not None:
            return cached, True
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Key {api_key}"
    resp = requests.get(
        PLATFORM_MODELS_URL,
        params={"category": category, "limit": limit, "status": "active"},
        headers=headers,
        timeout=30,
    )
    if resp.status_code >= 400:
        raise RuntimeError(
            f"fal model discovery failed (HTTP {resp.status_code}): "
            f"{resp.text.strip()[:300]}"
        )
    try:
        data = resp.json()
    except ValueError as exc:
        raise RuntimeError(f"fal model discovery returned invalid JSON: {exc}") from exc
    models = data.get("models", data if isinstance(data, list) else [])
    if not isinstance(models, list):
        raise RuntimeError("fal model discovery returned an unexpected payload")
    _write_cache(models)
    return models, False


def format_model_listing(models: list[dict]) -> str:
    lines = []
    for entry in models:
        if isinstance(entry, dict):
            endpoint = entry.get("endpoint_id", "?")
            meta = entry.get("metadata", {}) if isinstance(entry.get("metadata"), dict) else {}
            name = meta.get("display_name", "") or entry.get("display_name", "")
            lines.append(f"{endpoint}  {name}".rstrip())
        else:
            lines.append(str(entry))
    return "\n".join(lines)
