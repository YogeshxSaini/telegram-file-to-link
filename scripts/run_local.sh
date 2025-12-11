#!/usr/bin/env zsh
set -euo pipefail

if [ -f .env ]; then
  echo "Loading .env"
  export $(grep -v '^#' .env | xargs -I{} echo {})
fi

python3 telethon_ingest.py
