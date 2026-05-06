# ==============================================================
# Database Manager - MariaDB persistence layer
# Uses SQLAlchemy ORM for OOP-based persistence (no raw SQL in Orchestrator)
# ==============================================================

import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy import create_engine, Column, String, Integer, Float, Text, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base, Session

from ..models.slice import Slice, SliceStatus, TopologyType
from ..models.vm import VM, VMStatus
from ..models.host import Host, HostRole

logger = logging.getLogger("orchestrator.database")
Base = declarative_base()


# =============================================================
# SQLAlchemy ORM Models
# =============================================================

class SliceRecord(Base):
    __tablename__ = "slices"

    id = Column(String(64), primary_key=True)
    name = Column(String(255), nullable=False)
    topology = Column(String(50), nullable=False)
    num_vms = Column(Integer, nullable=False)
    vcpus_per_vm = Column(Integer, default=1)
    ram_mb_per_vm = Column(Integer, default=512)
    disk_gb_per_vm = Column(Integer, default=2)
    vlan_id = Column(Integer, nullable=True)
    subnet = Column(String(50), nullable=True)
    enable_dhcp = Column(Integer, default=0)
    enable_internet = Column(Integer, default=0)
    status = Column(String(50), default="pending")
    created_by = Column(String(255), default="admin")
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_slice(self) -> Slice:
        return Slice(
            id=self.id,
            name=self.name,
            topology=TopologyType(self.topology),
            num_vms=self.num_vms,
            vcpus_per_vm=self.vcpus_per_vm,
            ram_mb_per_vm=self.ram_mb_per_vm,
            disk_gb_per_vm=self.disk_gb_per_vm,
            vlan_id=self.vlan_id,
            subnet=self.subnet,
            enable_dhcp=bool(self.enable_dhcp),
            enable_internet=bool(self.enable_internet),
            status=SliceStatus(self.status) if self.status else SliceStatus.PENDING,
            created_by=self.created_by,
            created_at=self.created_at.isoformat() if self.created_at else "",
            updated_at=self.updated_at.isoformat() if self.updated_at else "",
            error_message=self.error_message,
        )


class VMRecord(Base):
    __tablename__ = "vms"

    id = Column(String(64), primary_key=True)
    slice_id = Column(String(64), nullable=False)
    name = Column(String(255), nullable=False)
    index = Column(Integer, nullable=False)
    host_ip = Column(String(50), nullable=True)
    vcpus = Column(Integer, default=1)
    ram_mb = Column(Integer, default=512)
    disk_gb = Column(Integer, default=2)
    ip_address = Column(String(50), nullable=True)
    mac_address = Column(String(50), nullable=True)
    vnc_port = Column(Integer, nullable=True)
    vnc_token = Column(String(50), nullable=True)
    tap_interface = Column(String(100), nullable=True)
    qemu_pid = Column(Integer, nullable=True)
    status = Column(String(50), default="pending")
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_vm(self) -> VM:
        return VM(
            id=self.id,
            slice_id=self.slice_id,
            name=self.name,
            index=self.index,
            host_ip=self.host_ip,
            vcpus=self.vcpus,
            ram_mb=self.ram_mb,
            disk_gb=self.disk_gb,
            ip_address=self.ip_address,
            mac_address=self.mac_address,
            vnc_port=self.vnc_port,
            vnc_token=self.vnc_token,
            tap_interface=self.tap_interface,
            qemu_pid=self.qemu_pid,
            status=VMStatus(self.status) if self.status else VMStatus.PENDING,
            error_message=self.error_message,
            created_at=self.created_at.isoformat() if self.created_at else "",
        )


class HostRecord(Base):
    __tablename__ = "hosts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    hostname = Column(String(255), unique=True, nullable=False)
    ip = Column(String(50), unique=True, nullable=False)
    role = Column(String(50), default="worker")
    total_vcpus = Column(Integer, default=8)
    total_ram_mb = Column(Integer, default=8192)
    total_disk_gb = Column(Integer, default=100)
    available_vcpus = Column(Integer, default=8)
    available_ram_mb = Column(Integer, default=8192)
    available_disk_gb = Column(Integer, default=100)
    is_active = Column(Integer, default=1)

    def to_host(self) -> Host:
        return Host(
            hostname=self.hostname,
            ip=self.ip,
            role=HostRole(self.role) if self.role else HostRole.WORKER,
            total_vcpus=self.total_vcpus,
            total_ram_mb=self.total_ram_mb,
            total_disk_gb=self.total_disk_gb,
            available_vcpus=self.available_vcpus,
            available_ram_mb=self.available_ram_mb,
            available_disk_gb=self.available_disk_gb,
            is_active=bool(self.is_active),
        )


class LogEntry(Base):
    __tablename__ = "logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    slice_id = Column(String(64), nullable=True)
    module = Column(String(100), nullable=False)
    level = Column(String(20), default="INFO")
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


# =============================================================
# Database Manager
# =============================================================

