# Base image providing ffmpeg + Python for custom builds
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/runtime
COPY ../../requirements.txt /opt/runtime/requirements.txt
RUN pip install --no-cache-dir -r /opt/runtime/requirements.txt

# Consumers can COPY their app into this image and set CMD/ENTRYPOINT
