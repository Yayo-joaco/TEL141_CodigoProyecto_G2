#!/bin/bash
# =============================================================
# setup-service.sh — install and enable the systemd service
# Run ONCE on the app server (requires sudo).
# Usage: bash scripts/setup-service.sh
# =============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SERVICE_SRC="$SCRIPT_DIR/pucp-orchestrator.service"
SERVICE_DST="/etc/systemd/system/pucp-orchestrator.service"

echo "=== Installing pucp-orchestrator systemd service ==="

# 1. Patch the WorkingDirectory path in the service file to match this install
TMP_SERVICE="/tmp/pucp-orchestrator.service"
sed "s|WorkingDirectory=.*|WorkingDirectory=$PROJECT_DIR|" "$SERVICE_SRC" > "$TMP_SERVICE"
# Also patch ExecStart python path
PYTHON_BIN="$(which python3)"
sed -i "s|ExecStart=.*|ExecStart=$PYTHON_BIN -m src.ui.app|" "$TMP_SERVICE"

# 2. Install
sudo cp "$TMP_SERVICE" "$SERVICE_DST"
sudo systemctl daemon-reload
sudo systemctl enable pucp-orchestrator
sudo systemctl start pucp-orchestrator

echo ""
echo "Service installed and started."
echo "Check status:  sudo systemctl status pucp-orchestrator"
echo "View logs:     sudo journalctl -u pucp-orchestrator -f"
echo "Or tail:       tail -f $PROJECT_DIR/logs/orchestrator.log"
echo ""
echo "After any git pull, run:  bash scripts/deploy.sh"
