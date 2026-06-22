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
    jsonify, make_response, session, flash, send_file, abort,
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
    os_cfg = {}
    os_yaml = CONFIG_DIR / "openstack.yaml"
    if os_yaml.exists():
        with open(os_yaml, "r") as f:
            os_cfg = yaml.safe_load(f) or {}
    return hosts_cfg, db_cfg, net_cfg, os_cfg


_orchestrator = None


def get_orchestrator():
    global _orchestrator
    if _orchestrator is None:
        hosts_cfg, db_cfg, net_cfg, os_cfg = load_configs()
        hosts = []
        linux = hosts_cfg.get("linux_cluster", hosts_cfg)
        headnode = linux.get("headnode", hosts_cfg.get("headnode", {}))
        workers_cfg = linux.get("workers", hosts_cfg.get("workers", []))
        hosts.append(Host(hostname=headnode["hostname"], ip=headnode["ip"],
                          role=HostRole.HEADNODE, port=headnode.get("port", 22)))
        for w in workers_cfg:
            hosts.append(Host(hostname=w["hostname"], ip=w["ip"],
                             role=HostRole.WORKER, port=w.get("port", 22)))
        db = DatabaseManager(
            user=db_cfg["database"]["user"],
            password=db_cfg["database"]["password"],
            host=db_cfg["database"]["host"],
            port=db_cfg["database"]["port"],
            database=db_cfg["database"]["database"],
        )
        for host in hosts:
            db.save_host(host)
        ssh_key = hosts_cfg.get("ssh", {}).get("key_path", "/home/ubuntu/.ssh/id_rsa")
        driver = LinuxDriver(ssh_key_path=ssh_key)
        trunk_port = net_cfg.get("linux", {}).get("ovs", {}).get("trunk_port") \
                     or net_cfg.get("ovs", {}).get("trunk_port", "ens4")
        nat_iface = net_cfg.get("linux", {}).get("internet", {}).get("nat_interface") \
                    or net_cfg.get("internet", {}).get("nat_interface", "ens3")
        network = NetworkManager(ssh_key_path=ssh_key,
                                 headnode_ip=headnode["ip"],
                                 trunk_port=trunk_port,
                                 nat_iface=nat_iface)
        base_image = hosts_cfg.get("base_image", {}).get("path", "/home/ubuntu/cirros-base.img")

        ovs2_ip = net_cfg.get("openstack", {}).get("ovs2", {}).get("ip") \
                  or hosts_cfg.get("openstack_cluster", {}).get("ovs", {}).get("ip")
        _orchestrator = Orchestrator(
            hosts=hosts, driver=driver, network=network, db=db,
            base_image=base_image,
            openstack_cfg=os_cfg,
            ovs2_ip=ovs2_ip,
            ovs2_ssh_key=ssh_key,
        )
        # Asegurar que la imagen de Ubuntu esté registrada
        img_list = db.list_images()
        ubuntu_exists = any(i["name"] == "ubuntu" for i in img_list)
        if not ubuntu_exists:
            db.save_image("ubuntu", "ubuntu-server.qcow2",
                         "/home/ubuntu/ubuntu-server.qcow2",
                         "qcow2", 3, "admin")
        cirros_exists = any(i["name"] == "cirros" for i in img_list)
        if not cirros_exists:
            db.save_image("cirros", "cirros-base.img",
                         base_image,
                         "qcow2", 1, "admin")
        # Cargar recursos reales de los servidores al iniciar
        result = _orchestrator.refresh_hosts()
        logger.info("Hosts refreshed: %d OK, %d failed",
                     result["refreshed"], len(result.get("failed", [])))
        # Seed demo users for Phase 2 demo
        _orchestrator.auth.seed_demo_users()
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
    # If Nueva UI dist is built, let the SPA handle login
    index = _os.path.join(_UI_DIST, "index.html")
    if request.method == "GET" and _os.path.exists(index):
        return send_file(index)
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
    """Vista principal: lista de slices para todos los roles."""
    orch = get_orchestrator()
    role = session.get("role", "user")
    username = session.get("username", "")
    user_obj = orch.db.get_user_by_username(username)

    if role == "admin":
        slices = orch.list_slices(user=None)
    else:
        slices = orch.list_slices(user=user_obj)

    hosts = orch.get_hosts_status() if role == "admin" else []

    return render_template("slices.html",
                           all_slices=slices,
                           hosts=hosts,
                           user_role=role,
                           username=username)


