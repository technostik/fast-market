#!/usr/bin/env python
"""Generate a CSV of long technical videos from the joriel channel for transfer selection."""

import csv
import os
import sys
from pathlib import Path

os.environ["FASTMARKET_PROFILE"] = "joriel"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.core.config import requires_common_config
requires_common_config("youtube", ["youtube"])
from core.engine import build_youtube_client
from common.youtube.utils import iso_duration_to_seconds

TECH_KEYWORDS = [
    "ia", "ai", "llm", "gpt", "claude", "openai", "anthropic", "gemini",
    "deepseek", "qwen", "kimi", "grok", "agi", "robot", "code", "programm",
    "algorithme", "rag", "agent", "prompt", "token", "embedding", "model",
    "modèle", "benchmark", "fine-tun", "fine tun", "perplex", "bolt", "crewai",
    "langchain", "hugging", "pytorch", "tensorflow", "transformer", "neural",
    "diffusion", "midjourney", "flux", "stable", "whisper", "transcription",
    "ocr", "vasa", "veo", "sora", "alphaevolve", "digits", "nvidia", "gpu",
    "cpu", "cloud", "serveur", "app", "application", "software", "logiciel",
    "numérique", "digital", "data", "données", "tech", "technologie", "outil",
    "tool", "tuto", "comment", "expliqué",
]


def fetch_owned_videos(client):
    cid = client.channel_id
    pid = client.get_uploads_playlist_id(cid)
    ids = []
    token = None
    while True:
        resp = client.youtube.playlistItems().list(
            part="contentDetails", playlistId=pid, maxResults=50, pageToken=token
        ).execute()
        for it in resp.get("items", []):
            ids.append(it["contentDetails"]["videoId"])
        token = resp.get("nextPageToken")
        if not token:
            break

    out = []
    for i in range(0, len(ids), 50):
        batch = ids[i:i + 50]
        r = client.youtube.videos().list(
            part="snippet,contentDetails,status", id=",".join(batch)
        ).execute()
        for it in r.get("items", []):
            sn = it.get("snippet", {})
            cd = it.get("contentDetails", {})
            dur = cd.get("duration", "")
            secs = iso_duration_to_seconds(dur)
            if secs <= 180:
                continue
            text = (sn.get("title", "") + " " + sn.get("description", "")).lower()
            matched = [k for k in TECH_KEYWORDS if k in text]
            if not matched:
                continue
            priority_keywords = [
                "#tech", "tuto", "code", "programm", "rag", "agent", "prompt",
                "llm", "gpt", "claude", "openai", "deepseek", "gemini", "grok",
                "algorithme", "transformer", "neural", "benchmark", "api", "github",
                "python", "software", "logiciel", "model", "modèle",
            ]
            preselected = any(k in matched for k in priority_keywords) or "#tech" in text
            out.append({
                "selected": "x" if preselected else "",
                "handle": it["id"],
                "title": sn.get("title", ""),
                "duration_min": round(secs / 60, 1),
                "url": f"https://www.youtube.com/watch?v={it['id']}",
                "matched_keywords": ",".join(matched),
                "description": sn.get("description", "").replace("\n", " ")[:500],
            })
    return out


def main():
    client = build_youtube_client()
    rows = fetch_owned_videos(client)
    out_path = Path(__file__).resolve().parent / "candidates.csv"
    fieldnames = [
        "selected", "handle", "title", "duration_min", "url",
        "matched_keywords", "description",
    ]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} candidates to {out_path}")


if __name__ == "__main__":
    main()
