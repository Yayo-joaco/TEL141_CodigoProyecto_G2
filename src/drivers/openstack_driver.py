# ==============================================================
# OpenStack Driver — REST-only (no CLI) via Keystone/Nova/Neutron/Glance
# Custom VM placement: query hypervisor stats, force via availability_zone
# ==============================================================

import logging
import time
import threading
from typing import Dict, List, Optional, Tuple

import requests

logger = logging.getLogger("orchestrator.openstack")


class OpenStackDriver:
    """
    Interacts with OpenStack APIs using plain HTTP requests.
    Token is cached and refreshed automatically.
    Each slice gets its own Keystone project for isolation.
    Custom placement: we query /os-hypervisors/detail and pick the host,
    then force Nova to use it via availability_zone="nova:<hostname>".
    """

    def __init__(self, auth_url: str, username: str, password: str,
                 project_name: str = "admin", domain_name: str = "Cloud",
                 nova_url: str = None, neutron_url: str = None,
                 glance_url: str = None, novnc_base: str = None,
                 token_cache_ttl: int = 3300):
        self.auth_url = auth_url.rstrip("/")
        self.username = username
        self.password = password
        self.project_name = project_name
        self.domain_name = domain_name
        self._nova_url = nova_url
        self._neutron_url = neutron_url
        self._glance_url = glance_url
        self.novnc_base = novnc_base or ""
        self.token_cache_ttl = token_cache_ttl

        self._admin_token: Optional[str] = None
        self._admin_token_expiry: float = 0
        self._token_lock = threading.Lock()
        self._unreachable_until: float = 0  # back-off when Keystone is down

    # ------------------------------------------------------------------
    # Keystone — token management
    # ------------------------------------------------------------------

    def _get_admin_token(self) -> str:
        with self._token_lock:
            now = time.time()
            # Fast-fail if we recently couldn't reach Keystone (60s back-off)
            if now < self._unreachable_until:
                raise ConnectionError("OpenStack Keystone unreachable (back-off active)")
            if self._admin_token and now < self._admin_token_expiry:
                return self._admin_token
            payload = {
                "auth": {
                    "identity": {
                        "methods": ["password"],
                        "password": {
                            "user": {
                                "name": self.username,
                                "domain": {"name": self.domain_name},
                                "password": self.password,
                            }
                        },
                    },
                    "scope": {
                        "project": {
                            "name": self.project_name,
                            "domain": {"name": self.domain_name},
                        }
                    },
                }
            }
            try:
                r = requests.post(f"{self.auth_url}/v3/auth/tokens", json=payload, timeout=5)
                r.raise_for_status()
            except Exception as e:
                self._unreachable_until = time.time() + 60  # back off 60s
                raise
            self._admin_token = r.headers["X-Subject-Token"]
            self._admin_token_expiry = now + self.token_cache_ttl
            self._unreachable_until = 0
            logger.debug("Admin token refreshed")
            return self._admin_token

    def _get_scoped_token(self, project_id: str) -> str:
        """Get a token scoped to a specific project."""
        token = self._get_admin_token()
        payload = {
            "auth": {
                "identity": {"methods": ["token"], "token": {"id": token}},
                "scope": {"project": {"id": project_id}},
            }
        }
        r = requests.post(f"{self.auth_url}/v3/auth/tokens", json=payload, timeout=15)
        r.raise_for_status()
        return r.headers["X-Subject-Token"]

    def _headers(self, project_id: str = None) -> dict:
        if project_id:
            return {"X-Auth-Token": self._get_scoped_token(project_id),
                    "Content-Type": "application/json"}
        return {"X-Auth-Token": self._get_admin_token(),
                "Content-Type": "application/json"}

    # ------------------------------------------------------------------
    # Keystone — project / user / role management
    # ------------------------------------------------------------------

    def _get_domain_id(self) -> str:
        r = requests.get(f"{self.auth_url}/v3/domains",
                         params={"name": self.domain_name},
                         headers=self._headers(), timeout=10)
        r.raise_for_status()
        return r.json()["domains"][0]["id"]

    def create_project(self, name: str) -> str:
        """Create a Keystone project; return its ID."""
        domain_id = self._get_domain_id()
        payload = {"project": {"name": name, "domain_id": domain_id, "enabled": True}}
        r = requests.post(f"{self.auth_url}/v3/projects",
                          json=payload, headers=self._headers(), timeout=10)
        r.raise_for_status()
        return r.json()["project"]["id"]

    def delete_project(self, project_id: str):
        r = requests.delete(f"{self.auth_url}/v3/projects/{project_id}",
                            headers=self._headers(), timeout=10)
        if r.status_code not in (204, 404):
            r.raise_for_status()

    def _get_admin_user_id(self) -> str:
        r = requests.get(f"{self.auth_url}/v3/users",
                         params={"name": self.username},
                         headers=self._headers(), timeout=10)
        r.raise_for_status()
        return r.json()["users"][0]["id"]

    def _get_member_role_id(self) -> str:
        r = requests.get(f"{self.auth_url}/v3/roles",
                         params={"name": "member"},
                         headers=self._headers(), timeout=10)
        r.raise_for_status()
        roles = r.json()["roles"]
        if not roles:
            r2 = requests.get(f"{self.auth_url}/v3/roles",
                              headers=self._headers(), timeout=10)
            r2.raise_for_status()
            roles = r2.json()["roles"]
        return roles[0]["id"]

    def assign_admin_to_project(self, project_id: str):
        user_id = self._get_admin_user_id()
        role_id = self._get_member_role_id()
        r = requests.put(
            f"{self.auth_url}/v3/projects/{project_id}/users/{user_id}/roles/{role_id}",
            headers=self._headers(), timeout=10,
        )
        if r.status_code not in (200, 201, 204):
            r.raise_for_status()

    # ------------------------------------------------------------------
    # Glance — images
    # ------------------------------------------------------------------

    def list_images(self) -> List[dict]:
        url = f"{self._glance_url}/v2/images?limit=100"
        r = requests.get(url, headers=self._headers(), timeout=15)
        r.raise_for_status()
        return r.json().get("images", [])

    def get_image_id(self, name: str) -> Optional[str]:
        for img in self.list_images():
            if img["name"] == name:
                return img["id"]
        return None

    def upload_image_to_glance(self, name: str, file_path: str,
                                disk_format: str = "qcow2",
                                container_format: str = "bare",
                                visibility: str = "public") -> dict:
        """Create image record in Glance then upload binary data from file_path."""
        # Step 1: create the image record
        create_url = f"{self._glance_url}/v2/images"
        payload = {
            "name": name,
            "disk_format": disk_format,
            "container_format": container_format,
            "visibility": visibility,
        }
        r = requests.post(create_url, json=payload, headers=self._headers(), timeout=30)
        r.raise_for_status()
        image_id = r.json()["id"]

        # Step 2: upload binary data (stream so we don't load 600MB in RAM)
        upload_url = f"{self._glance_url}/v2/images/{image_id}/file"
        upload_headers = dict(self._headers())
        upload_headers["Content-Type"] = "application/octet-stream"
        with open(file_path, "rb") as fh:
            r2 = requests.put(upload_url, data=fh, headers=upload_headers, timeout=600)
        r2.raise_for_status()

        logger.info("Uploaded image '%s' to Glance as %s", name, image_id)
        return {"image_id": image_id, "name": name, "status": "active"}

    # ------------------------------------------------------------------
    # Nova — flavors
    # ------------------------------------------------------------------

    def get_or_create_flavor(self, name: str, vcpus: int,
                             ram_mb: int, disk_gb: int) -> str:
        url = f"{self._nova_url}/v2.1/flavors"
        r = requests.get(url, headers=self._headers(), timeout=10)
        r.raise_for_status()
        for f in r.json().get("flavors", []):
            if f["name"] == name:
                return f["id"]
        payload = {"flavor": {"name": name, "vcpus": vcpus,
                               "ram": ram_mb, "disk": disk_gb,
                               "os-flavor-access:is_public": True}}
        r2 = requests.post(url, json=payload, headers=self._headers(), timeout=10)
        r2.raise_for_status()
        return r2.json()["flavor"]["id"]

    # ------------------------------------------------------------------
    # Nova — hypervisor stats (for our custom placement)
    # ------------------------------------------------------------------

    def get_hypervisor_stats(self) -> List[dict]:
        """
        Returns list of {hostname, free_vcpus, free_ram_mb, free_disk_gb}.
        Uses Nova microversion 2.6 for detailed data.
        """
        url = f"{self._nova_url}/v2.1/os-hypervisors/detail"
        headers = {**self._headers(), "X-OpenStack-Nova-API-Version": "2.6"}
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        result = []
        for h in r.json().get("hypervisors", []):
            result.append({
                "hostname": h.get("hypervisor_hostname", ""),
                "host_ip": h.get("host_ip", ""),
                "state": h.get("state", ""),
                "status": h.get("status", ""),
                "total_vcpus": h.get("vcpus", 0),
                "free_vcpus": h.get("vcpus", 0) - h.get("vcpus_used", 0),
                "total_ram_mb": h.get("memory_mb", 0),
                "free_ram_mb": h.get("free_ram_mb", 0),
                "total_disk_gb": h.get("local_gb", 0),
                "free_disk_gb": h.get("free_disk_gb", 0),
                "running_vms": h.get("running_vms", 0),
            })
        return result

    # ------------------------------------------------------------------
    # Neutron — networks / subnets / ports
    # ------------------------------------------------------------------

    def create_vlan_network(self, name: str, vlan_id: int,
                            project_id: str) -> str:
        url = f"{self._neutron_url}/v2.0/networks"
        payload = {"network": {
            "name": name,
            "provider:network_type": "vlan",
            "provider:physical_network": "physnet1",
            "provider:segmentation_id": vlan_id,
            "tenant_id": project_id,
            "shared": False,
        }}
        r = requests.post(url, json=payload, headers=self._headers(), timeout=15)
        r.raise_for_status()
        return r.json()["network"]["id"]

    def create_subnet(self, network_id: str, cidr: str,
                      name: str, project_id: str,
                      enable_dhcp: bool = True,
                      gateway_ip: str = None) -> str:
        url = f"{self._neutron_url}/v2.0/subnets"
        payload = {"subnet": {
            "network_id": network_id,
            "cidr": cidr,
            "ip_version": 4,
            "name": name,
            "tenant_id": project_id,
            "enable_dhcp": enable_dhcp,
        }}
        if gateway_ip:
            payload["subnet"]["gateway_ip"] = gateway_ip
        r = requests.post(url, json=payload, headers=self._headers(), timeout=15)
        r.raise_for_status()
        return r.json()["subnet"]["id"]

    def get_or_create_external_network(self, name: str = "external",
                                       cidr: str = "10.60.4.0/24") -> Tuple[str, str]:
        """Returns (network_id, subnet_id) for the external/provider network."""
        url = f"{self._neutron_url}/v2.0/networks"
        r = requests.get(url, params={"name": name}, headers=self._headers(), timeout=10)
        r.raise_for_status()
        nets = r.json().get("networks", [])
        if nets:
            net_id = nets[0]["id"]
            sr = requests.get(f"{self._neutron_url}/v2.0/subnets",
                               params={"network_id": net_id},
                               headers=self._headers(), timeout=10)
            sr.raise_for_status()
            subnets = sr.json().get("subnets", [])
            sub_id = subnets[0]["id"] if subnets else ""
            return net_id, sub_id
        # Create it
        payload = {"network": {
            "name": name,
            "provider:network_type": "flat",
            "provider:physical_network": "physnet1",
            "router:external": True,
            "shared": True,
        }}
        cr = requests.post(url, json=payload, headers=self._headers(), timeout=15)
        cr.raise_for_status()
        net_id = cr.json()["network"]["id"]
        sub_id = self.create_subnet(net_id, cidr, f"{name}-subnet", "admin",
                                    enable_dhcp=False)
        return net_id, sub_id

    def create_router(self, name: str, project_id: str,
                      ext_net_id: str, int_subnet_id: str) -> str:
        url = f"{self._neutron_url}/v2.0/routers"
        payload = {"router": {
            "name": name,
            "tenant_id": project_id,
            "external_gateway_info": {"network_id": ext_net_id},
        }}
        r = requests.post(url, json=payload, headers=self._headers(), timeout=15)
        r.raise_for_status()
        router_id = r.json()["router"]["id"]
        # Add internal subnet interface
        requests.put(
            f"{self._neutron_url}/v2.0/routers/{router_id}/add_router_interface",
            json={"subnet_id": int_subnet_id},
            headers=self._headers(), timeout=15,
        )
        return router_id

    def delete_router(self, router_id: str, subnet_id: str = None):
        if subnet_id:
            requests.put(
                f"{self._neutron_url}/v2.0/routers/{router_id}/remove_router_interface",
                json={"subnet_id": subnet_id},
                headers=self._headers(), timeout=10,
            )
        requests.delete(f"{self._neutron_url}/v2.0/routers/{router_id}",
                        headers=self._headers(), timeout=10)

    def delete_network(self, network_id: str):
        r = requests.delete(f"{self._neutron_url}/v2.0/networks/{network_id}",
                            headers=self._headers(), timeout=10)
        if r.status_code not in (204, 404):
            r.raise_for_status()

    def create_security_group(self, name: str, project_id: str) -> str:
        url = f"{self._neutron_url}/v2.0/security-groups"
        payload = {"security_group": {"name": name, "tenant_id": project_id}}
        r = requests.post(url, json=payload, headers=self._headers(), timeout=10)
        r.raise_for_status()
        sg_id = r.json()["security_group"]["id"]
        # Allow all ingress within group + ICMP + SSH
        rules = [
            {"direction": "ingress", "ethertype": "IPv4", "protocol": "tcp",
             "port_range_min": 22, "port_range_max": 22, "remote_ip_prefix": "0.0.0.0/0"},
            {"direction": "ingress", "ethertype": "IPv4", "protocol": "icmp"},
            {"direction": "ingress", "ethertype": "IPv4",
             "remote_group_id": sg_id},
        ]
        for rule in rules:
            rule["security_group_id"] = sg_id
            rule["tenant_id"] = project_id
            requests.post(f"{self._neutron_url}/v2.0/security-group-rules",
                          json={"security_group_rule": rule},
                          headers=self._headers(), timeout=10)
        return sg_id

    def delete_security_group(self, sg_id: str):
        r = requests.delete(f"{self._neutron_url}/v2.0/security-groups/{sg_id}",
                            headers=self._headers(), timeout=10)
        if r.status_code not in (204, 404):
            r.raise_for_status()

    def allocate_floating_ip(self, ext_net_id: str, project_id: str) -> Tuple[str, str]:
        """Returns (floatingip_id, floating_ip_address)."""
        url = f"{self._neutron_url}/v2.0/floatingips"
        payload = {"floatingip": {
            "floating_network_id": ext_net_id,
            "tenant_id": project_id,
        }}
        r = requests.post(url, json=payload, headers=self._headers(), timeout=15)
        r.raise_for_status()
        fip = r.json()["floatingip"]
        return fip["id"], fip["floating_ip_address"]

    def associate_floating_ip(self, fip_id: str, port_id: str):
        url = f"{self._neutron_url}/v2.0/floatingips/{fip_id}"
        requests.put(url, json={"floatingip": {"port_id": port_id}},
                     headers=self._headers(), timeout=10)

    def release_floating_ip(self, fip_id: str):
        r = requests.delete(f"{self._neutron_url}/v2.0/floatingips/{fip_id}",
                            headers=self._headers(), timeout=10)
        if r.status_code not in (204, 404):
            r.raise_for_status()

    def get_vm_port_id(self, server_id: str, project_id: str) -> Optional[str]:
        r = requests.get(f"{self._nova_url}/v2.1/servers/{server_id}/os-interface",
                         headers=self._headers(project_id), timeout=10)
        if r.status_code != 200:
            return None
        ifaces = r.json().get("interfaceAttachments", [])
        return ifaces[0]["port_id"] if ifaces else None

    # ------------------------------------------------------------------
    # Nova — VM lifecycle
    # ------------------------------------------------------------------

    def create_vm(self, name: str, image_id: str, flavor_id: str,
                  network_ids: List[str], project_id: str,
                  force_host: str = None,
                  security_group_ids: List[str] = None,
                  userdata: str = None) -> str:
        """Boot a VM; return server_id. force_host uses az hint."""
        url = f"{self._nova_url}/v2.1/servers"
        networks = [{"uuid": nid} for nid in network_ids]
        server = {
            "name": name,
            "imageRef": image_id,
            "flavorRef": flavor_id,
            "networks": networks,
        }
        if force_host:
            server["availability_zone"] = f"nova:{force_host}"
        if security_group_ids:
            server["security_groups"] = [{"name": sg} for sg in security_group_ids]
        if userdata:
            import base64
            server["user_data"] = base64.b64encode(userdata.encode()).decode()
        payload = {"server": server}
        scoped_token = self._get_scoped_token(project_id)
        headers = {"X-Auth-Token": scoped_token, "Content-Type": "application/json"}
        r = requests.post(url, json=payload, headers=headers, timeout=30)
        r.raise_for_status()
        return r.json()["server"]["id"]

    def wait_for_active(self, server_id: str, project_id: str,
                        timeout: int = 180) -> bool:
        url = f"{self._nova_url}/v2.1/servers/{server_id}"
        deadline = time.time() + timeout
        scoped_token = self._get_scoped_token(project_id)
        headers = {"X-Auth-Token": scoped_token, "Content-Type": "application/json"}
        while time.time() < deadline:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code != 200:
                time.sleep(5)
                continue
            status = r.json()["server"]["status"]
            if status == "ACTIVE":
                return True
            if status == "ERROR":
                logger.error("VM %s entered ERROR state", server_id)
                return False
            time.sleep(5)
        logger.error("VM %s timed out waiting for ACTIVE", server_id)
        return False

    def get_vm_ip(self, server_id: str, project_id: str,
                  network_name: str = None) -> Optional[str]:
        url = f"{self._nova_url}/v2.1/servers/{server_id}"
        scoped_token = self._get_scoped_token(project_id)
        headers = {"X-Auth-Token": scoped_token, "Content-Type": "application/json"}
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            return None
        addresses = r.json()["server"].get("addresses", {})
        for net, addrs in addresses.items():
            if network_name and net != network_name:
                continue
            for a in addrs:
                if a.get("version") == 4:
                    return a["addr"]
        return None

    def delete_vm(self, server_id: str, project_id: str):
        url = f"{self._nova_url}/v2.1/servers/{server_id}"
        scoped_token = self._get_scoped_token(project_id)
        headers = {"X-Auth-Token": scoped_token, "Content-Type": "application/json"}
        r = requests.delete(url, headers=headers, timeout=15)
        if r.status_code not in (204, 404):
            r.raise_for_status()

    def get_console_url(self, server_id: str, project_id: str = None) -> Optional[str]:
        url = f"{self._nova_url}/v2.1/servers/{server_id}/action"
        headers = self._headers(project_id)
        payload = {"os-getVNCConsole": {"type": "novnc"}}
        r = requests.post(url, json=payload, headers=headers, timeout=10)
        if r.status_code == 200:
            return r.json().get("console", {}).get("url")
        return None

    # ------------------------------------------------------------------
    # Composite: deploy_slice / teardown_slice
    # ------------------------------------------------------------------

    def deploy_slice(self, slice_obj, vms, force_hosts: Dict[str, str] = None) -> dict:
        """
        Deploy a complete slice on OpenStack.
        force_hosts: {vm_name → hypervisor_hostname} from our placement engine.
        Returns info dict with project_id, network_ids, vm server_ids.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        force_hosts = force_hosts or {}

        project_id = self.create_project(f"slice-{slice_obj.id}")
        self.assign_admin_to_project(project_id)
        logger.info("OS project created: %s for slice %s", project_id, slice_obj.id)

        # Network per slice (one flat VLAN network)
        vlan_id = slice_obj.vlan_id or 100
        subnet = slice_obj.subnet or "10.60.3.0/24"
        net_id = self.create_vlan_network(
            f"net-{slice_obj.id}", vlan_id, project_id
        )
        gw = subnet.rsplit(".", 1)[0] + ".1"
        sub_id = self.create_subnet(net_id, subnet, f"subnet-{slice_obj.id}",
                                    project_id, enable_dhcp=slice_obj.enable_dhcp,
                                    gateway_ip=gw)

        ext_net_id = None
        router_id = None
        if slice_obj.enable_internet:
            ext_net_id, _ = self.get_or_create_external_network()
            router_id = self.create_router(
                f"router-{slice_obj.id}", project_id, ext_net_id, sub_id
            )

        sg_id = self.create_security_group(f"sg-{slice_obj.id}", project_id)

        # Resolve flavor / image
        def _boot_vm(vm):
            image_name = vm.image or "cirros"
            image_id = self.get_image_id(image_name) or self.get_image_id("cirros")
            if not image_id:
                raise RuntimeError(f"Image '{image_name}' not found in Glance")
            flavor_id = self.get_or_create_flavor(
                f"f-{vm.vcpus}c-{vm.ram_mb}m",
                vm.vcpus, vm.ram_mb, vm.disk_gb,
            )
            host = force_hosts.get(vm.name)
            server_id = self.create_vm(
                name=f"{slice_obj.name}-{vm.name}",
                image_id=image_id,
                flavor_id=flavor_id,
                network_ids=[net_id],
                project_id=project_id,
                force_host=host,
                security_group_ids=[f"sg-{slice_obj.id}"],
            )
            ok = self.wait_for_active(server_id, project_id)
            if not ok:
                raise RuntimeError(f"VM {vm.name} failed to become ACTIVE")
            ip = self.get_vm_ip(server_id, project_id)
            fip_id, fip_addr = None, None
            if vm.enable_internet and ext_net_id:
                port_id = self.get_vm_port_id(server_id, project_id)
                if port_id:
                    fip_id, fip_addr = self.allocate_floating_ip(ext_net_id, project_id)
                    self.associate_floating_ip(fip_id, port_id)
            return vm, server_id, ip, fip_addr

        results = {}
        errors = []
        with ThreadPoolExecutor(max_workers=min(len(vms), 8)) as ex:
            futures = {ex.submit(_boot_vm, vm): vm for vm in vms}
            for fut in as_completed(futures):
                try:
                    vm, server_id, ip, fip = fut.result()
                    vm.openstack_server_id = server_id
                    vm.ip_address = ip or ""
                    vm.ip_address_external = fip or ""
                    results[vm.name] = server_id
                    logger.info("VM %s booted: server=%s ip=%s", vm.name, server_id, ip)
                except Exception as e:
                    errors.append(str(e))
                    logger.error("OS VM boot error: %s", e)

        if errors:
            logger.error("Slice %s had boot errors: %s", slice_obj.id, errors)

        return {
            "project_id": project_id,
            "network_id": net_id,
            "subnet_id": sub_id,
            "router_id": router_id,
            "sg_id": sg_id,
            "server_ids": results,
            "errors": errors,
        }

    def teardown_slice(self, slice_obj, vms) -> bool:
        """Delete all OS resources for a slice."""
        project_id = getattr(slice_obj, "openstack_project_id", None)
        if not project_id:
            logger.warning("No openstack_project_id on slice %s — skipping OS teardown",
                           slice_obj.id)
            return False

        # Delete VMs
        for vm in vms:
            sid = getattr(vm, "openstack_server_id", None)
            if sid:
                try:
                    self.delete_vm(sid, project_id)
                except Exception as e:
                    logger.warning("Delete VM %s: %s", sid, e)

        # Delete networks stored on slice
        net_ids_json = getattr(slice_obj, "openstack_network_ids", None) or []
        if isinstance(net_ids_json, str):
            import json
            try:
                net_ids_json = json.loads(net_ids_json)
            except Exception:
                net_ids_json = []
        for nid in net_ids_json:
            try:
                self.delete_network(nid)
            except Exception as e:
                logger.warning("Delete network %s: %s", nid, e)

        # Delete project (cascades routers, SGs, ports)
        try:
            self.delete_project(project_id)
        except Exception as e:
            logger.warning("Delete project %s: %s", project_id, e)

        return True
