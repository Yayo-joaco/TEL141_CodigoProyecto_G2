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

    def authenticate(self, username: str, password: str) -> Tuple[bool, Optional[dict]]:
        user = self.db.get_user_by_username(username)
        if not user or not user.is_active:
            logger.warning("Auth failed: user '%s' not found or inactive", username)
            return False, None

        if not self.verify_password(password, user.password_hash):
            logger.warning("Auth failed: invalid password for '%s'", username)
            return False, None

        token = self._generate_token(user)
        self._active_sessions[user.id] = {
            "token": token,
            "login_at": time.time(),
        }
        logger.info("User '%s' authenticated (role=%s)", username, user.role.value)

        return True, {
            "user_id": user.id,
            "username": user.username,
            "role": user.role.value,
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
                      role: Role = Role.USER, email: str = None) -> Tuple[bool, str]:
        existing = self.db.get_user_by_username(username)
        if existing:
            return False, "El usuario ya existe"

        password_hash = self.hash_password(password)
        user = User(
            id="",
            username=username,
            password_hash=password_hash,
            role=role,
            email=email,
        )
        self.db.save_user(user)
        logger.info("User '%s' registered (role=%s)", username, role.value)
        return True, user.id

    def get_active_sessions(self, user: User) -> list:
        if not user.can_view_all_slices():
            return []
        return [
            {"user_id": uid, "login_at": datetime.fromtimestamp(s["login_at"]).isoformat()}
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