@app.route("/crear-slice")
@login_required
def crear_slice_page():
    """Formulario de creación de slices."""
    orch = get_orchestrator()
    role = session.get("role", "user")
    username = session.get("username", "")
    hosts_status = orch.get_hosts_status()
    templates = orch.list_templates()
    return render_template("crear_slice.html",
                           hosts=hosts_status,
                           templates=templates,
                           user_role=role,
                           username=username)


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

        vms_internet_str = request.form.get("vms_internet", "")
        vms_internet = [int(x.strip()) for x in vms_internet_str.split(",") if x.strip().isdigit()]

        vms_image = {}
        for key in request.form:
            if key.startswith("vm_image_"):
                vm_num = key.replace("vm_image_", "")
                vms_image[vm_num] = request.form[key]

        if not name:
            flash("El nombre del slice es requerido", "error")
            return redirect(url_for("crear_slice_page"))

        result = orch.create_slice_async(
            name=name, topology=topology, num_vms=num_vms,
            vcpus=vcpus, ram_mb=ram_mb, disk_gb=disk_gb,
            enable_dhcp=enable_dhcp, enable_internet=enable_internet,
            created_by=session.get("username", "admin"),
            vms_internet=vms_internet, vms_image=vms_image,
        )
        return redirect(url_for("task_status_page", ticket_id=result,
                                next=url_for("index")))
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for("index"))


@app.route("/edit/<slice_id>", methods=["POST"])
@login_required
def edit_slice(slice_id):
    orch = get_orchestrator()
    try:
        username = session.get("username", "")
        user_obj = orch.db.get_user_by_username(username)
        info = orch.get_slice(slice_id)
        if not info:
            flash("Slice no encontrado", "error")
            return redirect(url_for("index"))
        if user_obj and not user_obj.can_view_all_slices() and info["slice"]["created_by"] != username:
            flash("No tienes permiso para editar este slice", "error")
            return redirect(url_for("index"))

        add_vms = int(request.form.get("add_vms", "0"))
        remove_vm_ids = request.form.getlist("remove_vms")
        new_vcpus = request.form.get("new_vcpus")
        new_ram_mb = request.form.get("new_ram_mb")
        new_disk_gb = request.form.get("new_disk_gb")

        new_vcpus = int(new_vcpus) if new_vcpus and new_vcpus.strip() else None
        new_ram_mb = int(new_ram_mb) if new_ram_mb and new_ram_mb.strip() else None
        new_disk_gb = int(new_disk_gb) if new_disk_gb and new_disk_gb.strip() else None

        new_vms_image = {}
        for key in request.form:
            if key.startswith("vm_image_"):
                vm_num = key.replace("vm_image_", "")
                new_vms_image[vm_num] = request.form[key]
        # new_vm_image_all applies the same image to all new VMs
        image_all = request.form.get("new_vm_image_all", "").strip()
        if image_all and add_vms > 0:
            current_vms = orch.db.get_vms_for_slice(slice_id)
            current_count = len([v for v in current_vms if v.status != "deleted"])
            for i in range(add_vms):
                vm_num = str(current_count + i + 1)
                if vm_num not in new_vms_image:
                    new_vms_image[vm_num] = image_all

        new_vms_internet_str = request.form.get("new_vms_internet", "")
        new_vms_internet = [int(x.strip()) for x in new_vms_internet_str.split(",") if x.strip().isdigit()]

        result = orch.edit_slice_async(
            slice_id=slice_id, add_vms=add_vms,
            remove_vm_ids=remove_vm_ids if remove_vm_ids else None,
            new_vcpus=new_vcpus, new_ram_mb=new_ram_mb,
            new_disk_gb=new_disk_gb, user=user_obj,
            new_vms_image=new_vms_image if new_vms_image else None,
            new_vms_internet=new_vms_internet if new_vms_internet else None,
            ext_topology=request.form.get("ext_topology", "lineal").strip() or None,
            anchor_vm_hint=request.form.get("anchor_vm_hint", "").strip() or None,
        )
        return redirect(url_for("task_status_page", ticket_id=result,
                                next=url_for("view_slice", slice_id=slice_id)))
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for("view_slice", slice_id=slice_id))


