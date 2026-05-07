# ==============================================================
# Flask UI v2 - Complete RBAC + Sessions + Edit + Templates
# ==============================================================

import json
import logging
import os
import sys
import uuid
import threading
from functools import wraps
from pathlib import Path

import yaml
from flask import (
    Flask, render_template, request, redirect, url_for,
    jsonify, make_response, session, flash, send_file,
)
from werkzeug.security import generate_password_hash, check_password_hash

from gevent import monkey; monkey.patch_all()
import gevent
from gevent.pywsgi import WSGIServer
from geventwebsocket.handler import WebSocketHandler
from geventwebsocket import WebSocketError
import websocket as ws_client

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.orchestrator import Orchestrator
from src.models.host import Host, HostRole
from src.models.user import Role
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
app.secret_key = "pucp-cloud-orchestrator-2026-g2-session"
CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"


def load_configs():
    with open(CONFIG_DIR / "hosts.yaml", "r") as f:
        hosts_cfg = yaml.safe_load(f)
    with open(CONFIG_DIR / "database.yaml", "r") as f:
        db_cfg = yaml.safe_load(f)
    with open(CONFIG_DIR / "network.yaml", "r") as f:
        net_cfg = yaml.safe_load(f)
    return hosts_cfg, db_cfg, net_cfg


_orchestrator = None


def get_orchestrator():
    global _orchestrator
    if _orchestrator is None:
        hosts_cfg, db_cfg, net_cfg = load_configs()
        hosts = []
        headnode = hosts_cfg["headnode"]
        hosts.append(Host(hostname=headnode["hostname"], ip=headnode["ip"],
                          role=HostRole.HEADNODE, port=headnode["port"]))
        for w in hosts_cfg["workers"]:
            hosts.append(Host(hostname=w["hostname"], ip=w["ip"],
                             role=HostRole.WORKER, port=w["port"]))
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
        _orchestrator = Orchestrator(hosts=hosts, driver=driver,
                                     network=network, db=db,
                                     base_image=base_image)
        # Cargar recursos reales de los servidores al iniciar
        result = _orchestrator.refresh_hosts()
        logger.info("Hosts refreshed: %d OK, %d failed",
                     result["refreshed"], len(result.get("failed", [])))
    return _orchestrator


# =============================================================
# Auth decorators
# =============================================================

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login_page"))
        if session.get("role") != "admin":
            return render_template("error.html", error="Acceso denegado: se requiere rol Admin"), 403
        return f(*args, **kwargs)
    return decorated


def operator_or_admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login_page"))
        if session.get("role") not in ("admin", "operator"):
            return render_template("error.html", error="Acceso denegado"), 403
        return f(*args, **kwargs)
    return decorated


# =============================================================
# Auth routes
# =============================================================

@app.route("/login", methods=["GET", "POST"])
def login_page():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        if not username or not password:
            return render_template("login.html", error="Usuario y contraseña requeridos")
        orch = get_orchestrator()
        success, result = orch.login(username, password)
        if success and result:
            session["user_id"] = result["user_id"]
            session["username"] = result["username"]
            session["role"] = result["role"]
            session["token"] = result["token"]
            return redirect(url_for("index"))
        return render_template("login.html", error="Credenciales inválidas")
    return render_template("login.html")


@app.route("/logout")
def logout():
    orch = get_orchestrator()
    orch.logout(session.get("user_id", ""))
    session.clear()
    return redirect(url_for("login_page"))


@app.route("/register", methods=["GET", "POST"])
def register_page():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        email = request.form.get("email", "").strip() or None
        role = request.form.get("role", "user")
        if not username or not password:
            return render_template("register.html", error="Todos los campos son requeridos")
        orch = get_orchestrator()
        success, msg = orch.register(username, password, Role(role), email)
        if success:
            return redirect(url_for("login_page"))
        return render_template("register.html", error=msg)
    return render_template("register.html")


# =============================================================
# Main dashboard
# =============================================================

