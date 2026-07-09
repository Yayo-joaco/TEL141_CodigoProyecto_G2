# ==============================================================
# Gateway Manager - Routes the OpenStack external range
# (10.60.4.0/24) from the VPN gateway to the OpenStack headnode,
# so VMs with enable_internet=True are directly SSH-reachable
# over VPN. Global, one-time infrastructure setup — invoked via
# scripts/setup_gateway_routing.py, never on the per-slice path.
# ==============================================================

import logging

import paramiko

logger = logging.getLogger("orchestrator.networking.gateway")


class GatewayManager:
    """Idempotent setup of IP forwarding + routing + NAT on the VPN
    gateway host so it can reach the OpenStack external subnet via
    the OpenStack headnode. Mirrors NetworkManager._connect()/_exec()."""

    def __init__(self, gateway_ip: str, ssh_key_path: str = "/home/ubuntu/.ssh/id_rsa",
                 ssh_user: str = "ubuntu",
                 openstack_headnode_ip: str = "192.168.202.1"):
        self.gateway_ip = gateway_ip
        self.ssh_key_path = ssh_key_path
        self.ssh_user = ssh_user
        self.openstack_headnode_ip = openstack_headnode_ip

    def setup_external_routing(self, ext_cidr: str = "10.60.4.0/24",
                                uplink_iface: str = "ens3"):
        """Idempotent: enable IP forwarding, route ext_cidr via the
        OpenStack headnode, allow FORWARD in both directions, and
        MASQUERADE return traffic on the gateway's uplink interface."""
        client = self._connect(self.gateway_ip)
        try:
            self._exec(client, "sudo sysctl -w net.ipv4.ip_forward=1")
            self._exec(client,
                       "grep -q '^net.ipv4.ip_forward=1' /etc/sysctl.conf || "
                       "echo 'net.ipv4.ip_forward=1' | sudo tee -a /etc/sysctl.conf")
            self._exec(client,
                       f"ip route show {ext_cidr} | grep -q . || "
                       f"sudo ip route add {ext_cidr} via {self.openstack_headnode_ip}")
            self._exec(client,
                       f"sudo iptables -C FORWARD -s {ext_cidr} -j ACCEPT 2>/dev/null || "
                       f"sudo iptables -A FORWARD -s {ext_cidr} -j ACCEPT")
            self._exec(client,
                       f"sudo iptables -C FORWARD -d {ext_cidr} "
                       f"-m state --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || "
                       f"sudo iptables -A FORWARD -d {ext_cidr} "
                       f"-m state --state RELATED,ESTABLISHED -j ACCEPT")
            self._exec(client,
                       f"sudo iptables -t nat -C POSTROUTING -s {ext_cidr} "
                       f"-o {uplink_iface} -j MASQUERADE 2>/dev/null || "
                       f"sudo iptables -t nat -A POSTROUTING -s {ext_cidr} "
                       f"-o {uplink_iface} -j MASQUERADE")
        finally:
            client.close()

    def _connect(self, host_ip: str) -> paramiko.SSHClient:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=host_ip,
            username=self.ssh_user,
            key_filename=self.ssh_key_path,
            timeout=15,
        )
        return client

    def _exec(self, client: paramiko.SSHClient, cmd: str) -> str:
        _, stdout, stderr = client.exec_command(cmd, timeout=30)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        if err and "warning" not in err.lower():
            logger.debug("SSH stderr [%s]: %s", cmd[:60], err.strip())
        return out
