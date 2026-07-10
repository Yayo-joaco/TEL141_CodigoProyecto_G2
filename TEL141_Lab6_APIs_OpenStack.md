# TEL141 - Ingeniería de Redes Cloud
## Laboratorio 6: Despliegue de slices usando las APIs de OpenStack

**Semestre:** 2026-1
**Profesor:** Rubén Córdova
**Jefe de Práctica:** Alonso Escobedo (alonso.escobedo@pucp.edu.pe)

---

## 0. Indicaciones generales

- **Tiempo estimado:**
  - Entregar el Informe Previo (IP) antes de la sesión de laboratorio.
  - Entregar el Reporte Final (RF) al finalizar la sesión de laboratorio.
- Cualquier tipo de plagio será reportado a facultad.

### Resultados de aprendizaje

1. Comprender y utilizar las APIs de OpenStack para la creación y administración de redes y VMs.
2. Adquirir herramientas para definir un plan de pruebas que valide el funcionamiento del proyecto del curso.

### Objetivos

1. Consolidar el uso de la API de OpenStack.
2. Comprender y utilizar las APIs de OpenStack para la creación de redes y máquinas virtuales.
3. Adquirir herramientas para definir el plan de pruebas del proyecto.

---

## 1. Escenario global del curso

(Igual al Laboratorio 5 — VNRT/GIRA, slices de cómputo, topología MGMT_1/MGMT_2, gateway central).

### Tabla de puertos del Gateway

| Cluster | Dispositivo | Puerto |
|---|---|---|
| Linux | server1 | 5811 |
| Linux | server2 | 5812 |
| Linux | server3 | 5813 |
| Linux | server4 | 5814 |
| Linux | ovs1 | 5815 |
| OpenStack | headnode | 5821 |
| OpenStack | worker1 | 5822 |
| OpenStack | worker2 | 5823 |
| OpenStack | worker3 | 5824 |
| OpenStack | ovs2 | 5825 |

```bash
ssh ubuntu@IP_Gateway -p 5821   # ejemplo: conexión al HeadNode
```

---

## 2. Conceptos fundamentales

### 2.1 Plan de pruebas

Documento técnico que define estrategia, metodología y criterios para validar el correcto funcionamiento de una solución desplegada. Garantiza que cada módulo cumpla los requerimientos funcionales, operacionales y de rendimiento.

| Tipo de prueba | Qué valida | Ejemplos |
|---|---|---|
| **Unitarias** | Módulos individuales | Validación del parser de topologías; algoritmo de VM Placement |
| **Integración** | Comunicación entre módulos | UI ↔ Slice Manager; Slice Manager ↔ Cluster OpenStack; Backend ↔ BD |
| **Funcionales** | Cumplimiento de requerimientos | Crear slices lineales/anillo; desplegar VMs; crear redes y reglas de seguridad; eliminar slices |
| **Rendimiento** | Carga y concurrencia | Despliegue simultáneo de VMs; tiempo de creación de slices; consumo de CPU/memoria |

### 2.2 Estructura básica de un caso de prueba

Nomenclatura: **`X.Y.Z TEST_NAME`**
- `X` = módulo principal
- `Y` = sección/funcionalidad evaluada
- `Z` = prueba específica

Campos mínimos de cada caso:
- Número de caso
- Tipo de prueba
- Objetivos
- Prerrequisitos
- Procedimiento
- Resultados esperados
- Resultado obtenido (**PASS** / **FAIL** / **NT**)
- Evidencias
- Comentarios u observaciones

#### Template de ejemplo

