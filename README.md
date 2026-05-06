# PUCP Private Cloud Orchestrator - Grupo 2

**TEL141 - Ingeniería de Redes Cloud 2026-1**

Sistema de orquestación para nube privada sobre infraestructura Linux.

## Módulos

| Módulo | Archivo | Requerimiento |
|--------|---------|--------------|
| Orchestrator | `src/orchestrator.py` | R1 (coordinador central) |
| VM Placement | `src/placement/placement_engine.py` | R4 (greedy algorithm) |
| Lifecycle | `src/lifecycle/slice_manager.py` | R1C (CRUD slices) |
| Linux Driver | `src/drivers/linux_driver.py` | R2 (SSH + QEMU) |
| Networking | `src/networking/network_manager.py` | R5 (OVS + VLANs) |
| Database | `src/database/db_manager.py` | Persistencia (MariaDB) |
| UI | `src/ui/app.py` | R1B (Flask web) |

## Topologías soportadas

- **Lineal**: VM1 ─ VM2 ─ VM3 ─ VM4
- **Anillo**: VM1 ─ VM2 ─ VM3 ─ VM4 ─ VM1
- **Malla**: Todos contra todos
- **Árbol**: Árbol binario
- **Bus**: Estrella desde VM1

## Instalación en Server1

```bash
cd /home/ubuntu/pucp-cloud-orchestrator
chmod +x scripts/install.sh
bash scripts/install.sh
```

## Ejecutar UI

```bash
cd /home/ubuntu/pucp-cloud-orchestrator
python3 -m src.ui.app
```

Acceder: `http://<server1-ip>:8080`

## Transferir a servidor

```bash
chmod +x scripts/deploy.sh
./scripts/deploy.sh 10.0.10.1
```
