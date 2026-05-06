# ==============================================================
# Base Driver - Abstract interface for infrastructure drivers
# Following the architecture document: the Orchestrator must NOT
# depend on specific driver implementations.
# ==============================================================

from abc import ABC, abstractmethod
from typing import List, Optional
from ..models.vm import VM
from ..models.placement_decision import PlacementDecision


class BaseDriver(ABC):
    @abstractmethod
    def create_vm(self, vm: VM, placement: PlacementDecision,
                  base_image_path: str) -> bool:
        pass

    @abstractmethod
    def delete_vm(self, vm: VM) -> bool:
        pass

    @abstractmethod
    def get_vm_status(self, vm_id: str) -> Optional[str]:
        pass

    @abstractmethod
    def get_console_token(self, vm: VM) -> Optional[str]:
        pass
