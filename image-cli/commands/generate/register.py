from __future__ import annotations

from pathlib import Path

import click
from PIL import Image

from commands.base import CommandManifest
from commands.helpers import build_engine, out
from core.models import ImageGenRequest, TextOverlayConfig
from core.overlay import apply_text_overlay, resolve_font_path


def register(plugin_manifests: dict) -> CommandManifest:
    engine_choices = list(plugin_manifests.keys())

    @click.command("generate")
    @click.argument("PROMPT")
    @click.option(
        "--engine",
        "-e",
        type=click.Choice(engine_choices),
        default=None,
        help="Image generation engine to use",
    )
    @click.option(
        "--size",
        "-s",
        type=click.Choice(
            ["square", "portrait", "landscape", "youtube", "wide", "tall", "custom"]
        ),
        default=None,
        help="Named image size preset (default: from config default_width/height)",
    )
    @click.option(
        "--width",
        "-w",
        type=int,
        default=None,
        help="Image width (overrides --size)",
    )
    @click.option(
        "--height",
        "-h",
        type=int,
        default=None,
        help="Image height (overrides --size)",
    )
    @click.option(
        "--guidance-scale",
        "-g",
        type=float,
        default=None,
        help="Guidance scale for generation",
    )
    @click.option(
        "--steps",
        "-S",
        type=int,
        default=None,
        help="Number of inference steps",
    )
    @click.option(
        "--seed",
        "-d",
        type=int,
        default=None,
        help="Random seed for reproducibility",
    )
    @click.option(
        "--init-image",
        "-i",
        type=click.Path(exists=True),
        default=None,
        help="Initial image for img2img generation",
    )
    @click.option(
        "--reference-image",
        "-R",
        "reference_images",
        type=click.Path(exists=True),
        multiple=True,
        help="Reference image for subject/character consistency (up to 4: image 0..3). "
             "The subject of the reference is kept and placed into the new scene. "
             "Reference it in the prompt as 'image 0', 'image 1', etc.",
    )
    @click.option(
        "--keep-original-size",
        is_flag=True,
        default=False,
        help="Keep original size of init image (ignore --size/--width/--height)",
    )
    @click.option(
        "--strength",
        "-t",
        type=float,
        default=None,
        help="Strength for img2img (0.0-1.0, how much to change init image)",
    )
    @click.option(
        "--output-format",
        type=click.Choice(["PNG", "JPEG", "WEBP"]),
        default=None,
        help="Output image format",
    )
    @click.option(
        "--output-dir",
        "-o",
        type=click.Path(),
        default=None,
        help="Output directory (default: from config)",
    )
    @click.option(
        "--format",
        "-F",
        "fmt",
        type=click.Choice(["json", "text"]),
        default="text",
        help="Output format",
    )
    @click.option(
        "--title",
        "-T",
        default=None,
        help="Text to superimpose on the generated image",
    )
    @click.option(
        "--position",
        type=click.Choice(
            [
                "top-left",
                "top-center",
                "top-right",
                "middle-left",
                "middle-center",
                "middle-right",
                "bottom-left",
                "bottom-center",
                "bottom-right",
            ]
        ),
        default=None,
        help="Text position (vertical-horizontal). Default: bottom-center",
    )
    @click.option(
        "--overlay-size",
        default=None,
        help="Font size: an integer (e.g. 48) or 'fit' to auto-scale",
    )
    @click.option(
        "--overlay-fg",
        default=None,
        help="Foreground (text) color name or hex. Default: blue",
    )
    @click.option(
        "--overlay-bg",
        default=None,
        help="Background effect color name/hex or 'none'. Default: light green",
    )
    @click.option(
        "--overlay-effect",
        type=click.Choice(["none", "box", "shadow", "band"]),
        default=None,
        help="Background effect: none/box/shadow/band. Default: band",
    )
    @click.option(
        "--overlay-style",
        type=click.Choice(["normal", "bold", "italic", "bold-italic"]),
        default=None,
        help="Font style: normal/bold/italic/bold-italic. Default: normal",
    )
    @click.option(
        "--overlay-band-size",
        type=int,
        default=None,
        help="Band height as %% of image height (band effect). Default: 8",
    )
    @click.option(
        "--overlay-size-pct",
        type=float,
        default=None,
        help="Font size multiplier vs the resolved size (e.g. 120 = +20%). Default: 100",
    )
    @click.option(
        "--overlay-offset",
        type=int,
        default=None,
        help="Shift text + band downward by this %% of image height (e.g. 10 = +10%%)",
    )
    @click.pass_context
    def generate_cmd(
        ctx,
        prompt,
        engine,
        size,
        width,
        height,
        guidance_scale,
        steps,
        seed,
        init_image,
        keep_original_size,
        strength,
        reference_images,
        output_format,
        output_dir,
        fmt,
        title,
        position,
        overlay_size,
        overlay_fg,
        overlay_bg,
        overlay_effect,
        overlay_style,
        overlay_band_size,
        overlay_size_pct,
        overlay_offset,
    ):
        """Generate an image from a text prompt."""
        engine_instance, plugins, config = build_engine(
            verbose=ctx.obj["verbose"],
            cache_pipeline=False,
        )

        actual_engine = engine or config.default_engine
        if actual_engine not in plugins:
            click.echo(f"Error: Unknown engine '{actual_engine}'", err=True)
            click.echo(f"Available engines: {', '.join(plugins.keys())}", err=True)
            ctx.exit(1)

        if width is not None or height is not None:
            actual_width = width or config.default_width
            actual_height = height or config.default_height
        else:
            size_preset = config.get_size(size)
            if size_preset:
                actual_width = size_preset.width
                actual_height = size_preset.height
            else:
                actual_width = config.default_width
                actual_height = config.default_height

        uploaded_image: Image.Image | None = None
        if init_image:
            uploaded_image = Image.open(init_image).convert("RGB")
            if keep_original_size:
                actual_width = uploaded_image.width
                actual_height = uploaded_image.height
            else:
                uploaded_image = uploaded_image.resize((actual_width, actual_height))

        # Reference images for subject consistency. Loaded and downscaled to <512px
        # on the longest side (required by some engines, e.g. Cloudflare FLUX.2
        # Klein). Up to 4 references are supported (indexed 0..3 in the prompt).
        ref_images: list[Image.Image] | None = None
        if reference_images:
            ref_images = []
            for ri in reference_images[:4]:
                im = Image.open(ri).convert("RGB")
                max_side = max(im.width, im.height)
                if max_side > 512:
                    scale = 511 / max_side
                    im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))))
                ref_images.append(im)

        request = ImageGenRequest(
            prompt=prompt,
            width=actual_width,
            height=actual_height,
            guidance_scale=guidance_scale
            if guidance_scale is not None
            else config.default_guidance_scale,
            num_inference_steps=steps
            if steps is not None
            else config.default_num_inference_steps,
            seed=seed,
            init_image=uploaded_image,
            strength=strength,
            reference_images=ref_images,
            output_format=output_format or config.default_output_format,
            engine=actual_engine,
        )

        try:
            result = engine_instance.generate(request, output_dir=output_dir)
            base_path = result.path

            if title:
                vpos = config.overlay.vpos
                hpos = config.overlay.hpos
                if position:
                    vpos, hpos = position.split("-")

                overlay_cfg = TextOverlayConfig(
                    enabled=True,
                    text=title,
                    vpos=vpos,
                    hpos=hpos,
                    size=overlay_size or config.overlay.size,
                    fg=overlay_fg or config.overlay.fg,
                    bg=overlay_bg or config.overlay.bg,
                    effect=overlay_effect or config.overlay.effect,
                    style=overlay_style or config.overlay.style,
                    band_size=overlay_band_size or config.overlay.band_size,
                    size_pct=overlay_size_pct if overlay_size_pct is not None else config.overlay.size_pct,
                    offset_pct=overlay_offset if overlay_offset is not None else config.overlay.offset_pct,
                )

                from PIL import Image

                final_image = apply_text_overlay(
                    Image.open(result.path),
                    overlay_cfg,
                    font_family=config.overlay.font,
                    font_style=overlay_style or config.overlay.style,
                )

                # Save the overlayed image separately; keep the base (no-overlay)
                # image intact so both versions are available.
                base_p = Path(result.path)
                overlay_path = base_p.parent / f"{base_p.stem}_overlay{base_p.suffix}"
                final_image.save(overlay_path, format=result.output_format)
                result.path = str(overlay_path)

                click.echo(
                    f"Using font: {resolve_font_path(config.overlay.font, overlay_style or config.overlay.style)}",
                    err=True,
                )
                click.echo(
                    f"Base (no overlay): {base_path}",
                    err=True,
                )

            out(result.to_dict(), fmt)
        except Exception as e:
            click.echo(f"Error: {e}", err=True)
            if ctx.obj["verbose"]:
                import traceback

                traceback.print_exc()
            ctx.exit(1)

    for pm in plugin_manifests.values():
        generate_cmd.params.extend(pm.cli_options.get("generate", []))
    for pm in plugin_manifests.values():
        generate_cmd.params.extend(pm.cli_options.get("*", []))

    return CommandManifest(name="generate", click_command=generate_cmd)
