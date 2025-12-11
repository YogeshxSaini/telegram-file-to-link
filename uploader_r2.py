#!/usr/bin/env python3
import argparse
import logging
import mimetypes
import os
import sys
from pathlib import Path

import boto3
from botocore.config import Config
from dotenv import load_dotenv


HLS_TYPES = {
    ".m3u8": "application/vnd.apple.mpegurl",
    ".ts": "video/MP2T",
}


def guess_content_type(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in HLS_TYPES:
        return HLS_TYPES[ext]
    ctype, _ = mimetypes.guess_type(str(path))
    return ctype or "application/octet-stream"


def get_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return v


def make_s3_client():
    account_id = get_env("R2_ACCOUNT_ID")
    access_key = get_env("R2_ACCESS_KEY_ID")
    secret_key = get_env("R2_SECRET_ACCESS_KEY")
    endpoint_url = f"https://{account_id}.r2.cloudflarestorage.com"
    cfg = Config(signature_version="s3v4", retries={"max_attempts": 10, "mode": "standard"})
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
        config=cfg,
    )


def upload_folder(folder: Path, key_prefix: str, bucket: str, dry_run: bool = False) -> None:
    s3 = make_s3_client()
    folder = folder.resolve()
    for root, _, files in os.walk(folder):
        for fname in files:
            fpath = Path(root) / fname
            rel = fpath.relative_to(folder)
            key = f"{key_prefix.rstrip('/')}/{rel.as_posix()}"
            ctype = guess_content_type(fpath)
            if dry_run:
                logging.info("[DRY-RUN] Would upload %s to s3://%s/%s (%s)", fpath, bucket, key, ctype)
                continue
            extra = {"ContentType": ctype}
            logging.info("Uploading %s -> s3://%s/%s", fpath, bucket, key)
            s3.upload_file(str(fpath), bucket, key, ExtraArgs=extra)
    logging.info("Upload complete for folder %s", folder)


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Upload HLS directory to Cloudflare R2 using boto3")
    sub = parser.add_subparsers(dest="command", required=True)

    up = sub.add_parser("upload", help="Upload a local folder to R2 under a key prefix")
    up.add_argument("folder", help="Local folder with HLS assets")
    up.add_argument("key_prefix", help="S3 key prefix, e.g., videos/<video_id>")
    up.add_argument("--dry-run", action="store_true", help="Only log intended uploads")
    up.add_argument("--log-level", default=os.getenv("LOG_LEVEL", "INFO"))

    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    bucket = get_env("R2_BUCKET")
    folder = Path(args.folder)
    if not folder.exists():
        logging.error("Folder does not exist: %s", folder)
        sys.exit(2)
    upload_folder(folder, args.key_prefix, bucket, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
