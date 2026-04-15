#!/usr/bin/env python3
"""Test script to check if we can retrieve transcript from member-only video."""

import sys
from pathlib import Path

# Add corpus-cli to path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from common.core.config import load_config
from common.core.registry import build_plugins
from common.youtube.client import YouTubeClient
from common.youtube.auth import YouTubeOAuth
from common.youtube.transport import RSSPlaylistTransport
from common import structlog

logger = structlog.get_logger(__name__)

VIDEO_ID = "9Fl0KPaJwOM"
VIDEO_URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"


def test_video_details_via_api():
    """Test 1: Check if API can see the video."""
    print("\n" + "=" * 80)
    print("TEST 1: Get video details via YouTube Data API")
    print("=" * 80)

    config = load_config()
    yt_cfg = config.get("youtube", {})

    # Get authenticated client
    client_secret = yt_cfg.get("client_secret_path")
    oauth = YouTubeOAuth(client_secret_path=client_secret)
    api = oauth.get_client()
    client = YouTubeClient(api, channel_id=yt_cfg["channel_id"], auth=oauth)

    # Try to get video details
    try:
        response = (
            client.youtube.videos()
            .list(part="snippet,contentDetails,status", id=VIDEO_ID)
            .execute()
        )

        if response.get("items"):
            video = response["items"][0]
            print(f"✓ Video found!")
            print(f"  Title: {video['snippet'].get('title', 'N/A')}")
            print(f"  Privacy: {video['status'].get('privacyStatus', 'N/A')}")
            print(f"  Duration: {video['contentDetails'].get('duration', 'N/A')}")
            print(f"  Description: {video['snippet'].get('description', '')[:100]}...")
            return True
        else:
            print(f"✗ Video NOT found via API")
            return False

    except Exception as e:
        print(f"✗ Error: {e}")
        return False


def test_video_via_yt_dlp():
    """Test 2: Check if yt-dlp can access the video with cookies."""
    print("\n" + "=" * 80)
    print("TEST 2: Get video details via yt-dlp (with cookies)")
    print("=" * 80)

    config = load_config()
    cookies = config.get("youtube", {}).get("cookies")

    if not cookies:
        print("⚠ No cookies configured, skipping")
        return False

    try:
        import yt_dlp

        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "cookiefile": cookies,
            "skip_download": True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(VIDEO_URL, download=False)

        if info:
            print(f"✓ Video accessible via yt-dlp!")
            print(f"  Title: {info.get('title', 'N/A')}")
            print(f"  Availability: {info.get('availability', 'N/A')}")
            print(f"  Duration: {info.get('duration', 'N/A')}s")
            return True
        else:
            print(f"✗ Video not accessible via yt-dlp")
            return False

    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_transcript_via_youtube_transcript_api():
    """Test 3: Check if youtube-transcript-api can get transcript."""
    print("\n" + "=" * 80)
    print("TEST 3: Get transcript via youtube-transcript-api")
    print("=" * 80)

    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        api = YouTubeTranscriptApi()
        transcript_list = api.list(VIDEO_ID)

        print(f"Available transcripts:")
        for t in transcript_list:
            print(f"  - {t.language} ({t.language_code}) - Auto: {t.is_generated}")

        # Try to fetch English or French transcript
        try:
            transcript = transcript_list.find_transcript(["en", "fr"])
            text = " ".join(entry["text"] for entry in transcript.fetch().to_raw_data())
            print(f"\n✓ Transcript fetched!")
            print(f"  Length: {len(text)} chars")
            print(f"  Preview: {text[:200]}...")
            return True
        except Exception as e:
            print(f"\n✗ Failed to fetch transcript: {e}")
            return False

    except Exception as e:
        print(f"✗ Error: {e}")
        return False