@app.route("/slice/<slice_id>")
@login_required
def view_slice(slice_id):
    orch = get_orchestrator()
    username = session.get("username", "")
    user_obj = orch.db.get_user_by_username(username)
    info = orch.get_slice(slice_id)
    if not info:
        flash("Slice no encontrado", "error")
        return redirect(url_for("index"))
    if user_obj and not user_obj.can_view_all_slices() and info["slice"]["created_by"] != username:
        flash("No tienes permiso para ver este slice", "error")
        return redirect(url_for("index"))
    logs = orch.get_logs(slice_id)
    return render_template("slice_detail.html",
                           slice=info["slice"], vms=info["vms"],
                           logs=logs, user_role=session.get("role"),
                           username=username,
                           can_manage_slice=bool(user_obj and (user_obj.can_view_all_slices() or info["slice"]["created_by"] == username)))


@app.route("/api/slice/<slice_id>/vms")
@login_required
def api_slice_vms(slice_id):
    orch = get_orchestrator()
    vms = orch.db.get_vms_for_slice(slice_id)
    return jsonify({"vms": [v.to_dict() for v in vms]})


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
    ticket_id = orch.delete_slice_async(slice_id, user=user_obj)
    return redirect(url_for("task_status_page", ticket_id=ticket_id,
                            next=url_for("index")))


@app.route("/refresh-hosts")
@login_required
def refresh_hosts():
    orch = get_orchestrator()
    result = orch.refresh_hosts()

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
    return render_template("images.html", images=images, user_role=session.get("role"),
                           username=session.get("username", ""))


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
    return redirect(url_for("index"))


@app.route("/slices")
@login_required
def slices_page():
    """Redirige a / que ahora es la lista de slices."""
    return redirect(url_for("index"))


@app.route("/admin/users/delete/<user_id>")
@admin_required
def admin_delete_user(user_id):
    orch = get_orchestrator()
    orch.delete_user(user_id)
    flash("Usuario desactivado", "success")
    return redirect(url_for("index"))


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
    return redirect(url_for("slices_page"))


@app.route("/admin/hosts/add", methods=["POST"])
@admin_required
def admin_add_host():
    orch = get_orchestrator()
    try:
        hostname = request.form.get("hostname", "").strip()
        ip = request.form.get("ip", "").strip()
        port = int(request.form.get("port", "22"))
        role = request.form.get("role", "worker")
        if not hostname or not ip:
            flash("Hostname e IP son requeridos", "error")
            return redirect(url_for("index"))
        result = orch.add_host(hostname, ip, port, role,
                               added_by=session.get("username", "admin"))
        flash(
            f"Host {hostname} ({ip}) agregado: {result.get('vcpus', '?')} vCPUs, "
            f"{result.get('ram_mb', '?')} MB RAM"
            if result["success"] else result.get("error", "Error"),
            "success" if result["success"] else "error"
        )
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for("index"))


@app.route("/admin/hosts/remove/<hostname>")
@admin_required
def admin_remove_host(hostname):
    orch = get_orchestrator()
    result = orch.remove_host(hostname, removed_by=session.get("username", "admin"))
    flash(
        f"Host {hostname} removido del cluster"
        if result["success"] else result.get("error", "Error"),
        "success" if result["success"] else "error"
    )
    return redirect(url_for("index"))


# =============================================================
# Task Queue - Polling endpoints (R1.4, R1.6, R1.7)
# =============================================================

@app.route("/api/task/<ticket_id>")
@login_required
def api_task_status(ticket_id):
    orch = get_orchestrator()
    task = orch.get_task_status(ticket_id)
    if not task:
        return jsonify({"error": "not_found"}), 404
    return jsonify(task)


@app.route("/task/<ticket_id>")
@login_required
def task_status_page(ticket_id):
    redirect_url = request.args.get("next", url_for("index"))
    return render_template("task_status.html",
                           ticket_id=ticket_id,
                           redirect_url=redirect_url,
                           user_role=session.get("role", ""),
                           username=session.get("username", ""))


@app.route("/admin/sessions")
@admin_required
def admin_sessions():
    orch = get_orchestrator()
    username = session.get("username", "")
    user_obj = orch.db.get_user_by_username(username)
    active = orch.get_active_sessions(user_obj) if user_obj else []
    return render_template("sessions.html", sessions=active,
                           username=username, user_role=session.get("role", ""))


