# ==============================================================
# PlacementDecision - Result of VM Placement algorithm
# ==============================================================

from dataclasses import dataclass
from typing import Optional


@dataclass
class PlacementDecision:
    vm_id: str
    vm_name: str
    vm_index: int
    host_ip: str
    host_hostname: str
    vcpus_allocated: int
    ram_mb_allocated: int
    disk_gb_allocated: int
    success: bool = True
    reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "vm_id": self.vm_id,
            "vm_name": self.vm_name,
            "vm_index": self.vm_index,
            "host_ip": self.host_ip,
            "host_hostname": self.host_hostname,
            "vcpus_allocated": self.vcpus_allocated,
            "ram_mb_allocated": self.ram_mb_allocated,
            "disk_gb_allocated": self.disk_gb_allocated,
            "success": self.success,
            "reason": self.reason,
        }


@dataclass
class PlacementPlan:
    slice_id: str
    decisions: list   # List[PlacementDecision]
    success: bool = True
    error_message: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "slice_id": self.slice_id,
            "decisions": [d.to_dict() for d in self.decisions],
            "success": self.success,
            "error_message": self.error_message,
        }
