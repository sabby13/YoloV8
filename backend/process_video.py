#!/usr/bin/env python3
"""
surveillance_system/backend/process_video.py

Standalone CLI tool — process a video without the API server.

Usage:
    python process_video.py --video path/to/video.mp4 --output ./output
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from tracker.pipeline import process_video


def main():
    parser = argparse.ArgumentParser(description="CCTV Video Processor")
    parser.add_argument("--video",  required=True, help="Input video path")
    parser.add_argument("--output", default="output", help="Output directory")
    args = parser.parse_args()

    if not Path(args.video).exists():
        print(f"[Error] Video not found: {args.video}")
        sys.exit(1)

    def on_progress(pct, msg):
        bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
        print(f"\r  [{bar}] {pct:3d}%  {msg}", end="", flush=True)

    print(f"\n🎬 Processing: {args.video}")
    print(f"📂 Output dir: {args.output}\n")

    result = process_video(args.video, args.output, on_progress)

    print(f"\n\n✅ Done — tracked {len(result)} person(s)\n")
    print("─" * 50)
    for pid, d in sorted(result.items()):
        print(f"  {pid}  │  first: {d['first_seen']:.1f}s  "
              f"│  last: {d['last_seen']:.1f}s  "
              f"│  appearances: {d['appearances']}")
    print("─" * 50)
    print(f"\n📋 Full data → {args.output}/tracking_data.json\n")


if __name__ == "__main__":
    main()