# =============================================================
# WebSocket Proxy for VNC Console
# =============================================================

@app.route('/ws-proxy/<vm_id>')
def ws_proxy(vm_id):
    wsock = request.environ.get('wsgi.websocket')
    if not wsock:
        abort(400, 'WebSocket requerido')

    orch = get_orchestrator()
    vm = orch.db.get_vm_by_id(vm_id)
    if not vm:
        abort(404)
    if not vm.host_ip or not vm.vnc_ws_port:
        abort(503)

    target_url = f"ws://{vm.host_ip}:{vm.vnc_ws_port}"
    app.logger.info("WS Proxy START: %s (%s) -> %s", vm.name, vm_id, target_url)

    try:
        subprotocols = request.environ.get('HTTP_SEC_WEBSOCKET_PROTOCOL', '')
        sub_list = [s.strip() for s in subprotocols.split(',')] if subprotocols else []
        if not sub_list:
            sub_list = ['binary', 'base64']
        remote = ws_client.create_connection(
            target_url, timeout=10, subprotocols=sub_list)
    except Exception as e:
        app.logger.error("WS Proxy cannot reach worker %s: %s", target_url, e)
        try:
            wsock.close()
        except Exception:
            pass
        return ''

    app.logger.info("WS Proxy connected to worker: %s", target_url)
    counter = {'b2r': 0, 'r2b': 0}

    def browser_to_remote():
        try:
            while True:
                data = wsock.receive()
                if data is None:
                    break
                counter['b2r'] += 1
                if isinstance(data, str):
                    data = data.encode('utf-8')
                if counter['b2r'] <= 2:
                    app.logger.debug("browser->worker msg#%d len=%d", counter['b2r'], len(data))
                remote.send_binary(data)
        except WebSocketError:
            app.logger.debug("browser->worker: WebSocket closed")
        except Exception as e:
            app.logger.debug("browser->worker: %s", e)
        finally:
            try:
                remote.close()
            except Exception:
                pass

    def remote_to_browser():
        try:
            while True:
                data = remote.recv()
                if data is None:
                    break
                counter['r2b'] += 1
                if isinstance(data, str):
                    data = data.encode('utf-8')
                if counter['r2b'] <= 2:
                    app.logger.debug("worker->browser msg#%d len=%d", counter['r2b'], len(data))
                wsock.send(data)
        except WebSocketError:
            app.logger.debug("worker->browser: WebSocket closed")
        except Exception as e:
            app.logger.debug("worker->browser: %s", e)
        finally:
            try:
                wsock.close()
            except Exception:
                pass

    g1 = gevent.spawn(browser_to_remote)
    g2 = gevent.spawn(remote_to_browser)
    gevent.joinall([g1, g2], timeout=600)
    app.logger.info("WS Proxy END: %s (b2r=%d, r2b=%d)", vm.name, counter['b2r'], counter['r2b'])
    return ''


# =============================================================
# REST API — helpers
# =============================================================

def _get_token() -> str:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return session.get("token", "")


def _require_api_auth(required_role=None):
    """Return (user, error_response). error_response is None if ok."""
    orch = get_orchestrator()
    token = _get_token()
    ok, user, msg = orch.validate_request(token, required_role)
    if not ok:
        return None, (jsonify({"error": msg}), 401)
    return user, None


def _slice_to_ui(s: dict, vms: list = None) -> dict:
    """Convert internal slice dict to Nueva UI shape."""
    topo = s.get("topology_ui") or s.get("topology", "linear")
    owner = s.get("created_by", "")
    if "@" not in owner:
        owner = f"{owner}@pucp.pe"
    out = {
        "id": s["id"],
        "name": s["name"],
        "topology": topo,
        "status": _map_slice_status(s.get("status", "pending")),
        "zone": s.get("zone_id") or "AZ-Compute-1",
        "infrastructureTarget": s.get("infrastructure_target", "linux"),
        "flavorId": s.get("flavor_id") or "small",
        "owner": owner,
        "createdAt": (s.get("created_at") or "")[:10],
        "vlan_id": s.get("vlan_id"),
        "subnet": s.get("subnet"),
        "enable_dhcp": s.get("enable_dhcp"),
        "enable_internet": s.get("enable_internet"),
        "num_vms": s.get("num_vms"),
        "error_message": s.get("error_message"),
        "vms": [_vm_to_ui(v) for v in (vms or [])],
        "logs": [],
    }
    return out


