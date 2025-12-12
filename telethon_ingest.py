#!/usr/bin/env python3
import asyncio
import logging
import os
import shlex
import sys
from pathlib import Path

from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential
from telethon import TelegramClient, events
from telethon.sessions import StringSession


VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v"}


def get_env(name: str, required: bool = True, default: str | None = None) -> str | None:
    v = os.getenv(name, default)
    if required and (v is None or v == ""):
        raise RuntimeError(f"Missing required environment variable: {name}")
    return v


def setup_logger() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=getattr(logging, level, logging.INFO), format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def is_video_message(msg) -> bool:
    if not getattr(msg, "media", None):
        return False
    # Telethon convenience attributes
    if getattr(msg, "video", None):
        return True
    doc = getattr(msg, "document", None)
    if doc:
        mime = getattr(doc, "mime_type", "") or ""
        if mime.startswith("video/"):
            return True
        # Fallback to filename extension
        for attr in getattr(doc, "attributes", []) or []:
            name = getattr(attr, "file_name", None)
            if name and Path(name).suffix.lower() in VIDEO_EXTS:
                return True
    return False


def get_message_extension(msg) -> str:
    doc = getattr(msg, "document", None)
    if doc:
        # prefer original filename extension if present
        for attr in getattr(doc, "attributes", []) or []:
            name = getattr(attr, "file_name", None)
            if name:
                return Path(name).suffix or ".mp4"
        mime = getattr(doc, "mime_type", "") or ""
        if "/" in mime:
            major, minor = mime.split("/", 1)
            if major == "video" and minor:
                return "." + minor
    if getattr(msg, "video", None):
        return ".mp4"
    return ".mp4"


def get_video_id(msg) -> str:
    doc = getattr(msg, "document", None)
    if doc and getattr(doc, "id", None):
        return str(doc.id)
    # fallback to chatId_messageId
    return f"{msg.chat_id}_{msg.id}"


async def build_client() -> TelegramClient:
    api_id = int(get_env("TELEGRAM_API_ID"))
    api_hash = get_env("TELEGRAM_API_HASH")
    session_str = os.getenv("TELEGRAM_SESSION_STRING")
    session_path = os.getenv("TELEGRAM_SESSION_PATH", ".telegram.session")
    if session_str:
        session = StringSession(session_str)
    else:
        # Will prompt on first run; good for local/dev.
        session = session_path
    client = TelegramClient(session, api_id, api_hash)
    await client.start()
    me = await client.get_me()
    logging.info("Logged in as %s", me.username or me.id)
    logging.info("Account type: %s", "bot" if getattr(me, "bot", False) else "user")
    return client


def run_subprocess(cmd: list[str], cwd: Path | None = None) -> None:
    logging.info("Running: %s", " ".join(shlex.quote(c) for c in cmd))
    proc = asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    async def _drain(p):
        assert p.stdout
        async for line in p.stdout:
            logging.info(line.decode(errors="ignore").rstrip())

    async def _wait(p):
        await _drain(p)
        rc = await p.wait()
        if rc != 0:
            raise RuntimeError(f"Command failed with exit code {rc}: {' '.join(cmd)}")

    return proc, _wait


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=20))
async def transcode(input_path: Path, hls_dir: Path) -> None:
    ffmpeg_bin = os.getenv("FFMPEG_PATH", "ffmpeg")
    segment_time = os.getenv("HLS_SEGMENT_TIME", "6")
    multi = os.getenv("MULTIBITRATE", "false").lower() == "true"
    cmd = [
        sys.executable,
        str(Path(__file__).with_name("transcode_hls.py")),
        str(input_path),
        str(hls_dir),
        "--ffmpeg",
        ffmpeg_bin,
        "--segment-time",
        str(segment_time),
    ]
    if multi:
        cmd.append("--multi")
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    assert proc.stdout
    async for line in proc.stdout:
        logging.info(line.decode(errors="ignore").rstrip())
    rc = await proc.wait()
    if rc != 0:
        raise RuntimeError("Transcode failed")


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=20))
async def upload_hls(hls_dir: Path, key_prefix: str) -> None:
    cmd = [
        sys.executable,
        str(Path(__file__).with_name("uploader_r2.py")),
        "upload",
        str(hls_dir),
        key_prefix,
    ]
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    assert proc.stdout
    async for line in proc.stdout:
        logging.info(line.decode(errors="ignore").rstrip())
    rc = await proc.wait()
    if rc != 0:
        raise RuntimeError("Upload failed")


