#!/bin/bash
# ==============================================================
# PUCP Cloud Orchestrator - Installation Script v2
# Run this on Server1 (Headnode) as user 'ubuntu'
# ==============================================================

set -e

echo "============================================"
echo " PUCP Cloud Orchestrator - Instalacion v2"
echo " Grupo 2 - Fase 1"
echo "============================================"
echo ""

echo "[1/7] Actualizando paquetes..."
sudo apt-get update -qq

echo "[2/7] Instalando Python 3 y pip..."
sudo apt-get install -y -qq python3 python3-pip python3-venv

echo "[3/7] Instalando MariaDB..."
sudo apt-get install -y -qq mariadb-server
sudo systemctl start mariadb
sudo systemctl enable mariadb

echo "[4/7] Configurando base de datos..."
sudo mysql -e "CREATE DATABASE IF NOT EXISTS pucp_orchestrator CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
sudo mysql -e "CREATE USER IF NOT EXISTS 'orchestrator'@'localhost' IDENTIFIED BY 'PucpCloud2026!';"
sudo mysql -e "GRANT ALL PRIVILEGES ON pucp_orchestrator.* TO 'orchestrator'@'localhost';"
sudo mysql -e "FLUSH PRIVILEGES;"
sudo mysql pucp_orchestrator < /home/ubuntu/pucp-cloud-orchestrator/scripts/setup_database.sql
echo "Base de datos configurada."

echo "[5/7] Instalando QEMU/KVM y Open vSwitch..."
sudo apt-get install -y -qq qemu-kvm qemu-utils openvswitch-switch bridge-utils iptables

echo "[5b/7] Instalando dnsmasq..."
# dnsmasq se instalara pero su servicio de sistema fallara (puerto 53 ocupado
# por systemd-resolved). No importa: nuestro codigo usa dnsmasq en
# network namespaces aislados, NO el servicio del sistema.
sudo apt-get install -y -qq dnsmasq || true
sudo systemctl stop dnsmasq 2>/dev/null || true
sudo systemctl disable dnsmasq 2>/dev/null || true
echo "dnsmasq instalado (servicio de sistema desactivado a proposito)"

echo "[6/7] Instalando dependencias Python..."
# python3-pip ya fue instalado en paso [2/7]
sudo apt-get install -y -qq --reinstall python3-pip 2>/dev/null || true
python3 -m pip install --upgrade pip -q 2>/dev/null || true

# Intentar instalar con pip. Si falla, instalar desde apt como fallback
python3 -m pip install -r /home/ubuntu/pucp-cloud-orchestrator/requirements.txt 2>/dev/null || {
    echo "pip fallo, instalando desde apt como fallback..."
    sudo apt-get install -y -qq python3-flask python3-paramiko python3-yaml python3-sqlalchemy python3-pymysql 2>/dev/null || true
    # PyJWT no tiene paquete apt en 20.04, se instala con pip aislado
    python3 -m pip install --user PyJWT 2>/dev/null || true
}

echo "[7/7] Verificando instalacion..."
python3 -c "import flask; import paramiko; import sqlalchemy; import yaml; import jwt; print('OK')" && echo "Todas las dependencias OK"

echo ""
echo "============================================"
echo " Instalacion completada exitosamente!"
echo "============================================"
echo ""
echo "Usuarios por defecto:"
echo "  admin     / admin123   (Admin Infraestructura)"
echo "  operador  / operador123 (Operador)"
echo "  usuario   / usuario123  (Usuario)"
echo ""
echo "Para ejecutar la UI:"
echo "  cd /home/ubuntu/pucp-cloud-orchestrator"
echo "  python3 -m src.ui.app"
echo ""
echo "Accede en: http://$(hostname -I | awk '{print $1}'):8080"
echo ""
