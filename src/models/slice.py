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

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())[:8]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "topology": self.topology.value if isinstance(self.topology, TopologyType) else self.topology,
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
        }