| Campo | Contenido |
|---|---|
| **Número de Caso** | 3.1.2 |
| **Tipo de prueba** | Funcional / Integración |
| **Objetivos** | Verificar el correcto despliegue de una VM dentro de la infraestructura OpenStack mediante el orquestador y sus APIs |
| **Prerrequisitos** | Sesión bash activa en red PUCP; sesión activa del CLI del orquestador |
| **Procedimiento** | 1. Ingresar al sistema. 2. Seleccionar creación de slice. 3. Definir parámetros de VM (nombre, imagen, red, flavor). 4. Ejecutar despliegue. 5. Verificar estado vía CLI/Horizon |
| **Resultados Esperados** | VM creada; estado ACTIVE; conectividad de red; sin errores |
| **Resultados Obtenidos** | PASS / FAIL / NT |
| **Evidencias** | Capturas de Horizon; resultado de pruebas de conectividad |
| **Comentarios** | Test simplificado de ejemplo; ampliar según requisitos del proyecto |

### 2.3 APIs de OpenStack usadas en el laboratorio

| Servicio | Función | Puerto |
|---|---|---|
| **Keystone** | Autenticación y autorización | 5000 |
| **Nova** | Administración de máquinas virtuales | 8774 |
| **Neutron** | Administración de redes virtuales | 9696 |
| **Glance** | Gestión de imágenes de VM | 9292 |

### 2.4 Flujo general de aprovisionamiento (vía API)

1. Obtener token administrativo (`admin_cloud`).
2. Crear proyecto en OpenStack.
3. Crear o asociar un usuario propietario del proyecto.
4. Asignar roles sobre el proyecto.
5. Obtener token *scoped* para el proyecto.
6. Crear red(es) virtual(es) (`networks`).
7. Crear subred(es) virtual(es) (`subnets`).
8. Crear puertos virtuales (`ports`).
9. Crear instancia(s) VM (`instances`).
10. Obtener acceso a consola remota.

**Pasos previos (por slice):**
- PRE-1: Crear el proyecto Slice en el Dominio Cloud.
- PRE-2: Crear el usuario (ej. `a20210850`) y asignarlo al proyecto Slice con rol `member`.

### Materiales y equipos

- VNRT (Virtual Network Research Testbed - GIRA)
- OpenStack instalado en el laboratorio anterior (Lab 5)
- VPN para acceso al VNRT

---

## 3. Criterios de evaluación

| Producto | Criterio | Descripción | Puntaje |
|---|---|---|---|
| Informe previo | Investigación y análisis | Factores de la interacción CLI (`--debug`) ↔ APIs de OpenStack, usando la documentación oficial | 5 pts |
| Experiencia de Laboratorio | Ejecución y resolución | 1. Despliega recursos (redes, puertos, VMs) usando las APIs. 2. Automatiza creación de escenarios con scripts Python que interactúan con la API | 6 pts |
| Experiencia de Laboratorio | Análisis | 3. Mapea el diseño del orquestador (proyecto), pasando del driver de cluster Linux al driver OpenStack | (incluido en 6 pts) |
| Evaluación personal | Comprensión del proceso | 1. Responde consultas sobre interacción con APIs. 2. Justifica el uso de tokens | 2 pts |
| Evaluación continua - Proyecto | Presentación | 1. Define un plan de pruebas cuyo resultado realmente valide lo indicado | 2 pts |
| Evaluación de clases | Comprensión de teoría | Fundamentos teóricos relacionados con la experiencia de laboratorio | 5 pts |

---

## 4. INFORME PREVIO (5 pts, GRUPAL)

- Desarrollar sobre `TEL141_Lab6_IP_Template.docx` → renombrar a `TEL141_Lab6_IP_GXXX.pdf`.
- Entrega: 1 semana de plazo.

### Pasos previos: acceso a las APIs de OpenStack

**Local Host** — túneles SSH hacia el HeadNode:

| Local Host Port | Head Node Port |
|---|---|
| 55000 | 5000 (Keystone) |
| 58774 | 8774 (Nova) |
| 59696 | 9696 (Neutron) |
| 59292 | 9292 (Glance) |
| 51080 | 80 (Horizon) |

