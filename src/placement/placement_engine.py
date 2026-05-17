# ==============================================================
# VM Placement Engine - Round Robin Algorithm
# Decides which VM goes to which physical host based on:
# - Available resources (CPU cores, RAM, disk)
# - Round Robin strategy (distributes VMs evenly across workers)
# - Headnode (server1) is EXCLUDED from placement
# ==============================================================

import logging
import threading
from typing import List

from ..models.host import Host, HostRole
from ..models.vm import VM
from ..models.placement_decision import PlacementDecision, PlacementPlan

logger = logging.getLogger("orchestrator.placement")


class PlacementEngine:
    """
    Round Robin VM Placement:
      1. Filter to only WORKER hosts (exclude headnode).
      2. Sort workers by hostname for deterministic ordering.
      3. Assign VMs to workers in round-robin fashion.
      4. If a worker can't fit a VM, try next worker.
      5. If no worker can fit, return failure.

    Thread-safe: all placement and release operations are protected by a lock
    to prevent race conditions and resource overcommit under concurrent requests.
    """

    def __init__(self, hosts: List[Host]):
        self.hosts = hosts
        self._round_robin_idx = 0
        self._lock = threading.Lock()

    def _get_workers(self) -> List[Host]:
        return sorted(
            [h for h in self.hosts if h.is_active and h.role == HostRole.WORKER],
            key=lambda h: h.hostname
        )

    def place_vms(self, slice_id: str, vms: List[VM]) -> PlacementPlan:
        with self._lock:
            decisions = []
            workers = self._get_workers()

            if not workers:
                return PlacementPlan(
                    slice_id=slice_id, decisions=[], success=False,
                    error_message="No worker hosts available for placement",
                )

            for vm in vms:
                decision = self._place_single_vm(vm, workers)
                decisions.append(decision)
                if not decision.success:
                    # Release already-allocated resources before returning failure
                    for d in decisions[:-1]:
                        for host in self.hosts:
                            if host.ip == d.host_ip:
                                host.release(d.vcpus_allocated, d.ram_mb_allocated, d.disk_gb_allocated)
                                break
                    return PlacementPlan(
                        slice_id=slice_id, decisions=decisions, success=False,
                        error_message=f"Cannot place VM '{vm.name}': {decision.reason}",
                    )

            return PlacementPlan(
                slice_id=slice_id, decisions=decisions, success=True,
            )

    def _place_single_vm(self, vm: VM, workers: List[Host]) -> PlacementDecision:
        num_workers = len(workers)

        for attempt in range(num_workers):
            idx = (self._round_robin_idx + attempt) % num_workers
            host = workers[idx]

            if host.can_allocate(vm.vcpus, vm.ram_mb, vm.disk_gb):
                host.allocate(vm.vcpus, vm.ram_mb, vm.disk_gb)

                logger.info(
                    "Placement: %s -> %s (%s) [vCPU=%d, RAM=%dMB, Disk=%dGB]",
                    vm.name, host.hostname, host.ip,
                    vm.vcpus, vm.ram_mb, vm.disk_gb
                )

                self._round_robin_idx = (idx + 1) % num_workers

                return PlacementDecision(
                    vm_id=vm.id, vm_name=vm.name, vm_index=vm.index,
                    host_ip=host.ip, host_hostname=host.hostname,
                    vcpus_allocated=vm.vcpus, ram_mb_allocated=vm.ram_mb,
                    disk_gb_allocated=vm.disk_gb, success=True,
                )

        vcpus_avail = max(h.available_vcpus for h in workers)
        ram_avail = max(h.available_ram_mb for h in workers)
        return PlacementDecision(
            vm_id=vm.id, vm_name=vm.name, vm_index=vm.index,
            host_ip="", host_hostname="", reason=(
                f"No worker with enough resources (need {vm.vcpus}vCPU/{vm.ram_mb}MB/{vm.disk_gb}GB; "
                f"max available: {vcpus_avail}vCPU/{ram_avail}MB)"
            ),
            vcpus_allocated=vm.vcpus, ram_mb_allocated=vm.ram_mb,
            disk_gb_allocated=vm.disk_gb, success=False,
        )

    def release_vm(self, vm: VM):
        with self._lock:
            for host in self.hosts:
                if host.ip == vm.host_ip:
                    host.release(vm.vcpus, vm.ram_mb, vm.disk_gb)
                    logger.info(
                        "Released resources on %s: vCPU=%d, RAM=%dMB, Disk=%dGB",
                        host.hostname, vm.vcpus, vm.ram_mb, vm.disk_gb
                    )
                    break
