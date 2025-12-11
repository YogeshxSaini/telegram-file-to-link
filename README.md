# Telegram ➜ HLS (Cloudflare R2 + Worker)

Production-ready, end-to-end pipeline to accept large videos (>1GB) sent via Telegram and publish HLS-streamable public links served by a Cloudflare Worker backed by Cloudflare R2.

- Ingest: Telethon (Telegram client) downloads new videos from a configured chat/channel
- Transcode: `ffmpeg` into HLS (playlist.m3u8 + `.ts` segments)
- Upload: S3-compatible `boto3` to Cloudflare R2 with multipart uploads
- Serve: Cloudflare Worker fetches from R2 with correct headers
- Player: Tiny HTML page using `hls.js`

## Features
- Handles very large files (no 20MB bot-API limit) using Telethon client
- Sensible defaults: 720p HLS, 6s segments, VOD playlist
- Optional multi-bitrate (720p + 480p) via `--multi` / `MULTIBITRATE=true`
- Robust logging, retries, and optional cleanup of temp files
- Docker image that includes ffmpeg + Python runtime

## Architecture
1. Telethon client listens to a Telegram chat and downloads videos into `workdir/<video_id>/input.ext`.
2. `transcode_hls.py` runs ffmpeg to produce `workdir/<video_id>/hls/` with `playlist.m3u8` and `.ts` segments.
3. `uploader_r2.py` uploads the entire `hls/` folder to R2 under `videos/<video_id>/`.
4. A Cloudflare Worker serves `https://<your-domain>/videos/<video_id>/playlist.m3u8` with caching and content types.
5. The Telethon client replies in Telegram with the public HLS URL.

## Prerequisites
- Python 3.10+
- ffmpeg (installed locally or via Docker image)
- Cloudflare account with R2 enabled
- Wrangler CLI (for Worker): `npm install -g wrangler`
- Telegram API credentials from https://my.telegram.org

## Setup

### 1) Cloudflare R2
- Create an R2 bucket (e.g., `video-hls`).
- Create R2 API tokens/keys.
- Note your `Account ID`.

### 2) Cloudflare Worker
- Edit `worker/wrangler.toml`:
  - `name`: set a unique worker name
  - `bucket_name`: your R2 bucket name
- Publish the Worker:

```bash
cd worker
wrangler login
wrangler publish
```

- In the Cloudflare dashboard or via Wrangler, bind the R2 bucket to the Worker as `VIDEO_BUCKET` (already configured in `wrangler.toml`).
- Obtain your Worker public base URL (e.g., `https://<name>.<account>.workers.dev`). If using a custom domain/route, set that up in Cloudflare and update the README references accordingly.

### 3) Telegram API
- Go to https://my.telegram.org and create an application to obtain `api_id` and `api_hash`.
- Decide how you want to authenticate:
  - Session file: provide `TELEGRAM_SESSION_PATH` and the script will prompt for phone/code on the first run
  - Session string: generate with Telethon and set `TELEGRAM_SESSION_STRING` (recommended for Docker/headless)

### 4) Configure environment
Copy `.env.example` to `.env` and fill in values:

```bash
cp .env.example .env
# edit .env
```

Required variables:
- `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`
- One of `TELEGRAM_SESSION_STRING` or `TELEGRAM_SESSION_PATH`
- `TELEGRAM_WATCH_SOURCE` (username, ID, invite link, or `me`)
- `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`
- `WORKER_PUBLIC_BASE_URL` (e.g., `https://your-worker.workers.dev`)

Optional:
- `WORKDIR` (default `./workdir`)
- `FFMPEG_PATH` (default `ffmpeg`)
- `HLS_SEGMENT_TIME` (default `6`)
- `MULTIBITRATE` (`true`/`false`, default `false`)
- `CLEANUP` (`true`/`false`) to remove temp files after upload
- `R2_KEY_ROOT` (default `videos`)
- `LOG_LEVEL` (e.g., `DEBUG`)

## Running Locally

### Option A: With Docker (recommended)

```bash
# Build the image
docker build -t telegram-hls:latest .

# Run with your .env and a local workdir volume for temp files
docker run --rm -it --env-file .env -v "$PWD/workdir:/app/workdir" telegram-hls:latest
```

On first run, if using a session file (and not a session string), Telethon will prompt for phone/code in the container terminal.

### Option B: Without Docker

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

# load .env and run
./scripts/run_local.sh
```

## Usage Flow
- Send a large video to the watched chat/channel (configured via `TELEGRAM_WATCH_SOURCE`).
- The pipeline downloads, transcodes to HLS, uploads to R2, and replies in the chat with:

```
https://<your-worker-domain>/videos/<video_id>/playlist.m3u8
```

- To quickly test playback, open `web/player.html` locally and paste the playlist URL or use a query param:

```
file:///.../web/player.html?url=https://<your-worker-domain>/videos/<video_id>/playlist.m3u8
```

## CLI Tools

- Transcoder:

```bash
python transcode_hls.py /path/to/input.mp4 ./outdir [--multi]
```

- Uploader:

```bash
python uploader_r2.py upload ./outdir videos/<video_id>
```

- Makefile helpers:

```bash
make venv
make transcode INPUT=/path/video.mp4 OUT=./outdir
make upload DIR=./outdir PREFIX=videos/123
make docker-build
make docker-run
```

## Worker Routing
- The Worker expects R2 keys to be stored under `videos/<video_id>/...`.
- The public URLs follow the same path: `https://<your-worker-domain>/videos/<video_id>/playlist.m3u8`.

