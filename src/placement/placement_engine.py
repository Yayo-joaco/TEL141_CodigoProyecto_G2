# ==============================================================
# VM Placement Engine - Multi-criteria scoring algorithm
# Decides which VM goes to which physical host based on:
# - Available resources (CPU cores, RAM, disk)
# - Weighted scoring: RAM utilization + CPU overcommit + batch concentration
# - Headnode (server1) is EXCLUDED from placement
# Shared by the Linux cluster (this module) and the OpenStack cluster
# (Orchestrator._place_vms_openstack, which delegates to score_hosts_for_vms).
# ==============================================================

import logging
import threading
import time
from typing import Dict, List, Optional, Tuple

from ..models.host import Host, HostRole
from ..models.vm import VM
from ..models.placement_decision import PlacementDecision, PlacementPlan

logger = logging.getLogger("orchestrator.placement")


class PlacementEngine:
    """
    Multi-criteria VM placement:
      1. Filter to only WORKER hosts (exclude headnode).
      2. Score each candidate host for each VM (lower = better):
           alpha * ram_util_after + beta * cpu_util_after + gamma * batch_concentration
      3. Place the whole slice as a unit; reject the batch (no partial
         allocation) if any VM can't be placed or the timeout is hit.

    Thread-safe: all placement and release operations are protected by a lock
    to prevent race conditions and resource overcommit under concurrent requests.
    """

    # Scoring weights (must sum to 1.0)
    _ALPHA = 0.50   # RAM utilization weight — hard resource, no overcommit
    _BETA = 0.30    # CPU utilization weight — soft, allows overcommit
    _GAMMA = 0.20   # batch-concentration penalty — discourages piling VMs on one host
    _CPU_OVERCOMMIT = 2.0    # CPUs can be shared; dynamic VMs rarely use 100% simultaneously
    _PLACEMENT_TIMEOUT = 30  # seconds — cap execution for large slices (R4.6)

    def __init__(self, hosts: List[Host]):
        self.hosts = hosts
        self._lock = threading.Lock()

    def _get_workers(self) -> List[Host]:
        return sorted(
            [h for h in self.hosts if h.is_active and h.role == HostRole.WORKER],
            key=lambda h: h.hostname
        )

    @staticmethod
    def _host_to_candidate(h: Host) -> dict:
        return {
            "hostname": h.hostname,
            "state": "up",
            "status": "enabled",
            "total_vcpus": h.total_vcpus,
            "free_vcpus": h.available_vcpus,
            "total_ram_mb": h.total_ram_mb,
            "free_ram_mb": h.available_ram_mb,
            "total_disk_gb": h.total_disk_gb,
            "free_disk_gb": h.available_disk_gb,
        }

    def score_hosts_for_vms(self, vms: List[VM], candidates: List[dict],
                             zone_id: str = None) -> Tuple[Dict[str, str], Optional[str]]:
        """
        Objective: minimise max weighted utilisation after placement.

        Per-host score (lower = better):
            alpha * (ram_after / ram_total)
          + beta  * (cpu_after / (cpu_total * CPU_OVERCOMMIT))
          + gamma * (vms_assigned_this_batch / total_vms)

        Virtual state tracks VMs already assigned in this batch but not yet
        booted — live stats don't reflect them yet (R4.4).
        The whole slice is placed as a unit before any VM boots (R4.5).
        RAM and disk are hard constraints; CPU allows overcommit (R4.3).

        Returns (force_hosts, error). force_hosts is a {vm_name: hostname}
        map. On any failure (no capacity for some VM, or timeout before the
        whole batch is placed) returns ({}, reason) — placement is
        all-or-nothing so callers never have to reconcile a partial plan.

        zone_id is accepted for future use: today one zone == one full
        cluster, and callers already scope `candidates` to the right
        cluster, so no further per-host filtering happens here. A future
        zone that's a subset of a cluster's servers would filter
        `candidates` down by a host->zone mapping at this point.
        """
        deadline = time.time() + self._PLACEMENT_TIMEOUT

        candidates = [
            h for h in candidates
            if h.get("state") == "up"
            and h.get("status") == "enabled"
            and h.get("total_ram_mb", 0) > 0
        ]

        if not candidates:
            return {}, "No active hosts available for placement"

        vram: Dict[str, int] = {h["hostname"]: 0 for h in candidates}
        vcpu: Dict[str, int] = {h["hostname"]: 0 for h in candidates}
        vdisk: Dict[str, int] = {h["hostname"]: 0 for h in candidates}
        batch: Dict[str, int] = {h["hostname"]: 0 for h in candidates}
        total_vms = len(vms)

        force_hosts: Dict[str, str] = {}

        for vm in vms:
            if time.time() > deadline:
                return {}, (
                    f"Placement timed out after {self._PLACEMENT_TIMEOUT}s "
                    f"({len(force_hosts)}/{total_vms} VMs placed)"
                )

            best_host = None
            best_score = float("inf")

            for h in candidates:
                hn = h["hostname"]
                ram_total = h["total_ram_mb"]
                cpu_total = h["total_vcpus"]
                disk_total = h["total_disk_gb"]

                ram_after = (ram_total - h["free_ram_mb"]) + vram[hn] + vm.ram_mb
                cpu_after = (cpu_total - h["free_vcpus"]) + vcpu[hn] + vm.vcpus
                disk_after = (disk_total - h["free_disk_gb"]) + vdisk[hn] + vm.disk_gb

                # Hard RAM/disk constraints
                if ram_after > ram_total or disk_after > disk_total:
                    continue

                # Soft CPU constraint with overcommit
                if cpu_after > cpu_total * self._CPU_OVERCOMMIT:
                    continue

                score = (
                    self._ALPHA * (ram_after / ram_total)
                    + self._BETA * (cpu_after / (cpu_total * self._CPU_OVERCOMMIT))
                    + self._GAMMA * (batch[hn] / max(total_vms, 1))
                )

                if score < best_score:
                    best_score = score
                    best_host = h

            if best_host is None:
                return {}, (
                    f"Cannot place VM '{vm.name}': no host with enough resources "
                    f"(need {vm.vcpus}vCPU/{vm.ram_mb}MB/{vm.disk_gb}GB)"
                )

            hn = best_host["hostname"]
            force_hosts[vm.name] = hn
            vram[hn] += vm.ram_mb
            vcpu[hn] += vm.vcpus
            vdisk[hn] += vm.disk_gb
            batch[hn] += 1

            logger.info(
                "Placement: %s -> %s  score=%.3f "
                "(ram_util=%.0f%%, cpu_util=%.0f%%, batch_on_host=%d)",
                vm.name, hn, best_score,
                ((best_host["total_ram_mb"] - best_host["free_ram_mb"]) + vram[hn])
                / best_host["total_ram_mb"] * 100,
                ((best_host["total_vcpus"] - best_host["free_vcpus"]) + vcpu[hn])
                / (best_host["total_vcpus"] * self._CPU_OVERCOMMIT) * 100,
                batch[hn],
            )

        return force_hosts, None

    def place_vms(self, slice_id: str, vms: List[VM], zone_id: str = None) -> PlacementPlan:
        with self._lock:
            workers = self._get_workers()

            if not workers:
                return PlacementPlan(
                    slice_id=slice_id, decisions=[], success=False,
                    error_message="No worker hosts available for placement",
                )

            candidates = [self._host_to_candidate(h) for h in workers]
            force_hosts, error = self.score_hosts_for_vms(vms, candidates, zone_id=zone_id)

            if error:
                return PlacementPlan(
                    slice_id=slice_id, decisions=[], success=False,
                    error_message=error,
                )

            hosts_by_name = {h.hostname: h for h in workers}
            decisions = []
            for vm in vms:
                hostname = force_hosts[vm.name]
                host = hosts_by_name[hostname]
                host.allocate(vm.vcpus, vm.ram_mb, vm.disk_gb)
                decisions.append(PlacementDecision(
                    vm_id=vm.id, vm_name=vm.name, vm_index=vm.index,
                    host_ip=host.ip, host_hostname=host.hostname,
                    vcpus_allocated=vm.vcpus, ram_mb_allocated=vm.ram_mb,
                    disk_gb_allocated=vm.disk_gb, success=True,
                ))

            return PlacementPlan(slice_id=slice_id, decisions=decisions, success=True)

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
