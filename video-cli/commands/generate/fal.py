from __future__ import annotations

import mimetypes
import os
import time
from pathlib import Path

QUEUE_BASE = "https://queue.fal.run"
STORAGE_INITIATE_URL = "https://rest.alpha.fal.ai/storage/upload/initiate"

_QUOTA_KEYWORDS = (
    "quota",
    "insufficient",
    "balance",
    "credit",
    "billing",
    "rate limit",
    "rate_limit",
    "too many requests",
    "free limit",
    "plan limit",
    "payment",
)


class FalError(RuntimeError):
    """fal.ai request failure with HTTP status for fallback decisions."""

    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


def is_quota_error(exc: BaseException) -> bool:
    """True when ``exc`` looks like an exhausted quota/billing/rate limit."""
    status = getattr(exc, "status", None)
    if status in (402, 429):
        return True
    text = str(exc).lower()
    return any(k in text for k in _QUOTA_KEYWORDS)


def resolve_api_key(explicit: str | None = None) -> str:
    """Resolve the fal API key: flag > FAL_KEY > FAL_API_KEY (root .env).

    ``cli/main.py`` already loads the repository ``.env`` at startup; this
    helper re-loads it best-effort so direct imports (tests, REPL) work too.
    """
    if explicit:
        return explicit
    key = os.environ.get("FAL_KEY") or os.environ.get("FAL_API_KEY")
    if key:
        return key
    try:
        from dotenv import load_dotenv

        env_path = Path(__file__).resolve().parents[3] / ".env"
        load_dotenv(env_path)
    except (ImportError, OSError):
        pass
    key = os.environ.get("FAL_KEY") or os.environ.get("FAL_API_KEY")
    if not key:
        raise FalError(
            "fal API key not set. Pass --api-key, set FAL_KEY, or add "
            "FAL_API_KEY to the repository root .env."
        )
    return key


def upload_image(image_path: str, api_key: str) -> str:
    """Upload a local image to the fal CDN; return its public file URL."""
    import requests

    path = Path(image_path)
    content_type, _ = mimetypes.guess_type(path.name)
    content_type = content_type or "image/png"
    try:
        init_resp = requests.post(
            STORAGE_INITIATE_URL,
            headers={
                "Authorization": f"Key {api_key}",
                "Content-Type": "application/json",
            },
            json={"content_type": content_type, "file_name": path.name},
            timeout=30,
        )
    except requests.RequestException as exc:
        raise FalError(f"fal storage initiate failed: {exc}") from exc
    if init_resp.status_code == 401:
        raise FalError(
            "fal rejected the API key (HTTP 401). Check FAL_KEY/FAL_API_KEY.",
            status=401,
        )
    if init_resp.status_code >= 400:
        raise FalError(
            f"fal storage initiate failed (HTTP {init_resp.status_code}): "
            f"{init_resp.text.strip()[:300]}",
            status=init_resp.status_code,
        )
    try:
        body = init_resp.json()
        upload_url = body["upload_url"]
        file_url = body["file_url"]
    except (ValueError, KeyError) as exc:
        raise FalError(f"fal storage initiate returned invalid JSON: {exc}") from exc
    try:
        with open(path, "rb") as handle:
            put_resp = requests.put(
                upload_url,
                data=handle,
                headers={"Content-Type": content_type},
                timeout=120,
            )
    except requests.RequestException as exc:
        raise FalError(f"fal image upload failed: {exc}") from exc
    if put_resp.status_code >= 400:
        raise FalError(
            f"fal image upload failed (HTTP {put_resp.status_code}): "
            f"{put_resp.text.strip()[:300]}",
            status=put_resp.status_code,
        )
    return file_url


