# ==============================================================
# Orchestrator - Central coordinator v2 (RBAC + Edit + Templates)
# ==============================================================

import json
import logging
from typing import List, Optional, Tuple

from .models.slice import Slice, SliceStatus, TopologyType
from .models.vm import VM, VMStatus
from .models.host import Host
from .models.user import User, Role
from .models.topology import Topology
from .placement.placement_engine import PlacementEngine
from .lifecycle.slice_manager import SliceManager
from .drivers.linux_driver import LinuxDriver
from .networking.network_manager import NetworkManager
from .database.db_manager import DatabaseManager
from .auth.auth_manager import AuthManager
from .queue.task_queue import TaskQueue

logger = logging.getLogger("orchestrator")


class Orchestrator:
    def __init__(self, hosts: List[Host], driver: LinuxDriver,
                 network: NetworkManager, db: DatabaseManager,
                 base_image: str = "/home/ubuntu/cirros-base.img"):
        self.hosts = hosts
        self.driver = driver
        self.network = network
        self.db = db
        self.base_image = base_image
        self.placement_engine = PlacementEngine(hosts)
        self.slice_manager = SliceManager(driver, network, db, base_image)
        self.auth = AuthManager(db)
        self.task_queue = TaskQueue()

    # ---- Authentication ----

    def login(self, username: str, password: str) -> Tuple[bool, Optional[dict]]:
        return self.auth.authenticate(username, password)

    def register(self, username: str, password: str,
                 role: Role = Role.USER, email: str = None) -> Tuple[bool, str]:
        return self.auth.register_user(username, password, role, email)

    def logout(self, user_id: str):
        self.auth.logout(user_id)

    def validate_request(self, token: str, required_role: Role = None) -> Tuple[bool, Optional[User], str]:
        return self.auth.validate_request(token, required_role)

    # ---- Slice Operations ----

    def create_slice(self, name: str, topology: str, num_vms: int,
                     vcpus: int = 1, ram_mb: int = 512, disk_gb: int = 2,
                     enable_dhcp: bool = False, enable_internet: bool = False,
                     created_by: str = "admin",
                     vms_internet: List[int] = None,
                     vms_image: dict = None) -> dict:
        try:
            topo = TopologyType(topology)
        except ValueError:
            return {"success": False, "error": f"Topología inválida: {topology}",
                    "valid_topologies": [t.value for t in TopologyType]}

        if num_vms < 1:
            return {"success": False, "error": "Se necesita al menos 1 VM"}

        slice_obj = Slice(
            id="", name=name, topology=topo, num_vms=num_vms,
            vcpus_per_vm=vcpus, ram_mb_per_vm=ram_mb, disk_gb_per_vm=disk_gb,
            enable_dhcp=enable_dhcp, enable_internet=enable_internet,
            status=SliceStatus.CREATING, created_by=created_by,
        )

        # Auto-assign VLAN and subnet (R5.3 + R1C.3 + R1.5)
        vlan_result = self.db.assign_vlan(slice_obj.id)
        if not vlan_result["success"]:
            slice_obj.status = SliceStatus.ERROR
            slice_obj.error_message = vlan_result.get("error", "No VLAN available")
            self.db.save_slice(slice_obj)
            self.db.save_log(slice_obj.id, "orchestrator", "ERROR",
                             f"VLAN assignment failed: {vlan_result.get('error')}",
                             user_id=created_by)
            return {"success": False, "error": vlan_result.get("error")}

        slice_obj.vlan_id = vlan_result["vlan_id"]
        slice_obj.subnet = vlan_result["subnet"]

        vms = []
        vms_internet = vms_internet or []
        vms_image = vms_image or {}
        for i in range(num_vms):
            vm_internet = (i + 1) in vms_internet
            vm_img = vms_image.get(str(i + 1))
            vm = VM(id="", slice_id=slice_obj.id,
                    name=f"vm{i+1}", index=i,
                    vcpus=vcpus, ram_mb=ram_mb, disk_gb=disk_gb,
                    status=VMStatus.PENDING,
                    enable_internet=vm_internet,
                    image=vm_img)
            vms.append(vm)

        plan = self.placement_engine.place_vms(slice_obj.id, vms)
        if not plan.success:
            slice_obj.status = SliceStatus.ERROR
            slice_obj.error_message = plan.error_message
            self.db.save_slice(slice_obj)
            self.db.release_vlan(slice_obj.id)
            self.db.save_log(slice_obj.id, "orchestrator", "ERROR",
                             f"Placement failed: {plan.error_message}", user_id=created_by)
            return {"success": False, "error": plan.error_message}

        allocated_ports: dict = {}  # host_ip -> set of vnc ports reserved this run
        for vm, decision in zip(vms, plan.decisions):
            vm.host_ip = decision.host_ip
            extra = allocated_ports.get(vm.host_ip, set())
            ports = self.db.allocate_vm_ports(vm.host_ip, extra_used=extra)
            vm.vnc_port = ports["vnc_port"]
            vm.vnc_ws_port = ports["vnc_ws_port"]
            allocated_ports.setdefault(vm.host_ip, set()).add(ports["vnc_port"])

        created_vms = self.slice_manager.create_slice(slice_obj, pre_placed_vms=vms)
        if not created_vms:
            self.db.release_vlan(slice_obj.id)
            return {"success": False, "error": "Fallo en despliegue del slice"}

        links = Topology.get_links(topo, num_vms)
        self.db.save_log(slice_obj.id, "orchestrator", "INFO",
                         f"Slice '{name}' creado: {num_vms} VMs, VLAN={slice_obj.vlan_id}, "
                         f"subnet={slice_obj.subnet}, topologia={topology}",
                         user_id=created_by)

        self.refresh_hosts()
        return {
            "success": True, "slice_id": slice_obj.id, "name": slice_obj.name,
            "topology": topology, "num_vms": num_vms,
            "vlan_id": slice_obj.vlan_id, "subnet": slice_obj.subnet,
            "vms": [vm.to_dict() for vm in created_vms], "links": links,
        }

    def edit_slice(self, slice_id: str, add_vms: int = 0,
                   remove_vm_ids: List[str] = None,
                   new_vcpus: int = None, new_ram_mb: int = None,
                   new_disk_gb: int = None, user: User = None,
                   new_vms_image: dict = None,
                   new_vms_internet: List[int] = None) -> dict:
        vms = self.db.get_vms_for_slice(slice_id)
        if remove_vm_ids:
            for vm in vms:
                if vm.id in (remove_vm_ids or []):
                    self.placement_engine.release_vm(vm)

        new_vms_image = new_vms_image or {}
        new_vms_internet = new_vms_internet or []

        extra_vms = []
        if add_vms > 0:
            slice_obj = self.db.get_slice(slice_id)
            if slice_obj:
                current_count = len([v for v in vms if v.status != VMStatus.DELETED])
                for i in range(add_vms):
                    vm_num = current_count + i + 1
                    new_vm = VM(id="", slice_id=slice_id,
                                name=f"vm{vm_num}",
                                index=current_count + i,
                                vcpus=new_vcpus or slice_obj.vcpus_per_vm,
                                ram_mb=new_ram_mb or slice_obj.ram_mb_per_vm,
                                disk_gb=new_disk_gb or slice_obj.disk_gb_per_vm,
                                image=new_vms_image.get(str(vm_num)),
                                enable_internet=(vm_num in new_vms_internet))
                    extra_vms.append(new_vm)
                plan = self.placement_engine.place_vms(slice_id, extra_vms)
                if not plan.success:
                    return {"success": False, "error": plan.error_message}
                allocated_ports: dict = {}
                for vm, decision in zip(extra_vms, plan.decisions):
                    vm.host_ip = decision.host_ip
                    extra = allocated_ports.get(vm.host_ip, set())
                    ports = self.db.allocate_vm_ports(vm.host_ip, extra_used=extra)
                    vm.vnc_port = ports["vnc_port"]
                    vm.vnc_ws_port = ports["vnc_ws_port"]
                    allocated_ports.setdefault(vm.host_ip, set()).add(ports["vnc_port"])

        success, msg, info = self.slice_manager.edit_slice(
            slice_id, add_vms, remove_vm_ids, new_vcpus, new_ram_mb, new_disk_gb,
            pre_placed_vms=extra_vms)
        return {"success": success, "message": msg, "slice": info}

    def delete_slice(self, slice_id: str, user: User = None) -> dict:
        slice_obj = self.db.get_slice(slice_id)
        if slice_obj and user and slice_obj.created_by != user.username and not user.can_force_delete():
            return {"success": False, "error": "No tienes permiso para eliminar este slice"}
        vms = self.db.get_vms_for_slice(slice_id)
        for vm in vms:
            self.placement_engine.release_vm(vm)
        success = self.slice_manager.delete_slice(slice_id)
        self.db.release_vlan(slice_id)
        self.db.save_log(slice_id, "orchestrator", "INFO",
                         f"Slice eliminado, VLAN liberada",
                         user_id=user.id if user else None)
        self.refresh_hosts()
        return {"success": success, "slice_id": slice_id}

    def get_slice(self, slice_id: str) -> Optional[dict]:
        return self.slice_manager.get_slice_info(slice_id)

    def list_slices(self, user: User = None) -> List[dict]:
        if user and user.can_view_all_slices():
            return self.slice_manager.list_all_slices_admin()
        return self.slice_manager.list_all_slices(created_by=user.username if user else None)

    def get_hosts_status(self) -> List[dict]:
        return self.slice_manager.get_hosts_status()

    # ---- Host Management (R1.3 — hot add/remove without restart) ----

    def add_host(self, hostname: str, ip: str, port: int = 22,
                 role: str = "worker", added_by: str = "admin") -> dict:
        from .models.host import HostRole
        try:
            host_role = HostRole(role)
        except ValueError:
            return {"success": False, "error": f"Rol inválido: {role}"}

        # Check duplicate
        for h in self.hosts:
            if h.ip == ip or h.hostname == hostname:
                return {"success": False, "error": f"Host {hostname} ({ip}) ya existe"}

        new_host = Host(hostname=hostname, ip=ip, role=host_role, port=port)

        # Try to query real resources; use defaults if unreachable
        res = self.driver.get_host_resources(ip)
        if res:
            new_host.total_vcpus = res.get("total_vcpus", 8)
            new_host.total_ram_mb = res.get("total_ram_mb", 8192)
            new_host.total_disk_gb = res.get("total_disk_gb", 100)
            new_host.available_vcpus = max(0, new_host.total_vcpus - int(
                res.get("cpu_usage_pct", 0) / 100.0 * new_host.total_vcpus))
            new_host.available_ram_mb = max(0, new_host.total_ram_mb - res.get("used_ram_mb", 0))
            new_host.available_disk_gb = max(0, new_host.total_disk_gb - res.get("used_disk_gb", 0))

        self.db.save_host(new_host)
        self.hosts.append(new_host)
        self.placement_engine.hosts = self.hosts
        self.db.save_log("system", "orchestrator", "INFO",
                         f"Host {hostname} ({ip}) agregado en caliente", user_id=added_by)
        logger.info("Host %s (%s) added at runtime", hostname, ip)
        return {"success": True, "hostname": hostname, "ip": ip,
                "vcpus": new_host.total_vcpus, "ram_mb": new_host.total_ram_mb}

    def remove_host(self, hostname: str, removed_by: str = "admin") -> dict:
        host = next((h for h in self.hosts if h.hostname == hostname), None)
        if not host:
            return {"success": False, "error": f"Host {hostname} no encontrado"}

        # Refuse if host has active VMs
        active_vms = self.db.get_vms_by_host(host.ip)
        running = [v for v in active_vms if v.status.value == "active"]
        if running:
            return {"success": False,
                    "error": f"Host {hostname} tiene {len(running)} VM(s) activas. Elimínalas primero."}

        host.is_active = False
        self.db.save_host(host)
        self.hosts[:] = [h for h in self.hosts if h.hostname != hostname]
        self.placement_engine.hosts = self.hosts
        self.db.save_log("system", "orchestrator", "INFO",
                         f"Host {hostname} removido en caliente", user_id=removed_by)
        logger.info("Host %s removed at runtime", hostname)
        return {"success": True, "hostname": hostname}

    def refresh_hosts(self) -> dict:
        """Query real resources from all hosts via SSH and update DB."""
        updated = 0
        failed = []
        for host in self.hosts:
            res = self.driver.get_host_resources(host.ip)
            if res:
                self.db.update_host_resources(
                    hostname=host.hostname, host_ip=host.ip,
                    total_vcpus=res.get("total_vcpus", host.total_vcpus),
                    total_ram_mb=res.get("total_ram_mb", host.total_ram_mb),
                    total_disk_gb=res.get("total_disk_gb", host.total_disk_gb),
                    cpu_usage_pct=res.get("cpu_usage_pct", 0),
                    used_ram_mb=res.get("used_ram_mb", 0),
                    used_disk_gb=res.get("used_disk_gb", 0),
                )
                updated += 1
                logger.info("Host %s refreshed: CPU=%d, RAM=%dMB, Disk=%dGB",
                            host.hostname, res.get("total_vcpus"),
                            res.get("total_ram_mb"), res.get("total_disk_gb"))
            else:
                failed.append(host.hostname)
        # Reload hosts from DB into memory for Placement engine
        db_hosts = self.db.get_hosts()
        if db_hosts:
            self.hosts[:] = db_hosts
            self.placement_engine.hosts = self.hosts

            for host in self.hosts:
                vms = self.db.get_vms_by_host(host.ip)
                active = [v for v in vms if v.status.value == 'active']
                host.vms_running = len(active)
        return {"refreshed": updated, "failed": failed}

    def get_logs(self, slice_id: str, user: User = None) -> List[dict]:
        if user and user.can_view_all_slices():
            return self.db.get_all_logs(limit=200)
        return self.db.get_logs_for_slice(slice_id)

    # ---- Template Export/Import ----

    def export_template(self, slice_id: str) -> Optional[dict]:
        return self.slice_manager.export_template(slice_id)

    def import_template(self, template_data: dict, created_by: str = "admin") -> dict:
        return self.create_slice(
            name=template_data.get("name", f"slice-{template_data.get('topology', 'lineal')}"),
            topology=template_data.get("topology", "lineal"),
            num_vms=template_data.get("num_vms", 4),
            vcpus=template_data.get("vcpus_per_vm", 1),
            ram_mb=template_data.get("ram_mb_per_vm", 512),
            disk_gb=template_data.get("disk_gb_per_vm", 2),
            enable_dhcp=template_data.get("enable_dhcp", False),
            enable_internet=template_data.get("enable_internet", False),
            created_by=created_by,
        )

    # ---- Template Management ----

    def save_template(self, name: str, config: dict, description: str = "",
                      created_by: str = "admin") -> str:
        return self.db.save_template(name, config, description, created_by)

    def list_templates(self) -> List[dict]:
        return self.db.list_templates()

    # ---- Image Management ----

    def import_image(self, name: str, filename: str, path: str,
                     format: str = "qcow2", size_gb: int = 2,
                     uploaded_by: str = "admin") -> dict:
        img_id = self.db.save_image(name, filename, path, format, size_gb, uploaded_by)
        self.db.save_log("system", "orchestrator", "INFO",
                         f"Image '{name}' imported by {uploaded_by}", user_id=uploaded_by)
        return {"success": True, "image_id": img_id, "name": name, "path": path}

    def list_images(self) -> List[dict]:
        return self.db.list_images()

    # ---- User Management (Admin only) ----

    def list_users(self) -> List[dict]:
        return self.db.list_users()

    def delete_user(self, user_id: str) -> dict:
        self.db.delete_user_record(user_id)
        return {"success": True}

    def get_active_sessions(self, user: User) -> list:
        return self.auth.get_active_sessions(user)

    # ---- Async Task Queue Operations (R1.4, R1.6, R1.7) ----

    def create_slice_async(self, name: str, topology: str, num_vms: int,
                           vcpus: int = 1, ram_mb: int = 512, disk_gb: int = 2,
                           enable_dhcp: bool = False, enable_internet: bool = False,
                           created_by: str = "admin",
                           vms_internet: List[int] = None,
                           vms_image: dict = None) -> str:
        return self.task_queue.enqueue(
            f"create_slice:{name}",
            self.create_slice,
            name, topology, num_vms, vcpus, ram_mb, disk_gb,
            enable_dhcp, enable_internet, created_by,
            vms_internet, vms_image,
        )

    def delete_slice_async(self, slice_id: str, user: User = None) -> str:
        return self.task_queue.enqueue(
            f"delete_slice:{slice_id}",
            self.delete_slice,
            slice_id, user,
        )

    def edit_slice_async(self, slice_id: str, add_vms: int = 0,
                         remove_vm_ids: List[str] = None,
                         new_vcpus: int = None, new_ram_mb: int = None,
                         new_disk_gb: int = None, user: User = None,
                         new_vms_image: dict = None,
                         new_vms_internet: List[int] = None) -> str:
        return self.task_queue.enqueue(
            f"edit_slice:{slice_id}",
            self.edit_slice,
            slice_id, add_vms, remove_vm_ids,
            new_vcpus, new_ram_mb, new_disk_gb, user,
            new_vms_image, new_vms_internet,
        )

    def get_task_status(self, ticket_id: str) -> Optional[dict]:
        return self.task_queue.get_task(ticket_id)
