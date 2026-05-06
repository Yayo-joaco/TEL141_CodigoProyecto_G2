# ==============================================================
# Lifecycle / Slice Manager - CRUD operations for slices
# Handles the business logic of creating, reading, and deleting slices
#
# Responsibilities (from architecture doc):
#   - CRUD for slices, VMs, networks, images (R1C)
#   - Rollback coordination when operations fail
#   - Cleanup of orphaned resources
# ==============================================================

import logging
from typing import List, Optional

from ..models.slice import Slice, SliceStatus
from ..models.vm import VM, VMStatus
from ..models.topology import Topology
from ..drivers.linux_driver import LinuxDriver
from ..networking.network_manager import NetworkManager
from ..database.db_manager import DatabaseManager

logger = logging.getLogger("orchestrator.lifecycle")


class SliceManager:
    """
    Lifecycle module: implements CRUD operations on slices, VMs, networks.
    The Orchestrator calls this module; it in turn calls drivers and networking.
    """

    def __init__(self, driver: LinuxDriver, network: NetworkManager,
                 db: DatabaseManager, base_image: str):
        self.driver = driver
        self.network = network
        self.db = db
        self.base_image = base_image

    def create_slice(self, slice_obj: Slice) -> List[VM]:
        """
        Executes the full creation flow for a slice:
          1. Create VM objects for each node
          2. Create each VM via the Linux driver
          3. Setup network (OVS, VLAN, topology links)
          4. Persist state to database
          5. Rollback on failure
        """
        vms = self._build_vm_objects(slice_obj)
        slice_obj.status = SliceStatus.CREATING

        for vm in vms:
            placement_decision = self._get_placement_for_vm(vm)
            if not placement_decision:
                self._rollback_slice(slice_obj, vms, "Placement data missing")
                return []

            success = self.driver.create_vm(vm, placement_decision, self.base_image)
            if not success:
                self._rollback_slice(slice_obj, vms, f"Failed to create VM {vm.name}")
                return []

        slice_obj.status = SliceStatus.CONFIGURING_NETWORK
        vlan_id = slice_obj.vlan_id or 300
        subnet = slice_obj.subnet or "10.60.3.0/24"

        net_ok = self.network.setup_slice_network(
            slice_obj, vms, vlan_id, subnet,
            enable_dhcp=slice_obj.enable_dhcp,
            enable_internet=slice_obj.enable_internet,
        )

        if not net_ok:
            self._rollback_slice(slice_obj, vms, "Network configuration failed")
            return []

        slice_obj.status = SliceStatus.ACTIVE

        self._persist_slice(slice_obj, vms)

        logger.info("Slice '%s' created successfully with %d VMs",
                     slice_obj.name, len(vms))
        return vms

    def delete_slice(self, slice_id: str) -> bool:
        slice_obj = self.db.get_slice(slice_id)
        if not slice_obj:
            logger.warning("Slice %s not found", slice_id)
            return False

        vms = self.db.get_vms_for_slice(slice_id)
        slice_obj.status = SliceStatus.DELETING

        for vm in vms:
            if vm.status != VMStatus.DELETED:
                self.driver.delete_vm(vm)

        if slice_obj.vlan_id:
            self.network.teardown_slice_network(vms, slice_obj.vlan_id)

        slice_obj.status = SliceStatus.DELETED
        self.db.delete_slice_record(slice_id)
        logger.info("Slice '%s' deleted", slice_obj.name)
        return True

    def get_slice_info(self, slice_id: str) -> Optional[dict]:
        slice_obj = self.db.get_slice(slice_id)
        if not slice_obj:
            return None
        vms = self.db.get_vms_for_slice(slice_id)
        return {
            "slice": slice_obj.to_dict(),
            "vms": [vm.to_dict() for vm in vms],
        }

    def list_all_slices(self) -> List[dict]:
        slices = self.db.list_slices()
        return [s.to_dict() for s in slices if s.status != SliceStatus.DELETED]

    def get_hosts_status(self) -> List[dict]:
        hosts = self.db.get_hosts()
        return [h.to_dict() for h in hosts]

    def _build_vm_objects(self, slice_obj: Slice) -> List[VM]:
        vms = []
        for i in range(slice_obj.num_vms):
            vm = VM(
                id="",
                slice_id=slice_obj.id,
                name=f"{slice_obj.name}-vm{i+1}",
                index=i,
                vcpus=slice_obj.vcpus_per_vm,
                ram_mb=slice_obj.ram_mb_per_vm,
                disk_gb=slice_obj.disk_gb_per_vm,
            )
            vms.append(vm)
        return vms

    def _get_placement_for_vm(self, vm: VM):
        from ..models.placement_decision import PlacementDecision
        return PlacementDecision(
            vm_id=vm.id,
            vm_name=vm.name,
            vm_index=vm.index,
            host_ip=vm.host_ip,
            host_hostname="",
            vcpus_allocated=vm.vcpus,
            ram_mb_allocated=vm.ram_mb,
            disk_gb_allocated=vm.disk_gb,
            success=True if vm.host_ip else False,
            reason="No host assigned" if not vm.host_ip else "",
        )

    def _rollback_slice(self, slice_obj: Slice, vms: List[VM], error: str):
        logger.error("Rolling back slice '%s': %s", slice_obj.name, error)
        slice_obj.status = SliceStatus.ERROR
        slice_obj.error_message = error
        for vm in vms:
            if vm.status == VMStatus.ACTIVE:
                self.driver.delete_vm(vm)
        self._persist_slice(slice_obj, vms)

    def _persist_slice(self, slice_obj: Slice, vms: List[VM]):
        self.db.save_slice(slice_obj)
        for vm in vms:
            self.db.save_vm(vm)
        self.db.save_log(slice_obj.id, "lifecycle", "INFO",
                         f"Slice '{slice_obj.name}' status: {slice_obj.status.value}")
