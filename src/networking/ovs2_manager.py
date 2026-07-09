# ==============================================================
# Physical-switch Networking Manager — VLAN pruning via SSH
# Implements R5.6: limit broadcast VLANs to servers that need them
#
# Used for BOTH physical switches in the topology:
#   OVS1 (192.168.201.5) — Linux cluster switch (server1..server4)
#   OVS2 (192.168.202.5) — OpenStack cluster switch (controller, compute1..3)
# Each gets its own OVS2Manager instance with a port map matching its
# actual node hostnames (see config/network.yaml).
#
# VLAN 14 is ALWAYS kept (external/br-provider, internet access).
# ==============================================================

import logging
from typing import Dict, List, Optional, Set

import paramiko

logger = logging.getLogger("orchestrator.ovs2")

# Default ports on OVS2 per OpenStack node hostname (fallback if no
# explicit port_map is passed in).
OVS2_PORT_MAP: Dict[str, str] = {
    "controller": "ens4",
    "headnode":   "ens4",
    "compute1":   "ens5",
    "worker1":    "ens5",
    "compute2":   "ens6",
    "worker2":    "ens6",
    "compute3":   "ens7",
    "worker3":    "ens7",
}

RESERVED_VLANS: List[int] = [14]   # never pruned — external/internet VLAN


class OVS2Manager:
    """
    Manages trunk VLAN lists on a physical OVS switch via SSH.

    Each time a slice is deployed or deleted, call add_slice_vlans()/
    remove_slice_vlans() to recompute which VLANs each trunk port
    carries, then push the changes with a single SSH session.
    """

    def __init__(self, ovs2_ip: str, ssh_key_path: str,
                 ssh_user: str = "ubuntu",
                 port_map: Optional[Dict[str, str]] = None,
                 reserved_vlans: Optional[List[int]] = None,
                 headnode_hostname: str = "controller"):
        self.ovs2_ip = ovs2_ip
        self.ssh_key_path = ssh_key_path
        self.ssh_user = ssh_user
        self.port_map: Dict[str, str] = port_map or OVS2_PORT_MAP
        self.reserved_vlans: List[int] = (
            reserved_vlans if reserved_vlans is not None else RESERVED_VLANS
        )
        # Hostname (key in port_map) whose port always carries every VLAN
        # (Neutron DHCP/L3 agent runs there, or it's the Linux headnode).
        self.headnode_hostname = headnode_hostname
        # In-memory state: port → set of active VLANs (besides reserved)
        self._port_vlans: Dict[str, Set[int]] = {
            p: set() for p in set(self.port_map.values())
        }

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def add_slice_vlans(self, vlan_ids: List[int], worker_hostnames: List[str]):
        """
        Register VLANs for a new slice and push updated trunks to OVS2.
        vlan_ids       — list of VLANs used by this slice's links
        worker_hostnames — compute nodes that host VMs of this slice
        """
        ports = self._hostnames_to_ports(worker_hostnames)
        # headnode always needs every VLAN (Neutron DHCP / L3 agent)
        headnode_port = self.port_map.get(self.headnode_hostname)
        if headnode_port:
            ports.add(headnode_port)

        for port in ports:
            self._port_vlans.setdefault(port, set()).update(vlan_ids)

        self._push_all_trunks()
        logger.info("OVS2 (%s): added VLANs %s to ports %s", self.ovs2_ip, vlan_ids, list(ports))

    def remove_slice_vlans(self, vlan_ids: List[int], worker_hostnames: List[str]):
        """
        Deregister VLANs after a slice is deleted and push updated trunks.
        Only removes a VLAN from a port if no other active slice uses it there.
        """
        ports = self._hostnames_to_ports(worker_hostnames)
        headnode_port = self.port_map.get(self.headnode_hostname)
        if headnode_port:
            ports.add(headnode_port)

        for port in ports:
            self._port_vlans.get(port, set()).difference_update(vlan_ids)

        self._push_all_trunks()
        logger.info("OVS2 (%s): removed VLANs %s from ports %s", self.ovs2_ip, vlan_ids, list(ports))

    def update_trunk_vlans(self, port_vlan_map: Dict[str, List[int]]):
        """
        Full replacement: set exact VLAN lists per port and push.
        port_vlan_map: {port_name → [vlan_id, ...]}
        """
        for port, vlans in port_vlan_map.items():
            self._port_vlans[port] = set(vlans)
        self._push_all_trunks()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _hostnames_to_ports(self, hostnames: List[str]) -> Set[str]:
        ports = set()
        for h in hostnames:
            p = self.port_map.get(h)
            if p:
                ports.add(p)
        return ports

    def _build_trunks_str(self, port: str) -> str:
        vlans = sorted(self.reserved_vlans + list(self._port_vlans.get(port, set())))
        return ",".join(str(v) for v in vlans)

    def _push_all_trunks(self):
        """SSH into the switch and set trunk lists on all ports in one session."""
        try:
            client = self._connect()
            for port in set(self.port_map.values()):
                trunks = self._build_trunks_str(port)
                cmd = f"sudo ovs-vsctl set port {port} trunks={trunks}"
                self._exec(client, cmd)
                logger.debug("OVS (%s) port %s trunks set to: %s", self.ovs2_ip, port, trunks)
            client.close()
        except Exception as e:
            logger.error("OVS (%s) push failed: %s", self.ovs2_ip, e)

    def _connect(self) -> paramiko.SSHClient:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=self.ovs2_ip,
            username=self.ssh_user,
            key_filename=self.ssh_key_path,
            timeout=15,
        )
        return client

    def _exec(self, client: paramiko.SSHClient, cmd: str) -> str:
        _, stdout, stderr = client.exec_command(cmd, timeout=15)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        if err and "Warning" not in err:
            logger.debug("OVS2 stderr: %s", err.strip())
        return out
