# ==============================================================
# Slice entity - Represents a network slice (topology of VMs)
# ==============================================================

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional
from datetime import datetime
import uuid


class SliceStatus(str, Enum):
    PENDING = "pending"
    PLACING = "placing"
    CREATING = "creating"
    CONFIGURING_NETWORK = "configuring_network"
    ACTIVE = "active"
    ERROR = "error"
    DELETING = "deleting"
    DELETED = "deleted"


class TopologyType(str, Enum):
    LINEAL = "lineal"
    ANILLO = "anillo"
    MALLA = "malla"
    ARBOL = "arbol"
    BUS = "bus"
    # English aliases (from Nueva UI)
    LINEAR = "linear"
    RING = "ring"
    MESH = "mesh"
    TREE = "tree"

    @classmethod
    def _missing_(cls, value):
        # Accept English names from the new UI and map them to stored values
        _map = {
            "linear": "lineal", "ring": "anillo", "mesh": "malla",
            "tree": "arbol", "bus": "bus",
            "lineal": "lineal", "anillo": "anillo", "malla": "malla",
            "arbol": "arbol",
        }
        normalized = _map.get(str(value).lower())
        if normalized:
            return cls(normalized)
        return None

    def to_ui(self) -> str:
        """Return the English name used by the Nueva UI."""
        _map = {
            "lineal": "linear", "anillo": "ring", "malla": "mesh",
            "arbol": "tree", "bus": "bus",
            "linear": "linear", "ring": "ring", "mesh": "mesh",
            "tree": "tree",
        }
        return _map.get(self.value, self.value)


@dataclass
class Slice:
    id: str
    name: str
    topology: TopologyType
    num_vms: int
    vcpus_per_vm: int = 1
    ram_mb_per_vm: int = 512
    disk_gb_per_vm: int = 2
    vlan_id: Optional[int] = None
    subnet: Optional[str] = None
    enable_dhcp: bool = False
    enable_internet: bool = False
    status: SliceStatus = SliceStatus.PENDING
    created_by: str = "admin"
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    error_message: Optional[str] = None
    ext_topology: Optional[str] = None
    anchor_vm_name: Optional[str] = None
    base_num_vms: Optional[int] = None
    link_vlans: Optional[List[dict]] = None  # [{link_idx, vlan_id, vm_a_name, vm_b_name}]
    # Phase 2
    infrastructure_target: str = "linux"   # linux | openstack | auto
    zone_id: Optional[str] = None
    flavor_id: Optional[str] = None
    openstack_project_id: Optional[str] = None
    openstack_network_ids: Optional[List[str]] = None

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())[:8]

    def to_dict(self) -> dict:
        topo_val = self.topology.value if isinstance(self.topology, TopologyType) else self.topology
        return {
            "id": self.id,
            "name": self.name,
            "topology": topo_val,
            "topology_ui": self.topology.to_ui() if isinstance(self.topology, TopologyType) else topo_val,
            "num_vms": self.num_vms,
            "vcpus_per_vm": self.vcpus_per_vm,
            "ram_mb_per_vm": self.ram_mb_per_vm,
            "disk_gb_per_vm": self.disk_gb_per_vm,
            "vlan_id": self.vlan_id,
            "subnet": self.subnet,
            "enable_dhcp": self.enable_dhcp,
            "enable_internet": self.enable_internet,
            "status": self.status.value if isinstance(self.status, SliceStatus) else self.status,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error_message": self.error_message,
            "ext_topology": self.ext_topology,
            "anchor_vm_name": self.anchor_vm_name,
            "base_num_vms": self.base_num_vms,
            "link_vlans": self.link_vlans or [],
            "infrastructure_target": self.infrastructure_target or "linux",
            "zone_id": self.zone_id,
            "flavor_id": self.flavor_id,
            "openstack_project_id": self.openstack_project_id,
            "openstack_network_ids": self.openstack_network_ids or [],
        }
