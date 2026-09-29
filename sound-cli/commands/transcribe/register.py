from __future__ import annotations

from pathlib import Path

import click

from commands.base import CommandManifest
from commands.transcribe.analysis import (
    ENGINES,
    cloudflare_credentials,
    resolve_engine,
    to_srt,
    transcribe_cloudflare,
    transcribe_groq,
    transcribe_local,
)
from common.cli.helpers import out
from core.config import load_sound_config


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("transcribe")
    @click.argument("FILE", type=click.Path(exists=True, dir_okay=False))
    @click.option(
        "--output", "-o",
        type=click.Path(),
        default=None,
        help="Also write the transcript to this path.",
    )
    @click.option(
        "--format", "-F", "fmt",
        type=click.Choice(["json", "text", "srt"]),
        default="text",
        help="Output format (default: text).",
    )
    @click.option("--language", "-l", default="auto", help="Language code or 'auto'.")
    @click.option("--model", "-m", default="medium", help="faster-whisper model size (tiny..large-v3).")
    @click.option(
        "--engine", "-e",
        type=click.Choice(list(ENGINES)),
        default="auto",
        help="Transcription engine. auto = groq if GROQ_API_KEY set, else cloudflare if "
             "CLOUDFLARE_ACCOUNT_ID/CLOUDFLARE_API_TOKEN set, else local faster-whisper.",
    )
    @click.option(
        "--modal",
        is_flag=True,
        default=False,
        help="Run faster-whisper on Modal remote infrastructure (ignores --engine).",
    )
    @click.pass_context
    def transcribe_cmd(ctx, file, output, fmt, language, model, engine, modal):
        """Transcribe an audio or video FILE to text (local faster-whisper, Modal, Groq or Cloudflare)."""
        input_path = Path(file).resolve()

        try:
            config = load_sound_config()
            if modal:
                engine_used = "modal"
                from commands.remote import run_remote_transcribe

                data = run_remote_transcribe(input_path, model, language)
            else:
                engine_used = resolve_engine(engine, config)
                if engine_used == "modal":
                    from commands.remote import run_remote_transcribe

                    data = run_remote_transcribe(input_path, model, language)
                elif engine_used == "groq":
                    data = transcribe_groq(str(input_path), language)
                elif engine_used == "cloudflare":
                    account_id, api_token = cloudflare_credentials(config)
                    data = transcribe_cloudflare(
                        str(input_path), language, account_id, api_token
                    )
                else:
                    data = transcribe_local(str(input_path), model, language)

            result = {
                "path": str(input_path),
                "engine": engine_used,
                "model": model if engine_used in ("local", "modal") else None,
                "language": data.get("language", language),
                "text": data.get("text", ""),
                "segments": data.get("segments", []),
            }

            if fmt == "text":
                content = result["text"]
            elif fmt == "srt":
                content = to_srt(result["segments"])
            else:
                content = None

            if output:
                output_path = Path(output)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                if content is None:
                    import json

                    output_path.write_text(
                        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
                    )
                else:
                    output_path.write_text(content, encoding="utf-8")

            if fmt == "json":
                out(result, "json")
            else:
                click.echo(content)

        except click.ClickException:
            raise
        except Exception as e:
            click.echo(f"Error: {e}", err=True)
            if ctx.obj.get("verbose"):
                import traceback

                traceback.print_exc()
            ctx.exit(1)

    return CommandManifest(name="transcribe", click_command=transcribe_cmd)
