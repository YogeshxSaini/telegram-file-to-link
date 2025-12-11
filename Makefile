PYTHON ?= python3
PIP ?= pip3

.PHONY: help
help:
	@echo "Common tasks:"
	@echo "  make venv         - Create virtualenv and install deps"
	@echo "  make run          - Run Telethon ingest locally"
	@echo "  make transcode    - Quick ffmpeg transcode test"
	@echo "  make upload       - Upload a local HLS dir to R2"
	@echo "  make docker-build - Build Docker image"
	@echo "  make docker-run   - Run Docker container"

.PHONY: venv
venv:
	$(PYTHON) -m venv .venv
	. .venv/bin/activate && pip install --upgrade pip && pip install -r requirements.txt

.PHONY: run
run:
	$(PYTHON) telethon_ingest.py

.PHONY: transcode
transcode:
	@[ -n "$(INPUT)" ] || (echo "Usage: make transcode INPUT=/path/video.mp4 OUT=./outdir" && exit 1)
	$(PYTHON) transcode_hls.py "$(INPUT)" "$(OUT)"

.PHONY: upload
upload:
	@[ -n "$(DIR)" ] && [ -n "$(PREFIX)" ] || (echo "Usage: make upload DIR=./workdir/<id>/hls PREFIX=videos/<id>" && exit 1)
	$(PYTHON) uploader_r2.py upload "$(DIR)" "$(PREFIX)"

.PHONY: docker-build
docker-build:
	docker build -t telegram-hls:latest .

.PHONY: docker-run
docker-run:
	docker run --rm -it --env-file .env -v "$$PWD/workdir:/app/workdir" telegram-hls:latest