## Notes on Access Control
- This sample sets objects without public ACLs; the Worker mediates access. If you prefer direct R2 access, set ACLs on upload (not recommended for granular control). The Worker currently sets CORS to `*` to simplify playback across origins.

## Limits, Cost, and Cleanup
- Cloudflare R2 free tier and Worker free tier apply; see Cloudflare pricing.
- HLS segments and playlists can consume storage quickly; set `CLEANUP=true` if you want temporary files removed after upload.
- Consider TTLs and lifecycle rules in R2 to manage storage costs over time.

## Security
- Do not commit `.env` or secrets.
- Never hardcode credentials in code. This repo uses environment variables and dotenv for local development.

## Troubleshooting
- ffmpeg not found: ensure it's installed or set `FFMPEG_PATH`.
- Missing env vars: scripts will error out with which name is missing.
- Worker 404: verify your R2 keys under the `videos/<video_id>/` prefix and ensure `WORKER_PUBLIC_BASE_URL` is correct.

## File Reference
- `telethon_ingest.py`: Telethon client; downloads, transcodes, uploads, and replies with URL
- `transcode_hls.py`: ffmpeg wrapper for HLS (single or multi-bitrate)
- `uploader_r2.py`: Uploads HLS folder to R2 via boto3
- `worker/worker.js`: Cloudflare Worker serving HLS files from R2
- `worker/wrangler.toml`: Example Wrangler config (binds `VIDEO_BUCKET`)
- `web/player.html`: Minimal HLS player using hls.js
- `Dockerfile` and `docker/ffmpeg.Dockerfile`: Containers with ffmpeg + Python
- `scripts/run_local.sh`: Helper to run locally with `.env`
- `.env.example`: All required/optional variables
- `Makefile`: Common tasks and shortcuts

## Sample Large Video Test
Use a >1GB sample video and send it to your configured Telegram chat. The pipeline will handle download, transcode to 720p HLS, upload, and return the public URL. For quick synthetic tests without Telegram, you can also run the transcoder and uploader manually as shown above.

## Deploy to Oracle Cloud (Always Free)

Oracle’s Always Free tier can run this pipeline 24/7. High-level steps:

1) Create an Always Free VM
- Shape: `VM.Standard.A1.Flex` (Arm/Ampere) or `VM.Standard.E2.1.Micro` if Arm not available.
- OCPUs: 2, Memory: 4–8 GB (adjust based on your video sizes).
- OS: Ubuntu 22.04 LTS recommended.

2) Configure networking
- Create a Virtual Cloud Network (VCN) with public subnet.
- Security List: allow outbound HTTPS (443) for Telegram and Cloudflare; inbound SSH (22) from your IP.
- Optional: add a Network Security Group (NSG) and attach to instance.

3) SSH + install Docker
```bash
ssh ubuntu@<public_ip>
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker
```

4) Copy repo and env
```bash
git clone <your-repo-url>
cd telegram_file_to_link
scp .env ubuntu@<public_ip>:/home/ubuntu/telegram_file_to_link/.env
```

5) Prefer session string (headless)
- Generate `TELEGRAM_SESSION_STRING` locally, set it in `.env`, and remove `TELEGRAM_SESSION_PATH` to avoid interactive login.

6) Run via Docker Compose (auto-restart)
```bash
docker compose up -d --build
docker compose logs -f ingest
```

7) Systemd (optional alternative to Compose)
- Create `/etc/systemd/system/telegram-hls.service`:
```
[Unit]
Description=Telegram HLS Ingest Service
After=network.target

[Service]
WorkingDirectory=/home/ubuntu/telegram_file_to_link
EnvironmentFile=/home/ubuntu/telegram_file_to_link/.env
ExecStart=/usr/bin/docker run --rm --name telegram-hls \
  --env-file /home/ubuntu/telegram_file_to_link/.env \
  -v /home/ubuntu/telegram_file_to_link/workdir:/app/workdir \
  telegram-hls:latest
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```
- Enable and start:
```bash
docker build -t telegram-hls:latest .
sudo systemctl daemon-reload
sudo systemctl enable telegram-hls
sudo systemctl start telegram-hls
sudo journalctl -u telegram-hls -f
```

8) Maintenance
- Update:
```bash
git pull
docker compose up -d --build
```
- Logs:
```bash
docker compose logs -f ingest
```

Notes:
- Ensure `WORKER_PUBLIC_BASE_URL` and all R2 creds are set in `.env`.
- Arm instances use ffmpeg from apt; performance is sufficient for typical 720p transcodes.
