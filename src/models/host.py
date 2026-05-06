# ==============================================================
# Host entity - Represents a physical server
# ==============================================================

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class HostRole(str, Enum):
    HEADNODE = "headnode"
    WORKER = "worker"


@dataclass
class Host:
    hostname: str
    ip: str
    role: HostRole = HostRole.WORKER
    port: int = 22
    user: str = "ubuntu"
    total_vcpus: int = 8
    total_ram_mb: int = 8192
    total_disk_gb: int = 100
    available_vcpus: int = 8
    available_ram_mb: int = 8192
    available_disk_gb: int = 100
    ovs_bridge: str = "br-int"
    is_active: bool = True
    vms_running: int = 0

    def can_allocate(self, vcpus: int, ram_mb: int, disk_gb: int) -> bool:
        return (
            self.is_active
            and self.available_vcpus >= vcpus
            and self.available_ram_mb >= ram_mb
            and self.available_disk_gb >= disk_gb
        )

    def allocate(self, vcpus: int, ram_mb: int, disk_gb: int):
        self.available_vcpus -= vcpus
        self.available_ram_mb -= ram_mb
        self.available_disk_gb -= disk_gb
        self.vms_running += 1

    def release(self, vcpus: int, ram_mb: int, disk_gb: int):
        self.available_vcpus = min(self.total_vcpus, self.available_vcpus + vcpus)
        self.available_ram_mb = min(self.total_ram_mb, self.available_ram_mb + ram_mb)
        self.available_disk_gb = min(self.total_disk_gb, self.available_disk_gb + disk_gb)
        self.vms_running = max(0, self.vms_running - 1)

    def usage_pct(self) -> float:
        cpu_used = self.total_vcpus - self.available_vcpus
        return (cpu_used / max(1, self.total_vcpus)) * 100

    def to_dict(self) -> dict:
        return {
            "hostname": self.hostname,
            "ip": self.ip,
            "role": self.role.value if isinstance(self.role, HostRole) else self.role,
            "total_vcpus": self.total_vcpus,
            "total_ram_mb": self.total_ram_mb,
            "total_disk_gb": self.total_disk_gb,
            "available_vcpus": self.available_vcpus,
            "available_ram_mb": self.available_ram_mb,
            "available_disk_gb": self.available_disk_gb,
            "is_active": self.is_active,
            "vms_running": self.vms_running,
            "usage_pct": round(self.usage_pct(), 2),
        }
