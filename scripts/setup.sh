#!/usr/bin/env bash
# PC Doctor - Unix first-time setup script (Linux & macOS).
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[ok]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
err()   { echo -e "${RED}[x]${NC} $1"; exit 1; }

echo ""
echo "  PC Doctor - Setup"
echo "  -------------------------------------"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$ROOT_DIR/backend"
VENV_DIR="$BACKEND_DIR/.venv"

# --- Python ------------------------------------------------------------------
if command -v python3 &>/dev/null; then
    info "Python found: $(python3 --version)"
elif command -v apt-get &>/dev/null; then
    warn "Python 3 not found. Installing with apt..."
    sudo apt-get update -qq
    sudo apt-get install -y python3 python3-pip python3-venv
elif command -v brew &>/dev/null; then
    warn "Python 3 not found. Installing with Homebrew..."
    brew install python
else
    err "Python 3.10+ is required. Install Python and run setup again."
fi

# --- Node.js -----------------------------------------------------------------
if command -v node &>/dev/null && command -v npm &>/dev/null; then
    info "Node found: $(node --version)"
elif command -v apt-get &>/dev/null; then
    warn "Node.js/npm not found. Installing with apt..."
    sudo apt-get update -qq
    sudo apt-get install -y nodejs npm
elif command -v brew &>/dev/null; then
    warn "Node.js/npm not found. Installing with Homebrew..."
    brew install node
else
    err "Node.js 18+ and npm are required. Install them and run setup again."
fi

# --- Python virtual environment ----------------------------------------------
if [ ! -d "$VENV_DIR" ]; then
    info "Creating Python virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

info "Installing Python backend dependencies..."
# Use python3 -m pip to avoid any pip binary lock issues
"$VENV_DIR/bin/python3" -m pip install --quiet --upgrade pip
"$VENV_DIR/bin/python3" -m pip install --quiet -r "$BACKEND_DIR/requirements.txt"

info "Populating repair knowledge database..."
# Force UTF-8 so the print statements work on all locales
PYTHONIOENCODING=utf-8 "$VENV_DIR/bin/python3" "$BACKEND_DIR/populate_db.py"

info "Installing Node app dependencies..."
npm --prefix "$ROOT_DIR" install

echo ""
info "Setup complete. Run: npm start"
echo ""
