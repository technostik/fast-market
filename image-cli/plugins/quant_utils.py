"""Shared helpers for local-engine weight quantization.

Only the bitsandbytes state repair lives here for now: it is the one piece
both quantized CUDA loaders (qwen21, flux3) need verbatim, and getting it
wrong only shows up as "Cannot copy out of meta tensor" at the first
offload hook, thousands of lines away from the cause.
"""

from __future__ import annotations

from typing import Any


def repair_bnb_meta_state(module: Any) -> tuple[int, int]:
    """Reset poisoned bnb flags on CPU-resident floating-point params.

    Standalone component loads propagate the ``init_empty_weights``
    quant_state (meta tensors, ``bnb_quantized=True``) onto params whose
    data is real fp on CPU. The offload hook's ``.to("cuda")`` then tries
    to move the meta state and dies ("Cannot copy out of meta tensor").
    Clearing the flag/state makes the bnb param take its other branch —
    quantize the block on the GPU on the fly — which is what streaming
    offload needs.

    Only touches floating-point, non-meta data (real weights); already
    quantized (uint8) or meta-data params are left alone.

    Returns ``(repaired, skipped)``.
    """
    import torch

    try:
        import bitsandbytes as bnb
    except ImportError:
        return (0, 0)

    repaired = 0
    skipped = 0
    for param in module.parameters():
        if not isinstance(param, bnb.nn.Params4bit):
            continue
        state = param.__dict__.get("quant_state")
        state_tensors = []
        if state is not None:
            for attr in ("absmax", "code", "state2"):
                tensor = getattr(state, attr, None)
                if isinstance(tensor, torch.Tensor):
                    state_tensors.append(tensor)
                elif attr == "state2" and tensor is not None:
                    for sub in ("absmax", "code"):
                        sub_tensor = getattr(tensor, sub, None)
                        if isinstance(sub_tensor, torch.Tensor):
                            state_tensors.append(sub_tensor)
        has_meta_state = any(t.is_meta for t in state_tensors)
        if (
            param.data is not None
            and not param.data.is_meta
            and param.data.is_floating_point()
            and (param.__dict__.get("bnb_quantized") or has_meta_state)
        ):
            param.__dict__["bnb_quantized"] = False
            param.__dict__["quant_state"] = None
            repaired += 1
        else:
            skipped += 1
    return repaired, skipped
