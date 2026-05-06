# ==============================================================
# Orchestrator - Central coordinator (brain of the system)
#
# Flow (from architecture doc):
#   1. Receives validated request from UI/API Gateway
#   2. Builds domain objects (Slice, VMs)
#   3. Queries Persistence for hosts, images, state
#   4. Invokes VM Placement to decide VM→host mapping
#   5. Invokes Lifecycle to execute CRUD
#   6. Lifecycle calls Drivers + Networking
#   7. Saves final state and logs
# ==============================================================

import logging
from typing import List, Optional

from .models.slice import Slice, SliceStatus, TopologyType
from .models.vm import VM, VMStatus
from .models.host import Host
from .models.topology import Topology
from .models.placement_decision import PlacementPlan
from .placement.placement_engine import PlacementEngine
from .lifecycle.slice_manager import SliceManager
from .drivers.linux_driver import LinuxDriver
from .networking.network_manager import NetworkManager
from .database.db_manager import DatabaseManager

logger = logging.getLogger("orchestrator")


class Orchestrator:
    """
    Central orchestrator that coordinates:
      - VM Placement (R4)
      - Lifecycle/Slice Manager (R1C)
      - Linux Driver (R2)
      - Networking & Security (R5)
      - Persistence (MariaDB)
    """

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

    def create_slice(self, name: str, topology: str, num_vms: int,
                     vcpus: int = 1, ram_mb: int = 512, disk_gb: int = 2,
                     vlan_id: int = 300, subnet: str = "10.60.3.0/24",
                     enable_dhcp: bool = False, enable_internet: bool = False,
                     created_by: str = "admin") -> dict:
        """
        Complete flow for creating a slice:

        Step 1: Build Slice domain object
        Step 2: Build VM objects for each node
        Step 3: Query DB for available hosts
        Step 4: Run VM Placement (greedy) to assign VM → host
        Step 5: Apply placement to VMs
        Step 6: Invoke Lifecycle to create VMs + configure network
        Step 7: Persist final state
        Step 8: Return result
        """
        try:
            topo = TopologyType(topology)
        except ValueError:
            return {"success": False, "error": f"Invalid topology: {topology}",
                    "valid_topologies": [t.value for t in TopologyType]}

        if num_vms < 2:
            return {"success": False, "error": "Slice needs at least 2 VMs"}

        slice_obj = Slice(
            id="",
            name=name,
            topology=topo,
            num_vms=num_vms,
            vcpus_per_vm=vcpus,
            ram_mb_per_vm=ram_mb,
            disk_gb_per_vm=disk_gb,
            vlan_id=vlan_id,
            subnet=subnet,
            enable_dhcp=enable_dhcp,
            enable_internet=enable_internet,
            status=SliceStatus.CREATING,
            created_by=created_by,
        )

        logger.info("Orchestrator: Starting slice creation '%s' (%s, %d VMs)",
                     name, topology, num_vms)

        vms = []
        for i in range(num_vms):
            vm = VM(
                id="",
                slice_id=slice_obj.id,
                name=f"{name}-vm{i+1}",
                index=i,
                vcpus=vcpus,
                ram_mb=ram_mb,
                disk_gb=disk_gb,
                status=VMStatus.PENDING,
            )
            vms.append(vm)

        logger.info("Orchestrator: Running VM Placement for %d VMs", num_vms)
        plan = self.placement_engine.place_vms(slice_obj.id, vms)

        if not plan.success:
            slice_obj.status = SliceStatus.ERROR
            slice_obj.error_message = plan.error_message
            self.db.save_slice(slice_obj)
            self.db.save_log(slice_obj.id, "orchestrator", "ERROR",
                             f"Placement failed: {plan.error_message}")
            return {"success": False, "error": plan.error_message}

        for vm, decision in zip(vms, plan.decisions):
            vm.host_ip = decision.host_ip
            vm.status = VMStatus.PENDING

        logger.info("Orchestrator: Invoking Lifecycle to create VMs")
        created_vms = self.slice_manager.create_slice(slice_obj)
        if not created_vms:
            return {"success": False, "error": "Slice creation failed during deployment"}

        logger.info("Orchestrator: Slice '%s' created successfully", name)

        links = Topology.get_links(topo, num_vms)
        self.db.save_log(slice_obj.id, "orchestrator", "INFO",
                         f"Slice '{name}' created: {num_vms} VMs, "
                         f"topology={topology}, links={links}")

        return {
            "success": True,
            "slice_id": slice_obj.id,
            "name": slice_obj.name,
            "topology": topology,
            "num_vms": num_vms,
            "vms": [vm.to_dict() for vm in created_vms],
            "links": links,
        }

    def delete_slice(self, slice_id: str) -> dict:
        logger.info("Orchestrator: Deleting slice %s", slice_id)
        vms = self.db.get_vms_for_slice(slice_id)
        for vm in vms:
            self.placement_engine.release_vm(vm)
        success = self.slice_manager.delete_slice(slice_id)
        return {"success": success, "slice_id": slice_id}

    def get_slice(self, slice_id: str) -> Optional[dict]:
        return self.slice_manager.get_slice_info(slice_id)

    def list_slices(self) -> List[dict]:
        return self.slice_manager.list_all_slices()

    def get_hosts_status(self) -> List[dict]:
        return self.slice_manager.get_hosts_status()

    def get_logs(self, slice_id: str) -> List[dict]:
        return self.db.get_logs_for_slice(slice_id)

    def import_image(self, image_path: str, image_name: str) -> dict:
        self.db.save_log("system", "orchestrator", "INFO",
                         f"Image imported: {image_name} from {image_path}")
        return {"success": True, "image_name": image_name, "path": image_path}