def test_transcript_via_yt_dlp():
    """Test 4: Check if yt-dlp can download subtitles."""
    print("\n" + "=" * 80)
    print("TEST 4: Get subtitles via yt-dlp")
    print("=" * 80)

    config = load_config()
    cookies = config.get("youtube", {}).get("cookies")

    if not cookies:
        print("⚠ No cookies configured, skipping")
        return False

    try:
        import yt_dlp
        import tempfile

        out_dir = Path(tempfile.mkdtemp())

        ydl_opts = {
            "outtmpl": str(out_dir / "%(id)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "cookiefile": cookies,
            "write_subs": True,
            "write_auto_subs": True,
            "skip_download": True,
            "subtitleslangs": ["en", "fr"],
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([VIDEO_URL])

        # Look for subtitle files
        found = False
        for ext in ["srt", "vtt", "txt"]:
            subs = list(out_dir.glob(f"*.{ext}"))
            if subs:
                text = subs[0].read_text(encoding="utf-8")
                print(f"✓ Subtitle file found: {subs[0].name}")
                print(f"  Length: {len(text)} chars")
                print(f"  Preview: {text[:200]}...")
                found = True
                break

        if not found:
            print("✗ No subtitle files downloaded")

        return found

    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_transcript_via_api_captions():
    """Test 5: Check if YouTube API captions endpoint works."""
    print("\n" + "=" * 80)
    print("TEST 5: Get captions via YouTube Data API")
    print("=" * 80)

    config = load_config()
    yt_cfg = config.get("youtube", {})

    try:
        client_secret = yt_cfg.get("client_secret_path")
        oauth = YouTubeOAuth(client_secret_path=client_secret)
        api = oauth.get_client()
        client = YouTubeClient(api, channel_id=yt_cfg["channel_id"], auth=oauth)

        # List captions
        response = (
            client.youtube.captions()
            .list(part="snippet", videoId=VIDEO_ID)
            .execute()
        )

        if response.get("items"):
            print(f"✓ Captions available!")
            for item in response["items"]:
                snippet = item["snippet"]
                print(f"  - {snippet.get('name', 'No name')} ({snippet.get('language', 'N/A')})")
                print(f"    Status: {snippet.get('status', 'N/A')}")

            # Try to download first caption
            caption_id = response["items"][0]["id"]
            caption = (
                client.youtube.captions()
                .download(id=caption_id, tfmt="srt")
                .execute()
            )

            if caption:
                text = caption.decode("utf-8") if isinstance(caption, bytes) else str(caption)
                print(f"\n✓ Caption downloaded!")
                print(f"  Length: {len(text)} chars")
                print(f"  Preview: {text[:200]}...")
                return True
        else:
            print(f"✗ No captions available via API")
            return False

    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_plugin_fetch():
    """Test 6: Try fetching via the actual plugin."""
    print("\n" + "=" * 80)
    print("TEST 6: Fetch video via YouTubePlugin")
    print("=" * 80)

    config = load_config()

    try:
        plugins = build_plugins(config, tool_root=ROOT)
        plugin = plugins["youtube"]

        # Create ItemMeta
        from plugins.base import ItemMeta
        from datetime import datetime

        item_meta = ItemMeta(
            source_id=VIDEO_ID,
            updated_at=datetime.now(),
            metadata={
                "id": VIDEO_ID,
                "title": "Member-only test",
                "description": "",
                "published_at": "",
                "url": VIDEO_URL,
                "duration_seconds": 0,
                "privacy_status": "private",  # Assuming member-only shows as private
            },
        )

        # Try to fetch
        print("Attempting to fetch video...")
        doc = plugin.fetch(item_meta)
        print(f"✓ Video fetched successfully!")
        print(f"  Title: {doc.title}")
        print(f"  Text length: {len(doc.raw_text)} chars")
        print(f"  Preview: {doc.raw_text[:200]}...")
        return True

    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("Testing member-only video transcript access")
    print(f"Video: {VIDEO_URL}")

    results = {
        "API Video Details": test_video_details_via_api(),
        "yt-dlp Access": test_video_via_yt_dlp(),
        "youtube-transcript-api": test_transcript_via_youtube_transcript_api(),
        "yt-dlp Subtitles": test_transcript_via_yt_dlp(),
        "YouTube API Captions": test_transcript_via_api_captions(),
        "Plugin Fetch": test_plugin_fetch(),
    }

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    for test_name, success in results.items():
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"{status} - {test_name}")

    # Overall result
    if any(results.values()):
        print(f"\n✓ At least one method works!")
    else:
        print(f"\n✗ No methods successfully retrieved the transcript")


if __name__ == "__main__":
    main()