def _vm_to_ui(v) -> dict:
    d = v if isinstance(v, dict) else v.to_dict()
    ip = d.get("ip_address_external") or d.get("ip_address") or ""
    status_map = {"active": "running", "pending": "pending", "error": "error",
                  "creating": "pending", "deleting": "stopped", "deleted": "stopped"}
    return {
        "id": d.get("id", ""),
        "name": d.get("name", ""),
        "status": status_map.get(d.get("status", "pending"), "pending"),
        "ip": ip,
        "cpu": d.get("vcpus", 1),
        "ram": round(d.get("ram_mb", 512) / 1024, 1),
        "disk": d.get("disk_gb", 2),
        "host": d.get("host_ip", ""),
        "image": d.get("image", ""),
        "flavorId": d.get("flavor_id") or "small",
        "vnc_port": d.get("vnc_port"),
        "vnc_ws_port": d.get("vnc_ws_port"),
        "openstack_server_id": d.get("openstack_server_id"),
    }


def _map_slice_status(s: str) -> str:
    m = {"active": "running", "creating": "pending", "configuring_network": "pending",
         "placing": "pending", "deleting": "stopped", "deleted": "deleted",
         "error": "error", "pending": "pending"}
    return m.get(s, s)


# =============================================================
# REST API — Auth
# =============================================================

@app.route("/api/auth/login", methods=["POST"])
def api_login():
    data = request.get_json(force=True) or {}
    identifier = data.get("email") or data.get("username", "")
    password = data.get("password", "")
    if not identifier or not password:
        return jsonify({"error": "email/username y password requeridos"}), 400
    orch = get_orchestrator()
    success, result = orch.login(identifier, password)
    if not success:
        return jsonify({"error": "Credenciales inválidas"}), 401
    return jsonify({
        "token": result["token"],
        "user": {
            "email": result.get("email", f"{result['username']}@pucp.pe"),
            "name": result.get("name", result["username"]),
            "role": result["role"],
            "cluster_assignment": result.get("cluster_assignment", "linux"),
        }
    })


@app.route("/api/auth/me")
def api_me():
    user, err = _require_api_auth()
    if err:
        return err
    return jsonify({
        "email": user.email or f"{user.username}@pucp.pe",
        "name": user.username,
        "role": user.role.value,
        "cluster_assignment": getattr(user, "cluster_assignment", "linux"),
    })


@app.route("/api/auth/logout", methods=["POST"])
def api_logout():
    user, _ = _require_api_auth()
    orch = get_orchestrator()
    if user:
        orch.logout(user.id)
    session.clear()
    return jsonify({"ok": True})


# =============================================================
# REST API — Slices
# =============================================================

@app.route("/api/slices", methods=["GET"])
def api_list_slices():
    user, err = _require_api_auth()
    if err:
        return err
    orch = get_orchestrator()
    raw = orch.list_slices(user=None if user.can_view_all_slices() else user)
    result = []
    for s in raw:
        sd = s if isinstance(s, dict) else s.to_dict()
        vms = orch.db.get_vms_for_slice(sd["id"])
        result.append(_slice_to_ui(sd, vms))
    return jsonify(result)