async def handle_message(client: TelegramClient, event):
    msg = event.message
    if not is_video_message(msg):
        return
    video_id = get_video_id(msg)
    workdir = Path(os.getenv("WORKDIR", "./workdir")) / video_id
    hls_dir = workdir / "hls"
    workdir.mkdir(parents=True, exist_ok=True)

    ext = get_message_extension(msg)
    input_path = workdir / f"input{ext}"
    logging.info("Downloading media to %s", input_path)
    try:
        await client.send_message(entity=msg.chat_id, message=f"⏳ Received video {video_id}. Downloading…")
    except Exception:
        pass
    def _progress(received: int, total: int):
        try:
            pct = (received / total * 100) if total else 0
            if received == 0 or received == total or received % (50 * 1024 * 1024) == 0:  # every ~50MB
                logging.info("Downloading… %s / %s (%.1f%%)",
                             f"{received/1024/1024:.1f}MB",
                             f"{(total or 0)/1024/1024:.1f}MB",
                             pct)
        except Exception:
            pass

    try:
        await client.download_media(msg, file=str(input_path), progress_callback=_progress)
    except Exception as e:
        logging.exception("Download failed: %s", e)
        return

    try:
        try:
            await client.send_message(entity=msg.chat_id, message=f"🎬 Transcoding {video_id} to HLS…")
        except Exception:
            pass
        await transcode(input_path, hls_dir)
        try:
            await client.send_message(entity=msg.chat_id, message=f"📤 Uploading {video_id} to R2…")
        except Exception:
            pass
        root = os.getenv("R2_KEY_ROOT", "videos").strip("/") or "videos"
        key_prefix = f"{root}/{video_id}"
        await upload_hls(hls_dir, key_prefix)
        base = get_env("WORKER_PUBLIC_BASE_URL")
        public_url = f"{base.rstrip('/')}/videos/{video_id}/playlist.m3u8"
        await client.send_message(entity=msg.chat_id, message=f"✅ Ready: {public_url}")
        if os.getenv("CLEANUP", "false").lower() == "true":
            try:
                for p in workdir.rglob("*"):
                    if p.is_file():
                        p.unlink(missing_ok=True)
                for p in sorted(workdir.glob("**/*"), reverse=True):
                    if p.is_dir():
                        p.rmdir()
            except Exception as ce:
                logging.warning("Cleanup failed: %s", ce)
    except Exception as e:
        logging.exception("Processing failed: %s", e)
        await client.send_message(entity=msg.chat_id, message=f"❌ Failed to process video: {e}")


async def main_async() -> None:
    load_dotenv()
    setup_logger()
    client = await build_client()
    # Preflight: ensure R2 and worker envs are present to avoid late-stage failures.
    missing = []
    for name in [
        "R2_ACCOUNT_ID",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET",
        "WORKER_PUBLIC_BASE_URL",
    ]:
        if not os.getenv(name):
            missing.append(name)
    if missing:
        logging.error(
            "Missing required env vars: %s. Please set them in your .env or container environment.",
            ", ".join(missing),
        )
        raise RuntimeError("Missing required environment variables: " + ", ".join(missing))
    # Watching source can be optional: for bot accounts, watch all incoming messages.
    source = os.getenv("TELEGRAM_WATCH_SOURCE")
    me = await client.get_me()

    if getattr(me, "bot", False):
        # For bots, messages come from users; filtering on the bot entity won't catch them.
        if source:
            try:
                entity = await client.get_entity(source)
                logging.info("Bot mode: filtering incoming messages for entity: %s", source)
                @client.on(events.NewMessage(chats=entity))
                async def _(event):
                    logging.debug("Incoming message: chat=%s id=%s", event.chat_id, event.id)
                    await handle_message(client, event)
            except Exception as e:
                logging.warning("Failed to resolve entity '%s' (%s). Falling back to all incoming messages.", source, e)
                @client.on(events.NewMessage(incoming=True))
                async def _(event):
                    logging.debug("Incoming message: chat=%s id=%s", event.chat_id, event.id)
                    await handle_message(client, event)
        else:
            logging.info("Bot mode: watching all incoming messages")
            @client.on(events.NewMessage(incoming=True))
            async def _(event):
                logging.debug("Incoming message: chat=%s id=%s", event.chat_id, event.id)
                await handle_message(client, event)
    else:
        # User accounts typically watch a specific chat or channel.
        if not source:
            raise RuntimeError("TELEGRAM_WATCH_SOURCE is required for user accounts (set to username, ID, invite link, or 'me')")
        entity = await client.get_entity(source)
        logging.info("User mode: watching messages in: %s", source)
        @client.on(events.NewMessage(chats=entity))
        async def _(event):
            logging.debug("Incoming message: chat=%s id=%s", event.chat_id, event.id)
            await handle_message(client, event)

    # Also process existing media if desired (optional; uncomment)
    # async for m in client.iter_messages(entity, limit=10):
    #     await handle_message(client, type("E", (), {"message": m}))

    await client.run_until_disconnected()


def main() -> None:
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
