# ==============================================================
# Flask UI - Web interface for PUCP Cloud Orchestrator (R1B)
#
# Requirements covered:
#   R1B - Interfaz de usuario
#     - Create, list, delete slices
#     - Configure slices with predefined topologies
#     - Visualize resource consumption
#     - View console tokens
# ==============================================================

import logging
import os
import sys
import yaml
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.orchestrator import Orchestrator
from src.models.host import Host, HostRole
from src.drivers.linux_driver import LinuxDriver
from src.networking.network_manager import NetworkManager
from src.database.db_manager import DatabaseManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("orchestrator.ui")

app = Flask(__name__)
app.secret_key = "pucp-cloud-orchestrator-2026-g2"

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"


def load_configs():
    with open(CONFIG_DIR / "hosts.yaml", "r") as f:
        hosts_cfg = yaml.safe_load(f)
    with open(CONFIG_DIR / "database.yaml", "r") as f:
        db_cfg = yaml.safe_load(f)
    with open(CONFIG_DIR / "network.yaml", "r") as f:
        net_cfg = yaml.safe_load(f)
    return hosts_cfg, db_cfg, net_cfg


def init_orchestrator():
    hosts_cfg, db_cfg, net_cfg = load_configs()

    hosts = []
    headnode = hosts_cfg["headnode"]
    hosts.append(Host(
        hostname=headnode["hostname"],
        ip=headnode["ip"],
        role=HostRole.HEADNODE,
        port=headnode["port"],
    ))
    for w in hosts_cfg["workers"]:
        hosts.append(Host(
            hostname=w["hostname"],
            ip=w["ip"],
            role=HostRole.WORKER,
            port=w["port"],
        ))

    db = DatabaseManager(
        user=db_cfg["database"]["user"],
        password=db_cfg["database"]["password"],
        host=db_cfg["database"]["host"],
        port=db_cfg["database"]["port"],
        database=db_cfg["database"]["database"],
    )

    for host in hosts:
        db.save_host(host)

    ssh_key = hosts_cfg["ssh"].get("key_path", "/home/ubuntu/.ssh/id_rsa")
    driver = LinuxDriver(ssh_key_path=ssh_key)
    network = NetworkManager(ssh_key_path=ssh_key)
    base_image = hosts_cfg["base_image"]["path"]

    orchestrator = Orchestrator(
        hosts=hosts,
        driver=driver,
        network=network,
        db=db,
        base_image=base_image,
    )

    return orchestrator


orchestrator = None


def get_orchestrator():
    global orchestrator
    if orchestrator is None:
        orchestrator = init_orchestrator()
    return orchestrator


@app.route("/")
def index():
    orch = get_orchestrator()
    slices = orch.list_slices()
    hosts_status = orch.get_hosts_status()
    return render_template("index.html", slices=slices, hosts=hosts_status)


@app.route("/create", methods=["POST"])
def create_slice():
    orch = get_orchestrator()
    try:
        name = request.form.get("name", "").strip()
        topology = request.form.get("topology", "lineal")
        num_vms = int(request.form.get("num_vms", "4"))
        vcpus = int(request.form.get("vcpus", "1"))
        ram_mb = int(request.form.get("ram_mb", "512"))
        disk_gb = int(request.form.get("disk_gb", "2"))
        vlan_id = int(request.form.get("vlan_id", "300"))
        subnet = request.form.get("subnet", "10.60.3.0/24")
        enable_dhcp = request.form.get("enable_dhcp") == "on"
        enable_internet = request.form.get("enable_internet") == "on"

        if not name:
            return render_template("index.html",
                                   slices=orch.list_slices(),
                                   hosts=orch.get_hosts_status(),
                                   message="El nombre del slice es requerido",
                                   message_type="alert-error")

        result = orch.create_slice(
            name=name, topology=topology, num_vms=num_vms,
            vcpus=vcpus, ram_mb=ram_mb, disk_gb=disk_gb,
            vlan_id=vlan_id, subnet=subnet,
            enable_dhcp=enable_dhcp, enable_internet=enable_internet,
        )

        slices = orch.list_slices()
        hosts_status = orch.get_hosts_status()

        if result["success"]:
            return render_template("index.html",
                                   slices=slices, hosts=hosts_status,
                                   message=f"Slice '{name}' creado con {num_vms} VMs",
                                   message_type="alert-success")
        else:
            return render_template("index.html",
                                   slices=slices, hosts=hosts_status,
                                   message=result.get("error", "Error al crear slice"),
                                   message_type="alert-error")
    except Exception as e:
        orch = get_orchestrator()
        return render_template("index.html",
                               slices=orch.list_slices(),
                               hosts=orch.get_hosts_status(),
                               message=f"Error: {e}",
                               message_type="alert-error")


@app.route("/slice/<slice_id>")
def view_slice(slice_id):
    orch = get_orchestrator()
    info = orch.get_slice(slice_id)
    if not info:
        return redirect(url_for("index"))
    logs = orch.get_logs(slice_id)
    return render_template("slice_detail.html",
                           slice=info["slice"],
                           vms=info["vms"],
                           logs=logs)


@app.route("/delete/<slice_id>")
def delete_slice(slice_id):
    orch = get_orchestrator()
    result = orch.delete_slice(slice_id)
    slices = orch.list_slices()
    hosts_status = orch.get_hosts_status()
    if result["success"]:
        return render_template("index.html",
                               slices=slices, hosts=hosts_status,
                               message=f"Slice eliminado",
                               message_type="alert-success")
    else:
        return render_template("index.html",
                               slices=slices, hosts=hosts_status,
                               message="Error al eliminar slice",
                               message_type="alert-error")


if __name__ == "__main__":
    ports = yaml.safe_load(open(CONFIG_DIR / "hosts.yaml"))
    headnode_port = ports.get("headnode", {}).get("port", 22)
    app.run(host="0.0.0.0", port=8080, debug=False)
