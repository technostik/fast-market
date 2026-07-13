from __future__ import annotations

import asyncio
from typing import Optional


_active_proc: Optional[asyncio.Process] = None
_active_job = None


def set_active_proc(proc: asyncio.Process) -> None:
    global _active_proc
    _active_proc = proc


def clear_active_proc() -> None:
    global _active_proc
    _active_proc = None


def get_active_proc() -> Optional[asyncio.Process]:
    return _active_proc


def set_active_job(job) -> None:
    global _active_job
    _active_job = job


def clear_active_job() -> None:
    global _active_job
    _active_job = None


def request_stop() -> None:
    """Signal the currently running publish job to abort and terminate its
    active subprocess (SIGTERM so a Modal child can cancel its remote call)."""
    global _active_proc
    if _active_job is not None:
        _active_job.stop_requested = True
    proc = _active_proc
    if proc is not None and proc.returncode is None:
        try:
            proc.terminate()
        except ProcessLookupError:
            pass
