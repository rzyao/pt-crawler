#!/bin/sh
set -e

CONFIG_DIR="/config"
CONFIG_FILE="$CONFIG_DIR/config.yaml"
DEFAULT_FILE="/app/config.yaml"

mkdir -p "$CONFIG_DIR"

if [ ! -f "$CONFIG_FILE" ]; then
  if [ ! -f "$DEFAULT_FILE" ] && [ -f "config.yaml" ]; then
    DEFAULT_FILE="config.yaml"
  fi
  if [ ! -f "$DEFAULT_FILE" ]; then
    echo "missing $CONFIG_FILE and default config not found" >&2
    exit 1
  fi
  cp "$DEFAULT_FILE" "$CONFIG_FILE"
fi

exec python -m uvicorn app:app --host 0.0.0.0 --port 8000 --log-level info
