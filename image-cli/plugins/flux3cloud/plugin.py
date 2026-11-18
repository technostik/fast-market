"""FLUX.3 [klein] via the Cloudflare Unified AI catalog.

Unlike the Workers AI models (`@cf/...`, called as
`/ai/run/<model>` with multipart/form-data), FLUX.3 Klein is a
*Unified catalog* model: the model id has no `@cf/` prefix and the
request is a single JSON POST to `/ai/run`:

    POST /client/v4/accounts/<account>/ai/run
    {"model": "black-forest-labs/flux-3-image-klein",
     "input": {"prompt": "...", "resolution": "1k", "aspect_ratio": "16:9"}}

The response is not base64: it carries a URI for the generated image,
which has to be downloaded before we can save it.

Input schema (see developers.cloudflare.com/ai/models/black-forest-labs/
flux-3-image-klein): prompt (required), images[] (up to 10 URIs),
aspect_ratio, resolution (768sq/1k/1.5k/2k/4k), seed. There is no
width/height, no steps and no guidance — the requested size is mapped
onto the closest aspect ratio + resolution bucket, then the downloaded
image is resized to the exact size the CLI asked for.
"""

from __future__ import annotations

import base64
import io
import json
import math
import random
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from PIL import Image

from core.models import EngineConfig, ImageGenRequest
from plugins.base import ImageEnginePlugin
from plugins.flux2cloud.plugin import apply_cloudflare_credentials

#: Unified catalog model id. No "@cf/" prefix: this is not a Workers AI model.
CF_MODEL = "black-forest-labs/flux-3-image-klein"

#: Socket timeout for the generation POST and for the image download.
API_TIMEOUT = 180
DOWNLOAD_TIMEOUT = 120

#: `resolution` enum from the Cloudflare schema, with the long edge it covers.
RESOLUTION_BUCKETS: tuple[tuple[int, str], ...] = (
    (768, "768sq"),
    (1024, "1k"),
    (1536, "1.5k"),
    (2048, "2k"),
)
RESOLUTION_MAX = "4k"

#: `aspect_ratio` enum from the Cloudflare schema.
ASPECT_RATIOS: tuple[str, ...] = (
    "21:9",
    "2:1",
    "16:9",
    "3:2",
    "7:5",
    "4:3",
    "5:4",
    "1:1",
    "4:5",
    "3:4",
    "5:7",
    "2:3",
    "9:16",
    "1:2",
    "9:21",
)

MAX_REFERENCE_IMAGES = 10


def resolution_for(width: int, height: int) -> str:
    """Smallest resolution bucket whose long edge covers the request."""
    long_edge = max(width, height)
    for edge, name in RESOLUTION_BUCKETS:
        if long_edge <= edge:
            return name
    return RESOLUTION_MAX


def aspect_ratio_for(width: int, height: int) -> str:
    """Closest allowed aspect ratio, compared in log space."""
    if width <= 0 or height <= 0:
        return "1:1"
    target = math.log(width / height)
    return min(
        ASPECT_RATIOS,
        key=lambda ratio: abs(target - math.log(int(ratio.split(":")[0]) / int(ratio.split(":")[1]))),
    )


def _to_data_uri(image: Image.Image) -> str:
    """Encode a reference image as a data URI (the API takes URIs, not uploads)."""
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


