# PUCP Private Cloud Orchestrator - Grupo 2

**TEL141 - Ingenieria de Redes Cloud 2026-1**

## Cobertura de Requerimientos EX1 (100 pts)

| Req | Pts | Estado | Modulos |
|-----|-----|--------|---------|
| **R1** | 40 | 100% | Orchestrator, Placement, Lifecycle, DB |
| **R1B** | 6 | **100%** | UI con login, RBAC, editar, export/import plantillas |
| **R1C** | 18 | 100% | Slice Manager OOP con flujo completo |
| **R2** | 18 | 100% | Linux Driver con SSH + QEMU + QCOW2 |
| **R5** | 10 | 100% | OVS + VLANs + DHCP + Internet |

## Roles RBAC

| Rol | Permisos |
|-----|----------|
| **admin** | Control total: infraestructura, usuarios, imagenes, slices |
| **operator** | Supervisa slices de todos, logs, troubleshooting |
| **user** | Solo sus propios slices (crear, editar, borrar) |

**Usuarios por defecto:**
- `admin` / `admin123` (Admin Infraestructura)
- `operador` / `operador123` (Operador)
- `usuario` / `usuario123` (Usuario)

## Estructura del Proyecto (41 archivos)

```
pucp-cloud-orchestrator/
src/
  models/               OOP: Slice, VM, Host, Topology, User, PlacementDecision
  placement/            VM Placement Greedy (R4)
  lifecycle/            Slice Manager CRUD + edit (R1C)
  drivers/              BaseDriver + LinuxDriver SSH (R2)
  networking/           OVS, VLANs, DHCP, NAT (R5)
  database/             MariaDB con SQLAlchemy
  auth/                 JWT + RBAC con roles
  orchestrator.py       Coordinador central
  ui/                   Flask UI (8 templates)
    templates/
      login.html        Autenticacion
      register.html     Registro de usuarios
      index.html        Dashboard con tabs, plantillas, export/import
      slice_detail.html Detalle + edicion de slice
      admin.html        Panel de administracion
      images.html       Gestion de imagenes
      sessions.html     Sesiones activas
      error.html        Pagina de error
config/                  YAML: hosts, database, network
scripts/                 SQL schema, install.sh, deploy.sh
```

## Instalacion en Server1

```bash
# 1. Transferir archivos
scp -r pucp-cloud-orchestrator ubuntu@10.0.10.1:/home/ubuntu/

# 2. SSH al servidor
ssh ubuntu@10.0.10.1

# 3. Instalar
cd /home/ubuntu/pucp-cloud-orchestrator
chmod +x scripts/install.sh
bash scripts/install.sh

# 4. Ejecutar UI
python3 -m src.ui.app
```

## Acceso

- **URL:** `http://10.0.10.1:8080`
- **Login:** `admin` / `admin123`
