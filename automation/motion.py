#!/usr/bin/env python3
"""Original 9:16 autoplay clip of the take. We never re-encode someone else's video."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from quote_card import render_quote_card

HERE = Path(__file__).resolve().parent
FFMPEG_CANDIDATES = (
    "/opt/homebrew/bin/ffmpeg",
    "/usr/bin/ffmpeg",
    "/usr/local/bin/ffmpeg",
)


def ffmpeg_bin() -> str | None:
    for p in FFMPEG_CANDIDATES:
        if Path(p).is_file():
            return p
    return shutil.which("ffmpeg")


def render_take_video(copy: dict, story: dict, out_path: Path) -> Path:
    """6–7s Ken Burns 1080×1920 H.264 + silent AAC. Autoplays on X and IG Reels."""
    bin_ = ffmpeg_bin()
    if not bin_:
        raise RuntimeError("ffmpeg not installed")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tease = out_path.with_name(out_path.stem + "-tease.jpg")
    full = out_path.with_name(out_path.stem + "-full.jpg")
    tease.write_bytes(render_quote_card(copy, story, tease=True))
    full.write_bytes(render_quote_card(copy, story, tease=False))

    # Beat 1: kicker. Beat 2: take zooms in. Silent audio so IG doesn't reject.
    cmd = [
        bin_, "-y",
        "-loop", "1", "-t", "1.5", "-i", str(tease),
        "-loop", "1", "-t", "6.2", "-i", str(full),
        "-f", "lavfi", "-t", "8", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-filter_complex",
        "[0:v]scale=1080:1920,fps=30,format=yuv420p,setsar=1[v0];"
        "[1:v]scale=1296:2304,zoompan=z='min(1.14,1+0.0008*on)':"
        "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=186:s=1080x1920:fps=30,"
        "format=yuv420p,setsar=1[v1];"
        "[v0][v1]xfade=transition=fade:duration=0.35:offset=1.15,"
        "scale=in_range=full:out_range=tv,format=yuv420p[v]",
        "-map", "[v]", "-map", "2:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-profile:v", "high", "-level", "4.1",
        "-pix_fmt", "yuv420p", "-r", "30",
        "-c:a", "aac", "-ac", "2", "-ar", "44100", "-b:a", "96k",
        "-shortest", "-t", "7",
        "-movflags", "+faststart",
        str(out_path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not out_path.exists() or out_path.stat().st_size < 40000:
        print("  video   xfade failed, using single-card zoom")
        if r.stderr:
            print("  ffmpeg ", (r.stderr or "")[-400:].replace("\n", " "))
        cmd2 = [
            bin_, "-y",
            "-loop", "1", "-i", str(full),
            "-f", "lavfi", "-t", "8", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-filter_complex",
            "[0:v]scale=1296:2304,zoompan=z='min(1.14,1+0.0009*on)':"
            "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=210:s=1080x1920:fps=30,"
            "fade=t=in:st=0:d=0.35,scale=in_range=full:out_range=tv,format=yuv420p[v]",
            "-map", "[v]", "-map", "1:a",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-profile:v", "high", "-level", "4.1",
            "-pix_fmt", "yuv420p", "-r", "30",
            "-c:a", "aac", "-ac", "2", "-ar", "44100", "-b:a", "96k",
            "-shortest", "-t", "7",
            "-movflags", "+faststart",
            str(out_path),
        ]
        r2 = subprocess.run(cmd2, capture_output=True, text=True)
        if r2.returncode != 0 or not out_path.exists() or out_path.stat().st_size < 40000:
            err = (r2.stderr or r.stderr or "ffmpeg failed")[-600:]
            raise RuntimeError(err)
    print(f"  video   {out_path.name} {out_path.stat().st_size // 1024}KB")
    return out_path
