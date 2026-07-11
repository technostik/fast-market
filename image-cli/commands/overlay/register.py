from __future__ import annotations

from pathlib import Path

import click
from PIL import Image

from commands.base import CommandManifest
from commands.helpers import out
from core.config import load_image_config
from core.models import TextOverlayConfig
from core.overlay import apply_text_overlay


_POSITIONS = [
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


def _save_output(image: Image.Image, output: str) -> str:
    """Save the image, inferring format from the output path extension."""
    out_path = Path(output)
    ext = out_path.suffix.lstrip(".").upper() or "PNG"
    fmt = "JPEG" if ext in ("JPG", "JPEG") else ext
    save_image = image
    if fmt == "JPEG" and save_image.mode == "RGBA":
        save_image = save_image.convert("RGB")
    save_image.save(out_path, format=fmt)
    return str(out_path.absolute())


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("overlay")
    @click.argument("IMAGE", type=click.Path(exists=True))
    @click.option("--title", "-T", required=True, help="Text to superimpose on the image")
    @click.option(
        "--position",
        type=click.Choice(_POSITIONS),
        default=None,
        help="Text position (vertical-horizontal). Default from config: bottom-center",
    )
    @click.option(
        "--output",
        "-o",
        type=click.Path(),
        default=None,
        help="Output image path (default: <input>_overlay<ext>)",
    )
    @click.option(
        "--overlay-size",
        default=None,
        help="Font size: an integer (e.g. 48) or 'fit' to auto-scale",
    )
    @click.option(
        "--overlay-fg",
        default=None,
        help="Foreground (text) color name or hex. Default from config: blue",
    )
    @click.option(
        "--overlay-bg",
        default=None,
        help="Background effect color name/hex or 'none'. Default from config: light green",
    )
    @click.option(
        "--overlay-effect",
        type=click.Choice(["none", "box", "shadow", "band"]),
        default=None,
        help="Background effect: none/box/shadow/band. Default from config: band",
    )
    @click.option(
        "--overlay-style",
        type=click.Choice(["normal", "bold", "italic", "bold-italic"]),
        default=None,
        help="Font style: normal/bold/italic/bold-italic. Default from config: normal",
    )
    @click.option(
        "--overlay-band-size",
        type=int,
        default=None,
        help="Band height as %% of image height (band effect). Default from config: 8",
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
    def overlay_cmd(
        ctx,
        image,
        title,
        position,
        output,
        overlay_size,
        overlay_fg,
        overlay_bg,
        overlay_effect,
        overlay_style,
        overlay_band_size,
        fmt,
    ):
        """Add superimposed text (a title) onto an existing IMAGE."""
        config = load_image_config()

        if position:
            vpos, hpos = position.split("-")
        else:
            vpos, hpos = config.overlay.vpos, config.overlay.hpos

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
        )

        src = Image.open(image)
        final_image = apply_text_overlay(
            src,
            overlay_cfg,
            font_family=config.overlay.font,
            font_style=overlay_style or config.overlay.style,
        )

        if not output:
            p = Path(image)
            output = str(p.parent / f"{p.stem}_overlay{p.suffix}")

        path = _save_output(final_image, output)

        out(
            {
                "path": path,
                "width": final_image.width,
                "height": final_image.height,
                "prompt": None,
                "engine": None,
            },
            fmt,
        )

    return CommandManifest(name="overlay", click_command=overlay_cmd)