class Flux3CloudEnginePlugin(ImageEnginePlugin):
    """FLUX.3 Image Klein via the Cloudflare Unified AI catalog."""

    name = "flux3cloud"

    def __init__(self, config: EngineConfig | dict[str, Any]):
        if isinstance(config, dict):
            config = EngineConfig.from_dict(config)
        self.config = config
        # Pin the Unified catalog id regardless of what was stored: a profile
        # with no `engines.flux3cloud` block hands us EngineConfig's generic
        # "@cf/...flux-2-klein-4b" default, which is a different API.
        self.config.cf_model = CF_MODEL

    def _endpoint(self) -> str:
        return (
            f"https://api.cloudflare.com/client/v4/accounts/"
            f"{self.config.account_id}/ai/run"
        )

    def _input_payload(self, request: ImageGenRequest, seed: int) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "prompt": request.prompt,
            "resolution": resolution_for(request.width, request.height),
            "aspect_ratio": aspect_ratio_for(request.width, request.height),
            "seed": seed,
        }
        refs = (request.reference_images or [])[:MAX_REFERENCE_IMAGES]
        if refs:
            payload["images"] = [_to_data_uri(ref) for ref in refs]
        return payload

    @staticmethod
    def _image_source(payload: dict[str, Any]) -> str:
        """Pull the image URI out of the various response shapes."""
        result = payload.get("result") or {}
        if isinstance(result, dict):
            for key in ("image", "sample", "url"):
                value = result.get(key)
                if isinstance(value, str) and value:
                    return value
        for key in ("image", "sample"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        raise RuntimeError(
            f"flux3cloud: no image in response: {json.dumps(payload)[:500]}"
        )

    @staticmethod
    def _download(source: str) -> bytes:
        """Resolve a response image URI: data URI, http(s) URL or raw base64."""
        if source.startswith("data:"):
            _, _, data = source.partition(",")
            return base64.b64decode(data)
        if urllib.parse.urlparse(source).scheme in ("http", "https"):
            try:
                with urllib.request.urlopen(source, timeout=DOWNLOAD_TIMEOUT) as resp:
                    return resp.read()
            except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
                raise RuntimeError(
                    f"flux3cloud: could not download the generated image from "
                    f"{source[:120]} (timeout={DOWNLOAD_TIMEOUT}s): "
                    f"{getattr(exc, 'reason', exc)}"
                ) from exc
        return base64.b64decode(source)

    def generate(self, request: ImageGenRequest, verbose: bool = False) -> Image.Image:
        apply_cloudflare_credentials(self.config)
        if not self.config.account_id:
            raise ValueError(
                f"{self.name}: account_id is required in engines.{self.name} "
                "config or CLOUDFLARE_ACCOUNT_ID"
            )
        if not self.config.api_token:
            raise ValueError(
                f"{self.name}: api_token is required in engines.{self.name} "
                "config or CLOUDFLARE_API_TOKEN"
            )

        def _vlog(message: str, elapsed: float | None = None) -> None:
            if not verbose:
                return
            suffix = f" [{elapsed:.1f}s]" if elapsed is not None else ""
            print(f"{self.name}: {message}{suffix}", file=sys.stderr, flush=True)

        seed = request.seed
        if seed is None:
            seed = random.randint(0, 999999999)

        input_payload = self._input_payload(request, seed)
        body = json.dumps(
            {"model": self.config.cf_model, "input": input_payload}
        ).encode()
        url = self._endpoint()

        _vlog(
            f"calling Unified AI catalog model={self.config.cf_model} "
            f"{request.width}x{request.height} "
            f"resolution={input_payload['resolution']} "
            f"aspect_ratio={input_payload['aspect_ratio']} seed={seed} "
            f"refs={len(input_payload.get('images') or [])} "
            f"timeout={API_TIMEOUT}s"
        )
        _vlog(f"POST {url}")

        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Authorization": f"Bearer {self.config.api_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        api_start = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=API_TIMEOUT) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            elapsed = time.monotonic() - api_start
            err_body = exc.read().decode("utf-8", errors="replace")
            if exc.code == 402:
                raise RuntimeError(
                    "flux3cloud: Cloudflare refused the request — payment required "
                    f"(402) after {elapsed:.1f}s. FLUX.3 Klein is a *third-party* "
                    "model of the Unified AI catalog: it is billed through AI "
                    "Gateway unified billing (or your own Black Forest Labs key via "
                    "BYOK), unlike the Cloudflare-hosted @cf/... models behind "
                    "flux2cloud / flux29bcloud. Cloudflare said: "
                    f"{err_body}\n"
                    "Fix: add AI Gateway credits (dashboard -> AI Gateway -> "
                    "Billing) or store a Black Forest Labs key (BYOK) — or use "
                    "`--engine flux29bcloud` for the free Cloudflare-hosted "
                    "FLUX.2 Klein-9B."
                ) from exc
            raise RuntimeError(
                f"flux3cloud: Cloudflare API error {exc.code} after {elapsed:.1f}s: "
                f"{err_body}"
            ) from exc
        except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
            elapsed = time.monotonic() - api_start
            raise RuntimeError(
                f"flux3cloud: API read timed out after {elapsed:.1f}s "
                f"(timeout={API_TIMEOUT}s, model={self.config.cf_model}, "
                f"{request.width}x{request.height}): {getattr(exc, 'reason', exc)}. "
                "The request was sent but no complete response arrived — "
                "retry, or rerun with --verbose to see timings."
            ) from exc
        elapsed = time.monotonic() - api_start
        _vlog(f"API responded bytes={len(raw)}", elapsed)

        payload = json.loads(raw.decode("utf-8", errors="replace"))
        if payload.get("success") is False:
            raise RuntimeError(
                f"flux3cloud: API returned failure: {payload.get('errors', payload)}"
            )
        source = self._image_source(payload)

        download_start = time.monotonic()
        image_bytes = self._download(source)
        image = Image.open(io.BytesIO(image_bytes))
        image.load()
        _vlog(
            f"image {image.width}x{image.height} downloaded bytes={len(image_bytes)}",
            time.monotonic() - download_start,
        )

        if image.size != (request.width, request.height):
            image = image.convert("RGB").resize(
                (request.width, request.height), Image.LANCZOS
            )
            _vlog(f"resized to {request.width}x{request.height}")
        return image

    def supports_img2img(self) -> bool:
        return False

    def supports_reference_image(self) -> bool:
        return True

    def supports_seeds(self) -> bool:
        return True

    def get_default_size(self) -> tuple[int, int]:
        return (1024, 1024)

    def get_default_steps(self) -> int:
        return 4

    def get_default_guidance_scale(self) -> float:
        return 1.0

    def validate_model_path(self) -> bool:
        return bool(self.config.account_id and self.config.api_token)
