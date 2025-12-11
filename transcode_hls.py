#!/usr/bin/env python3
import argparse
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path


def setup_logger(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def run_ffmpeg_single(input_path: Path, output_dir: Path, ffmpeg_bin: str, segment_time: int) -> None:
    playlist = output_dir / "playlist.m3u8"
    segment_pattern = str((output_dir / "seg_%05d.ts").resolve())
    cmd = [
        ffmpeg_bin,
        "-hide_banner",
        "-y",
        "-i",
        str(input_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-g",
        "48",
        "-sc_threshold",
        "0",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-vf",
        "scale=-2:720:flags=lanczos",
        "-hls_time",
        str(segment_time),
        "-hls_playlist_type",
        "vod",
        "-hls_segment_filename",
        segment_pattern,
        str(playlist),
    ]
    logging.info("Running ffmpeg: %s", " ".join(cmd))
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if proc.returncode != 0:
        logging.error("ffmpeg failed with output:\n%s", proc.stdout)
        raise SystemExit(proc.returncode)
    else:
        logging.info("ffmpeg completed successfully. Output at %s", playlist)


def run_ffmpeg_multibitrate(input_path: Path, output_dir: Path, ffmpeg_bin: str, segment_time: int) -> None:
    # 720p and 480p renditions, separate playlists, and a master playlist.
    var_dir = output_dir / "variants"
    var_dir.mkdir(parents=True, exist_ok=True)
    renditions = [
        {"name": "720p", "scale": "-2:720", "v_bitrate": "3000k", "a_bitrate": "128k"},
        {"name": "480p", "scale": "-2:480", "v_bitrate": "1500k", "a_bitrate": "96k"},
    ]
    for r in renditions:
        playlist = var_dir / f"{r['name']}.m3u8"
        segment_pattern = str((var_dir / f"seg_{r['name']}_%05d.ts").resolve())
        cmd = [
            ffmpeg_bin,
            "-hide_banner",
            "-y",
            "-i",
            str(input_path),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-g",
            "48",
            "-sc_threshold",
            "0",
            "-c:a",
            "aac",
            "-b:a",
            r["a_bitrate"],
            "-vf",
            f"scale={r['scale']}:flags=lanczos",
            "-maxrate",
            r["v_bitrate"],
            "-bufsize",
            "2M",
            "-hls_time",
            str(segment_time),
            "-hls_playlist_type",
            "vod",
            "-hls_segment_filename",
            segment_pattern,
            str(playlist),
        ]
        logging.info("Running ffmpeg (rendition %s): %s", r['name'], " ".join(cmd))
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if proc.returncode != 0:
            logging.error("ffmpeg failed for %s with output:\n%s", r['name'], proc.stdout)
            raise SystemExit(proc.returncode)

    # Write master playlist
    master = output_dir / "playlist.m3u8"
    with master.open("w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        f.write("#EXT-X-VERSION:3\n")
        # Rough BANDWIDTH estimates
        f.write("#EXT-X-STREAM-INF:BANDWIDTH=3200000,RESOLUTION=1280x720\n")
        f.write("variants/720p.m3u8\n")
        f.write("#EXT-X-STREAM-INF:BANDWIDTH=1700000,RESOLUTION=854x480\n")
        f.write("variants/480p.m3u8\n")
    logging.info("Master playlist generated at %s", master)


def clean_output_dir(output_dir: Path) -> None:
    if output_dir.exists():
        for p in output_dir.glob("*"):
            if p.is_file():
                p.unlink(missing_ok=True)
            elif p.is_dir():
                shutil.rmtree(p, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Transcode a video into HLS output directory")
    parser.add_argument("input_path", help="Path to input video file")
    parser.add_argument("output_dir", help="Directory to write HLS files")
    parser.add_argument("--ffmpeg", dest="ffmpeg_bin", default=os.getenv("FFMPEG_PATH", "ffmpeg"), help="ffmpeg binary path")
    parser.add_argument("--segment-time", dest="segment_time", type=int, default=int(os.getenv("HLS_SEGMENT_TIME", "6")), help="HLS segment duration seconds")
    parser.add_argument("--multi", dest="multi", action="store_true", help="Enable multi-bitrate (720p+480p) with master playlist")
    parser.add_argument("--log-level", dest="log_level", default=os.getenv("LOG_LEVEL", "INFO"))
    args = parser.parse_args()

    setup_logger(args.log_level)

    input_path = Path(args.input_path)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    clean_output_dir(output_dir)

    if not input_path.exists():
        logging.error("Input file not found: %s", input_path)
        sys.exit(2)

    if args.multi:
        run_ffmpeg_multibitrate(input_path, output_dir, args.ffmpeg_bin, args.segment_time)
    else:
        run_ffmpeg_single(input_path, output_dir, args.ffmpeg_bin, args.segment_time)


if __name__ == "__main__":
    main()
