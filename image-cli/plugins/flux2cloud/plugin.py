from __future__ import annotations

import base64
import io
import random
import urllib.error
import urllib.request
from typing import Any

from PIL import Image

from core.models import EngineConfig, ImageGenRequest
from plugins.base import ImageEnginePlugin


def _encode_multipart(fields: dict[str, str], boundary: str) -> bytes:
    """Encode fields as multipart/form-data."""
    lines = []
    for name, value in fields.items():
        lines.append(f"--{boundary}".encode())
        lines.append(f'Content-Disposition: form-data; name="{name}"'.encode())
        lines.append(b"")
        lines.append(value.encode())
    lines.append(f"--{boundary}--".encode())
    return b"\r\n".join(lines)


class Flux2CloudEnginePlugin(ImageEnginePlugin):
    """FLUX.2 Klein-4B image generation via Cloudflare Workers AI (free tier)."""

    name = "flux2cloud"

    def __init__(self, config: EngineConfig | dict[str, Any]):
        if isinstance(config, dict):
            config = EngineConfig.from_dict(config)
        self.config = config

    def generate(self, request: ImageGenRequest) -> Image.Image:
        """Generate an image using Cloudflare Workers AI."""
        if not self.config.account_id:
            raise ValueError(
                "flux2cloud: account_id is required in engines.flux2cloud config"
            )
        if not self.config.api_token:
            raise ValueError(
                "flux2cloud: api_token is required in engines.flux2cloud config"
            )

        seed = request.seed
        if seed is None:
            seed = random.randint(0, 999999999)

        url = (
            f"https://api.cloudflare.com/client/v4/accounts/"
            f"{self.config.account_id}/ai/run/{self.config.cf_model}"
        )

        boundary = "----FormBoundary7MA4YWxkTrZu0gW"
        fields = {
            "prompt": request.prompt,
            "width": str(request.width),
            "height": str(request.height),
            "steps": str(request.num_inference_steps),
        }
        body = _encode_multipart(fields, boundary)

        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Authorization": f"Bearer {self.config.api_token}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            body_err = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"flux2cloud: Cloudflare API error {exc.code}: {body_err}"
            ) from exc

        import json as _json
        payload = _json.loads(raw)
        if not payload.get("success"):
            errors = payload.get("errors", [])
            raise RuntimeError(f"flux2cloud: API returned failure: {errors}")

        b64 = payload["result"]["image"]
        image_bytes = base64.b64decode(b64)
        image = Image.open(io.BytesIO(image_bytes))
        image.load()
        return image

    def supports_img2img(self) -> bool:
        return False

    def supports_seeds(self) -> bool:
        return False

    def get_default_size(self) -> tuple[int, int]:
        return (1024, 1024)

    def get_default_steps(self) -> int:
        return 4

    def get_default_guidance_scale(self) -> float:
        return 1.0

    def validate_model_path(self) -> bool:
        return bool(self.config.account_id and self.config.api_token)
