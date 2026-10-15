from __future__ import annotations

from plugins.qwen21.plugin import Qwen21EnginePlugin

#: Accelerated Qwen-Image-2.1 checkpoint: same 7B architecture, usable
#: text-to-image + editing in 8 denoising steps (saved sampling schedule
#: in the checkpoint, CFG=1 default). Requires diffusers with
#: pipeline-configured sampling sigmas (PR #14950 — install from git main,
#: same requirement as the base qwen21 engine).
TURBO_MODEL_ID = "Qwen/Qwen-Image-2.1-Turbo"


class Qwen21TurboEnginePlugin(Qwen21EnginePlugin):
    """Qwen-Image-2.1-Turbo local engine (8-step generation + editing).

    Reuses the qwen21 loader verbatim (sequential offload, attention
    slicing, VAE tiling, bnb int8/int4 + quanto backends) — only the
    checkpoint, the recommended defaults (8 steps / CFG 1.0), and the
    prefix KV-cache flag differ. The checkpoint carries its own sampling
    schedule, so an explicit ``num_inference_steps`` alone does not
    override Turbo's saved schedule; the CLI default of 8 matches it.
    """

    name = "qwen21turbo"

    default_model_id = TURBO_MODEL_ID

    extra_pipe_kwargs = {"use_kv_cache": True}

    def get_default_steps(self) -> int:
        return 8

    def get_default_guidance_scale(self) -> float:
        return 1.0
