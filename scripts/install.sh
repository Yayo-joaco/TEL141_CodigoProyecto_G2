#!/bin/bash
# ==============================================================
# PUCP Cloud Orchestrator - Installation Script
# Run this on Server1 (Headnode) as user 'ubuntu'
# ==============================================================

set -e

echo "============================================"
echo " PUCP Cloud Orchestrator - Instalación"
echo " Grupo 2 - Fase 1"
echo "============================================"
echo ""

# Update system
echo "[1/6] Actualizando paquetes..."
sudo apt-get update -qq

# Install Python 3 and pip
echo "[2/6] Instalando Python 3 y pip..."
sudo apt-get install -y -qq python3 python3-pip python3-venv

# Install MariaDB
echo "[3/6] Instalando MariaDB..."
sudo apt-get install -y -qq mariadb-server

# Start MariaDB
sudo systemctl start mariadb
sudo systemctl enable mariadb

# Setup database
echo "[4/6] Configurando base de datos..."
sudo mysql < /home/ubuntu/pucp-cloud-orchestrator/scripts/setup_database.sql

# Install QEMU/KVM + OVS (for VM management)
echo "[5/6] Instalando QEMU/KVM y Open vSwitch..."
sudo apt-get install -y -qq qemu-kvm qemu-utils openvswitch-switch bridge-utils dnsmasq

# Install Python dependencies
echo "[6/6] Instalando dependencias Python..."
pip3 install -r /home/ubuntu/pucp-cloud-orchestrator/requirements.txt

echo ""
echo "============================================"
echo " Instalación completada exitosamente!"
echo "============================================"
echo ""
echo "Para ejecutar la UI:"
echo "  cd /home/ubuntu/pucp-cloud-orchestrator"
echo "  python3 -m src.ui.app"
echo ""
echo "Accede en: http://$(hostname -I | awk '{print $1}'):8080"
echo ""