@app.route("/")
@login_required
def index():
    orch = get_orchestrator()
    role = session.get("role", "user")
    username = session.get("username", "")
    role_enum = Role(role) if role else Role.USER

    user_obj = orch.db.get_user_by_username(username)
    slices = orch.list_slices(user=user_obj)
    hosts_status = orch.get_hosts_status()
    templates = orch.list_templates()

    return render_template("index.html",
                           slices=slices, hosts=hosts_status,
                           templates=templates,
                           user_role=role, username=username)


# =============================================================
# Slice operations
# =============================================================

@app.route("/create", methods=["POST"])
@login_required
def create_slice():
    orch = get_orchestrator()
    try:
        name = request.form.get("name", "").strip()
        topology = request.form.get("topology", "lineal")
        num_vms = int(request.form.get("num_vms", "4"))
        vcpus = int(request.form.get("vcpus", "1"))
        ram_mb = int(request.form.get("ram_mb", "512"))
        disk_gb = int(request.form.get("disk_gb", "2"))
        enable_dhcp = request.form.get("enable_dhcp") == "on"
        enable_internet = request.form.get("enable_internet") == "on"

        if not name:
            flash("El nombre del slice es requerido", "error")
            return redirect(url_for("index"))

        result = orch.create_slice(
            name=name, topology=topology, num_vms=num_vms,
            vcpus=vcpus, ram_mb=ram_mb, disk_gb=disk_gb,
            enable_dhcp=enable_dhcp, enable_internet=enable_internet,
            created_by=session.get("username", "admin"),
        )

        if result["success"]:
            orch.refresh_hosts()
            flash(f"Slice '{name}' creado: {num_vms} VMs, VLAN={result.get('vlan_id','?')}, "
                  f"subnet={result.get('subnet','?')}", "success")
        else:
            flash(result.get("error", "Error al crear slice"), "error")
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for("index"))


@app.route("/edit/<slice_id>", methods=["POST"])
@login_required
def edit_slice(slice_id):
    orch = get_orchestrator()
    try:
        add_vms = int(request.form.get("add_vms", "0"))
        remove_vm_ids = request.form.getlist("remove_vms")
        new_vcpus = request.form.get("new_vcpus")
        new_ram_mb = request.form.get("new_ram_mb")
        new_disk_gb = request.form.get("new_disk_gb")

        new_vcpus = int(new_vcpus) if new_vcpus and new_vcpus.strip() else None
        new_ram_mb = int(new_ram_mb) if new_ram_mb and new_ram_mb.strip() else None
        new_disk_gb = int(new_disk_gb) if new_disk_gb and new_disk_gb.strip() else None

        result = orch.edit_slice(
            slice_id=slice_id, add_vms=add_vms,
            remove_vm_ids=remove_vm_ids if remove_vm_ids else None,
            new_vcpus=new_vcpus, new_ram_mb=new_ram_mb,
            new_disk_gb=new_disk_gb,
        )
        if result["success"]:
            orch.refresh_hosts()
        flash(result.get("message", "Slice editado"), "success" if result["success"] else "error")
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for("view_slice", slice_id=slice_id))


@app.route("/slice/<slice_id>")
@login_required
def view_slice(slice_id):
    orch = get_orchestrator()
    info = orch.get_slice(slice_id)
    if not info:
        flash("Slice no encontrado", "error")
        return redirect(url_for("index"))
    logs = orch.get_logs(slice_id)
    return render_template("slice_detail.html",
                           slice=info["slice"], vms=info["vms"],
                           logs=logs, user_role=session.get("role"))


@app.route("/console/<vm_id>")
@login_required
def console_vm(vm_id):
    orch = get_orchestrator()
    vm = orch.db.get_vm_by_id(vm_id)
    if not vm:
        flash("VM no encontrada", "error")
        return redirect(url_for("index"))
    return render_template("console.html", vm=vm.to_dict())


@app.route("/delete/<slice_id>")
@login_required
def delete_slice(slice_id):
    orch = get_orchestrator()
    username = session.get("username", "")
    user_obj = orch.db.get_user_by_username(username)
    result = orch.delete_slice(slice_id, user=user_obj)
    if result["success"]:
        orch.refresh_hosts()
    flash("Slice eliminado" if result["success"] else result.get("error", "Error"), "success")
    return redirect(url_for("index"))