```bash
ssh -NL 55000:127.0.0.1:5000 ubuntu@10.20.12.X -p 5821
ssh -NL 58774:127.0.0.1:8774 ubuntu@10.20.12.X -p 5821
ssh -NL 59696:127.0.0.1:9696 ubuntu@10.20.12.X -p 5821
ssh -NL 59292:127.0.0.1:9292 ubuntu@10.20.12.X -p 5821
ssh -NL 51080:127.0.0.1:80 ubuntu@10.20.12.X -p 5821
```

**OPCIONAL** — reglas DNAT en el Gateway para acceso directo `<IP_GATEWAY>:<PUERTO>`:

```bash
# Habilitar ip_forward
sudo sysctl -w net.ipv4.ip_forward=1

# Regla DNAT
sudo iptables -t nat -A PREROUTING -p tcp --dport <PUERTO> -j DNAT \
  --to-destination <IP_HEADNODE>:<PUERTO>

# Permitir el reenvío
sudo iptables -A FORWARD -p tcp --dport <PUERTO> -j ACCEPT
```

> **Nota:** se asume que ya existen (del Lab 5): dominio `Cloud`, proyecto `cloud_admin`, usuario `cloud_admin`, fichero `cloud-admin-openrc` en `env-scripts/`, además de 1 flavor y 1 imagen creados.

### Actividad 1: Funcionamiento de las APIs de OpenStack (2 pts)

**Previo (Head Node):**

```bash
. ~/env-scripts/cloud-admin-openrc
```

**Paso 1** — comparar `server list` con y sin `--debug`:

```bash
openstack server list
openstack --debug server list
```
Preguntas a responder en el template:
- ¿Qué información adicional aparece al usar `--debug`?
- ¿Cuántas llamadas HTTP se realizaron en total?
- ¿A qué servicios se conectó el CLI y en qué orden?
- ¿Por qué se contacta más de un servicio para un solo comando?

**Paso 2** — token de autenticación:

```bash
openstack --debug token issue
```
Preguntas:
- ¿En qué header HTTP viaja el token en llamadas subsecuentes?
- ¿A qué endpoint de Keystone se conectó para obtenerlo?

