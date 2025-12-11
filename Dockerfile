# Simple Dockerfile for local/dev runs of the pipeline
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

# Create workdir for volumes
RUN mkdir -p /app/workdir

ENV WORKDIR=/app/workdir \
    FFMPEG_PATH=ffmpeg

CMD ["python", "telethon_ingest.py"]
