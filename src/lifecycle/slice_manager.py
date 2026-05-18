# ==============================================================
# Lifecycle / Slice Manager - CRUD operations (v2 + editing + RBAC)
# ==============================================================

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Tuple

from ..models.slice import Slice, SliceStatus, TopologyType
from ..models.vm import VM, VMStatus
from ..models.user import User, Role
from ..models.topology import Topology
from ..models.placement_decision import PlacementDecision
from ..drivers.linux_driver import LinuxDriver
from ..networking.network_manager import NetworkManager, SSH_FWD_BASE
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

        # Compute per-link VLANs from topology
        links = Topology.get_links(slice_obj.topology, len(vms))
        vm_names = [vm.name for vm in vms]
        link_vlans = []
        for link_idx, (a, b) in enumerate(links):
            lv = self.db.assign_vlan_for_link(slice_obj.id, link_idx)
            if lv:
                link_vlans.append({
                    "link_idx": link_idx,
                    "vlan_id": lv,
                    "vm_a_name": vm_names[a] if a < len(vm_names) else f"vm{a+1}",
                    "vm_b_name": vm_names[b] if b < len(vm_names) else f"vm{b+1}",
                })
        slice_obj.link_vlans = link_vlans if link_vlans else None

        # Build per-VM link interface list
        vm_link_map = self._build_vm_link_map(vms, links, link_vlans)

        # Deploy all VMs in parallel (R1.11 — paralelismo en despliegue)
        def _deploy(vm: VM):
            placement = self._get_placement_for_vm(vm)
            if not placement:
                return vm, False, f"Placement missing for {vm.name}"
            image_path = self.base_image
            if vm.image:
                img = self.db.get_image_path(vm.image)
                if img:
                    image_path = img
            ok = self.driver.create_vm(vm, placement, image_path,
                                       link_interfaces=vm_link_map.get(vm.name, []))
            return vm, ok, vm.error_message if not ok else None

        failed_error = None
        with ThreadPoolExecutor(max_workers=len(vms)) as executor:
            futures = {executor.submit(_deploy, vm): vm for vm in vms}
            for future in as_completed(futures):
                vm, ok, err = future.result()
                if not ok and failed_error is None:
                    failed_error = err or f"Failed to create VM {vm.name}"

        if failed_error:
            self._rollback_slice(slice_obj, vms, failed_error)
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
        logger.info("Slice '%s' created with %d VMs, %d links",
                    slice_obj.name, len(vms), len(link_vlans))
        return vms

    def edit_slice(self, slice_id: str, add_vms: int = 0,
                   remove_vm_ids: List[str] = None,
                   new_vcpus: int = None, new_ram_mb: int = None,
                   new_disk_gb: int = None,
                   pre_placed_vms: List[VM] = None,
                   ext_topology: str = None,
                   anchor_vm_hint: str = None) -> Tuple[bool, str, Optional[dict]]:
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
            # Compute extension links and allocate VLANs for them
            all_vms_after = active_vms + pre_placed_vms
            ext_topo_type = TopologyType(ext_topology) if ext_topology else TopologyType.LINEAL
            anchor_idx = next(
                (i for i, vm in enumerate(all_vms_after) if vm.name == anchor_vm_hint),
                len(active_vms) - 1
            )
            ext_links_raw = Topology.get_links(ext_topo_type, len(pre_placed_vms) + 1)
            # Offset indices: anchor is at anchor_idx, new VMs start at len(active_vms)
            base_link_count = len(slice_obj.link_vlans or [])
            ext_link_vlans = []
            for li, (a, b) in enumerate(ext_links_raw):
                real_a = anchor_idx if a == 0 else len(active_vms) + a - 1
                real_b = anchor_idx if b == 0 else len(active_vms) + b - 1
                lv = self.db.assign_vlan_for_link(slice_obj.id, base_link_count + li)
                if lv:
                    ext_link_vlans.append({
                        "link_idx": base_link_count + li,
                        "vlan_id": lv,
                        "vm_a_name": all_vms_after[real_a].name if real_a < len(all_vms_after) else "",
                        "vm_b_name": all_vms_after[real_b].name if real_b < len(all_vms_after) else "",
                    })
            # Merge into slice link_vlans
            existing_lv = slice_obj.link_vlans or []
            slice_obj.link_vlans = existing_lv + ext_link_vlans

            # Build link map for new VMs only
            ext_vm_link_map = self._build_vm_link_map(
                all_vms_after,
                [(anchor_idx if a == 0 else len(active_vms) + a - 1,
                  anchor_idx if b == 0 else len(active_vms) + b - 1)
                 for a, b in ext_links_raw],
                ext_link_vlans,
            )

            for new_vm in pre_placed_vms:
                placement = self._get_placement_for_vm(new_vm)
                if not placement:
                    return False, f"No se pudo ubicar VM {new_vm.name}", None
                image_path = self.base_image
                if new_vm.image:
                    img = self.db.get_image_path(new_vm.image)
                    if img:
                        image_path = img
                success = self.driver.create_vm(
                    new_vm, placement, image_path,
                    link_interfaces=ext_vm_link_map.get(new_vm.name, [])
                )
                if not success:
                    return False, f"Fallo al crear VM {new_vm.name}", None
                new_vms_list.append(new_vm)
                logger.info("VM %s added to slice %s", new_vm.name, slice_obj.name)

        all_vms = active_vms + new_vms_list
        slice_obj.num_vms = len(all_vms)

        if add_vms > 0 and new_vms_list:
            slice_obj.ext_topology = ext_topology or 'lineal'
            slice_obj.anchor_vm_name = anchor_vm_hint or (active_vms[-1].name if active_vms else None)
            slice_obj.base_num_vms = len(active_vms)

        if new_vms_list:
            vlan_id = slice_obj.vlan_id or 300
            subnet = slice_obj.subnet or "10.60.3.0/24"
            subnet_base = subnet.split("/")[0].rsplit(".", 1)[0]

            for vm in new_vms_list:
                if vm.tap_interface and vm.host_ip:
                    self.network._set_vlan(vm.host_ip, vm.tap_interface, vlan_id)
                for iface in (vm.interfaces or []):
                    if iface.get("type") == "link" and iface.get("vlan_id") and vm.host_ip:
                        self.network._set_vlan(vm.host_ip, iface["tap_name"], iface["vlan_id"])
                # Assign predictable IP to new VM
                if not vm.ip_address:
                    vm.ip_address = f"{subnet_base}.{vm.index + 2}"

            # Restart dnsmasq with leases for ALL VMs (old + new)
            if slice_obj.enable_dhcp:
                self.network._setup_dhcp(
                    self.network.headnode_ip, vlan_id, subnet, all_vms
                )

            # SSH forwarding for new VMs that need internet access
            if slice_obj.enable_internet:
                for vm in new_vms_list:
                    if vm.enable_internet and vm.vnc_port and vm.ip_address:
                        fwd_port = SSH_FWD_BASE + vm.vnc_port
                        self.network._setup_ssh_forward(
                            self.network.headnode_ip, fwd_port, vm.ip_address, vm
                        )

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
                name=f"vm{i+1}", index=i,
                vcpus=slice_obj.vcpus_per_vm,
                ram_mb=slice_obj.ram_mb_per_vm,
                disk_gb=slice_obj.disk_gb_per_vm,
            )
            vms.append(vm)
        return vms

    def _build_vm_link_map(self, vms: List[VM],
                           links: List[Tuple[int, int]],
                           link_vlans: List[dict]) -> dict:
        """
        Returns {vm_name: [{link_idx, vlan_id, peer_vm_name}]} for each VM.
        Each entry represents one link interface the VM needs.
        """
        vm_names = [vm.name for vm in vms]
        vlan_by_link = {lv["link_idx"]: lv["vlan_id"] for lv in link_vlans}
        result = {vm.name: [] for vm in vms}
        for link_idx, (a, b) in enumerate(links):
            if a >= len(vm_names) or b >= len(vm_names):
                continue
            vlan_id = vlan_by_link.get(link_idx)
            result[vm_names[a]].append({
                "link_idx": link_idx,
                "vlan_id": vlan_id,
                "peer_vm_name": vm_names[b],
            })
            result[vm_names[b]].append({
                "link_idx": link_idx,
                "vlan_id": vlan_id,
                "peer_vm_name": vm_names[a],
            })
        return result

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
