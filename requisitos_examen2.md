# Requisitos de Evaluación — Examen 2

## Tabla de Evaluación: Implementación

### R1B — Interfaz de Usuario (UI) / Gestión del ciclo de vida de Slices *(12 pts)*

| # | Criterio de Implementación | Peso |
|---|---------------------------|------|
| 1 | Ser independiente de la capa de infraestructura (cluster de servidores Linux, OpenStack, AWS, etc.) | 10 |
| 2 | Implementación soporta concurrencia de usuarios | 10 |
| 3 | Permite seleccionar slices con topologías predefinidas: lineal, malla, árbol, anillo, y bus | 10 |
| 4 | Permite editar slices (aún no desplegadas) combinando topologías predefinidas | 10 |
| 5 | Permite editar slices (aún no desplegadas) agregando nodos y enlaces | 10 |
| 6 | Permite grabar slices (aún no desplegadas) para posterior edición | 5 |
| 7 | Permite exportar topologías | 5 |
| 8 | Permite importar topologías | 5 |
| 9 | Permite crear nuevos slices sobre la base de editar topologías importadas | 5 |
| 10 | Permite especificar la configuración (capacidad) de cada máquina virtual (VM) creada | 5 |
| 11 | Lista la información necesaria de los slices que le pertenecen al usuario | 5 |
| 12 | Permite visualizar el consumo de recursos del sistema | 5 |
| 13 | Permite borrar o editar slices previamente instanciados | 5 |
| 14 | Permite importar imágenes de VMs en forma independiente de la plataforma | 5 |
| 15 | Provee los tokens/credenciales necesarias para que el dueño del slice pueda acceder a la consola virtual de cada VM | 5 |

---

### R3 — Soporte de OpenStack *(18 pts)*

| # | Criterio de Implementación | Peso |
|---|---------------------------|------|
| 1 | Implementó OpenStack con al menos los mínimos servicios requeridos (Keystone, Horizon, Nova, Neutron & ML2 Plugin, Glance) | 20 |
| 2 | Orquesta Topologías (predefinidas y personalizadas) usando OpenStack | 30 |
| 3 | Orquesta slices/topologías en capa 2 | 20 |
| 4 | Uso eficiente (p.ej., paralelo) de APIs de OpenStack en el despliegue de VMs sobre OpenStack | 10 |
| 5 | Borrado de slices | 10 |
| 6 | Permite visualizar máquinas virtuales desplegadas en Horizon | 10 |

---

### R4 — VM Placement *(12 pts)*

| # | Criterio de Implementación | Peso |
|---|---------------------------|------|
| 1 | Lista recursos (servidores) disponibles en ambas plataformas (Linux Cluster y OpenStack) | 20 |
| 2 | Entrega una asignación de VMs a servidores de acuerdo al algoritmo diseñado en caso haya capacidad | 50 |
| 3 | Rechaza la asignación de VMs cuando no hay recursos disponibles, indicando la razón de la falla (logs o consola) | 20 |
| 4 | Las VMs son asignadas a servidores en las zonas de disponibilidad elegida por el usuario | 10 |

---

### R5 — Networking y Seguridad *(14 pts)*

| # | Criterio de Implementación | Peso |
|---|---------------------------|------|
| 1 | Usa VLANs para segmentar los enlaces/subredes minimizando el overhead (p.ej., no usa túneles en el Linux cluster ni redes "self-service" en OpenStack) | 15 |
| 2 | Implementa las reglas de seguridad requeridas en los slices en el Linux cluster | 15 |
| 3 | Implementa las reglas de seguridad requeridas en los slices en OpenStack | 10 |
| 4 | Provee de salida a internet a las máquinas que lo requieran (Linux Cluster y OpenStack) | 15 |
| 5 | Provee acceso desde internet (p.ej., SSH) a máquinas virtuales que lo requieran (Linux Cluster y OpenStack) | 20 |
| 6 | Configuran dinámicamente el switch físico para limitar los broadcasts de cada enlace virtual a los servidores que realmente los necesiten | 25 |

---

## Tabla de Evaluación: Presentación, Documentación y Diseño

### R0 — Performance en presentación, temas requeridos y documentación *(14 pts)*

| # | Criterio | Peso |
|---|----------|------|
| 1 | Claridad de exposición y respuesta a preguntas | 35 |
| 2 | High Level Software Design claramente documentado | 35 |
| 3 | Reporte de pruebas: completo y bien documentado | 30 |

---

### R3 — Diseño: Despliegue en OpenStack *(12 pts)*

| # | Criterio | Peso |
|---|----------|------|
| 1 | Consideración en diseño y fundamentación de los mínimos servicios requeridos (Keystone, Horizon, Nova, Neutron & ML2 Plugin, Glance) | 20 |
| 2 | Uso eficiente (p.ej., paralelo, manejo de errores, auth de módulos, uso de caché) de APIs de OpenStack en el despliegue de VMs sobre OpenStack | 25 |
| 3 | Permite orquestar VMs usando OpenStack (Topologías personalizadas y predefinidas) | 25 |
| 4 | Diseño permite crear topologías capa 2 | 20 |
| 5 | Permite visualizar los proyectos desplegados por usuario (p.ej., en Horizon) | 10 |

---

### R4 — Diseño: VM Placement *(18 pts)*

| # | Criterio | Peso |
|---|----------|------|
| 1 | Estrategia de monitoreo de recursos es consistente con el algoritmo a desarrollar y con el evitar superar el máximo nivel de congestión permitido | 15 |
| 2 | Algoritmo de aprovisionamiento de VMs tiene función objetivo bien definida y sustentada | 20 |
| 3 | Algoritmo considera uso eficiente (utilización) de recursos para aquellas cargas dinámicas que no consumen (en todo momento) el 100% de recursos y pueden soportar que sus recursos (p.ej., cores físicos) sean compartidos | 15 |
| 4 | Algoritmo considera no solo la utilización actual, sino el estimado de la congestión durante el ciclo de vida del slice. Tanto el impacto de un número grande de asignaciones de VMs con baja utilización (pero que podrían variar/aumentar en el tiempo), como el impacto de asignaciones recientes cuyo uso aún no se ve reflejado en las mediciones (p.ej., aún no bootea la VM) | 15 |
| 5 | Algoritmo de aprovisionamiento de VMs considera slices como un todo, y no VMs individuales | 15 |
| 6 | Algoritmo considera/limita el tiempo de ejecución para instancias (osea, slices) grandes | 10 |
| 7 | Considera la zona de disponibilidad pedida al colocar las VMs | 10 |

