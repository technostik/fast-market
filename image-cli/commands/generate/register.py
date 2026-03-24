from __future__ import annotations

from pathlib import Path

import click
from PIL import Image

from commands.base import CommandManifest
from commands.helpers import build_engine, out
from core.models import ImageGenRequest


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
        default="square",
        help="Named image size preset",
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
        output_format,
        output_dir,
        fmt,
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
            output_format=output_format or config.default_output_format,
            engine=actual_engine,
        )

        try:
            result = engine_instance.generate(request, output_dir=output_dir)
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
