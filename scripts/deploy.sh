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

echo "=== PUCP Cloud Orchestrator — Deploy ==="
echo "Project: $PROJECT_DIR"

# 1. Pull latest
echo ""
echo "[1/4] git pull..."
cd "$PROJECT_DIR"
git pull

# 2. Build React frontend (skip if directory missing)
if [ -d "$UI_DIR" ]; then
    echo ""
    echo "[2/4] Building React frontend..."
    cd "$UI_DIR"
    npm install --silent
    npm run build
    echo "      Frontend built -> $UI_DIR/dist"
else
    echo "[2/4] No 'Nueva UI' directory — skipping frontend build."
fi

cd "$PROJECT_DIR"

# 3. Ensure log directory exists
mkdir -p "$LOG_DIR"

# 4. Restart or start systemd service
echo ""
echo "[3/4] Restarting backend service..."
if systemctl list-unit-files pucp-orchestrator.service &>/dev/null; then
    sudo systemctl restart pucp-orchestrator
    echo "      pucp-orchestrator restarted."
else
    echo "      Service not installed. Run:  bash scripts/setup-service.sh"
    exit 1
fi

# 5. Show live status
echo ""
echo "[4/4] Status:"
sudo systemctl status pucp-orchestrator --no-pager -l | head -25

echo ""
echo "=== Done. App at http://$(hostname -I | awk '{print $1}'):8080 ==="
