#!/usr/bin/env python
"""Transfer selected videos from joriel channel to techno_sophia channel."""

import json
import os
import sys
import time
from pathlib import Path

import requests
import yt_dlp

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Source profile for metadata
os.environ["FASTMARKET_PROFILE"] = "joriel"
from common.core.config import requires_common_config
requires_common_config("youtube", ["youtube"])
from core.engine import build_youtube_client
from commands.upload.register import upload_video

TRANSFER_DIR = Path(__file__).resolve().parent
SELECTED = TRANSFER_DIR / "selected_videos.json"
LOG = TRANSFER_DIR / "transfer_log.json"
TMP = Path("/tmp/yt_transfer")
TMP.mkdir(parents=True, exist_ok=True)


def load_log():
    if LOG.exists():
        return json.loads(LOG.read_text(encoding="utf-8"))
    return {"done": [], "failed": []}


def save_log(log):
    LOG.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


def download_video(video_id, url):
    out = TMP / f"{video_id}.mp4"
    if out.exists() and out.stat().st_size > 0:
        return out
    ydl_opts = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]",
        "outtmpl": str(out),
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    return out


def download_thumbnail(video_id):
    for name in ("maxresdefault", "hqdefault", "sddefault"):
        url = f"https://img.youtube.com/vi/{video_id}/{name}.jpg"
        try:
            r = requests.get(url, timeout=15)
            if r.status_code == 200 and len(r.content) > 1000:
                out = TMP / f"{video_id}.jpg"
                out.write_bytes(r.content)
                return out
        except requests.RequestException:
            continue
    return None


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--privacy", default="unlisted", choices=["private", "unlisted", "public"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    selected = json.loads(SELECTED.read_text(encoding="utf-8"))
    log = load_log()
    done = set(log.get("done", []))

    # Target profile for uploads
    os.environ["FASTMARKET_PROFILE"] = "techno_sophia"

    for item in selected:
        vid = item["handle"]
        if args.resume and vid in done:
            print(f"SKIP (already done): {vid} {item['title']}")
            continue
        print(f"\n=== {vid} | {item['title']} ===")
        if args.dry_run:
            print("DRY RUN: would transfer")
            continue
        try:
            video_file = download_video(vid, item["url"])
            thumb = download_thumbnail(vid)
            url = upload_video(
                str(video_file),
                title=item["title"],
                description=item.get("description", ""),
                tags=[],
                privacy=args.privacy,
                thumbnail=str(thumb) if thumb else None,
            )
            print(f"UPLOADED -> {url}")
            log.setdefault("done", []).append(vid)
            save_log(log)
            time.sleep(2)
        except Exception as e:
            print(f"FAILED: {e}")
            log.setdefault("failed", []).append({"handle": vid, "error": str(e)})
            save_log(log)

    print("\nDone. Log:", LOG)


if __name__ == "__main__":
    main()