@app.route("/api/slices", methods=["POST"])
def api_create_slice():
    user, err = _require_api_auth()
    if err:
        return err
    data = request.get_json(force=True) or {}

    # Resolve flavor → vcpus/ram_mb/disk_gb
    orch = get_orchestrator()
    flavor_id = data.get("flavorId") or data.get("flavor_id") or "small"
    flavor = orch.db.get_flavor(flavor_id)
    vcpus = data.get("vcpus") or (flavor["vcpus"] if flavor else 1)
    ram_mb = data.get("ram_mb") or ((flavor["ramGb"] * 1024) if flavor else 512)
    disk_gb = data.get("disk_gb") or (flavor["diskGb"] if flavor else 10)

    owner = data.get("owner") or data.get("created_by") or user.email or user.username
    infra = data.get("infrastructureTarget") or data.get("infrastructure_target") or "linux"
    # Non-admin users use their assigned cluster
    if user.role.value == "user":
        infra = getattr(user, "cluster_assignment", "linux")

    ticket_id = orch.create_slice_async(
        name=data.get("name", "slice"),
        topology=data.get("topology", "linear"),
        num_vms=int(data.get("vmCount") or data.get("num_vms", 2)),
        vcpus=int(vcpus), ram_mb=int(ram_mb), disk_gb=int(disk_gb),
        enable_dhcp=data.get("enable_dhcp", False),
        enable_internet=data.get("enable_internet", False),
        created_by=owner,
        vms_internet=data.get("vms_internet", []),
        vms_image=data.get("vms_image", {}),
        infrastructure_target=infra,
        zone_id=data.get("zone") or data.get("zone_id"),
        flavor_id=flavor_id,
    )
    return jsonify({"ticketId": ticket_id}), 202


@app.route("/api/slices/<slice_id>", methods=["GET"])
def api_get_slice(slice_id):
    user, err = _require_api_auth()
    if err:
        return err
    orch = get_orchestrator()
    info = orch.get_slice(slice_id)
    if not info:
        return jsonify({"error": "not found"}), 404
    sd = info["slice"]
    if not user.can_view_all_slices() and sd.get("created_by") != (user.email or user.username):
        return jsonify({"error": "forbidden"}), 403
    vms = info.get("vms", [])
    return jsonify(_slice_to_ui(sd, vms))


@app.route("/api/slices/<slice_id>", methods=["DELETE"])
def api_delete_slice(slice_id):
    user, err = _require_api_auth()
    if err:
        return err
    orch = get_orchestrator()
    ticket_id = orch.delete_slice_async(slice_id, user=user)
    return jsonify({"ticketId": ticket_id}), 202


@app.route("/api/slices/<slice_id>", methods=["PATCH"])
def api_edit_slice(slice_id):
    user, err = _require_api_auth()
    if err:
        return err
    orch = get_orchestrator()
    data = request.get_json(force=True) or {}
    ticket_id = orch.edit_slice_async(
        slice_id=slice_id,
        add_vms=int(data.get("add_vms", 0)),
        remove_vm_ids=data.get("remove_vm_ids"),
        user=user,
    )
    return jsonify({"ticketId": ticket_id}), 202


@app.route("/api/slices/<slice_id>/vms")
def api_slice_vms_json(slice_id):
    user, err = _require_api_auth()
    if err:
        return err
    orch = get_orchestrator()
    vms = orch.db.get_vms_for_slice(slice_id)
    return jsonify([_vm_to_ui(v) for v in vms])


@app.route("/api/slices/<slice_id>/logs")
def api_slice_logs(slice_id):
    user, err = _require_api_auth()
    if err:
        return err
    orch = get_orchestrator()
    logs = orch.db.get_logs_for_slice(slice_id)
    return jsonify([{
        "ts": l.get("created_at", "")[:16].replace("T", " "),
        "message": l.get("message", ""),
        "level": l.get("level", "INFO"),
        "module": l.get("module", ""),
    } for l in logs])


