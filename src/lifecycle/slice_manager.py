# ==============================================================
# Lifecycle / Slice Manager - CRUD operations (v2 + editing + RBAC)
# ==============================================================

import logging
import uuid
from typing import List, Optional, Tuple

from ..models.slice import Slice, SliceStatus, TopologyType
from ..models.vm import VM, VMStatus
from ..models.user import User, Role
from ..models.topology import Topology
from ..models.placement_decision import PlacementDecision
from ..drivers.linux_driver import LinuxDriver
from ..networking.network_manager import NetworkManager
from ..database.db_manager import DatabaseManager

logger = logging.getLogger("orchestrator.lifecycle")


class SliceManager:
    def __init__(self, driver: LinuxDriver, network: NetworkManager,
                 db: DatabaseManager, base_image: str):
        self.driver = driver
        self.network = network
        self.db = db
        self.base_image = base_image

    def create_slice(self, slice_obj: Slice, pre_placed_vms: List[VM] = None) -> List[VM]:
        if pre_placed_vms:
            vms = pre_placed_vms
        else:
            vms = self._build_vm_objects(slice_obj)
        slice_obj.status = SliceStatus.CREATING

        for vm in vms:
            placement = self._get_placement_for_vm(vm)
            if not placement:
                self._rollback_slice(slice_obj, vms, f"Placement missing for {vm.name}")
                return []
            success = self.driver.create_vm(vm, placement, self.base_image)
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
        logger.info("Slice '%s' created with %d VMs", slice_obj.name, len(vms))
        return vms

    def edit_slice(self, slice_id: str, add_vms: int = 0,
                   remove_vm_ids: List[str] = None,
                   new_vcpus: int = None, new_ram_mb: int = None,
                   new_disk_gb: int = None,
                   pre_placed_vms: List[VM] = None) -> Tuple[bool, str, Optional[dict]]:
        """
        Edit an existing slice:
          - Add N more VMs (with placement)
          - Remove specific VMs by ID
          - Change resource specs for future VMs
          - pre_placed_vms: VMs already placed by orchestrator (with host_ip set)
        """
        remove_vm_ids = remove_vm_ids or []
        slice_obj = self.db.get_slice(slice_id)
        if not slice_obj:
            return False, "Slice no encontrado", None

        current_vms = self.db.get_vms_for_slice(slice_id)
        active_vms = [vm for vm in current_vms if vm.status != VMStatus.DELETED]

        if new_vcpus is not None:
            slice_obj.vcpus_per_vm = new_vcpus
        if new_ram_mb is not None:
            slice_obj.ram_mb_per_vm = new_ram_mb
        if new_disk_gb is not None:
            slice_obj.disk_gb_per_vm = new_disk_gb

        for rm_id in remove_vm_ids:
            vm_to_remove = next((vm for vm in active_vms if vm.id == rm_id), None)
            if vm_to_remove:
                self.driver.delete_vm(vm_to_remove)
                self.db.delete_vm_record(rm_id)
                active_vms.remove(vm_to_remove)
                logger.info("VM %s removed from slice %s", vm_to_remove.name, slice_obj.name)

        new_vms_list = []
        if add_vms > 0 and pre_placed_vms:
            for new_vm in pre_placed_vms:
                placement = self._get_placement_for_vm(new_vm)
                if not placement:
                    return False, f"No se pudo ubicar VM {new_vm.name}", None
                success = self.driver.create_vm(new_vm, placement, self.base_image)
                if not success:
                    return False, f"Fallo al crear VM {new_vm.name}", None
                new_vms_list.append(new_vm)
                logger.info("VM %s added to slice %s", new_vm.name, slice_obj.name)

        all_vms = active_vms + new_vms_list
        slice_obj.num_vms = len(all_vms)

        if new_vms_list:
            vlan_id = slice_obj.vlan_id or 300
            subnet = slice_obj.subnet or "10.60.3.0/24"
            for vm in new_vms_list:
                if vm.tap_interface and vm.host_ip:
                    self.network._set_vlan(vm.host_ip, vm.tap_interface, vlan_id)

        self._persist_slice(slice_obj, all_vms)
        return True, f"Slice editado: {len(all_vms)} VMs total", self.get_slice_info(slice_id)

    def delete_slice(self, slice_id: str) -> bool:
        slice_obj = self.db.get_slice(slice_id)
        if not slice_obj:
            return False
        vms = self.db.get_vms_for_slice(slice_id)
        slice_obj.status = SliceStatus.DELETING
        for vm in vms:
            if vm.status != VMStatus.DELETED:
                self.driver.delete_vm(vm)
                self.db.save_vm(vm)
        if slice_obj.vlan_id:
            self.network.teardown_slice_network(vms, slice_obj.vlan_id)
        slice_obj.status = SliceStatus.DELETED
        self.db.delete_slice_record(slice_id)
        return True

    def export_template(self, slice_id: str) -> Optional[dict]:
        slice_obj = self.db.get_slice(slice_id)
        if not slice_obj:
            return None
        return {
            "topology": slice_obj.topology.value,
            "num_vms": slice_obj.num_vms,
            "vcpus_per_vm": slice_obj.vcpus_per_vm,
            "ram_mb_per_vm": slice_obj.ram_mb_per_vm,
            "disk_gb_per_vm": slice_obj.disk_gb_per_vm,
            "vlan_id": slice_obj.vlan_id,
            "subnet": slice_obj.subnet,
            "enable_dhcp": slice_obj.enable_dhcp,
            "enable_internet": slice_obj.enable_internet,
        }

    def get_slice_info(self, slice_id: str) -> Optional[dict]:
        slice_obj = self.db.get_slice(slice_id)
        if not slice_obj:
            return None
        vms = self.db.get_vms_for_slice(slice_id)
        return {"slice": slice_obj.to_dict(), "vms": [vm.to_dict() for vm in vms]}

    def list_all_slices(self, created_by: str = None) -> List[dict]:
        slices = self.db.list_slices(created_by=created_by)
        return [s.to_dict() for s in slices]

    def list_all_slices_admin(self) -> List[dict]:
        slices = self.db.list_slices(include_deleted=False)
        return [s.to_dict() for s in slices]

    def get_hosts_status(self) -> List[dict]:
        hosts = self.db.get_hosts()
        return [h.to_dict() for h in hosts]

    def _build_vm_objects(self, slice_obj: Slice) -> List[VM]:
        vms = []
        for i in range(slice_obj.num_vms):
            vm = VM(
                id="", slice_id=slice_obj.id,
                name=f"{slice_obj.name}-vm{i+1}", index=i,
                vcpus=slice_obj.vcpus_per_vm,
                ram_mb=slice_obj.ram_mb_per_vm,
                disk_gb=slice_obj.disk_gb_per_vm,
            )
            vms.append(vm)
        return vms

    def _get_placement_for_vm(self, vm: VM):
        if not vm.host_ip:
            return None
        return PlacementDecision(
            vm_id=vm.id, vm_name=vm.name, vm_index=vm.index,
            host_ip=vm.host_ip, host_hostname="",
            vcpus_allocated=vm.vcpus, ram_mb_allocated=vm.ram_mb,
            disk_gb_allocated=vm.disk_gb,
            success=True,
            reason="",
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
                         f"Slice '{slice_obj.name}' status={slice_obj.status.value}, {len(vms)} VMs")
