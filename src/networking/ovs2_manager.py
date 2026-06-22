# ==============================================================
# OVS2 Networking Manager — VLAN pruning via SSH on OVS2
# Implements R5.6: limit broadcast VLANs to servers that need them
#
# OVS2 (192.168.202.5) trunk port → node mapping:
#   ens4 → headnode/controller (192.168.202.1)
#   ens5 → compute1/worker1   (192.168.202.2)
#   ens6 → compute2/worker2   (192.168.202.3)
#   ens7 → compute3/worker3   (192.168.202.4)
#
# VLAN 14 is ALWAYS kept (external/br-provider, internet access).
# ==============================================================

import logging
from typing import Dict, List, Set

import paramiko

logger = logging.getLogger("orchestrator.ovs2")

# Ports on OVS2 per node hostname
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
    Manages trunk VLAN lists on OVS2 via SSH.

    Each time a slice is deployed or deleted, call update_trunk_vlans()
    to recompute which VLANs each trunk port carries, then push the
    changes to OVS2 with a single SSH session.
    """

    def __init__(self, ovs2_ip: str, ssh_key_path: str,
                 ssh_user: str = "ubuntu"):
        self.ovs2_ip = ovs2_ip
        self.ssh_key_path = ssh_key_path
        self.ssh_user = ssh_user
        # In-memory state: port → set of active VLANs (besides reserved)
        self._port_vlans: Dict[str, Set[int]] = {
            p: set() for p in set(OVS2_PORT_MAP.values())
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
        ports.add(OVS2_PORT_MAP["controller"])

        for port in ports:
            self._port_vlans.setdefault(port, set()).update(vlan_ids)

        self._push_all_trunks()
        logger.info("OVS2: added VLANs %s to ports %s", vlan_ids, list(ports))

    def remove_slice_vlans(self, vlan_ids: List[int], worker_hostnames: List[str]):
        """
        Deregister VLANs after a slice is deleted and push updated trunks.
        Only removes a VLAN from a port if no other active slice uses it there.
        """
        ports = self._hostnames_to_ports(worker_hostnames)
        ports.add(OVS2_PORT_MAP["controller"])

        for port in ports:
            self._port_vlans.get(port, set()).difference_update(vlan_ids)

        self._push_all_trunks()
        logger.info("OVS2: removed VLANs %s from ports %s", vlan_ids, list(ports))

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
            p = OVS2_PORT_MAP.get(h)
            if p:
                ports.add(p)
        return ports

    def _build_trunks_str(self, port: str) -> str:
        vlans = sorted(RESERVED_VLANS + list(self._port_vlans.get(port, set())))
        return ",".join(str(v) for v in vlans)

    def _push_all_trunks(self):
        """SSH into OVS2 and set trunk lists on all ports in one session."""
        try:
            client = self._connect()
            for port in set(OVS2_PORT_MAP.values()):
                trunks = self._build_trunks_str(port)
                cmd = f"sudo ovs-vsctl set port {port} trunks={trunks}"
                self._exec(client, cmd)
                logger.debug("OVS2 port %s trunks set to: %s", port, trunks)
            client.close()
        except Exception as e:
            logger.error("OVS2 push failed: %s", e)

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
