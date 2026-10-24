#!/usr/bin/env python
"""Convert a filled candidates.csv into selected_videos.json."""

import csv
import json
import sys
from pathlib import Path

TRUTHY = {"x", "yes", "y", "1", "true", "oui"}


def main():
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "candidates.csv"
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parent / "selected_videos.json"

    selected = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if (row.get("selected") or "").strip().lower() in TRUTHY:
                selected.append({
                    "handle": row["handle"],
                    "title": row["title"],
                    "duration_min": row["duration_min"],
                    "url": row["url"],
                    "description": row.get("description", ""),
                })

    out_path.write_text(json.dumps(selected, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Selected {len(selected)} videos -> {out_path}")


if __name__ == "__main__":
    main()
