# ==============================================================
# Auth Manager - JWT Authentication + RBAC Authorization
# Handles:
#   - User authentication (login/register)
#   - JWT token generation and validation
#   - Session management
#   - Role-based access control (RBAC)
# ==============================================================

import logging
import hashlib
import time
import jwt
from typing import Optional, Tuple
from datetime import datetime, timedelta

from ..models.user import User, Role

logger = logging.getLogger("orchestrator.auth")

SECRET_KEY = "pucp-cloud-orchestrator-2026-g2-jwt-secret"
TOKEN_EXPIRE_HOURS = 8
SESSION_TIMEOUT = 3600  # 1 hour in seconds


class AuthManager:
    """
    Handles JWT authentication and RBAC authorization.

    Flow:
      1. User logs in with username/password
      2. AuthManager validates credentials against DB
      3. Generates JWT with user_id, role, exp
      4. All subsequent requests validate JWT and extract role
      5. Each method checks role before executing
    """

    def __init__(self, db):
        self.db = db
        self._active_sessions = {}

    def hash_password(self, password: str) -> str:
        return hashlib.sha256(
            f"{password}:{SECRET_KEY}".encode()
        ).hexdigest()

    def verify_password(self, password: str, password_hash: str) -> bool:
        return self.hash_password(password) == password_hash

    def authenticate(self, username_or_email: str, password: str, ip: str = "") -> Tuple[bool, Optional[dict]]:
        # Accept both email and username
        if "@" in username_or_email:
            user = self.db.get_user_by_email(username_or_email)
        else:
            user = self.db.get_user_by_username(username_or_email)

        if not user or not user.is_active:
            logger.warning("Auth failed: '%s' not found or inactive", username_or_email)
            return False, None

        if not self.verify_password(password, user.password_hash):
            logger.warning("Auth failed: invalid password for '%s'", username_or_email)
            return False, None

        token = self._generate_token(user)
        self._active_sessions[user.id] = {
            "token": token,
            "login_at": time.time(),
            "user": user.username,
            "role": user.role.value,
            "ip": ip,
        }
        logger.info("User '%s' authenticated (role=%s)", user.username, user.role.value)

        return True, {
            "user_id": user.id,
            "username": user.username,
            "email": user.email or f"{user.username}@pucp.pe",
            "name": user.username,
            "role": user.role.value,
            "cluster_assignment": getattr(user, "cluster_assignment", "linux"),
            "token": token,
        }

    def validate_token(self, token: str) -> Tuple[bool, Optional[dict]]:
        if not token:
            return False, None
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            return True, payload
        except jwt.ExpiredSignatureError:
            logger.debug("Token expired")
            return False, None
        except jwt.InvalidTokenError:
            logger.debug("Invalid token")
            return False, None

    def validate_request(self, token: str, required_role: Optional[Role] = None) -> Tuple[bool, Optional[User], str]:
        valid, payload = self.validate_token(token)
        if not valid:
            return False, None, "Token inválido o expirado"

        user_id = payload.get("user_id")
        user = self.db.get_user(user_id)
        if not user or not user.is_active:
            return False, None, "Usuario no encontrado o inactivo"

        if required_role and not user.has_permission(required_role):
            return False, user, f"Permiso denegado: se requiere rol {required_role.value}"

        return True, user, "ok"

    def logout(self, user_id: str):
        self._active_sessions.pop(user_id, None)
        logger.info("User %s logged out", user_id)

    def register_user(self, username: str, password: str,
                      role: Role = Role.USER, email: str = None,
                      cluster_assignment: str = "linux") -> Tuple[bool, str]:
        existing = self.db.get_user_by_username(username)
        if existing:
            return False, "El usuario ya existe"
        if email:
            existing_email = self.db.get_user_by_email(email)
            if existing_email:
                return False, "El email ya está registrado"

        password_hash = self.hash_password(password)
        user = User(
            id="",
            username=username,
            password_hash=password_hash,
            role=role,
            email=email,
            cluster_assignment=cluster_assignment,
        )
        self.db.save_user(user)
        logger.info("User '%s' registered (role=%s, cluster=%s)", username, role.value, cluster_assignment)
        return True, user.id

    def seed_demo_users(self):
        """Create default demo users if they don't exist."""
        demos = [
            ("admin",    "admin123",    Role.ADMIN,    "admin@pucp.pe",    "both"),
            ("operador", "op123",       Role.OPERATOR, "operador@pucp.pe", "both"),
            ("user",     "user123",     Role.USER,     "user@pucp.pe",     "linux"),
        ]
        for username, password, role, email, cluster in demos:
            if not self.db.get_user_by_username(username):
                self.register_user(username, password, role, email, cluster)
                logger.info("Demo user seeded: %s (%s)", username, email)

    def get_active_sessions(self, user: User) -> list:
        if not user.can_view_all_slices():
            return []
        return [
            {
                "id": uid,
                "user": s.get("user", uid),
                "role": s.get("role", "user"),
                "loginTime": __import__('datetime').datetime.fromtimestamp(s["login_at"]).isoformat(),
                "ip": s.get("ip", ""),
            }
            for uid, s in self._active_sessions.items()
        ]

    def _generate_token(self, user: User) -> str:
        payload = {
            "user_id": user.id,
            "username": user.username,
            "role": user.role.value,
            "exp": datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS),
            "iat": datetime.utcnow(),
        }
        return jwt.encode(payload, SECRET_KEY, algorithm="HS256")
