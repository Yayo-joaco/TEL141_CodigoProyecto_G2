#!/usr/bin/env python3
# ==============================================================
# One-time setup: route the OpenStack external subnet
# (10.60.4.0/24) through the VPN gateway to the OpenStack
# headnode, so VMs with enable_internet=True are directly
# SSH-reachable over VPN.
#
# Run manually after the app server's SSH public key
# (hosts.yaml -> ssh.key_path) has been added to the gateway's
# ~ubuntu/.ssh/authorized_keys:
#
#   python3 scripts/setup_gateway_routing.py
#
# This is global infrastructure setup, not part of the per-slice
# deploy path — it is never invoked automatically.
# ==============================================================

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.networking.gateway_manager import GatewayManager

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def main():
    with open(CONFIG_DIR / "hosts.yaml", "r") as f:
        hosts_cfg = yaml.safe_load(f)
    with open(CONFIG_DIR / "network.yaml", "r") as f:
        net_cfg = yaml.safe_load(f)

    gateway_cfg = hosts_cfg.get("gateway")
    if not gateway_cfg:
        print("ERROR: no 'gateway' section found in config/hosts.yaml", file=sys.stderr)
        sys.exit(1)

    ssh_key_path = hosts_cfg.get("ssh", {}).get("key_path", "/home/ubuntu/.ssh/id_rsa")
    openstack_headnode_ip = hosts_cfg["openstack_cluster"]["headnode"]["ip"]
    ext_cidr = net_cfg["openstack"]["external_network"]["cidr"]

    manager = GatewayManager(
        gateway_ip=gateway_cfg["ip"],
        ssh_key_path=ssh_key_path,
        ssh_user=gateway_cfg.get("user", "ubuntu"),
        openstack_headnode_ip=openstack_headnode_ip,
    )

    print(f"Setting up routing on gateway {gateway_cfg['ip']} for {ext_cidr} "
          f"via headnode {openstack_headnode_ip}...")
    manager.setup_external_routing(ext_cidr=ext_cidr)
    print("Done. Verify with: ssh ubuntu@<10.60.4.x> from a VPN-connected machine.")


if __name__ == "__main__":
    main()