def submit(endpoint: str, payload: dict, api_key: str) -> dict:
    """Submit a queue request.

    Returns ``{"request_id", "status_url", "response_url"}``. The gateway
    canonicalizes the app route (e.g. ``fal-ai/minimax/h3-max/...`` is
    served as ``fal-ai/minimax``), so callers must use the returned
    ``status_url``/``response_url`` instead of building
    ``{endpoint}/requests/{id}/...`` paths by hand — hand-built paths
    return HTTP 405.
    """
    import requests

    try:
        resp = requests.post(
            f"{QUEUE_BASE}/{endpoint}",
            headers={
                "Authorization": f"Key {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60,
        )
    except requests.RequestException as exc:
        raise FalError(f"fal submit failed for {endpoint}: {exc}") from exc
    if resp.status_code == 401:
        raise FalError(
            "fal rejected the API key (HTTP 401). Check FAL_KEY/FAL_API_KEY.",
            status=401,
        )
    if resp.status_code >= 400:
        raise FalError(
            f"fal submit failed for {endpoint} (HTTP {resp.status_code}): "
            f"{resp.text.strip()[:300]}",
            status=resp.status_code,
        )
    try:
        body = resp.json()
        request_id = body["request_id"]
    except (ValueError, KeyError) as exc:
        raise FalError(f"fal submit returned invalid JSON: {exc}") from exc
    return {
        "request_id": request_id,
        "status_url": body.get("status_url")
        or f"{QUEUE_BASE}/{endpoint}/requests/{request_id}/status",
        "response_url": body.get("response_url")
        or f"{QUEUE_BASE}/{endpoint}/requests/{request_id}",
    }


def poll_result(
    status_url: str,
    result_url: str,
    api_key: str,
    *,
    timeout: float = 600,
    poll_interval: float = 2.0,
    progress_cb=None,
) -> dict:
    """Poll ``status_url`` until COMPLETED; fetch and return the result payload.

    A COMPLETED status carrying ``error``/``error_type`` (model failure)
    raises ``FalError``. ``progress_cb`` receives a short human-readable
    status string (e.g. ``"IN_QUEUE pos=2"``).
    """
    import requests

    deadline = time.monotonic() + timeout
    headers = {"Authorization": f"Key {api_key}", "Accept": "application/json"}
    last_status = "?"
    while True:
        if time.monotonic() > deadline:
            raise FalError(
                f"fal request timed out after {timeout:.0f}s "
                f"(last status: {last_status}). Re-run with --timeout to wait longer.",
                status=None,
            )
        try:
            resp = requests.get(status_url, headers=headers, timeout=30)
        except requests.RequestException as exc:
            raise FalError(f"fal status poll failed: {exc}") from exc
        if resp.status_code >= 400:
            raise FalError(
                f"fal status poll failed (HTTP {resp.status_code}): "
                f"{resp.text.strip()[:300]}",
                status=resp.status_code,
            )
        try:
            status_body = resp.json()
        except ValueError as exc:
            raise FalError(f"fal status poll returned invalid JSON: {exc}") from exc
        last_status = str(status_body.get("status", "?"))
        if progress_cb:
            try:
                detail = last_status
                if last_status == "IN_QUEUE" and "queue_position" in status_body:
                    detail = f"IN_QUEUE pos={status_body['queue_position']}"
                progress_cb(detail)
            except Exception:
                pass
        if last_status == "COMPLETED":
            error = status_body.get("error")
            if error:
                error_type = status_body.get("error_type", "")
                raise FalError(
                    f"fal generation failed ({error_type or 'model error'}): "
                    f"{str(error)[:300]}",
                    status=None,
                )
            break
        time.sleep(poll_interval)
    try:
        result_resp = requests.get(result_url, headers=headers, timeout=60)
    except requests.RequestException as exc:
        raise FalError(f"fal result fetch failed: {exc}") from exc
    if result_resp.status_code >= 400:
        raise FalError(
            f"fal result fetch failed (HTTP {result_resp.status_code}): "
            f"{result_resp.text.strip()[:300]}",
            status=result_resp.status_code,
        )
    try:
        return result_resp.json()
    except ValueError as exc:
        raise FalError(f"fal result returned invalid JSON: {exc}") from exc


def extract_video_url(result: dict) -> str:
    """Extract the output video URL from a queue result payload."""
    video = result.get("video")
    if isinstance(video, dict) and video.get("url"):
        return video["url"]
    if isinstance(video, str) and video.startswith("http"):
        return video
    videos = result.get("videos")
    if isinstance(videos, list) and videos:
        first = videos[0]
        if isinstance(first, dict) and first.get("url"):
            return first["url"]
        if isinstance(first, str) and first.startswith("http"):
            return first
    for key in ("video_url", "output_url", "url"):
        value = result.get(key)
        if isinstance(value, str) and value.startswith("http"):
            return value
    raise FalError(f"fal result contained no video URL: {str(result)[:300]}")


def download_video(video_url: str, dest: Path) -> Path:
    """Stream a (public) video CDN URL to ``dest``."""
    import requests

    try:
        with requests.get(video_url, stream=True, timeout=120) as resp:
            resp.raise_for_status()
            with open(dest, "wb") as handle:
                for chunk in resp.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        handle.write(chunk)
    except requests.RequestException as exc:
        raise FalError(f"fal video download failed: {exc}") from exc
    return dest


def generate_video(
    *,
    endpoint: str,
    payload: dict,
    output_path: Path,
    api_key: str,
    timeout: float = 600,
    poll_interval: float = 2.0,
    progress_cb=None,
) -> dict:
    """Submit → poll → download one generation; return result metadata."""
    handle = submit(endpoint, payload, api_key)
    result = poll_result(
        handle["status_url"],
        handle["response_url"],
        api_key,
        timeout=timeout,
        poll_interval=poll_interval,
        progress_cb=progress_cb,
    )
    video_url = extract_video_url(result)
    download_video(video_url, output_path)
    return {"request_id": handle["request_id"], "video_url": video_url, "result": result}