@app.route("/api/slices/<slice_id>/vms/<vm_id>/console")
def api_vm_console(slice_id, vm_id):
    user, err = _require_api_auth()
    if err:
        return err
    orch = get_orchestrator()
    vm = orch.db.get_vm_by_id(vm_id)
    if not vm:
        return jsonify({"error": "VM not found"}), 404
    # For OpenStack VMs, delegate to OpenStack driver
    if getattr(vm, "openstack_server_id", None):
        try:
            from ..drivers.openstack_driver import OpenStackDriver
            os_driver = orch._get_openstack_driver()
            url = os_driver.get_console_url(vm.openstack_server_id)
            return jsonify({"url": url, "type": "novnc"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    # Linux VMs — return websockify info
    return jsonify({
        "url": f"/console/{vm_id}",
        "ws_port": vm.vnc_ws_port,
        "type": "novnc_local",
    })


# =============================================================
# REST API — Flavors
# =============================================================

@app.route("/api/flavors", methods=["GET"])
def api_list_flavors():
    _, err = _require_api_auth()
    if err:
        return err
    orch = get_orchestrator()
    return jsonify(orch.db.list_flavors())


@app.route("/api/flavors", methods=["POST"])
def api_create_flavor():
    user, err = _require_api_auth()
    if err:
        return err
    if user.role.value != "admin":
        return jsonify({"error": "Admin only"}), 403
    data = request.get_json(force=True) or {}
    orch = get_orchestrator()
    import uuid as _uuid
    fid = data.get("id") or data.get("name") or str(_uuid.uuid4())[:8]
    f = orch.db.save_flavor(
        flavor_id=fid,
        name=data.get("name", fid),
        vcpus=int(data.get("vcpus", 1)),
        ram_gb=int(data.get("ramGb", 1)),
        disk_gb=int(data.get("diskGb", 10)),
        description=data.get("description", ""),
    )
    return jsonify(f), 201


@app.route("/api/flavors/<flavor_id>", methods=["DELETE"])
def api_delete_flavor(flavor_id):
    user, err = _require_api_auth()
    if err:
        return err
    if user.role.value != "admin":
        return jsonify({"error": "Admin only"}), 403
    orch = get_orchestrator()
    orch.db.delete_flavor(flavor_id)
    return jsonify({"ok": True})


# =============================================================
# REST API — Images
# =============================================================

@app.route("/api/images", methods=["GET"])
def api_list_images():
    _, err = _require_api_auth()
    if err:
        return err
    orch = get_orchestrator()
    imgs = orch.list_images()
    return jsonify([{
        "id": i["id"], "name": i["name"], "os": i["name"],
        "sizeGB": i.get("size_gb", 0), "uploadedAt": (i.get("created_at") or "")[:10],
        "inUse": True, "format": i.get("format", "qcow2"), "path": i.get("path", ""),
    } for i in imgs])


@app.route("/api/images", methods=["POST"])
def api_create_image():
    user, err = _require_api_auth()
    if err:
        return err
    if user.role.value != "admin":
        return jsonify({"error": "Admin only"}), 403
    data = request.get_json(force=True) or {}
    orch = get_orchestrator()
    result = orch.import_image(
        name=data.get("name", ""),
        filename=data.get("filename", ""),
        path=data.get("path", ""),
        format=data.get("format", "qcow2"),
        size_gb=int(data.get("sizeGB", 2)),
        uploaded_by=user.email or user.username,
    )
    return jsonify(result), 201


# =============================================================
# REST API — Servers / Hosts
# =============================================================

@app.route("/api/servers", methods=["GET"])
def api_list_servers():
    user, err = _require_api_auth()
    if err:
        return err
    orch = get_orchestrator()
    hosts = orch.get_hosts_status()
    return jsonify([{
        "id": h.get("hostname", ""),
        "hostname": h.get("hostname", ""),
        "ip": h.get("ip", ""),
        "cpuTotal": h.get("total_vcpus", 0),
        "cpuUsed": h.get("total_vcpus", 0) - h.get("available_vcpus", 0),
        "ramTotal": round(h.get("total_ram_mb", 0) / 1024),
        "ramUsed": round((h.get("total_ram_mb", 0) - h.get("available_ram_mb", 0)) / 1024),
        "diskTotal": h.get("total_disk_gb", 0),
        "diskUsed": h.get("total_disk_gb", 0) - h.get("available_disk_gb", 0),
        "zone": h.get("zone_id", "AZ-Compute-1"),
        "status": "online" if h.get("is_active") else "offline",
        "vms_running": h.get("vms_running", 0),
        "cluster": h.get("cluster", "linux"),
    } for h in hosts])


# =============================================================
# REST API — Zones
# =============================================================

@app.route("/api/zones", methods=["GET"])
def api_list_zones():
    _, err = _require_api_auth()
    if err:
        return err
    orch = get_orchestrator()
    return jsonify(orch.db.list_zones())


# =============================================================
# REST API — Logs
# =============================================================

@app.route("/api/logs", methods=["GET"])
def api_list_logs():
    user, err = _require_api_auth()
    if err:
        return err
    orch = get_orchestrator()
    raw = orch.db.get_all_logs(limit=200)
    return jsonify([{
        "id": str(i),
        "ts": l.get("created_at", "")[:16].replace("T", " "),
        "severity": l.get("level", "INFO").lower(),
        "sliceId": l.get("slice_id"),
        "user": l.get("user_id"),
        "message": l.get("message", ""),
    } for i, l in enumerate(raw)])


# =============================================================
# REST API — Users (admin)
# =============================================================

@app.route("/api/users", methods=["GET"])
def api_list_users():
    user, err = _require_api_auth()
    if err:
        return err
    if user.role.value not in ("admin", "operator"):
        return jsonify({"error": "forbidden"}), 403
    orch = get_orchestrator()
    users = orch.list_users()
    return jsonify([{
        "id": u.get("id", ""),
        "name": u.get("username", ""),
        "email": u.get("email") or f"{u.get('username', '')}@pucp.pe",
        "role": u.get("role", "user"),
        "status": "active" if u.get("is_active") else "disabled",
        "cluster_assignment": u.get("cluster_assignment", "linux"),
        "slicesCount": 0,
        "createdAt": (u.get("created_at") or "")[:10],
    } for u in users])


@app.route("/api/users", methods=["POST"])
def api_create_user():
    user, err = _require_api_auth()
    if err:
        return err
    if user.role.value != "admin":
        return jsonify({"error": "Admin only"}), 403
    data = request.get_json(force=True) or {}
    orch = get_orchestrator()
    try:
        role = Role(data.get("role", "user"))
    except ValueError:
        role = Role.USER
    success, msg = orch.register(
        username=data.get("username") or data.get("name", ""),
        password=data.get("password", "pucp2026"),
        role=role,
        email=data.get("email"),
        cluster_assignment=data.get("cluster_assignment", "linux"),
    )
    if not success:
        return jsonify({"error": msg}), 400
    return jsonify({"ok": True, "message": msg}), 201


@app.route("/api/users/<user_id>", methods=["DELETE"])
def api_delete_user(user_id):
    user, err = _require_api_auth()
    if err:
        return err
    if user.role.value != "admin":
        return jsonify({"error": "Admin only"}), 403
    orch = get_orchestrator()
    orch.delete_user(user_id)
    return jsonify({"ok": True})


# =============================================================
# REST API — Sessions
# =============================================================

@app.route("/api/sessions", methods=["GET"])
def api_list_sessions():
    user, err = _require_api_auth()
    if err:
        return err
    if user.role.value not in ("admin", "operator"):
        return jsonify({"error": "forbidden"}), 403
    orch = get_orchestrator()
    return jsonify(orch.get_active_sessions(user))


# =============================================================
# REST API — Tasks (async polling)
# =============================================================

@app.route("/api/tasks/<ticket_id>", methods=["GET"])
def api_task_status_json(ticket_id):
    _, err = _require_api_auth()
    if err:
        return err
    orch = get_orchestrator()
    task = orch.get_task_status(ticket_id)
    if not task:
        return jsonify({"error": "not found"}), 404
    return jsonify(task)


# =============================================================
# Catch-all: serve React SPA (Nueva UI build)
# =============================================================

import os as _os

_UI_DIST_CANDIDATES = [
    _os.path.join(_os.path.dirname(__file__), "..", "..", "Nueva UI", "dist", "client"),
    _os.path.join(_os.path.dirname(__file__), "..", "..", "Nueva UI", "dist"),
]
_UI_DIST = next((p for p in _UI_DIST_CANDIDATES if _os.path.exists(_os.path.join(p, "index.html"))), _UI_DIST_CANDIDATES[0])


@app.route("/assets/<path:filename>")
def ui_assets(filename):
    return send_file(_os.path.join(_UI_DIST, "assets", filename))


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def spa_fallback(path):
    # API and WebSocket routes are already handled above — skip them here
    if path.startswith("api/") or path.startswith("ws-proxy/"):
        abort(404)
    # Always serve React SPA if dist is built
    index = _os.path.join(_UI_DIST, "index.html")
    if _os.path.exists(index):
        return send_file(index)
    # Fallback to old Flask templates
    if "user_id" not in session:
        return redirect(url_for("login_page"))
    return redirect(url_for("index"))


# =============================================================
# Run
# =============================================================

if __name__ == "__main__":
    port = int(os.environ.get("TEL141_UI_PORT", "8080"))
    http_server = WSGIServer(('0.0.0.0', port), app, handler_class=WebSocketHandler)
    print(f"PUCP Cloud Orchestrator running on http://0.0.0.0:{port}")
    http_server.serve_forever()
