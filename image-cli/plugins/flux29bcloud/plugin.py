from __future__ import annotations

from typing import Any

from core.models import EngineConfig
from plugins.flux2cloud.plugin import CF_MODEL_9B, Flux2CloudEnginePlugin


class Flux29bCloudEnginePlugin(Flux2CloudEnginePlugin):
    """FLUX.2 Klein-9B via Cloudflare Workers AI (fixed 4-step, higher quality).

    Dedicated engine pinned to the 9B model so it can coexist with the
    `flux2cloud` (4B) entry and be selected with `-e flux29bcloud`.
    `account_id`/`api_token` are reused from its own config block.
    """

    name = "flux29bcloud"

    def __init__(self, config: EngineConfig | dict[str, Any]):
        super().__init__(config)
        # Pin to 9B regardless of what cf_model was stored.
        self.config.cf_model = CF_MODEL_9B
