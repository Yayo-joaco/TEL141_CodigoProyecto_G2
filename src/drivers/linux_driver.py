# ==============================================================
# Linux Driver - Implements VM lifecycle on Linux hosts via SSH
# Uses: paramiko for SSH, qemu-system-x86_64 for VMs, OVS for networking
#
# Requirements covered:
#   R2 - Soporte de cluster Linux
#   R5 - Networking L2 via OVS
# ==============================================================

import logging
import time
import uuid
from typing import Optional

import paramiko

from .base_driver import BaseDriver
from ..models.vm import VM, VMStatus
from ..models.placement_decision import PlacementDecision

logger = logging.getLogger("orchestrator.linux_driver")


class LinuxDriver(BaseDriver):
    """
    Manages VMs on remote Linux hosts via SSH.

    VM images use QCOW2 delta (backing file) for space efficiency (R2 req #10).
    Console access via VNC on a local port (R2 req #7).
    """

    VM_BASE_DIR = "/home/ubuntu/vms"
    OVS_BRIDGE = "br-int"

    def __init__(self, ssh_key_path: str = "/home/ubuntu/.ssh/id_rsa"):
        self.ssh_key_path = ssh_key_path
        self.vnc_base_port = 6000
        self.vnc_ws_base_port = 17000

    def create_vm(self, vm: VM, placement: PlacementDecision,
                  base_image_path: str) -> bool:
        host_ip = placement.host_ip
        vm_name = vm.name
        vcpus = placement.vcpus_allocated
        ram_mb = placement.ram_mb_allocated
        disk_gb = placement.disk_gb_allocated

        try:
            client = self._connect(host_ip)

            self._exec(client, f"mkdir -p {self.VM_BASE_DIR}/{vm_name}")

            vm_disk = f"{self.VM_BASE_DIR}/{vm_name}/{vm_name}.qcow2"
            self._exec(client, (
                f"sudo qemu-img create -f qcow2 -b {base_image_path} "
                f"-F qcow2 {vm_disk}"
            ))

            vm.tap_interface = f"tap-{vm_name}"
            self._exec(client, f"sudo ip tuntap add mode tap {vm.tap_interface}")
            self._exec(client, f"sudo ip link set {vm.tap_interface} up")

            vm.vnc_port = vm.vnc_port or (self.vnc_base_port + vm.index)
            vm.vnc_ws_port = vm.vnc_ws_port or (self.vnc_ws_base_port + vm.index)
            vm.vnc_token = str(uuid.uuid4())[:12]

            mac_addr = self._gen_mac(vm.index)
            vnc_display = vm.vnc_port - self.vnc_base_port

            qemu_cmd = (
                f"sudo qemu-system-x86_64 "
                f"-name {vm_name} "
                f"-m {ram_mb} "
                f"-smp {vcpus} "
                f"-drive file={vm_disk},if=virtio,format=qcow2 "
                f"-netdev tap,id=net0,ifname={vm.tap_interface},script=no,downscript=no "
                f"-device virtio-net-pci,netdev=net0,mac={mac_addr} "
                f"-vnc 0.0.0.0:{vnc_display} "
                f"-daemonize "
                f"-enable-kvm"
            )

            self._exec(client, qemu_cmd)

            time.sleep(2)

            pid_out = self._exec(client, f"sudo pgrep -f 'qemu-system-x86_64.*-name {vm_name}'")
            if pid_out.strip():
                vm.qemu_pid = int(pid_out.strip().split('\n')[0])
                vm.mac_address = mac_addr
                vm.status = VMStatus.ACTIVE
                logger.info("VM %s created on %s (PID=%d, VNC=%d)",
                            vm_name, host_ip, vm.qemu_pid, vm.vnc_port)

                self._exec(client, f"sudo ovs-vsctl add-port {self.OVS_BRIDGE} {vm.tap_interface}")

                vnc_raw = 5900 + vnc_display
                self._exec(client,
                           f"sudo nohup websockify {vm.vnc_ws_port} 127.0.0.1:{vnc_raw} "
                           f">/dev/null 2>&1 &")
                logger.info("websockify started on port %d -> 127.0.0.1:%d", vm.vnc_ws_port, vnc_raw)
            else:
                vm.status = VMStatus.ERROR
                vm.error_message = "QEMU process not found after start"
                logger.error("VM %s: QEMU did not start on %s", vm_name, host_ip)
                client.close()
                return False

            client.close()
            return True

        except Exception as e:
            vm.status = VMStatus.ERROR
            vm.error_message = str(e)
            logger.error("Failed to create VM %s on %s: %s", vm_name, host_ip, e)
            return False

    def delete_vm(self, vm: VM) -> bool:
        host_ip = vm.host_ip
        vm_name = vm.name

        try:
            client = self._connect(host_ip)

            if vm.qemu_pid:
                self._exec(client, f"sudo kill {vm.qemu_pid} 2>/dev/null")
                time.sleep(1)

            if vm.vnc_ws_port:
                self._exec(client, f"sudo pkill -f 'websockify.*{vm.vnc_ws_port}' 2>/dev/null")

            if vm.tap_interface:
                self._exec(client, f"sudo ovs-vsctl del-port {self.OVS_BRIDGE} {vm.tap_interface} 2>/dev/null")
                self._exec(client, f"sudo ip link delete {vm.tap_interface} 2>/dev/null")

            self._exec(client, f"rm -rf {self.VM_BASE_DIR}/{vm_name}")

            vm.status = VMStatus.DELETED
            logger.info("VM %s deleted from %s", vm_name, host_ip)
            client.close()
            return True

        except Exception as e:
            logger.error("Failed to delete VM %s from %s: %s", vm_name, host_ip, e)
            return False

    def get_vm_status(self, vm: VM) -> Optional[str]:
        try:
            client = self._connect(vm.host_ip)
            out = self._exec(client, f"sudo pgrep -f 'qemu-system-x86_64.*-name {vm.name}'")
            client.close()
            return VMStatus.ACTIVE.value if out.strip() else VMStatus.DELETED.value
        except Exception:
            return None

    def get_console_token(self, vm: VM) -> Optional[str]:
        return vm.vnc_token

    def get_host_resources(self, host_ip: str) -> dict:
        """
        Query real hardware resources from a remote Linux host via SSH.
        Returns: {total_vcpus, total_ram_mb, total_disk_gb,
                  used_vcpus_approx, used_ram_mb, used_disk_gb}
        """
        try:
            client = self._connect(host_ip)

            cpu_total = int(self._exec(client, "nproc").strip() or "1")

            ram_raw = self._exec(
                client,
                "free -m | awk '/^Mem:/{print $2}'"
            ).strip()
            ram_total = int(ram_raw) if ram_raw.isdigit() else 8192

            ram_used_raw = self._exec(
                client,
                "free -m | awk '/^Mem:/{print $3}'"
            ).strip()
            ram_used = int(ram_used_raw) if ram_used_raw.isdigit() else 0

            disk_raw = self._exec(
                client,
                "df -BM / | tail -1 | awk '{print $2}' | sed 's/M//'"
            ).strip()
            disk_total_mb = int(disk_raw) if disk_raw.isdigit() else 100000
            disk_total_gb = max(1, disk_total_mb // 1024)

            disk_used_raw = self._exec(
                client,
                "df -BM / | tail -1 | awk '{print $3}' | sed 's/M//'"
            ).strip()
            disk_used_mb = int(disk_used_raw) if disk_used_raw.isdigit() else 0
            disk_used_gb = max(0, disk_used_mb // 1024)

            cpu_used_approx = int(float(
                self._exec(
                    client,
                    "top -bn1 | grep 'Cpu(s)' | awk '{print $2}' | cut -d'%' -f1"
                ).strip() or "0"
            ))

            client.close()

            return {
                "total_vcpus": cpu_total,
                "total_ram_mb": ram_total,
                "total_disk_gb": disk_total_gb,
                "used_ram_mb": ram_used,
                "used_disk_gb": disk_used_gb,
                "cpu_usage_pct": cpu_used_approx,
            }
        except Exception as e:
            logger.error("Failed to query resources from %s: %s", host_ip, e)
            return {}

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
        if err and "Warning" not in err:
            logger.debug("SSH stderr: %s", err.strip())
        return out

    def _gen_mac(self, idx: int) -> str:
        return f"52:54:00:60:03:{idx:02x}"
