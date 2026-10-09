from __future__ import annotations

import json
import re
import time
from pathlib import Path

import click

from commands.base import CommandManifest


def _slugify(text: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (slug[:max_len].rstrip("-") or "video")


def register(plugin_manifests: dict) -> CommandManifest:
    from commands.generate import fal as _fal
    from commands.generate import models as _models

    @click.command("generate")
    @click.argument("prompt", required=False, default=None)
    @click.option(
        "--model", "-m",
        metavar="[auto|minimax|flux|kling|ltx|ENDPOINT_ID]",
        default=None,
        help="fal model alias, full endpoint ID (contains '/'), or 'auto'. "
             "Default: auto (first catalog model with remaining quota).",
    )
    @click.option(
        "--custom-model", "custom_model",
        default=None,
        help="Full fal endpoint ID override (e.g. fal-ai/veo3.1). Same as --model with a '/'.",
    )
    @click.option(
        "--image",
        type=click.Path(exists=True, dir_okay=False),
        default=None,
        help="Local still image for image-to-video (uploaded to the fal CDN).",
    )
    @click.option(
        "--image-url",
        default=None,
        help="Already-hosted image URL for image-to-video (skips CDN upload).",
    )
    @click.option("--output", "-o", type=click.Path(), default=None,
                  help="Output MP4 path (default: <prompt-slug>_fal.mp4 in CWD). "
                       "Missing parent directories are created.")
    @click.option("--duration", type=int, default=None,
                  help="Clip duration in seconds (model-dependent; default: model default).")
    @click.option("--aspect-ratio", type=str, default=None,
                  help="Aspect ratio hint, e.g. '16:9' (model-dependent).")
    @click.option("--seed", type=int, default=None, help="Random seed (model-dependent).")
    @click.option("--negative-prompt", default=None,
                  help="Negative prompt (model-dependent).")
    @click.option("--set", "extra_sets", multiple=True, default=(),
                  help="Model-specific passthrough as KEY=VALUE (repeatable, overrides defaults).")
    @click.option("--timeout", type=float, default=600, show_default=True,
                  help="Max seconds to wait for the queued generation.")
    @click.option("--api-key", default=None,
                  help="fal API key (default: FAL_KEY, then FAL_API_KEY from root .env).")
    @click.option("--list-models", "list_models", is_flag=True, default=False,
                  help="List discoverable fal text-to-video models (cached 24h) and exit.")
    @click.option("--free-only", "free_only", is_flag=True, default=False,
                  help="With --list-models, show only curated models with a free "
                       "daily sandbox allowance (sandbox-free is playground-only; "
                       "API calls are pay-per-use).")
    @click.option("--refresh-models", "refresh_models", is_flag=True, default=False,
                  help="Force-refresh the cached fal model catalog, then list and exit.")
    @click.option("--format", "-F", "fmt", type=click.Choice(["text", "json"]), default="text",
                  show_default=True, help="Output format")
    @click.option("--verbose", "-v", is_flag=True, default=False,
                  help="Show queue progress with timings on stderr.")
    def generate_cmd(prompt, model, custom_model, image, image_url, output,
                     duration, aspect_ratio, seed, negative_prompt,
                     extra_sets, timeout, api_key, list_models, free_only,
                     refresh_models, fmt, verbose):
        """Generate a video from text with fal.ai (cloud), optionally from an image.

        With --image/--image-url the image-to-video endpoint variant is used.
        The model actually used is always reported on stderr.
        """
        _start = time.monotonic()

        def _vlog(message: str) -> None:
            if verbose:
                click.echo(f"[+{time.monotonic() - _start:.1f}s] {message}", err=True)

        if list_models or refresh_models:
            if free_only:
                for m in _models.free_models():
                    click.echo(f"{m.alias}  {m.text_endpoint}  {m.label}")
                click.echo(
                    "Sandbox-free is playground-only; API calls are pay-per-use.",
                    err=True,
                )
                return
            try:
                key = _fal.resolve_api_key(api_key)
            except _fal.FalError as exc:
                raise click.ClickException(str(exc)) from exc
            try:
                found, from_cache = _models.fetch_models(
                    api_key=key, force_refresh=refresh_models
                )
            except RuntimeError as exc:
                raise click.ClickException(str(exc)) from exc
            click.echo(_models.format_model_listing(found))
            click.echo(
                f"{len(found)} models ({'cache' if from_cache else 'live'}). "
                "Curated aliases: " + ", ".join(_models.get_aliases()),
                err=True,
            )
            return

        if not prompt:
            raise click.UsageError("PROMPT is required (or use --list-models).")
        if image and image_url:
            raise click.UsageError("--image and --image-url are mutually exclusive.")
        try:
            extra = _models.parse_set_option(tuple(extra_sets))
        except ValueError as exc:
            raise click.BadParameter(str(exc)) from exc

        requested = custom_model or model or "auto"
        has_image = bool(image or image_url)
        try:
            candidates = _models.resolve_candidate_endpoints(requested, has_image)
        except ValueError as exc:
            raise click.BadParameter(str(exc)) from exc

        try:
            key = _fal.resolve_api_key(api_key)
        except _fal.FalError as exc:
            raise click.ClickException(str(exc)) from exc

        hosted_image_url = image_url
        if image and not hosted_image_url:
            click.echo(f"Uploading {Path(image).name} to fal CDN …", err=True)
            try:
                hosted_image_url = _fal.upload_image(str(image), key)
            except _fal.FalError as exc:
                raise click.ClickException(str(exc)) from exc
            _vlog(f"image CDN url={hosted_image_url}")

        if output is None:
            output_path = Path.cwd() / f"{_slugify(prompt)}_fal.mp4"
        else:
            output_path = Path(output)
            if not output_path.is_absolute():
                output_path = Path.cwd() / output_path
        # Unlike older video commands, generate creates missing parents.
        output_path.parent.mkdir(parents=True, exist_ok=True)

        payload = _models.build_payload(
            prompt,
            image_url=hosted_image_url,
            duration=duration,
            aspect_ratio=aspect_ratio,
            seed=seed,
            negative_prompt=negative_prompt,
            extra=extra,
        )
        mode = "image-to-video" if has_image else "text-to-video"

        last_error: Exception | None = None
        for endpoint in candidates:
            click.echo(f"Using model: {endpoint} ({mode})", err=True)
            _vlog(f"submit endpoint={endpoint} payload_keys={sorted(payload)}")
            try:
                info = _fal.generate_video(
                    endpoint=endpoint,
                    payload=payload,
                    output_path=output_path,
                    api_key=key,
                    timeout=timeout,
                    progress_cb=(lambda s: _vlog(f"queue status={s}")) if verbose else None,
                )
            except Exception as exc:  # noqa: BLE001 — fallback decision below
                last_error = exc
                if _fal.is_quota_error(exc) and endpoint != candidates[-1]:
                    click.echo(
                        f"Model {endpoint} exhausted quota/billing ({exc}); "
                        "trying next model …",
                        err=True,
                    )
                    continue
                raise click.ClickException(str(exc)) from exc
            _vlog(f"done in {time.monotonic() - _start:.1f}s saved={output_path}")
            if fmt == "json":
                click.echo(json.dumps({
                    "path": str(output_path),
                    "model": endpoint,
                    "mode": mode,
                    "prompt": prompt,
                    "image": str(image or image_url or ""),
                    "video_url": info.get("video_url", ""),
                    "request_id": info.get("request_id", ""),
                }))
            else:
                click.echo(str(output_path))
            return

        raise click.ClickException(
            f"All {len(candidates)} models exhausted quota/billing. "
            f"Last error: {last_error}"
        )

    return CommandManifest(name="generate", click_command=generate_cmd)
