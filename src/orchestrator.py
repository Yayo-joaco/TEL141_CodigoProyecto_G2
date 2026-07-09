# ==============================================================
# Orchestrator - Central coordinator v2 (RBAC + Edit + Templates)
# ==============================================================

import json
import logging
from typing import List, Optional, Tuple, Dict

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
                 base_image: str = "/home/ubuntu/cirros-base.img",
                 openstack_cfg: dict = None,
                 ovs1_ip: str = None, ovs1_ssh_key: str = None,
                 ovs1_port_map: dict = None, ovs1_headnode: str = "server1",
                 ovs2_ip: str = None, ovs2_ssh_key: str = None,
                 ovs2_port_map: dict = None, ovs2_headnode: str = "controller"):
        self.hosts = hosts
        self.driver = driver
        self.network = network
        self.db = db
        self.base_image = base_image
        self.placement_engine = PlacementEngine(hosts)
        self.slice_manager = SliceManager(driver, network, db, base_image)
        self.auth = AuthManager(db)
        self.task_queue = TaskQueue()
        self._os_cfg = openstack_cfg or {}
        self._os_driver = None          # lazy-loaded
        # ovs1 = Linux cluster's physical switch (192.168.201.5)
        self._ovs1_ip = ovs1_ip
        self._ovs1_ssh_key = ovs1_ssh_key
        self._ovs1_port_map = ovs1_port_map
        self._ovs1_headnode = ovs1_headnode
        self._ovs1 = None               # lazy-loaded
        # ovs2 = OpenStack cluster's physical switch (192.168.202.5)
        self._ovs2_ip = ovs2_ip
        self._ovs2_ssh_key = ovs2_ssh_key
        self._ovs2_port_map = ovs2_port_map
        self._ovs2_headnode = ovs2_headnode
        self._ovs2 = None               # lazy-loaded

    # ---- Internal helpers ----

    def _get_openstack_driver(self):
        if self._os_driver is None:
            from .drivers.openstack_driver import OpenStackDriver
            auth = self._os_cfg.get("auth", {})
            ep = self._os_cfg.get("endpoints", {})
            self._os_driver = OpenStackDriver(
                auth_url=ep.get("keystone", "http://192.168.202.1:5000"),
                username=auth.get("username", "cloud_admin"),
                password=auth.get("password", ""),
                project_name=auth.get("project_name", "cloud_admin"),
                domain_name=auth.get("domain_name", "Cloud"),
                nova_url=ep.get("nova", "http://192.168.202.1:8774"),
                neutron_url=ep.get("neutron", "http://192.168.202.1:9696"),
                glance_url=ep.get("glance", "http://192.168.202.1:9292"),
                novnc_base=ep.get("novnc", "http://192.168.202.1:6080"),
                token_cache_ttl=self._os_cfg.get("token_cache_ttl", 3300),
            )
        return self._os_driver

    def _get_ovs1(self):
        if self._ovs1 is None and self._ovs1_ip and self._ovs1_ssh_key:
            from .networking.ovs2_manager import OVS2Manager
            self._ovs1 = OVS2Manager(self._ovs1_ip, self._ovs1_ssh_key,
                                     port_map=self._ovs1_port_map,
                                     headnode_hostname=self._ovs1_headnode)
        return self._ovs1

    def _get_ovs2(self):
        if self._ovs2 is None and self._ovs2_ip and self._ovs2_ssh_key:
            from .networking.ovs2_manager import OVS2Manager
            self._ovs2 = OVS2Manager(self._ovs2_ip, self._ovs2_ssh_key,
                                     port_map=self._ovs2_port_map,
                                     headnode_hostname=self._ovs2_headnode)
        return self._ovs2

    def _get_ovs_for_infra(self, infra: str):
        return self._get_ovs1() if infra == "linux" else self._get_ovs2()

    # ---- Authentication ----

    def login(self, username: str, password: str, ip: str = "") -> Tuple[bool, Optional[dict]]:
        return self.auth.authenticate(username, password, ip=ip)

    def register(self, username: str, password: str,
                 role: Role = Role.USER, email: str = None,
                 cluster_assignment: str = "linux") -> Tuple[bool, str]:
        return self.auth.register_user(username, password, role, email, cluster_assignment)

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
                     vms_image: dict = None,
                     infrastructure_target: str = "linux",
                     zone_id: str = None,
                     flavor_id: str = None) -> dict:
        try:
            topo = TopologyType(topology)
        except ValueError:
            return {"success": False, "error": f"Topología inválida: {topology}",
                    "valid_topologies": [t.value for t in TopologyType]}

        if num_vms < 1:
            return {"success": False, "error": "Se necesita al menos 1 VM"}

        infra = infrastructure_target or "linux"

        if zone_id:
            zone = self.db.get_zone(zone_id)
            if not zone:
                return {"success": False, "error": f"Zona '{zone_id}' no existe"}
            if zone.get("cluster") != infra:
                return {"success": False,
                        "error": f"Zona '{zone_id}' pertenece al cluster '{zone.get('cluster')}', "
                                 f"no a '{infra}'"}

        slice_obj = Slice(
            id="", name=name, topology=topo, num_vms=num_vms,
            vcpus_per_vm=vcpus, ram_mb_per_vm=ram_mb, disk_gb_per_vm=disk_gb,
            enable_dhcp=enable_dhcp, enable_internet=enable_internet,
            status=SliceStatus.CREATING, created_by=created_by,
            infrastructure_target=infra,
            zone_id=zone_id,
            flavor_id=flavor_id,
        )

        # Auto-assign VLAN and subnet (R5.3 + R1C.3 + R1.5)
        vlan_result = self.db.assign_vlan(slice_obj.id, cluster=infra)
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

        # Linux placement (skipped for OpenStack — placement done inside _create_slice_openstack)
        if infra != "openstack":
            plan = self.placement_engine.place_vms(slice_obj.id, vms, zone_id=zone_id)
            if not plan.success:
                slice_obj.status = SliceStatus.ERROR
                slice_obj.error_message = plan.error_message
                self.db.save_slice(slice_obj)
                self.db.release_vlan(slice_obj.id)
                self.db.save_log(slice_obj.id, "orchestrator", "ERROR",
                                 f"Placement failed: {plan.error_message}", user_id=created_by)
                return {"success": False, "error": plan.error_message}

            allocated_ports: dict = {}
            for vm, decision in zip(vms, plan.decisions):
                vm.host_ip = decision.host_ip
                extra = allocated_ports.get(vm.host_ip, set())
                ports = self.db.allocate_vm_ports(vm.host_ip, extra_used=extra)
                vm.vnc_port = ports["vnc_port"]
                vm.vnc_ws_port = ports["vnc_ws_port"]
                allocated_ports.setdefault(vm.host_ip, set()).add(ports["vnc_port"])

        if infra == "openstack":
            created_vms = self._create_slice_openstack(slice_obj, vms)
        else:
            created_vms = self.slice_manager.create_slice(slice_obj, pre_placed_vms=vms)

        if not created_vms:
            self.db.release_vlan(slice_obj.id)
            return {"success": False, "error": "Fallo en despliegue del slice"}

        # Physical-switch VLAN pruning (R5.6) — Linux cluster only here;
        # OpenStack's own pruning (per-link VLANs + hypervisor hostnames)
        # happens inside _create_slice_openstack() where placement info lives.
        if infra == "linux":
            worker_hosts = list({vm.host_ip for vm in created_vms if vm.host_ip})
            worker_names = []
            for ip in worker_hosts:
                h = next((h for h in self.hosts if h.ip == ip), None)
                if h:
                    worker_names.append(h.hostname)
            vlan_ids = [slice_obj.vlan_id] if slice_obj.vlan_id else []
            if hasattr(slice_obj, "link_vlans") and slice_obj.link_vlans:
                vlan_ids += [lv["vlan_id"] for lv in slice_obj.link_vlans if lv.get("vlan_id")]
            ovs1 = self._get_ovs1()
            if ovs1 and vlan_ids:
                ovs1.add_slice_vlans(vlan_ids, worker_names)

        links = Topology.get_links(topo, num_vms)
        self.db.save_log(slice_obj.id, "orchestrator", "INFO",
                         f"Slice '{name}' creado: {num_vms} VMs, VLAN={slice_obj.vlan_id}, "
                         f"subnet={slice_obj.subnet}, topologia={topology}, infra={infra}",
                         user_id=created_by)

        self.refresh_hosts()
        return {
            "success": True, "slice_id": slice_obj.id, "name": slice_obj.name,
            "topology": topology, "num_vms": num_vms,
            "vlan_id": slice_obj.vlan_id, "subnet": slice_obj.subnet,
            "vms": [vm.to_dict() for vm in created_vms], "links": links,
        }

    # ------------------------------------------------------------------
    # OpenStack multi-criteria placement
    # ------------------------------------------------------------------

    def _place_vms_openstack(self, vms: List[VM], hypervisors: List[dict],
                              zone_id: str = None) -> Tuple[Dict[str, str], Optional[str]]:
        """
        Delegates to PlacementEngine.score_hosts_for_vms — the same
        multi-criteria scoring algorithm used for the Linux cluster,
        applied here to Nova hypervisor stats instead of Host objects.
        Returns (force_hosts, error); error is set (and force_hosts empty)
        if any VM can't be placed or the batch times out.
        """
        return self.placement_engine.score_hosts_for_vms(vms, hypervisors, zone_id=zone_id)

    def _create_slice_openstack(self, slice_obj: Slice, vms: List[VM]) -> List[VM]:
        """
        Custom placement on OpenStack:
        1. Query Nova hypervisor stats.
        2. Run multi-criteria scoring algorithm.
        3. Force placement via availability_zone="nova:<hostname>".
        """
        os_drv = self._get_openstack_driver()
        try:
            hypervisors = os_drv.get_hypervisor_stats()
        except Exception as e:
            logger.error("Cannot fetch hypervisor stats: %s", e)
            hypervisors = []

        force_hosts, place_error = self._place_vms_openstack(
            vms, hypervisors, zone_id=slice_obj.zone_id
        )
        if place_error:
            logger.error("OpenStack placement failed: %s", place_error)
            slice_obj.status = SliceStatus.ERROR
            slice_obj.error_message = place_error
            self.db.save_slice(slice_obj)
            return []

        # Per-link VLANs (R3.3/R5.1) — one distinct VLAN per topology edge,
        # mirroring the Linux driver so arping between peer VMs surfaces the
        # specific VLAN carrying that link's traffic.
        links = Topology.get_links(slice_obj.topology, len(vms))
        vm_names = [vm.name for vm in vms]
        link_vlans = []
        for link_idx, (a, b) in enumerate(links):
            lv = self.db.assign_vlan_for_link(slice_obj.id, link_idx, cluster="openstack")
            if lv:
                link_vlans.append({
                    "link_idx": link_idx,
                    "vlan_id": lv,
                    "vm_a_name": vm_names[a] if a < len(vm_names) else f"vm{a+1}",
                    "vm_b_name": vm_names[b] if b < len(vm_names) else f"vm{b+1}",
                })
        vm_link_map = Topology.build_vm_link_map(vms, links, link_vlans)

        try:
            result = os_drv.deploy_slice(slice_obj, vms, force_hosts=force_hosts,
                                         vm_link_map=vm_link_map)
        except Exception as e:
            logger.error("OpenStack deploy_slice failed: %s", e)
            slice_obj.status = SliceStatus.ERROR
            slice_obj.error_message = str(e)
            self.db.save_slice(slice_obj)
            return []

        slice_obj.openstack_project_id = result.get("project_id", "")
        net_ids = result.get("all_network_ids") or (
            [result["network_id"]] if result.get("network_id") else []
        )
        slice_obj.openstack_network_ids = net_ids

        # deploy_slice boots VMs in parallel and collects per-VM exceptions
        # into result["errors"] instead of raising, so a slice with any
        # failed VM would otherwise fall through to the success path below
        # and get marked ACTIVE with phantom VMs (they'd have no
        # openstack_server_id, so nothing SSH/Horizon-visible ever existed).
        # Treat any boot failure as whole-slice failure — same all-or-nothing
        # contract as the Linux/placement path — and tear down whatever
        # partially came up so it doesn't leak a Keystone project + orphan
        # VMs the user never sees.
        if result.get("errors") or len(result.get("server_ids", {})) < len(vms):
            error = ("; ".join(result.get("errors", [])) or
                     f"Solo {len(result.get('server_ids', {}))}/{len(vms)} VMs bootearon")
            logger.error("OpenStack deploy incomplete for slice %s: %s",
                         slice_obj.id, error)
            slice_obj.status = SliceStatus.ERROR
            slice_obj.error_message = error
            for vm in vms:
                sid = result.get("server_ids", {}).get(vm.name)
                if sid:
                    vm.openstack_server_id = sid
            try:
                os_drv.teardown_slice(slice_obj, vms)
            except Exception as e:
                logger.warning("Cleanup after partial OS deploy failed: %s", e)
            self.db.save_slice(slice_obj)
            return []

        slice_obj.link_vlans = link_vlans if link_vlans else None
        slice_obj.status = SliceStatus.ACTIVE
        self.db.save_slice(slice_obj)
        for vm in vms:
            vm.status = VMStatus.ACTIVE
            vm.hypervisor_hostname = force_hosts.get(vm.name)
            self.db.save_vm(vm)

        # Physical-switch VLAN pruning (R5.6) — OpenStack cluster's own
        # switch (OVS2), scoped to the hypervisor hostnames actually used.
        ovs2 = self._get_ovs2()
        if ovs2 and link_vlans:
            worker_names = list(set(force_hosts.values()))
            vlan_ids = [lv["vlan_id"] for lv in link_vlans if lv.get("vlan_id")]
            if slice_obj.vlan_id:
                vlan_ids.append(slice_obj.vlan_id)
            if vlan_ids and worker_names:
                ovs2.add_slice_vlans(vlan_ids, worker_names)

        logger.info("OpenStack slice '%s' created with %d VMs, %d links",
                    slice_obj.name, len(vms), len(link_vlans))
        return vms

    def edit_slice(self, slice_id: str, add_vms: int = 0,
                   remove_vm_ids: List[str] = None,
                   new_vcpus: int = None, new_ram_mb: int = None,
                   new_disk_gb: int = None, user: User = None,
                   new_vms_image: dict = None,
                   new_vms_internet: List[int] = None,
                   new_vms_flavor_id: str = None,
                   ext_topology: str = None,
                   anchor_vm_hint: str = None) -> dict:
        slice_obj = self.db.get_slice(slice_id)
        infra = getattr(slice_obj, "infrastructure_target", "linux") if slice_obj else "linux"

        vms = self.db.get_vms_for_slice(slice_id)
        if remove_vm_ids:
            for vm in vms:
                if vm.id in (remove_vm_ids or []):
                    self.placement_engine.release_vm(vm)

        new_vms_image = new_vms_image or {}
        new_vms_internet = new_vms_internet or []

        # Explicit flavor choice for new VMs (same resolution pattern as
        # api_create_slice) — falls back to the per-request vcpus/ram/disk
        # overrides, then to the slice's original per-VM sizing.
        flavor = self.db.get_flavor(new_vms_flavor_id) if new_vms_flavor_id else None
        flavor_vcpus = flavor["vcpus"] if flavor else None
        flavor_ram_mb = flavor["ramMb"] if flavor else None
        flavor_disk_gb = flavor["diskGb"] if flavor else None

        extra_vms = []
        if add_vms > 0 and slice_obj:
            current_count = len([v for v in vms if v.status != VMStatus.DELETED])
            for i in range(add_vms):
                vm_num = current_count + i + 1
                new_vm = VM(id="", slice_id=slice_id,
                            name=f"vm{vm_num}",
                            index=current_count + i,
                            vcpus=new_vcpus or flavor_vcpus or slice_obj.vcpus_per_vm,
                            ram_mb=new_ram_mb or flavor_ram_mb or slice_obj.ram_mb_per_vm,
                            disk_gb=new_disk_gb or flavor_disk_gb or slice_obj.disk_gb_per_vm,
                            image=new_vms_image.get(str(vm_num)),
                            enable_internet=(vm_num in new_vms_internet),
                            flavor_id=new_vms_flavor_id)
                extra_vms.append(new_vm)

            if infra == "openstack":
                try:
                    os_drv = self._get_openstack_driver()
                    hypervisors = os_drv.get_hypervisor_stats()
                except Exception as e:
                    logger.error("Cannot fetch hypervisor stats for edit: %s", e)
                    hypervisors = []
                force_hosts, place_error = self._place_vms_openstack(
                    extra_vms, hypervisors, zone_id=slice_obj.zone_id
                )
                if place_error:
                    return {"success": False, "error": place_error}
                for vm in extra_vms:
                    vm.host_ip = None  # OpenStack VMs don't use SSH-cluster host_ip
            else:
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

        if infra == "openstack":
            return self._edit_slice_openstack(
                slice_obj, vms, extra_vms, add_vms,
                remove_vm_ids=remove_vm_ids,
                force_hosts=force_hosts if add_vms > 0 else {},
                ext_topology=ext_topology,
                anchor_vm_hint=anchor_vm_hint,
            )

        success, msg, info = self.slice_manager.edit_slice(
            slice_id, add_vms, remove_vm_ids, new_vcpus, new_ram_mb, new_disk_gb,
            pre_placed_vms=extra_vms,
            ext_topology=ext_topology,
            anchor_vm_hint=anchor_vm_hint)
        return {"success": success, "message": msg, "slice": info}

    def _edit_slice_openstack(self, slice_obj: Slice, vms: List[VM],
                              extra_vms: List[VM], add_vms: int,
                              remove_vm_ids: List[str] = None,
                              force_hosts: Dict[str, str] = None,
                              ext_topology: str = None,
                              anchor_vm_hint: str = None) -> dict:
        """
        OpenStack edit path: remove VMs via Nova delete, then (optionally)
        add VMs forming a second topology anchored on an existing VM —
        using Nova hot-attach (os-interface) for the anchor instead of the
        Linux driver's kill+rebuild restart.
        """
        os_drv = self._get_openstack_driver()
        project_id = getattr(slice_obj, "openstack_project_id", None)
        remove_vm_ids = remove_vm_ids or []

        if remove_vm_ids and project_id:
            for vm in vms:
                if vm.id in remove_vm_ids and getattr(vm, "openstack_server_id", None):
                    try:
                        os_drv.delete_vm(vm.openstack_server_id, project_id)
                    except Exception as e:
                        logger.error("OS delete_vm failed for %s: %s", vm.name, e)
                    self.db.delete_vm_record(vm.id)

        active_vms = [vm for vm in vms if vm.id not in remove_vm_ids
                     and vm.status != VMStatus.DELETED]

        if not (add_vms > 0 and extra_vms):
            slice_obj.num_vms = len(active_vms)
            self.db.save_slice(slice_obj)
            return {"success": True, "message": f"Slice editado: {len(active_vms)} VMs total",
                   "slice": self.get_slice(slice_obj.id)}

        all_vms_after = active_vms + extra_vms
        ext_topo_type = TopologyType(ext_topology) if ext_topology else TopologyType.LINEAL
        anchor_idx = next(
            (i for i, vm in enumerate(all_vms_after) if vm.name == anchor_vm_hint),
            len(active_vms) - 1
        )
        ext_links_raw = Topology.get_links(ext_topo_type, len(extra_vms) + 1)
        base_link_count = len(slice_obj.link_vlans or [])
        ext_link_vlans = []
        for li, (a, b) in enumerate(ext_links_raw):
            real_a = anchor_idx if a == 0 else len(active_vms) + a - 1
            real_b = anchor_idx if b == 0 else len(active_vms) + b - 1
            lv = self.db.assign_vlan_for_link(slice_obj.id, base_link_count + li, cluster="openstack")
            if lv:
                ext_link_vlans.append({
                    "link_idx": base_link_count + li,
                    "vlan_id": lv,
                    "vm_a_name": all_vms_after[real_a].name if real_a < len(all_vms_after) else "",
                    "vm_b_name": all_vms_after[real_b].name if real_b < len(all_vms_after) else "",
                })

        ext_links_real = [
            (anchor_idx if a == 0 else len(active_vms) + a - 1,
             anchor_idx if b == 0 else len(active_vms) + b - 1)
            for a, b in ext_links_raw
        ]
        ext_vm_link_map = Topology.build_vm_link_map(all_vms_after, ext_links_real, ext_link_vlans)

        anchor_vm_obj = all_vms_after[anchor_idx]
        anchor_new_links = ext_vm_link_map.get(anchor_vm_obj.name, [])
        new_vm_link_map = {vm.name: ext_vm_link_map.get(vm.name, []) for vm in extra_vms}

        try:
            result = os_drv.extend_slice(
                slice_obj, extra_vms, force_hosts=force_hosts,
                new_vm_link_map=new_vm_link_map,
                anchor_server_id=getattr(anchor_vm_obj, "openstack_server_id", None),
                anchor_link_map=anchor_new_links,
            )
        except Exception as e:
            logger.error("OS extend_slice failed: %s", e)
            return {"success": False, "error": str(e)}

        if result.get("errors"):
            logger.warning("OS extend_slice had errors: %s", result["errors"])

        if anchor_vm_obj.interfaces is None:
            anchor_vm_obj.interfaces = []
        anchor_vm_obj.interfaces.extend(result.get("anchor_interfaces", []))
        self.db.save_vm(anchor_vm_obj)

        existing_net_ids = getattr(slice_obj, "openstack_network_ids", None) or []
        slice_obj.openstack_network_ids = list(existing_net_ids) + result.get("network_ids", [])
        slice_obj.link_vlans = (slice_obj.link_vlans or []) + ext_link_vlans
        slice_obj.ext_topology = ext_topology or 'lineal'
        slice_obj.anchor_vm_name = anchor_vm_hint or (active_vms[-1].name if active_vms else None)
        slice_obj.base_num_vms = len(active_vms)
        slice_obj.num_vms = len(active_vms) + len(extra_vms)
        self.db.save_slice(slice_obj)

        for vm in extra_vms:
            vm.status = VMStatus.ACTIVE if vm.name in result.get("server_ids", {}) else VMStatus.ERROR
            vm.hypervisor_hostname = (force_hosts or {}).get(vm.name)
            self.db.save_vm(vm)

        # Extend R5.6 pruning to whatever hypervisors the new VMs landed on.
        ovs2 = self._get_ovs2()
        new_vlan_ids = [lv["vlan_id"] for lv in ext_link_vlans if lv.get("vlan_id")]
        if ovs2 and new_vlan_ids and force_hosts:
            ovs2.add_slice_vlans(new_vlan_ids, list(set(force_hosts.values())))

        return {"success": True,
               "message": f"Slice editado: {len(active_vms) + len(extra_vms)} VMs total",
               "slice": self.get_slice(slice_obj.id)}

    def delete_slice(self, slice_id: str, user: User = None) -> dict:
        slice_obj = self.db.get_slice(slice_id)
        if slice_obj and user and slice_obj.created_by != user.username and not user.can_force_delete():
            return {"success": False, "error": "No tienes permiso para eliminar este slice"}
        vms = self.db.get_vms_for_slice(slice_id)
        for vm in vms:
            self.placement_engine.release_vm(vm)

        infra = getattr(slice_obj, "infrastructure_target", "linux") if slice_obj else "linux"

        if infra == "openstack" and slice_obj:
            try:
                os_drv = self._get_openstack_driver()
                os_drv.teardown_slice(slice_obj, vms)
            except Exception as e:
                logger.error("OS teardown failed for slice %s: %s", slice_id, e)

            # OVS2 VLAN pruning cleanup (OpenStack cluster physical switch).
            # We don't persist per-VM hypervisor hostnames, so prune across
            # every known compute port — removing a VLAN a port never had
            # is a no-op (set difference), so this is safe.
            ovs2 = self._get_ovs2()
            if ovs2 and slice_obj:
                vlan_ids = [slice_obj.vlan_id] if slice_obj.vlan_id else []
                if hasattr(slice_obj, "link_vlans") and slice_obj.link_vlans:
                    vlan_ids += [lv["vlan_id"] for lv in slice_obj.link_vlans if lv.get("vlan_id")]
                if vlan_ids:
                    all_hostnames = list(ovs2.port_map.keys())
                    ovs2.remove_slice_vlans(vlan_ids, all_hostnames)

            slice_obj.status = SliceStatus.DELETED
            self.db.save_slice(slice_obj)
            for vm in vms:
                vm.status = VMStatus.DELETED
                self.db.save_vm(vm)
            success = True
        else:
            # OVS1 VLAN pruning cleanup (Linux cluster physical switch)
            if slice_obj:
                worker_names = []
                for vm in vms:
                    h = next((h for h in self.hosts if h.ip == vm.host_ip), None)
                    if h:
                        worker_names.append(h.hostname)
                vlan_ids = [slice_obj.vlan_id] if slice_obj.vlan_id else []
                if hasattr(slice_obj, "link_vlans") and slice_obj.link_vlans:
                    vlan_ids += [lv["vlan_id"] for lv in slice_obj.link_vlans if lv.get("vlan_id")]
                ovs1 = self._get_ovs1()
                if ovs1 and vlan_ids:
                    ovs1.remove_slice_vlans(vlan_ids, list(set(worker_names)))
            success = self.slice_manager.delete_slice(slice_id)

        self.db.release_vlan(slice_id)
        self.db.save_log(slice_id, "orchestrator", "INFO",
                         f"Slice eliminado, VLAN liberada, infra={infra}",
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
                           vms_image: dict = None,
                           infrastructure_target: str = "linux",
                           zone_id: str = None,
                           flavor_id: str = None) -> str:
        return self.task_queue.enqueue(
            f"create_slice:{name}",
            self.create_slice,
            name, topology, num_vms, vcpus, ram_mb, disk_gb,
            enable_dhcp, enable_internet, created_by,
            vms_internet, vms_image,
            infrastructure_target, zone_id, flavor_id,
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
                         new_vms_internet: List[int] = None,
                         new_vms_flavor_id: str = None,
                         ext_topology: str = None,
                         anchor_vm_hint: str = None) -> str:
        return self.task_queue.enqueue(
            f"edit_slice:{slice_id}",
            self.edit_slice,
            slice_id, add_vms, remove_vm_ids,
            new_vcpus, new_ram_mb, new_disk_gb, user,
            new_vms_image, new_vms_internet, new_vms_flavor_id,
            ext_topology, anchor_vm_hint,
        )

    def get_task_status(self, ticket_id: str) -> Optional[dict]:
        return self.task_queue.get_task(ticket_id)
