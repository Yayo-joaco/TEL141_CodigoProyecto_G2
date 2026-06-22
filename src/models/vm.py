# ==============================================================
# VM entity - Represents a virtual machine within a slice
# ==============================================================

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List
from datetime import datetime
import uuid


class VMStatus(str, Enum):
    PENDING = "pending"
    CREATING = "creating"
    ACTIVE = "active"
    ERROR = "error"
    DELETING = "deleting"
    DELETED = "deleted"


@dataclass
class VM:
    id: str
    slice_id: str
    name: str
    index: int
    host_ip: Optional[str] = None
    vcpus: int = 1
    ram_mb: int = 512
    disk_gb: int = 2
    ip_address: Optional[str] = None
    mac_address: Optional[str] = None
    vnc_port: Optional[int] = None
    vnc_ws_port: Optional[int] = None
    vnc_token: Optional[str] = None
    tap_interface: Optional[str] = None
    qemu_pid: Optional[int] = None
    interfaces: Optional[List[dict]] = None  # [{type, tap_name, mac, vlan_id, link_idx, peer_vm_name, iface_name}]
    status: VMStatus = VMStatus.PENDING
    error_message: Optional[str] = None
    enable_internet: bool = False
    image: Optional[str] = None
    # Phase 2
    flavor_id: Optional[str] = None
    openstack_server_id: Optional[str] = None
    ip_address_external: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())[:8]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "slice_id": self.slice_id,
            "name": self.name,
            "index": self.index,
            "host_ip": self.host_ip,
            "vcpus": self.vcpus,
            "ram_mb": self.ram_mb,
            "ram_gb": round(self.ram_mb / 1024, 1),
            "disk_gb": self.disk_gb,
            "ip_address": self.ip_address,
            "ip_address_external": self.ip_address_external,
            "mac_address": self.mac_address,
            "vnc_port": self.vnc_port,
            "vnc_ws_port": self.vnc_ws_port,
            "vnc_token": self.vnc_token,
            "tap_interface": self.tap_interface,
            "qemu_pid": self.qemu_pid,
            "interfaces": self.interfaces or [],
            "status": self.status.value if isinstance(self.status, VMStatus) else self.status,
            "enable_internet": self.enable_internet,
            "image": self.image,
            "flavor_id": self.flavor_id,
            "openstack_server_id": self.openstack_server_id,
            "error_message": self.error_message,
            "created_at": self.created_at,
        }
