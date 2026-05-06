#!/bin/bash
# ==============================================================
# PUCP Cloud Orchestrator - Deploy Script
# Transfer code from local machine to Server1 via SCP
# Usage: ./deploy.sh <server_ip>
# ==============================================================

set -e

SERVER_IP=${1:-"10.0.10.1"}
REMOTE_USER="ubuntu"
REMOTE_PATH="/home/ubuntu/pucp-cloud-orchestrator"

echo "Deploying to ${REMOTE_USER}@${SERVER_IP}:${REMOTE_PATH}"

# Create remote directory
ssh ${REMOTE_USER}@${SERVER_IP} "mkdir -p ${REMOTE_PATH}"

# Transfer all files
cd "$(dirname "$0")/.."
scp -r config/ src/ scripts/ requirements.txt README.md ${REMOTE_USER}@${SERVER_IP}:${REMOTE_PATH}/

echo ""
echo "Files transferred. Now SSH into server and run:"
echo "  ssh ${REMOTE_USER}@${SERVER_IP}"
echo "  cd ${REMOTE_PATH}"
echo "  bash scripts/install.sh"
