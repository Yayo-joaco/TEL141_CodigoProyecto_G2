#!/bin/bash
# =============================================================
# deploy.sh — pull latest code, rebuild frontend, restart backend
# Run once on the app server after cloning, then use for updates.
# Usage: bash scripts/deploy.sh
# =============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
UI_DIR="$PROJECT_DIR/Nueva UI"
LOG_DIR="$PROJECT_DIR/logs"
VENV="$PROJECT_DIR/venv"

echo "=== PUCP Cloud Orchestrator — Deploy ==="
echo "Project: $PROJECT_DIR"

# 1. Pull latest (backend + submodules)
echo ""
echo "[1/4] git pull + submodule update..."
cd "$PROJECT_DIR"
git pull
git submodule update --init --remote "Nueva UI" 2>/dev/null || git submodule update --init --recursive

# 2. Python venv + dependencies
echo ""
echo "[2/4] Installing Python dependencies in venv..."
if [ ! -d "$VENV" ]; then
    python3 -m venv "$VENV"
    echo "      Virtualenv created."
fi
"$VENV/bin/pip" install --quiet -r requirements.txt
echo "      Python deps OK."

# 3. Build React frontend
if [ -d "$UI_DIR" ]; then
    echo ""
    echo "[3/4] Building React frontend..."
    export NVM_DIR="$HOME/.nvm"
    [ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"
    if command -v nvm &>/dev/null; then
        nvm use 20 2>/dev/null || nvm use default 2>/dev/null || true
    fi
    echo "      Node: $(node --version 2>/dev/null || echo 'not found'), npm: $(npm --version 2>/dev/null || echo 'not found')"
    cd "$UI_DIR"
    npm install --silent
    npm run build
    echo "      Frontend built -> $UI_DIR/dist"
else
    echo "[3/4] No 'Nueva UI' directory — skipping frontend build."
fi

cd "$PROJECT_DIR"
mkdir -p "$LOG_DIR"

# 4. Reload and restart systemd service
echo ""
echo "[4/4] Restarting backend service..."
if systemctl list-unit-files pucp-orchestrator.service &>/dev/null; then
    sudo systemctl daemon-reload
    sudo systemctl restart pucp-orchestrator
    sleep 2
    sudo systemctl status pucp-orchestrator --no-pager -l | head -20
else
    echo "      Service not installed. Run: bash scripts/setup-service.sh"
    exit 1
fi

echo ""
echo "=== Done. App at http://$(hostname -I | awk '{print $1}'):8080 ==="