class DatabaseManager:
    def __init__(self, user: str, password: str, host: str = "localhost",
                 port: int = 3306, database: str = "pucp_orchestrator"):
        url = f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}"
        self.engine = create_engine(url, echo=False, pool_size=10, max_overflow=20)
        self.Session = sessionmaker(bind=self.engine)
        self._ensure_tables()

    def _ensure_tables(self):
        Base.metadata.create_all(self.engine)
        logger.info("Database tables verified/created")

    def get_session(self) -> Session:
        return self.Session()

    # ---- Slice operations ----

    def save_slice(self, slice_obj: Slice):
        session = self.get_session()
        try:
            record = SliceRecord(
                id=slice_obj.id,
                name=slice_obj.name,
                topology=slice_obj.topology.value,
                num_vms=slice_obj.num_vms,
                vcpus_per_vm=slice_obj.vcpus_per_vm,
                ram_mb_per_vm=slice_obj.ram_mb_per_vm,
                disk_gb_per_vm=slice_obj.disk_gb_per_vm,
                vlan_id=slice_obj.vlan_id,
                subnet=slice_obj.subnet,
                enable_dhcp=int(slice_obj.enable_dhcp),
                enable_internet=int(slice_obj.enable_internet),
                status=slice_obj.status.value,
                created_by=slice_obj.created_by,
                error_message=slice_obj.error_message,
            )
            session.merge(record)
            session.commit()
            logger.info("Slice %s saved to DB", slice_obj.name)
        except Exception as e:
            session.rollback()
            logger.error("Failed to save slice: %s", e)
            raise
        finally:
            session.close()

    def get_slice(self, slice_id: str) -> Optional[Slice]:
        session = self.get_session()
        try:
            record = session.query(SliceRecord).filter_by(id=slice_id).first()
            return record.to_slice() if record else None
        finally:
            session.close()

    def list_slices(self) -> List[Slice]:
        session = self.get_session()
        try:
            records = session.query(SliceRecord).order_by(SliceRecord.created_at.desc()).all()
            return [r.to_slice() for r in records]
        finally:
            session.close()

    def update_slice_status(self, slice_id: str, status: SliceStatus,
                            error_message: str = None):
        session = self.get_session()
        try:
            record = session.query(SliceRecord).filter_by(id=slice_id).first()
            if record:
                record.status = status.value
                record.error_message = error_message
                record.updated_at = datetime.utcnow()
                session.commit()
        except Exception as e:
            session.rollback()
            logger.error("Failed to update slice status: %s", e)
        finally:
            session.close()

    def delete_slice_record(self, slice_id: str):
        session = self.get_session()
        try:
            record = session.query(SliceRecord).filter_by(id=slice_id).first()
            if record:
                record.status = SliceStatus.DELETED.value
                record.updated_at = datetime.utcnow()
                session.commit()
        except Exception as e:
            session.rollback()
            logger.error("Failed to mark slice as deleted: %s", e)
        finally:
            session.close()

    # ---- VM operations ----

    def save_vm(self, vm: VM):
        session = self.get_session()
        try:
            record = VMRecord(
                id=vm.id,
                slice_id=vm.slice_id,
                name=vm.name,
                index=vm.index,
                host_ip=vm.host_ip,
                vcpus=vm.vcpus,
                ram_mb=vm.ram_mb,
                disk_gb=vm.disk_gb,
                ip_address=vm.ip_address,
                mac_address=vm.mac_address,
                vnc_port=vm.vnc_port,
                vnc_token=vm.vnc_token,
                tap_interface=vm.tap_interface,
                qemu_pid=vm.qemu_pid,
                status=vm.status.value,
                error_message=vm.error_message,
            )
            session.merge(record)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error("Failed to save VM: %s", e)
        finally:
            session.close()

    def get_vms_for_slice(self, slice_id: str) -> List[VM]:
        session = self.get_session()
        try:
            records = session.query(VMRecord).filter_by(slice_id=slice_id).all()
            return [r.to_vm() for r in records]
        finally:
            session.close()

    def update_vm_status(self, vm_id: str, status: VMStatus):
        session = self.get_session()
        try:
            record = session.query(VMRecord).filter_by(id=vm_id).first()
            if record:
                record.status = status.value
                session.commit()
        except Exception as e:
            session.rollback()
        finally:
            session.close()

    # ---- Host operations ----

    def save_host(self, host: Host):
        session = self.get_session()
        try:
            record = session.query(HostRecord).filter_by(hostname=host.hostname).first()
            if record:
                record.available_vcpus = host.available_vcpus
                record.available_ram_mb = host.available_ram_mb
                record.available_disk_gb = host.available_disk_gb
                record.is_active = int(host.is_active)
            else:
                record = HostRecord(
                    hostname=host.hostname,
                    ip=host.ip,
                    role=host.role.value,
                    total_vcpus=host.total_vcpus,
                    total_ram_mb=host.total_ram_mb,
                    total_disk_gb=host.total_disk_gb,
                    available_vcpus=host.available_vcpus,
                    available_ram_mb=host.available_ram_mb,
                    available_disk_gb=host.available_disk_gb,
                    is_active=int(host.is_active),
                )
                session.add(record)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error("Failed to save host: %s", e)
        finally:
            session.close()

    def get_hosts(self) -> List[Host]:
        session = self.get_session()
        try:
            records = session.query(HostRecord).filter_by(is_active=1).all()
            return [r.to_host() for r in records]
        finally:
            session.close()

    # ---- Log operations ----

    def save_log(self, slice_id: str, module: str, level: str, message: str):
        session = self.get_session()
        try:
            entry = LogEntry(
                slice_id=slice_id,
                module=module,
                level=level,
                message=message,
            )
            session.add(entry)
            session.commit()
        except Exception as e:
            session.rollback()
        finally:
            session.close()

    def get_logs_for_slice(self, slice_id: str) -> List[dict]:
        session = self.get_session()
        try:
            entries = session.query(LogEntry).filter_by(slice_id=slice_id).order_by(
                LogEntry.created_at.desc()
            ).limit(50).all()
            return [
                {"module": e.module, "level": e.level, "message": e.message,
                 "created_at": e.created_at.isoformat()}
                for e in entries
            ]
        finally:
            session.close()
