# ==============================================================
# Networking Manager - Configures OVS and VLANs for slices (R5)
# Handles:
#   - OVS bridge creation on each host
#   - Physical uplink as trunk port (cross-host L2 via VLAN tags)
#   - VLAN tagging for slice isolation
#   - Connectivity between VMs based on topology (lineal/anillo)
#   - Optional DHCP via dnsmasq in network namespace
#   - Optional Internet via NAT (MASQUERADE)
#   - SSH port forwarding for VMs with enable_internet=True (R2.9)
# ==============================================================

import logging
import time
from typing import List, Tuple

import paramiko

from ..models.vm import VM
from ..models.slice import Slice

logger = logging.getLogger("orchestrator.networking")

# Base external SSH port for VM forwarding: gateway maps 5801-5804 to server1-4.
# We use ports 10000+ on the headnode for per-VM SSH forwarding.
SSH_FWD_BASE = 10000


class NetworkManager:
    """
    Configures layer-2 network connectivity for slices using OVS.

    Cross-host L2 connectivity is achieved by adding the physical uplink
    (trunk_port, default eth1) as a trunk port on br-int on every worker.
    VLAN-tagged frames travel over the physical switch between workers, so
    VMs on different hosts in the same VLAN see each other at L2 without
    tunnels. NAT/MASQUERADE uses a separate interface (nat_iface, default
    eth0) which is the management NIC — keeping it out of OVS.

    Requirements covered:
      R5.1 - Internet access (NAT/MASQUERADE)
      R5.2 - Access from exterior (iptables DNAT for SSH)
      R5.3 - VLANs instead of tunnels
      R5.4 - Reconfigure OVS switch
      R2.9 - SSH access from Internet to selected VMs
    """

    OVS_BRIDGE = "br-int"

    def __init__(self, ssh_key_path: str = "/home/ubuntu/.ssh/id_rsa",
                 headnode_ip: str = "10.0.10.1",
                 trunk_port: str = "eth1",
                 nat_iface: str = "eth0"):
        self.ssh_key_path = ssh_key_path
        self.headnode_ip = headnode_ip
        # eth1: added as OVS trunk so VLAN frames cross the physical switch.
        self.trunk_port = trunk_port
        # eth0: management NIC used only for NAT/MASQUERADE — never added to OVS.
        self.nat_iface = nat_iface

    def setup_slice_network(self, slice_obj: Slice, vms: List[VM],
                            vlan_id: int, subnet: str,
                            enable_dhcp: bool = False,
                            enable_internet: bool = False) -> bool:
        """
        Full network setup for a slice:
        1. Ensure OVS bridge + trunk uplink on all involved hosts
        2. Tag each VM primary tap with the slice VLAN
        3. Tag each VM link tap with its per-link VLAN
        4. DHCP namespace on headnode (if requested)
        5. NAT + ip_forward on headnode (if requested)
        6. SSH port forwarding on headnode for VMs with enable_internet=True
        """
        hosts_involved = list(set(vm.host_ip for vm in vms if vm.host_ip))

        logger.info("Setting up network for slice %s (VLAN %d, subnet %s)",
                    slice_obj.name, vlan_id, subnet)

        try:
            for host_ip in hosts_involved:
                self._ensure_bridge(host_ip)
            # Headnode also needs br-int for the DHCP gateway interface
            self._ensure_bridge(self.headnode_ip)

            for vm in vms:
                if vm.tap_interface and vm.host_ip:
                    # Primary tap → slice VLAN (internet/management)
                    self._set_vlan(vm.host_ip, vm.tap_interface, vlan_id)
                # Link taps → per-link VLAN
                for iface in (vm.interfaces or []):
                    if iface.get("type") == "link" and iface.get("vlan_id") and vm.host_ip:
                        self._set_vlan(vm.host_ip, iface["tap_name"], iface["vlan_id"])

            # Assign predictable IPs before DHCP so leases and SSH rules match
            subnet_base = subnet.split("/")[0].rsplit(".", 1)[0]
            for vm in vms:
                if not vm.ip_address:
                    vm.ip_address = f"{subnet_base}.{vm.index + 2}"

            if enable_dhcp:
                self._setup_dhcp(self.headnode_ip, vlan_id, subnet, vms)

            if enable_internet:
                self._setup_internet(self.headnode_ip, vlan_id, subnet)

            for vm in vms:
                if not vm.enable_internet or not vm.vnc_port:
                    continue
                fwd_port = SSH_FWD_BASE + vm.vnc_port
                self._setup_ssh_forward(self.headnode_ip, fwd_port, vm.ip_address, vm)

            time.sleep(1)
            logger.info("Network configured for slice %s", slice_obj.name)
            return True

        except Exception as e:
            logger.error("Failed to setup network for slice %s: %s",
                         slice_obj.name, e)
            return False

    def teardown_slice_network(self, vms: List[VM], vlan_id: int) -> bool:
        try:
            for vm in vms:
                if vm.tap_interface and vm.host_ip:
                    client = self._connect(vm.host_ip)
                    self._exec(client,
                               f"sudo ovs-vsctl del-port {self.OVS_BRIDGE} "
                               f"{vm.tap_interface} 2>/dev/null")
                    client.close()
                # Remove SSH port forwarding rule if it was set
                if vm.enable_internet and vm.vnc_port:
                    fwd_port = SSH_FWD_BASE + vm.vnc_port
                    self._teardown_ssh_forward(self.headnode_ip, fwd_port)

            hosts_involved = list(set(vm.host_ip for vm in vms if vm.host_ip))
            if hosts_involved and vlan_id:
                self._cleanup_dhcp(self.headnode_ip, vlan_id)
                self._cleanup_internet(self.headnode_ip, vlan_id)
            return True
        except Exception as e:
            logger.error("Failed to teardown network: %s", e)
            return False

    def configure_topology_links(self, vms: List[VM], links: List[Tuple[int, int]],
                                 vlan_id: int) -> bool:
        """
        L2 links are implicit: all VMs in the same VLAN on br-int can
        communicate. The physical uplink trunk carries VLAN frames between
        workers, so cross-host links work without tunnels (R5.3).
        """
        logger.info("Topology links active via VLAN %d trunk on %s",
                    vlan_id, self.trunk_port)
        return True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_bridge(self, host_ip: str):
        """Create br-int if missing, then add physical uplink as trunk port."""
        client = self._connect(host_ip)
        _, stdout, _ = client.exec_command(
            f"sudo ovs-vsctl br-exists {self.OVS_BRIDGE}", timeout=10
        )
        stdout.channel.recv_exit_status()
        if stdout.channel.exit_status != 0:
            self._exec(client, f"sudo ovs-vsctl add-br {self.OVS_BRIDGE}")
            logger.info("Created OVS bridge %s on %s", self.OVS_BRIDGE, host_ip)

        # Add physical uplink as trunk (carries all VLANs between workers).
        # Idempotent: ovs-vsctl ignores the port if it already exists.
        self._exec(client,
                   f"sudo ovs-vsctl --may-exist add-port {self.OVS_BRIDGE} "
                   f"{self.trunk_port}")
        # Trunk mode = no tag set on the port (default OVS behaviour).
        self._exec(client,
                   f"sudo ip link set {self.trunk_port} up 2>/dev/null")
        client.close()

    def _set_vlan(self, host_ip: str, tap_name: str, vlan_id: int):
        client = self._connect(host_ip)
        self._exec(client,
                   f"sudo ovs-vsctl set port {tap_name} tag={vlan_id} 2>/dev/null")
        client.close()

    def _setup_dhcp(self, host_ip: str, vlan_id: int, subnet: str,
                    vms: List[VM] = None):
        """
        Run dnsmasq in the main namespace via an OVS internal port tagged with
        the slice VLAN.  Running in the main namespace (not a netns) lets the
        kernel forward VM traffic through ip_forward + MASQUERADE so VMs can
        reach the Internet.  Static --dhcp-host entries pin each VM to a
        predictable IP so SSH DNAT rules always match.
        """
        client = self._connect(host_ip)
        iface = f"dhcp-vlan{vlan_id}"
        parts = subnet.split("/")[0].split(".")
        subnet_base = f"{parts[0]}.{parts[1]}.{parts[2]}"
        gw_ip = f"{subnet_base}.1"
        # /28 gives .0-.15; gateway=.1, VMs=.2-.14
        range_start = f"{subnet_base}.2"
        range_end = f"{subnet_base}.14"

        self._exec(client,
                   f"sudo ovs-vsctl --may-exist add-port {self.OVS_BRIDGE} {iface} "
                   f"-- set interface {iface} type=internal 2>/dev/null")
        self._exec(client,
                   f"sudo ovs-vsctl set port {iface} tag={vlan_id} 2>/dev/null")
        self._exec(client, f"sudo ip link set {iface} up 2>/dev/null")
        self._exec(client,
                   f"sudo ip addr add {gw_ip}/24 dev {iface} 2>/dev/null")
        self._exec(client,
                   f"sudo pkill -f 'dnsmasq.*{iface}' 2>/dev/null; true")

        # Static leases: pin each VM to subnet_base.{index+2} via its primary MAC
        dhcp_host_args = ""
        if vms:
            for vm in vms:
                mac = vm.mac_address
                if not mac:
                    continue
                vm_ip = f"{subnet_base}.{vm.index + 2}"
                dhcp_host_args += f"--dhcp-host={mac},{vm_ip} "

        self._exec(client,
                   f"sudo dnsmasq "
                   f"--interface={iface} "
                   f"--dhcp-range={range_start},{range_end},255.255.255.0,12h "
                   f"--dhcp-option=3,{gw_ip} "
                   f"--dhcp-option=6,8.8.8.8 "
                   f"{dhcp_host_args}"
                   f"--no-resolv --server=8.8.8.8 "
                   f"--pid-file=/tmp/dnsmasq-{iface}.pid")
        logger.info("DHCP configured for VLAN %d on %s (gateway %s)",
                    vlan_id, host_ip, gw_ip)
        client.close()

    def _setup_internet(self, host_ip: str, vlan_id: int, subnet: str):
        """Enable NAT (MASQUERADE) so VMs can reach the Internet."""
        client = self._connect(host_ip)
        self._exec(client, "sudo sysctl -w net.ipv4.ip_forward=1 2>/dev/null")
        # Persist ip_forward across reboots
        self._exec(client,
                   "grep -q 'net.ipv4.ip_forward=1' /etc/sysctl.conf || "
                   "echo 'net.ipv4.ip_forward=1' | sudo tee -a /etc/sysctl.conf")
        # MASQUERADE: VMs → internet via headnode's external NIC
        self._exec(client,
                   f"sudo iptables -t nat -C POSTROUTING "
                   f"-s {subnet} -o {self.nat_iface} -j MASQUERADE 2>/dev/null || "
                   f"sudo iptables -t nat -A POSTROUTING "
                   f"-s {subnet} -o {self.nat_iface} -j MASQUERADE")
        # FORWARD rules: allow VM traffic out and established traffic back
        self._exec(client,
                   f"sudo iptables -C FORWARD -s {subnet} -j ACCEPT 2>/dev/null || "
                   f"sudo iptables -A FORWARD -s {subnet} -j ACCEPT")
        self._exec(client,
                   f"sudo iptables -C FORWARD -d {subnet} "
                   f"-m state --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || "
                   f"sudo iptables -A FORWARD -d {subnet} "
                   f"-m state --state RELATED,ESTABLISHED -j ACCEPT")
        logger.info("NAT enabled for VLAN %d subnet %s on %s",
                    vlan_id, subnet, host_ip)
        client.close()

    def _setup_ssh_forward(self, host_ip: str, ext_port: int,
                           vm_ip: str, vm: VM):
        """
        DNAT rule on headnode: external TCP:{ext_port} -> vm_ip:22
        Allows SSH from Internet to a specific VM (R2.9, R5.2).
        """
        client = self._connect(host_ip)
        self._exec(client, "sudo sysctl -w net.ipv4.ip_forward=1 2>/dev/null")
        check = self._exec(client,
                           f"sudo iptables -t nat -C PREROUTING "
                           f"-p tcp --dport {ext_port} "
                           f"-j DNAT --to-destination {vm_ip}:22 2>&1")
        if "No chain" in check or "no chain" in check or check.strip() == "":
            self._exec(client,
                       f"sudo iptables -t nat -A PREROUTING "
                       f"-p tcp --dport {ext_port} "
                       f"-j DNAT --to-destination {vm_ip}:22")
            self._exec(client,
                       f"sudo iptables -A FORWARD -p tcp -d {vm_ip} "
                       f"--dport 22 -j ACCEPT")
        vm.ssh_fwd_port = ext_port
        logger.info("SSH forward: headnode:%d -> %s:22 (VM %s)",
                    ext_port, vm_ip, vm.name)
        client.close()

    def _teardown_ssh_forward(self, host_ip: str, ext_port: int):
        client = self._connect(host_ip)
        self._exec(client,
                   f"sudo iptables -t nat -D PREROUTING "
                   f"-p tcp --dport {ext_port} -j DNAT "
                   f"--to-destination 0.0.0.0:22 2>/dev/null; true")
        client.close()

    def _cleanup_dhcp(self, host_ip: str, vlan_id: int):
        client = self._connect(host_ip)
        iface = f"dhcp-vlan{vlan_id}"
        self._exec(client, f"sudo pkill -f 'dnsmasq.*{iface}' 2>/dev/null; true")
        self._exec(client,
                   f"sudo ovs-vsctl del-port {self.OVS_BRIDGE} {iface} 2>/dev/null; true")
        self._exec(client, f"sudo ip link delete {iface} 2>/dev/null; true")
        # Also clean up old-style namespace if it exists from a previous version
        ns = f"dnsmasq-vlan{vlan_id}"
        self._exec(client, f"sudo ip netns delete {ns} 2>/dev/null; true")
        client.close()

    def _cleanup_internet(self, host_ip: str, vlan_id: int):
        """Best-effort removal of NAT rule (subnet unknown at teardown time)."""
        client = self._connect(host_ip)
        # Flush only rules matching our VLAN subnet range (10.60.3.x)
        self._exec(client,
                   f"sudo iptables-save | grep -v '10.60.3.' | "
                   f"sudo iptables-restore 2>/dev/null; true")
        client.close()

    def _connect(self, host_ip: str) -> paramiko.SSHClient:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=host_ip,
            username="ubuntu",
            key_filename=self.ssh_key_path,
            timeout=15,
        )
        return client

    def _exec(self, client: paramiko.SSHClient, cmd: str) -> str:
        _, stdout, stderr = client.exec_command(cmd, timeout=30)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        if err and "Warning" not in err and "warning" not in err:
            logger.debug("SSH stderr [%s]: %s", cmd[:60], err.strip())
        return out
