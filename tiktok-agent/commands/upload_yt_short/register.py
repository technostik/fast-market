from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional, List

import click

from commands.base import CommandManifest
from core.config import load_config


class rt_subprocess:
    @staticmethod
    def run(*args, capture_output=True, text=True, **kwargs):
        return rt_subprocess._run_with_real_time(
            *args, capture_output=capture_output, text=text, **kwargs
        )

    @staticmethod
    def _run_with_real_time(*args, capture_output=True, text=True, **kwargs):
        stdout_lines = []
        stderr_lines = []

        process = subprocess.Popen(
            *args,
            stdout=subprocess.PIPE if capture_output else None,
            stderr=subprocess.PIPE if capture_output else None,
            text=text,
            **kwargs,
        )

        def read_stream(stream, lines_list, output_stream=None):
            if stream:
                for line in iter(stream.readline, ""):
                    if line:
                        lines_list.append(line)
                        if output_stream:
                            output_stream.write(line)
                            output_stream.flush()

        threads = []

        if capture_output:
            stdout_thread = threading.Thread(
                target=read_stream, args=(process.stdout, stdout_lines, sys.stdout)
            )
            stdout_thread.start()
            threads.append(stdout_thread)

            stderr_thread = threading.Thread(
                target=read_stream, args=(process.stderr, stderr_lines, sys.stderr)
            )
            stderr_thread.start()
            threads.append(stderr_thread)

        returncode = process.wait()

        for thread in threads:
            thread.join()

        return subprocess.CompletedProcess(
            args=process.args,
            returncode=returncode,
            stdout="".join(stdout_lines) if capture_output else None,
            stderr="".join(stderr_lines) if capture_output else None,
        )

    PIPE = subprocess.PIPE
    STDOUT = subprocess.STDOUT
    DEVNULL = subprocess.DEVNULL
    CalledProcessError = subprocess.CalledProcessError
    TimeoutExpired = subprocess.TimeoutExpired


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("upload-yt-short")
    @click.option("--title", "-t", required=True, help="Title for the TikTok video")
    @click.option("--url", "-u", required=True, help="YouTube Short URL")
    @click.pass_context
    def upload_yt_short_cmd(ctx, title, url, **kwargs):
        """Upload a YouTube Short to TikTok."""
        config = load_config()

        tiktok_config = config.get("tiktok", {})
        uploader_path = tiktok_config.get("tiktok_auto_uploader_path")
        username = tiktok_config.get("username")

        if not uploader_path:
            raise click.ClickException(
                "TikTokAutoUploader path not configured. "
                "Add 'tiktok.tiktok_auto_uploader_path' to config.yaml"
            )
        if not username:
            raise click.ClickException(
                "TikTok username not configured. Add 'tiktok.username' to config.yaml"
            )

        uploader_path = Path(uploader_path).expanduser()
        cli_path = uploader_path / "cli.py"

        if not cli_path.exists():
            raise click.ClickException(f"cli.py not found at {cli_path}")

        python_path = uploader_path / "venv" / "bin" / "python"
        if not python_path.exists():
            python_path = "python"

        cmd = [
            str(python_path),
            str(cli_path),
            "upload",
            "-u",
            username,
            "-t",
            f'"{title}"',
            "-yt",
            url,
        ]

        click.echo(f"Running: {' '.join(cmd)}")

        result = rt_subprocess.run(
            cmd,
            cwd=str(uploader_path),
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise click.ClickException("Upload failed")

    return CommandManifest(
        name="upload-yt-short",
        click_command=upload_yt_short_cmd,
    )
