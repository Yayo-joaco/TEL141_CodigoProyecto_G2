# ==============================================================
# Database Manager - MariaDB persistence layer (v2 + RBAC)
# Uses SQLAlchemy ORM for OOP-based persistence
# ==============================================================

import json
import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy import create_engine, Column, String, Integer, Float, Text, DateTime
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.declarative import declarative_base

from ..models.slice import Slice, SliceStatus, TopologyType
from ..models.vm import VM, VMStatus
from ..models.host import Host, HostRole
from ..models.user import User, Role

logger = logging.getLogger("orchestrator.database")
Base = declarative_base()


# =============================================================
# SQLAlchemy ORM Models
# =============================================================

class UserRecord(Base):
    __tablename__ = "users"
    id = Column(String(64), primary_key=True)
    username = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), default="user")
    email = Column(String(255), nullable=True)
    is_active = Column(Integer, default=1)
    max_vcpus = Column(Integer, default=16)
    max_ram_mb = Column(Integer, default=16384)
    max_slices = Column(Integer, default=10)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_user(self) -> User:
        return User(
            id=self.id,
            username=self.username,
            password_hash=self.password_hash,
            role=Role(self.role) if self.role else Role.USER,
            email=self.email,
            is_active=bool(self.is_active),
            max_vcpus=self.max_vcpus,
            max_ram_mb=self.max_ram_mb,
            max_slices=self.max_slices,
            created_at=self.created_at.isoformat() if self.created_at else "",
        )


class ImageRecord(Base):
    __tablename__ = "images"
    id = Column(String(64), primary_key=True)
    name = Column(String(255), nullable=False)
    filename = Column(String(255), nullable=False)
    path = Column(String(512), nullable=False)
    format = Column(String(20), default="qcow2")
    sha256 = Column(String(128), nullable=True)
    size_gb = Column(Integer, default=2)
    uploaded_by = Column(String(255), default="admin")
    is_active = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "filename": self.filename,
            "path": self.path,
            "format": self.format,
            "sha256": self.sha256,
            "size_gb": self.size_gb,
            "uploaded_by": self.uploaded_by,
            "is_active": bool(self.is_active),
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }


class TemplateRecord(Base):
    __tablename__ = "templates"
    id = Column(String(64), primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    config_json = Column(Text, nullable=False)
    created_by = Column(String(255), default="admin")
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "config": json.loads(self.config_json) if self.config_json else {},
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }


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
    updated_at = Column(DateTime, default=datetime.utcnow)

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
    index = Column("index", Integer, nullable=False)
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
    zone_id = Column(String(64), nullable=True)
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
    user_id = Column(String(64), nullable=True)
    module = Column(String(100), nullable=False)
    level = Column(String(20), default="INFO")
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class VLANPoolRecord(Base):
    __tablename__ = "vlan_pool"
    id = Column(Integer, primary_key=True, autoincrement=True)
    vlan_id = Column(Integer, unique=True, nullable=False)
    slice_id = Column(String(64), nullable=True)
    subnet = Column(String(50), nullable=True)
    in_use = Column(Integer, default=0)
    assigned_at = Column(DateTime, default=datetime.utcnow)


