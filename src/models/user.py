# ==============================================================
# User entity - OOP model for authentication and RBAC
# Roles: user, operator, admin, system (from RBAC doc)
# ==============================================================

from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from typing import Optional
import uuid


class Role(str, Enum):
    USER = "user"
    OPERATOR = "operator"
    ADMIN = "admin"
    SYSTEM = "system"


@dataclass
class User:
    id: str
    username: str
    password_hash: str
    role: Role = Role.USER
    email: Optional[str] = None
    cluster_assignment: str = "linux"   # linux | openstack | both
    is_active: bool = True
    max_vcpus: int = 16
    max_ram_mb: int = 16384
    max_slices: int = 10
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())[:8]

    def has_permission(self, required_role: Role) -> bool:
        role_rank = {Role.USER: 0, Role.OPERATOR: 1, Role.ADMIN: 2, Role.SYSTEM: 3}
        return role_rank.get(self.role, 0) >= role_rank.get(required_role, 0)

    def can_view_all_slices(self) -> bool:
        return self.role in (Role.OPERATOR, Role.ADMIN)

    def can_manage_infrastructure(self) -> bool:
        return self.role == Role.ADMIN

    def can_manage_users(self) -> bool:
        return self.role == Role.ADMIN

    def can_manage_images(self) -> bool:
        return self.role == Role.ADMIN

    def can_force_delete(self) -> bool:
        return self.role in (Role.OPERATOR, Role.ADMIN)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "name": self.username,
            "email": self.email or f"{self.username}@pucp.pe",
            "role": self.role.value if isinstance(self.role, Role) else self.role,
            "cluster_assignment": self.cluster_assignment,
            "is_active": self.is_active,
            "max_vcpus": self.max_vcpus,
            "max_ram_mb": self.max_ram_mb,
            "max_slices": self.max_slices,
            "created_at": self.created_at,
        }
