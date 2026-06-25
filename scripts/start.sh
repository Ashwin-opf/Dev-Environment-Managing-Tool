#!/usr/bin/env bash
# PC Doctor - Unix start script.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

if [ ! -d "$ROOT_DIR/node_modules" ]; then
  echo "[!] Node dependencies are missing. Run ./scripts/setup.sh first."
  exit 1
fi

if [ ! -d "$ROOT_DIR/backend/.venv" ]; then
  echo "[!] Python backend environment is missing. Run ./scripts/setup.sh first."
  exit 1
fi

echo "[PC Doctor] Launching Tauri desktop app..."
cd "$ROOT_DIR"
npm run dev