# =============================================================
# Database Manager (v2 + RBAC)
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
        self._populate_vlan_pool()
        logger.info("Database tables verified/created")

    def _populate_vlan_pool(self):
        """Ensure VLAN pool has data (16 VLANs: 300-315)."""
        session = self.Session()
        try:
            count = session.query(VLANPoolRecord).count()
            if count == 0:
                for vlan_id in range(300, 316):
                    session.add(VLANPoolRecord(vlan_id=vlan_id, in_use=0))
                session.commit()
                logger.info("VLAN pool populated: VLANs 300-315")
        except Exception as e:
            session.rollback()
            logger.warning("VLAN pool population skipped: %s", e)
        finally:
            session.close()

    def get_session(self) -> Session:
        return self.Session()

    # ---- User operations (RBAC) ----

    def save_user(self, user: User):
        session = self.get_session()
        try:
            record = UserRecord(
                id=user.id,
                username=user.username,
                password_hash=user.password_hash,
                role=user.role.value,
                email=user.email,
                is_active=int(user.is_active),
                max_vcpus=user.max_vcpus,
                max_ram_mb=user.max_ram_mb,
                max_slices=user.max_slices,
            )
            session.merge(record)
            session.commit()
        except Exception as e:
            session.rollback()
            raise
        finally:
            session.close()

    def get_user(self, user_id: str) -> Optional[User]:
        session = self.get_session()
        try:
            record = session.query(UserRecord).filter_by(id=user_id).first()
            return record.to_user() if record else None
        finally:
            session.close()

    def get_user_by_username(self, username: str) -> Optional[User]:
        session = self.get_session()
        try:
            record = session.query(UserRecord).filter_by(username=username).first()
            return record.to_user() if record else None
        finally:
            session.close()

    def list_users(self) -> List[dict]:
        session = self.get_session()
        try:
            records = session.query(UserRecord).order_by(UserRecord.created_at.desc()).all()
            return [r.to_user().to_dict() for r in records]
        finally:
            session.close()

    def delete_user_record(self, user_id: str):
        session = self.get_session()
        try:
            record = session.query(UserRecord).filter_by(id=user_id).first()
            if record:
                record.is_active = 0
                session.commit()
        except Exception as e:
            session.rollback()
        finally:
            session.close()

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
        except Exception as e:
            session.rollback()
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

    def list_slices(self, created_by: str = None, include_deleted: bool = False) -> List[Slice]:
        session = self.get_session()
        try:
            q = session.query(SliceRecord).order_by(SliceRecord.created_at.desc())
            if created_by:
                q = q.filter_by(created_by=created_by)
            records = q.all()
            result = [r.to_slice() for r in records]
            if not include_deleted:
                result = [s for s in result if s.status != SliceStatus.DELETED]
            return result
        finally:
            session.close()

    def list_all_slices(self) -> List[Slice]:
        return self.list_slices(include_deleted=True)

    def update_slice_status(self, slice_id: str, status: SliceStatus,
                            error_message: str = None, num_vms: int = None):
        session = self.get_session()
        try:
            record = session.query(SliceRecord).filter_by(id=slice_id).first()
            if record:
                record.status = status.value
                record.error_message = error_message
                if num_vms is not None:
                    record.num_vms = num_vms
                record.updated_at = datetime.utcnow()
                session.commit()
        except Exception as e:
            session.rollback()
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
        finally:
            session.close()

    def get_vms_for_slice(self, slice_id: str) -> List[VM]:
        session = self.get_session()
        try:
            records = session.query(VMRecord).filter_by(slice_id=slice_id).order_by(VMRecord.index).all()
            return [r.to_vm() for r in records]
        finally:
            session.close()

    def delete_vm_record(self, vm_id: str):
        session = self.get_session()
        try:
            session.query(VMRecord).filter_by(id=vm_id).delete()
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
        finally:
            session.close()

    def get_hosts(self) -> List[Host]:
        session = self.get_session()
        try:
            records = session.query(HostRecord).filter_by(is_active=1).all()
            return [r.to_host() for r in records]
        finally:
            session.close()

    def update_host_resources(self, hostname: str, host_ip: str,
                               total_vcpus: int, total_ram_mb: int,
                               total_disk_gb: int, cpu_usage_pct: float = 0,
                               used_ram_mb: int = 0, used_disk_gb: int = 0):
        session = self.get_session()
        try:
            record = session.query(HostRecord).filter_by(hostname=hostname).first()
            if record:
                record.available_vcpus = max(0, total_vcpus - int(
                    cpu_usage_pct / 100.0 * total_vcpus
                ))
                record.total_vcpus = total_vcpus
                record.total_ram_mb = total_ram_mb
                record.total_disk_gb = total_disk_gb
                record.available_ram_mb = max(0, total_ram_mb - used_ram_mb)
                record.available_disk_gb = max(0, total_disk_gb - used_disk_gb)
            else:
                record = HostRecord(
                    hostname=hostname, ip=host_ip,
                    total_vcpus=total_vcpus, total_ram_mb=total_ram_mb,
                    total_disk_gb=total_disk_gb,
                    available_vcpus=max(0, total_vcpus - int(
                        cpu_usage_pct / 100.0 * total_vcpus
                    )),
                    available_ram_mb=max(0, total_ram_mb - used_ram_mb),
                    available_disk_gb=max(0, total_disk_gb - used_disk_gb),
                    is_active=1,
                )
                session.add(record)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error("Failed to update host resources: %s", e)
        finally:
            session.close()

    # ---- Image operations ----

    def save_image(self, name: str, filename: str, path: str,
                   format: str = "qcow2", size_gb: int = 2,
                   uploaded_by: str = "admin") -> str:
        import uuid
        session = self.get_session()
        try:
            img_id = str(uuid.uuid4())[:8]
            record = ImageRecord(
                id=img_id, name=name, filename=filename, path=path,
                format=format, size_gb=size_gb, uploaded_by=uploaded_by
            )
            session.add(record)
            session.commit()
            return img_id
        finally:
            session.close()

    def list_images(self) -> List[dict]:
        session = self.get_session()
        try:
            records = session.query(ImageRecord).filter_by(is_active=1).order_by(
                ImageRecord.created_at.desc()
            ).all()
            return [r.to_dict() for r in records]
        finally:
            session.close()

    def delete_image(self, image_id: str):
        session = self.get_session()
        try:
            record = session.query(ImageRecord).filter_by(id=image_id).first()
            if record:
                record.is_active = 0
                session.commit()
        except Exception as e:
            session.rollback()
        finally:
            session.close()

    # ---- Template operations ----

    def save_template(self, name: str, config: dict, description: str = "",
                      created_by: str = "admin") -> str:
        import uuid
        session = self.get_session()
        try:
            tid = str(uuid.uuid4())[:8]
            record = TemplateRecord(
                id=tid, name=name, description=description,
                config_json=json.dumps(config), created_by=created_by
            )
            session.add(record)
            session.commit()
            return tid
        finally:
            session.close()

    def list_templates(self) -> List[dict]:
        session = self.get_session()
        try:
            records = session.query(TemplateRecord).order_by(
                TemplateRecord.created_at.desc()
            ).all()
            return [r.to_dict() for r in records]
        finally:
            session.close()

    def get_template(self, template_id: str) -> Optional[dict]:
        session = self.get_session()
        try:
            record = session.query(TemplateRecord).filter_by(id=template_id).first()
            return record.to_dict() if record else None
        finally:
            session.close()

    def delete_template(self, template_id: str):
        session = self.get_session()
        try:
            session.query(TemplateRecord).filter_by(id=template_id).delete()
            session.commit()
        finally:
            session.close()

    # ---- Log operations ----

    def save_log(self, slice_id: str, module: str, level: str, message: str,
                 user_id: str = None):
        session = self.get_session()
        try:
            entry = LogEntry(
                slice_id=slice_id, user_id=user_id,
                module=module, level=level, message=message,
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
            ).limit(100).all()
            return [
                {"module": e.module, "level": e.level, "message": e.message,
                 "user_id": e.user_id,
                 "created_at": e.created_at.isoformat()}
                for e in entries
            ]
        finally:
            session.close()

    def get_all_logs(self, limit: int = 200) -> List[dict]:
        session = self.get_session()
        try:
            entries = session.query(LogEntry).order_by(
                LogEntry.created_at.desc()
            ).limit(limit).all()
            return [
                {"slice_id": e.slice_id, "user_id": e.user_id,
                 "module": e.module, "level": e.level, "message": e.message,
                 "created_at": e.created_at.isoformat()}
                for e in entries
            ]
        finally:
            session.close()

    # ---- VLAN pool operations (auto-assign, no collision) ----

    def assign_vlan(self, slice_id: str) -> dict:
        """Auto-assign next free VLAN + /28 subnet from 10.60.3.0/24 (G2)."""
        session = self.get_session()
        try:
            record = session.query(VLANPoolRecord).filter_by(in_use=0).order_by(
                VLANPoolRecord.vlan_id
            ).first()
            if not record:
                return {"success": False, "error": "No hay VLANs disponibles en el pool"}

            used = session.query(VLANPoolRecord).filter_by(in_use=1).count()
            subnet = f"10.60.3.{used * 16}/28"

            record.in_use = 1
            record.slice_id = slice_id
            record.subnet = subnet
            record.assigned_at = datetime.utcnow()
            session.commit()
            return {
                "success": True,
                "vlan_id": record.vlan_id,
                "subnet": subnet,
            }
        except Exception as e:
            session.rollback()
            return {"success": False, "error": str(e)}
        finally:
            session.close()

    def release_vlan(self, slice_id: str):
        """Release VLAN back to pool when slice is deleted."""
        session = self.get_session()
        try:
            record = session.query(VLANPoolRecord).filter_by(slice_id=slice_id).first()
            if record:
                record.in_use = 0
                record.slice_id = None
                record.subnet = None
                session.commit()
        except Exception as e:
            session.rollback()
        finally:
            session.close()
