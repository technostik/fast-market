from __future__ import annotations

from typing import Any

from core.models import EngineConfig
from plugins.flux2cloud.plugin import Flux2CloudEnginePlugin

CF_MODEL = "@cf/black-forest-labs/flux-3-image-klein"


class Flux3CloudEnginePlugin(Flux2CloudEnginePlugin):
    """FLUX.3 Image Klein via Cloudflare Workers AI."""

    name = "flux3cloud"

    def __init__(self, config: EngineConfig | dict[str, Any]):
        super().__init__(config)
        # Pin to the Cloudflare FLUX.3 model.
        self.config.cf_model = CF_MODEL
