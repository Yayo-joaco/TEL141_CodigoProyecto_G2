# ==============================================================
# Networking Manager - Configures OVS and VLANs for slices (R5)
# Handles:
#   - OVS bridge creation on each host
#   - VLAN tagging for slice isolation
#   - Connectivity between VMs based on topology (lineal/anillo)
#   - Optional DHCP via dnsmasq
#   - Optional Internet via NAT
# ==============================================================

import logging
import time
from typing import List, Tuple

import paramiko

from ..models.vm import VM
from ..models.slice import Slice

logger = logging.getLogger("orchestrator.networking")


class NetworkManager:
    """
    Configures layer-2 network connectivity for slices using OVS.

    Requirements covered:
      R5 - Networking y Seguridad (VLANs instead of tunnels, L2 connectivity)
    """

    OVS_BRIDGE = "br-int"

    def __init__(self, ssh_key_path: str = "/home/ubuntu/.ssh/id_rsa"):
        self.ssh_key_path = ssh_key_path

    def setup_slice_network(self, slice_obj: Slice, vms: List[VM],
                            vlan_id: int, subnet: str,
                            enable_dhcp: bool = False,
                            enable_internet: bool = False) -> bool:
        """
        Configures network for a complete slice:
        1. Ensure OVS bridge exists on all involved hosts
        2. Set VLAN on all VM tap interfaces
        3. Configure DHCP (if enabled) on headnode
        4. Configure NAT/Internet (if enabled) on headnode
        """
        hosts_involved = list(set(vm.host_ip for vm in vms if vm.host_ip))

        logger.info("Setting up network for slice %s (VLAN %d, subnet %s)",
                     slice_obj.name, vlan_id, subnet)

        try:
            for host_ip in hosts_involved:
                self._ensure_bridge(host_ip)

            for vm in vms:
                if vm.tap_interface and vm.host_ip:
                    self._set_vlan(vm.host_ip, vm.tap_interface, vlan_id)

            if enable_dhcp:
                self._setup_dhcp(vms[0].host_ip, vlan_id, subnet)

            if enable_internet:
                self._setup_internet(vms[0].host_ip, vlan_id)

            time.sleep(1)
            logger.info("Network configured for slice %s", slice_obj.name)
            return True

        except Exception as e:
            logger.error("Failed to setup network for slice %s: %s",
                         slice_obj.name, e)
            return False

    def teardown_slice_network(self, vms: List[VM], vlan_id: int) -> bool:
        hosts_involved = list(set(vm.host_ip for vm in vms if vm.host_ip))
        try:
            for vm in vms:
                if vm.tap_interface and vm.host_ip:
                    client = self._connect(vm.host_ip)
                    self._exec(client,
                               f"ovs-vsctl del-port {self.OVS_BRIDGE} {vm.tap_interface} 2>/dev/null")
                    client.close()
            if hosts_involved and vlan_id:
                self._cleanup_dhcp(hosts_involved[0], vlan_id)
            return True
        except Exception as e:
            logger.error("Failed to teardown network: %s", e)
            return False

    def configure_topology_links(self, vms: List[VM], links: List[Tuple[int, int]],
                                 vlan_id: int) -> bool:
        """
        Links between VMs are achieved implicitly via OVS:
          - All VMs in the same slice share the same VLAN.
          - OVS bridge forwards traffic within the VLAN.
          - The topology defines which VMs are "allowed" to communicate
            (enforced via OpenFlow rules or just documented logically).

        For Phase 1, we use VLAN isolation (all VMs in VLAN can communicate).
        Advanced filtering (OpenFlow rules per link) can be added in Phase 2.
        """
        logger.info("Topology links configured via VLAN %d (all-to-all on VLAN)", vlan_id)
        return True

    def _ensure_bridge(self, host_ip: str):
        client = self._connect(host_ip)
        out = self._exec(client, f"ovs-vsctl br-exists {self.OVS_BRIDGE}")
        if "true" not in out.lower():
            self._exec(client, f"ovs-vsctl add-br {self.OVS_BRIDGE}")
            logger.info("Created OVS bridge %s on %s", self.OVS_BRIDGE, host_ip)
        client.close()

    def _set_vlan(self, host_ip: str, tap_name: str, vlan_id: int):
        client = self._connect(host_ip)
        cmd = f"ovs-vsctl set port {tap_name} tag={vlan_id} 2>/dev/null"
        self._exec(client, cmd)
        client.close()

    def _setup_dhcp(self, host_ip: str, vlan_id: int, subnet: str):
        client = self._connect(host_ip)

        self._exec(client, f"ip netns add dnsmasq-vlan{vlan_id} 2>/dev/null")

        self._exec(client, (
            f"ovs-vsctl add-port {self.OVS_BRIDGE} dhcp-vlan{vlan_id} "
            f"-- set interface dhcp-vlan{vlan_id} type=internal "
            f" 2>/dev/null"
        ))
        self._exec(client, f"ip link set dhcp-vlan{vlan_id} netns dnsmasq-vlan{vlan_id} 2>/dev/null")
        self._exec(client, f"ip netns exec dnsmasq-vlan{vlan_id} ip link set dhcp-vlan{vlan_id} up")
        self._exec(client, f"ip netns exec dnsmasq-vlan{vlan_id} ip addr add {subnet.split('.')[0]}.{subnet.split('.')[1]}.{subnet.split('.')[2]}.1/24 dev dhcp-vlan{vlan_id}")

        self._exec(client,
                   f"pkill -f 'dnsmasq.*dnsmasq-vlan{vlan_id}' 2>/dev/null")
        self._exec(client, (
            f"ip netns exec dnsmasq-vlan{vlan_id} "
            f"dnsmasq "
            f"--interface=dhcp-vlan{vlan_id} "
            f"--dhcp-range={subnet.split('.')[0]}.{subnet.split('.')[1]}.{subnet.split('.')[2]}.100,"
            f"{subnet.split('.')[0]}.{subnet.split('.')[1]}.{subnet.split('.')[2]}.200,255.255.255.0,12h "
            f"--no-resolv "
            f"--server=8.8.8.8 "
            f"--pid-file=/tmp/dnsmasq-vlan{vlan_id}.pid"
        ))

        logger.info("DHCP configured for VLAN %d on %s", vlan_id, host_ip)
        client.close()

    def _setup_internet(self, host_ip: str, vlan_id: int):
        client = self._connect(host_ip)
        self._exec(client, (
            f"iptables -t nat -A POSTROUTING "
            f"-s {10}.{60}.{3}.0/24 "
            f"-o eth0 -j MASQUERADE 2>/dev/null"
        ))
        self._exec(client, "sysctl -w net.ipv4.ip_forward=1 2>/dev/null")
        logger.info("Internet access enabled for VLAN %d", vlan_id)
        client.close()

    def _cleanup_dhcp(self, host_ip: str, vlan_id: int):
        client = self._connect(host_ip)
        self._exec(client, f"pkill -f 'dnsmasq.*dnsmasq-vlan{vlan_id}' 2>/dev/null")
        self._exec(client, f"ip netns delete dnsmasq-vlan{vlan_id} 2>/dev/null")
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
        return out
