# ==============================================================
# VM Placement Engine - Greedy Algorithm (R4)
# Decides which VM goes to which physical host based on:
# - Available resources (CPU cores, RAM, disk)
# - Least-loaded server strategy (greedy)
# ==============================================================

import logging
from typing import List

from ..models.host import Host
from ..models.vm import VM
from ..models.placement_decision import PlacementDecision, PlacementPlan

logger = logging.getLogger("orchestrator.placement")


class PlacementEngine:
    """
    Greedy VM Placement:
      1. Sort hosts by available resources (descending).
      2. For each VM, pick the host with the most free resources.
      3. If no host can fit the VM, return failure.
    """

    def __init__(self, hosts: List[Host]):
        self.hosts = hosts

    def place_vms(self, slice_id: str, vms: List[VM]) -> PlacementPlan:
        decisions = []
        available_hosts = list(self.hosts)

        for vm in vms:
            decision = self._place_single_vm(vm, available_hosts)
            decisions.append(decision)
            if not decision.success:
                return PlacementPlan(
                    slice_id=slice_id,
                    decisions=decisions,
                    success=False,
                    error_message=f"Cannot place VM '{vm.name}': {decision.reason}",
                )

        return PlacementPlan(
            slice_id=slice_id,
            decisions=decisions,
            success=True,
        )

    def _place_single_vm(self, vm: VM, hosts: List[Host]) -> PlacementDecision:
        candidates = [
            h for h in hosts
            if h.is_active and h.can_allocate(vm.vcpus, vm.ram_mb, vm.disk_gb)
        ]

        if not candidates:
            return PlacementDecision(
                vm_id=vm.id,
                vm_name=vm.name,
                vm_index=vm.index,
                host_ip="",
                host_hostname="",
                vcpus_allocated=vm.vcpus,
                ram_mb_allocated=vm.ram_mb,
                disk_gb_allocated=vm.disk_gb,
                success=False,
                reason=f"No host with enough resources (need {vm.vcpus} vCPU, "
                       f"{vm.ram_mb}MB RAM, {vm.disk_gb}GB disk)",
            )

        best = max(
            candidates,
            key=lambda h: h.available_vcpus * 1000 + h.available_ram_mb
        )

        best.allocate(vm.vcpus, vm.ram_mb, vm.disk_gb)

        logger.info(
            "Placement: %s -> %s (%s) [vCPU=%d, RAM=%dMB, Disk=%dGB]",
            vm.name, best.hostname, best.ip,
            vm.vcpus, vm.ram_mb, vm.disk_gb
        )

        return PlacementDecision(
            vm_id=vm.id,
            vm_name=vm.name,
            vm_index=vm.index,
            host_ip=best.ip,
            host_hostname=best.hostname,
            vcpus_allocated=vm.vcpus,
            ram_mb_allocated=vm.ram_mb,
            disk_gb_allocated=vm.disk_gb,
            success=True,
        )

    def release_vm(self, vm: VM):
        for host in self.hosts:
            if host.ip == vm.host_ip:
                host.release(vm.vcpus, vm.ram_mb, vm.disk_gb)
                logger.info(
                    "Released resources on %s: vCPU=%d, RAM=%dMB, Disk=%dGB",
                    host.hostname, vm.vcpus, vm.ram_mb, vm.disk_gb
                )
                break