@app.route("/refresh-hosts")
@login_required
def refresh_hosts():
    orch = get_orchestrator()
    result = orch.refresh_hosts()

    for host in orch.hosts:
        vms = orch.db.get_vms_by_host(host.ip)
        active = [v for v in vms if v.status.value == 'active']
        host.vms_running = len(active)
        orch.db.save_host(host)

    flash(f"Hosts actualizados: {result['refreshed']} OK, {len(result.get('failed',[]))} fallaron", "success")
    return redirect(url_for("index"))


# =============================================================
# Template Export/Import
# =============================================================

@app.route("/export/<slice_id>")
@login_required
def export_template_route(slice_id):
    orch = get_orchestrator()
    template = orch.export_template(slice_id)
    if not template:
        flash("Slice no encontrado", "error")
        return redirect(url_for("index"))
    slice_obj = orch.get_slice(slice_id)
    template["name"] = slice_obj["slice"]["name"]
    return jsonify(template)


@app.route("/export-file/<slice_id>")
@login_required
def export_file(slice_id):
    orch = get_orchestrator()
    template = orch.export_template(slice_id)
    if not template:
        flash("Slice no encontrado", "error")
        return redirect(url_for("index"))
    slice_obj = orch.get_slice(slice_id)
    template["name"] = slice_obj["slice"]["name"]
    response = make_response(json.dumps(template, indent=2, ensure_ascii=False))
    response.headers["Content-Type"] = "application/json"
    response.headers["Content-Disposition"] = f"attachment; filename={template['name']}_template.json"
    return response


@app.route("/import", methods=["POST"])
@login_required
def import_template():
    orch = get_orchestrator()
    try:
        if "template_file" in request.files:
            file = request.files["template_file"]
            template_data = json.loads(file.read().decode("utf-8"))
        else:
            template_data = json.loads(request.form.get("template_json", "{}"))
        result = orch.import_template(template_data, created_by=session.get("username", "admin"))
        flash("Slice importado exitosamente" if result["success"] else result.get("error", "Error"), "success")
    except Exception as e:
        flash(f"Error al importar plantilla: {e}", "error")
    return redirect(url_for("index"))


@app.route("/save-template", methods=["POST"])
@login_required
def save_template_route():
    orch = get_orchestrator()
    try:
        name = request.form.get("template_name", "").strip()
        description = request.form.get("description", "").strip()
        config = {
            "topology": request.form.get("topology", "lineal"),
            "num_vms": int(request.form.get("num_vms", "4")),
            "vcpus_per_vm": int(request.form.get("vcpus", "1")),
            "ram_mb_per_vm": int(request.form.get("ram_mb", "512")),
            "disk_gb_per_vm": int(request.form.get("disk_gb", "2")),
            "enable_dhcp": request.form.get("enable_dhcp") == "on",
            "enable_internet": request.form.get("enable_internet") == "on",
        }
        tid = orch.save_template(name, config, description, session.get("username", "admin"))
        flash(f"Plantilla '{name}' guardada", "success")
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for("index"))


@app.route("/delete-template/<template_id>")
@login_required
def delete_template_route(template_id):
    orch = get_orchestrator()
    orch.db.delete_template(template_id)
    flash("Plantilla eliminada", "success")
    return redirect(url_for("index"))


# =============================================================
# Image Management
# =============================================================

@app.route("/images")
@login_required
def images_page():
    orch = get_orchestrator()
    images = orch.list_images()
    return render_template("images.html", images=images, user_role=session.get("role"))


@app.route("/import-image", methods=["POST"])
@login_required
def import_image_route():
    orch = get_orchestrator()
    try:
        name = request.form.get("image_name", "").strip()
        filename = request.form.get("filename", "").strip()
        path = request.form.get("path", "").strip()
        format = request.form.get("format", "qcow2")
        size_gb = int(request.form.get("size_gb", "2"))
        orch.import_image(name, filename, path, format, size_gb,
                          uploaded_by=session.get("username", "admin"))
        flash(f"Imagen '{name}' importada", "success")
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for("images_page"))