**Paso 3** — relacionar debug con documentación oficial (Neutron API: https://docs.openstack.org/api-ref/network/v2):

```bash
openstack --debug network list
```
Preguntas:
- URL completa del request a Neutron.
- Parámetros opcionales del endpoint `/v2.0/networks`.
- Cómo filtrar redes por nombre desde el CLI.

**Paso 3.5** — replicar la llamada manualmente con `curl`:

```bash
# Obtener el token
openstack token issue -f value -c id

# Replicar la llamada que hizo el CLI
curl -s -X GET http://192.168.202.1:9696/v2.0/networks \
  -H "X-Auth-Token: <token_obtenido>" | python3 -m json.tool
```
Preguntas:
- ¿El resultado de `curl` es igual al de `openstack network list`? ¿Por qué?
- ¿Qué hace el CLI con la respuesta JSON?
- ¿Qué cambios aplica el CLI sobre la respuesta de la API?

**Paso 4** — interpretar un error HTTP (ID inexistente):

```bash
openstack --debug server show 00000000-0000-0000-0000-000000000000
```
Preguntas:
- Código HTTP retornado.
- Significado según la documentación de Nova API.
- Dónde se ve el cuerpo completo del error en el debug.

**Paso 5** — explicación (máx. 7 líneas) de qué hace realmente el CLI "por debajo" en cada comando (token, llamadas REST, parsing JSON, etc.).

---

## 5. EXPERIENCIA DE LABORATORIO — Informe Previo: Actividad 2 (3 pts)

### Actividad 2: Topología anillo de 3 nodos vía APIs

**Objetivo:** crear (100% vía API REST, sin CLI) una red tipo anillo conectando 3 instancias (`instance_1`, `instance_2`, `instance_3`) sobre el proyecto `topo1_lab6`.

**Topología:**
- `network_link1` / `subnet_link1` (`192.168.1.0/30`): `instance_1` (port2_link1) ↔ `instance_2` (port1_link1)
- `network_link2` / `subnet_link2` (`192.168.2.0/30`): `instance_2` (port1_link2) ↔ `instance_3` (port2_link2)
- `network_link3` / `subnet_link3` (`192.168.3.0/30`): `instance_3` (port1_link3) ↔ `instance_1` (port2_link3)

### Paso 1: Completar archivo `.env`

| Variable | Cómo obtenerla |
|---|---|
| `ACCESS_NODE_IP` | IP del nodo de acceso a los servicios del HeadNode |
| `ADMIN_USER_ID` | `openstack user list --domain Cloud -f value \| grep cloud_admin \| awk '{print $1}'` |
| `ADMIN_USER_PASSWORD` | `cat env-scripts/cloud-admin-openrc \| grep OS_PASSWORD \| awk -F'=' '{print $2}'` |
| `DOMAIN_ID` | `openstack domain list -f value \| grep Cloud \| awk '{print $1}'` |
| `ADMIN_PROJECT_ID` | `openstack project list --domain Cloud -f value \| grep cloud_admin \| awk '{print $1}'` |
| `ADMIN_ROLE_ID` | `openstack role list -f value \| grep admin \| awk '{print $1}'` |
| `PROJECT_NAME` | `topo1_lab6` |

### Paso 2

Ejecutar/modificar la secuencia de comandos del **Jupyter Notebook** adjunto, respetando el flujo de aprovisionamiento (sección 2.4). **Sin token de Keystone, ningún endpoint responde.**

### Paso 3: Verificar instancias creadas (vía Python/requests)

```python
import requests

def list_servers_by_project(nova_endpoint, token, project_id):
    url = f"{nova_endpoint}/servers/detail?project_id={project_id}"
    headers = {"X-Auth-Token": token}
    r = requests.get(url, headers=headers)
    return r.json()["servers"] if r.status_code == 200 else []

servers = list_servers_by_project(NOVA_ENDPOINT, admin_token, project_id)
for s in servers:
    print(s["id"], s["name"], s["status"])
```

### Paso 5: Obtener URL de consola (noVNC) de cada instancia

```python
def get_server_console(nova_endpoint, token, server_id, compute_api_version):
    """POST /servers/{id}/remote-consoles — URL noVNC. Éxito = 200."""
    url = nova_endpoint + "/servers/" + server_id + "/remote-consoles"
    headers = {
        "Content-type": "application/json",
        "X-Auth-Token": token,
        "OpenStack-API-Version": "compute " + compute_api_version,
    }
    data = {"remote_console": {"protocol": "vnc", "type": "novnc"}}
    return requests.post(url=url, headers=headers, data=json.dumps(data))

console_url = get_server_console(NOVA_ENDPOINT, admin_token, instance_id, COMPUTE_API_VERSION)
print("Consola:", console_url)
```

**Local Host** — túnel para el proxy noVNC:

```bash
ssh -NL 56080:127.0.0.1:6080 ubuntu@10.20.12.X -p 5821
```

### Paso 6: Configurar interfaces dentro de las VMs (vía consola noVNC)

```bash
ip add add 192.168.X.X dev ethX
ip link set dev ethX up
```

Luego: probar conectividad con `ping` entre las 3 instancias → Template: Paso 6, Actividad 1.

### Paso 7: Revisar topología en Horizon → Template: Paso 7 y Paso 8, Actividad 1.

---

## 6. EXPERIENCIA DE LABORATORIO — Reporte Final (6 pts, GRUPAL)

- Desarrollar la Actividad 1 sobre `TEL141_Lab6_RF_Template.docx` → renombrar `TEL141_Lab6_RF_GXXX.pdf`.
- Entrega: al finalizar la sesión síncrona.

### Actividad 1: Topología anillo de 3 nodos con salida a Internet (3 pts)

**Objetivo:** mismo anillo de 3 instancias del Informe Previo, pero dando salida a Internet a `instance_1` e `instance_2` mediante una red **external** tipo `provider/flat`, NAT en el Gateway y en el HeadNode.

**Esquema:**
```
external_network (--share --flat) --- br_ext --- Headnode --- Gateway (NAT + Port Forwarding) --- Internet
```

### Paso 1

Reusar el `.env` de la Actividad 2 (Informe Previo), cambiando solo:
```
PROJECT_NAME = topo2_lab6
```

### Paso 2: Preparar la red external y conectividad a Internet

**Importante:** la red `external` (creada en el Lab 5) **NO se borra**; solo se eliminan sus *puertos* y su *subnet* (`external_subnet`), vía Horizon.

#### En el Gateway

```bash
# IP forwarding
sudo sysctl -w net.ipv4.ip_forward=1

# Ruta hacia las VMs vía headnode
sudo ip route add 10.60.X.0/24 via 192.168.202.1

# Reglas FORWARD y MASQUERADE
sudo iptables -A FORWARD -s 10.60.X.0/24 -o ens3 -j ACCEPT
sudo iptables -A FORWARD -d 10.60.X.0/24 -i ens3 -m state --state RELATED,ESTABLISHED -j ACCEPT
sudo iptables -t nat -A POSTROUTING -s 10.60.X.0/24 -o ens3 -j MASQUERADE
```

#### En el HeadNode

```bash
# IP de gateway de las VMs en br-provider
sudo ip addr add 10.60.X.1/24 dev br-provider
sudo ip link set br-provider up

# Reservar VLAN sobre ens4 para la red provider flat
ip link add link ens4 name ens4.<VLAN> type vlan id <VLAN>
ip link set ens4.<VLAN> up
ovs-vsctl add-port br-provider ens4.<VLAN>

# IP forwarding
sysctl -w net.ipv4.ip_forward=1

# NAT hacia Internet
iptables -t nat -A POSTROUTING -s 10.60.X.0/24 -o ens3 -j MASQUERADE
iptables -A FORWARD -i br-provider -o ens3 -j ACCEPT
iptables -A FORWARD -i ens3 -o br-provider -m state --state RELATED,ESTABLISHED -j ACCEPT

# Ruta de retorno hacia el Gateway
ip route add 10.60.X.0/24 dev br-provider

# Reiniciar agentes
sudo systemctl restart neutron-openvswitch-agent
sudo systemctl restart nova-compute
```

#### En cada Worker (worker1, worker2, worker3)

> Necesario para que Neutron pueda hacer *binding* de puertos en la red provider flat; si se omite, las instancias con puertos en `external` fallan con **"Binding failed for port"**.

```bash
sudo ovs-vsctl add-br br-provider
sudo ip link add link ens4 name ens4.<VLAN> type vlan id <VLAN>
sudo ip link set ens4.<VLAN> up
sudo ovs-vsctl add-port br-provider ens4.<VLAN>
```

Editar `/etc/neutron/plugins/ml2/openvswitch_agent.ini`:

```diff
- bridge_mappings = physnet1:br-vlan
+ bridge_mappings = physnet1:br-vlan,physnet0:br-provider
```

> ⚠️ Editar con cuidado: un error aquí puede romper la instalación de OpenStack existente.

```bash
sudo systemctl restart neutron-openvswitch-agent
sudo systemctl restart nova-compute
```

### Paso 4

Ejecutar/modificar el **Notebook Jupyter** según la topología pedida (mismo flujo de la sección 2.4). Prestar atención a las etiquetas **ACT2** del notebook; para dar salida a Internet hay que **recrear `external_subnet`** (paso 7 del notebook).

### Paso 5: Verificar instancias (mismo snippet `list_servers_by_project` del IP)

```python
import requests

def list_servers_by_project(nova_endpoint, token, project_id):
    url = f"{nova_endpoint}/servers/detail?project_id={project_id}"
    headers = {"X-Auth-Token": token}
    r = requests.get(url, headers=headers)
    return r.json()["servers"] if r.status_code == 200 else []

servers = list_servers_by_project(NOVA_ENDPOINT, admin_token, project_id)
for s in servers:
    print(s["id"], s["name"], s["status"])
```

### Paso 6: URL de consola (mismo snippet `get_server_console`)

```python
def get_server_console(nova_endpoint, token, server_id, compute_api_version):
    url = nova_endpoint + "/servers/" + server_id + "/remote-consoles"
    headers = {
        "Content-type": "application/json",
        "X-Auth-Token": token,
        "OpenStack-API-Version": "compute " + compute_api_version,
    }
    data = {"remote_console": {"protocol": "vnc", "type": "novnc"}}
    return requests.post(url=url, headers=headers, data=json.dumps(data))
```

**Local Host** — túnel noVNC (igual que antes):
```bash
ssh -NL 56080:127.0.0.1:6080 ubuntu@10.20.12.X -p 5821
```

### Paso 7: Configurar interfaces de red en las VMs

Topología final:
- `instance_1`: `PORT DHCP IP` (hacia external) + `192.168.1.1/30` (link1) + `192.168.3.2/30` (link3)
- `instance_2`: `192.168.1.2/30` (link1) + `192.168.2.1/30` (link2) + `PORT DHCP IP` (hacia external)
- `instance_3`: `192.168.2.2/30` (link2) + `192.168.3.1/30` (link3)

```bash
ip add add 192.168.X.X dev ethX
ip link set dev ethX up
```

### Paso 8 → Template: Paso 1, Actividad 1
Pruebe la conexión entre las tres instancias mediante `ping`.

### Paso 9 → Template: Paso 2, Actividad 1
Pruebe la conexión a Internet desde `instance_1` e `instance_2`.

### Paso 10 → Template: Paso 3, Actividad 1
Acceda por SSH a `instance_1`.

### Paso 11 → Template: Paso 4, Actividad 1
Revise la topología de red del proyecto en Horizon.

---

## 7. Actividad 2: Elaboración del Plan de Pruebas (3 pts)

- Elaborar el plan de pruebas del módulo **Slice Manager** del proyecto del curso (el nombre puede variar según la arquitectura de cada grupo).
- Considerar los requerimientos evaluados en EX1 (parcial) y los que se evaluarán en EX2 (final), según el documento oficial del proyecto.
- Entregar en PDF, siguiendo el template de la sección 2.2 (nomenclatura `X.Y.Z`).

---

## 8. Evaluación Continua (2 pts)

- Entregable: `TEL141_LAB6_EC_GXXX.pdf`.
- **Plazo:** domingo 7 de julio, 23:59 hrs (sin tolerancia).
- Nota individual (2 pts) + grupal (2 pts), evaluada por el coach del grupo.
- Contenido: explicación clara y concisa del plan de pruebas elaborado en el Reporte Final (módulo Slice Manager).

### Desempeño en el laboratorio (2 pts)
Evaluación personal según desempeño durante la sesión.

---

## 9. Criterios clave para Claude Code

- **Todo el flujo de aprovisionamiento de este laboratorio se hace vía HTTP/REST puro** (Keystone, Nova, Neutron, Glance), normalmente desde un **Jupyter Notebook** con la librería `requests`, no con el CLI `openstack`.
- **Sin token de Keystone, ningún otro endpoint responde** — siempre obtener primero un token (admin → scoped al proyecto).
- Endpoints base (vía túneles SSH a Local Host o IP del Gateway con DNAT):
  - Keystone: puerto 5000
  - Nova: puerto 8774
  - Neutron: puerto 9696
  - Glance: puerto 9292
  - Horizon: puerto 80
  - noVNC proxy: puerto 6080