# =============================================================
# Admin Panel
# =============================================================

@app.route("/admin")
@admin_required
def admin_page():
    orch = get_orchestrator()
    users = orch.list_users()
    hosts = orch.get_hosts_status()
    all_slices = orch.list_slices( user=None)
    users_with_role = [u for u in users]
    return render_template("admin.html",
                           users=users_with_role, hosts=hosts,
                           all_slices=all_slices)


@app.route("/admin/users/delete/<user_id>")
@admin_required
def admin_delete_user(user_id):
    orch = get_orchestrator()
    orch.delete_user(user_id)
    flash("Usuario desactivado", "success")
    return redirect(url_for("admin_page"))


@app.route("/admin/users/create", methods=["POST"])
@admin_required
def admin_create_user():
    orch = get_orchestrator()
    try:
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        role = request.form.get("role", "user")
        email = request.form.get("email", "").strip() or None
        success, msg = orch.register(username, password, Role(role), email)
        flash(msg, "success" if success else "error")
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for("admin_page"))


@app.route("/admin/sessions")
@admin_required
def admin_sessions():
    orch = get_orchestrator()
    username = session.get("username", "")
    user_obj = orch.db.get_user_by_username(username)
    active = orch.get_active_sessions(user_obj) if user_obj else []
    return render_template("sessions.html", sessions=active)


# =============================================================
# WebSocket Proxy for VNC Console
# =============================================================

@app.route('/ws-proxy/<vm_id>')
def ws_proxy(vm_id):
    ws = request.environ.get('wsgi.websocket')
    if not ws:
        return jsonify({"error": "WebSocket connection required"}), 400
    orch = get_orchestrator()
    vm = orch.db.get_vm_by_id(vm_id)
    if not vm:
        return jsonify({"error": "VM not found"}), 404
    if not vm.host_ip or not vm.vnc_ws_port:
        return jsonify({"error": "VM not ready"}), 503

    worker_url = f"ws://{vm.host_ip}:{vm.vnc_ws_port}"
    logger = logging.getLogger("ws-proxy")
    logger.info("Proxy: %s -> %s", vm_id, worker_url)

    worker_ws = None
    try:
        worker_ws = ws_client.create_connection(worker_url, timeout=10)
    except Exception as e:
        logger.error("Cannot connect to worker %s: %s", worker_url, e)
        try:
            ws.send(f"ERROR: Cannot reach VM at {worker_url}")
            ws.close()
        except Exception:
            pass
        return ""

    running = {"value": True}

    def browser_to_worker():
        try:
            while running["value"]:
                msg = ws.receive()
                if msg is None:
                    break
                worker_ws.send_binary(msg) if isinstance(msg, bytes) else worker_ws.send(msg)
        except WebSocketError:
            pass
        except Exception as e:
            logger.debug("browser->worker closed: %s", e)
        finally:
            running["value"] = False

    def worker_to_browser():
        try:
            while running["value"]:
                msg = worker_ws.recv()
                if msg is None:
                    break
                ws.send(msg)
        except ws_client.WebSocketConnectionClosedException:
            pass
        except Exception as e:
            logger.debug("worker->browser closed: %s", e)
        finally:
            running["value"] = False

    g1 = gevent.spawn(browser_to_worker)
    g2 = gevent.spawn(worker_to_browser)
    gevent.joinall([g1, g2], timeout=300)

    try:
        worker_ws.close()
    except Exception:
        pass
    try:
        ws.close()
    except Exception:
        pass
    logger.info("Proxy closed: %s", vm_id)
    return ""


# =============================================================
# Run
# =============================================================

if __name__ == "__main__":
    http_server = WSGIServer(('0.0.0.0', 8080), app, handler_class=WebSocketHandler)
    print("PUCP Cloud Orchestrator running on http://0.0.0.0:8080")
    http_server.serve_forever()
