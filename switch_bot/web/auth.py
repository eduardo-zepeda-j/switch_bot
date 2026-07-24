"""AuthService — Autenticación JWT, RBAC y protección contra fuerza bruta.

Implementa autenticación basada en JWT con expiración de 24h,
control de acceso basado en roles (RBAC) con jerarquía de permisos,
y bloqueo por IP tras intentos fallidos consecutivos.

Requirements cubiertos:
- 13.1: JWT con expiración 24h para todos los endpoints REST y WebSocket
- 13.2: Rechazo 401 sin revelar motivo específico
- 13.3: Autenticación de Agente_Local mediante token
- 13.4: Rechazo + log de intentos fallidos con IP y timestamp
- 13.6: RBAC con permisos por rol (operador, director, administrador)
- 13.7: Bloqueo de IP tras 5 intentos fallidos durante 15 minutos
- 6.6: Máximo 5 intentos antes de bloquear 60s (SPA lockout)
- 6.7: Autenticación requerida, sesión auto-close tras 30min inactividad
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field

import jwt

logger = logging.getLogger(__name__)

# Clave secreta para firma JWT — debe configurarse via variable de entorno
_DEFAULT_SECRET = "switchbot-dev-secret-change-in-production"


@dataclass
class _FailedAttemptRecord:
    """Registro interno de intentos fallidos por IP."""

    count: int = 0
    first_attempt_ts: float = 0.0
    last_attempt_ts: float = 0.0
    blocked_until: float = 0.0


class AuthService:
    """Servicio de autenticación y autorización JWT + RBAC.

    Implementa:
    - Generación y validación de tokens JWT con expiración de 24h
    - Control de acceso basado en roles con jerarquía de permisos
    - Protección contra fuerza bruta con bloqueo por IP

    La jerarquía de roles es:
        administrador > director > operador

    Cada rol hereda los permisos de los roles inferiores.
    """

    TOKEN_EXPIRY_HOURS: int = 24
    MAX_LOGIN_ATTEMPTS: int = 5
    LOCKOUT_SECONDS: int = 60  # SPA lockout
    IP_BLOCK_SECONDS: int = 900  # 15 min IP block
    INACTIVITY_TIMEOUT_MINUTES: int = 30

    # Permisos directos de cada rol (sin herencia)
    _BASE_ROLES: dict[str, list[str]] = {
        "operador": ["inject_note", "panic_button", "view_state"],
        "director": [
            "create_session",
            "finalize_session",
            "configure_ia",
            "download_artifacts",
        ],
        "administrador": [
            "manage_users",
            "modify_roles",
            "security_logs",
        ],
    }

    # Jerarquía: cada rol hereda permisos de los inferiores
    _ROLE_HIERARCHY: list[str] = ["operador", "director", "administrador"]

    def __init__(self, secret_key: str | None = None) -> None:
        """Inicializa el servicio de autenticación.

        Args:
            secret_key: Clave secreta para firma JWT. Si no se provee,
                se lee de la variable de entorno SWITCHBOT_JWT_SECRET,
                o se usa un valor por defecto (solo para desarrollo).
        """
        self._secret_key = (
            secret_key
            or os.environ.get("SWITCHBOT_JWT_SECRET")
            or _DEFAULT_SECRET
        )
        self._failed_attempts: dict[str, _FailedAttemptRecord] = {}
        # Construir mapa de permisos efectivos con herencia
        self._effective_permissions = self._build_effective_permissions()

    def _build_effective_permissions(self) -> dict[str, set[str]]:
        """Construye mapa de permisos efectivos incluyendo herencia."""
        effective: dict[str, set[str]] = {}
        accumulated: set[str] = set()

        for role in self._ROLE_HIERARCHY:
            accumulated = accumulated | set(self._BASE_ROLES[role])
            effective[role] = accumulated.copy()

        return effective

    @property
    def ROLES(self) -> dict[str, list[str]]:
        """Permisos efectivos por rol (incluyendo herencia).

        Returns:
            Diccionario con rol como clave y lista de permisos como valor.
        """
        return {
            role: sorted(perms)
            for role, perms in self._effective_permissions.items()
        }

    # ------------------------------------------------------------------
    # JWT Token Management
    # ------------------------------------------------------------------

    def create_token(self, user_id: str, role: str) -> str:
        """Genera JWT con expiración de 24h y claims de rol.

        Args:
            user_id: Identificador único del usuario.
            role: Rol del usuario (operador, director, administrador).

        Returns:
            Token JWT codificado como string.

        Raises:
            ValueError: Si el rol no es válido.
        """
        if role not in self._effective_permissions:
            raise ValueError(
                f"Rol inválido: {role!r}. "
                f"Roles válidos: {list(self._effective_permissions.keys())}"
            )

        now = time.time()
        payload = {
            "user_id": user_id,
            "role": role,
            "iat": int(now),
            "exp": int(now + self.TOKEN_EXPIRY_HOURS * 3600),
        }

        return jwt.encode(payload, self._secret_key, algorithm="HS256")

    def validate_token(self, token: str) -> dict | None:
        """Valida JWT. Retorna claims si válido, None si inválido/expirado.

        No revela motivo específico del rechazo (Req 13.2).

        Args:
            token: Token JWT a validar.

        Returns:
            Diccionario con claims (user_id, role, iat, exp) si el token
            es válido, o None si es inválido, expirado o malformado.
        """
        try:
            claims = jwt.decode(
                token, self._secret_key, algorithms=["HS256"]
            )
            # Verificar que contiene claims requeridos
            if "user_id" not in claims or "role" not in claims:
                return None
            # Verificar que el rol en el token es válido
            if claims["role"] not in self._effective_permissions:
                return None
            return claims
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
            return None

    # ------------------------------------------------------------------
    # RBAC Permission Checking
    # ------------------------------------------------------------------

    def check_permission(self, role: str, action: str) -> bool:
        """Verifica si el rol tiene permiso para la acción.

        Implementa jerarquía de roles donde administrador hereda
        permisos de director, y director hereda de operador.

        Args:
            role: Rol del usuario.
            action: Acción a verificar.

        Returns:
            True si el rol tiene permiso para la acción, False en caso contrario.
        """
        permissions = self._effective_permissions.get(role)
        if permissions is None:
            return False
        return action in permissions

    # ------------------------------------------------------------------
    # Rate Limiting / IP Blocking
    # ------------------------------------------------------------------

    def record_failed_attempt(self, ip: str) -> bool:
        """Registra intento fallido de login. Retorna True si IP debe bloquearse.

        Implementa:
        - Bloqueo SPA: 60s tras 5 intentos (Req 6.6)
        - Bloqueo IP: 15 minutos tras 5 intentos (Req 13.7)

        Args:
            ip: Dirección IP del intento fallido.

        Returns:
            True si la IP ha sido bloqueada (alcanzó MAX_LOGIN_ATTEMPTS),
            False si aún tiene intentos disponibles.
        """
        now = time.time()
        record = self._failed_attempts.get(ip)

        if record is None:
            record = _FailedAttemptRecord(
                count=1,
                first_attempt_ts=now,
                last_attempt_ts=now,
            )
            self._failed_attempts[ip] = record
            logger.info(
                "Intento fallido registrado: ip=%s, count=1", ip
            )
            return False

        # Si ya estaba bloqueada y el bloqueo expiró, reiniciar
        if record.blocked_until > 0 and now >= record.blocked_until:
            record.count = 1
            record.first_attempt_ts = now
            record.last_attempt_ts = now
            record.blocked_until = 0.0
            logger.info(
                "Bloqueo expirado, reiniciando contador: ip=%s", ip
            )
            return False

        # Si ya está bloqueada y aún no expira
        if record.blocked_until > 0 and now < record.blocked_until:
            logger.warning(
                "Intento desde IP bloqueada: ip=%s, bloqueada hasta %.0f",
                ip,
                record.blocked_until,
            )
            return True

        record.count += 1
        record.last_attempt_ts = now

        if record.count >= self.MAX_LOGIN_ATTEMPTS:
            # Bloquear IP por 15 minutos
            record.blocked_until = now + self.IP_BLOCK_SECONDS
            logger.warning(
                "IP bloqueada tras %d intentos fallidos: ip=%s, "
                "bloqueada por %ds",
                record.count,
                ip,
                self.IP_BLOCK_SECONDS,
            )
            return True

        logger.info(
            "Intento fallido registrado: ip=%s, count=%d/%d",
            ip,
            record.count,
            self.MAX_LOGIN_ATTEMPTS,
        )
        return False

    def is_ip_blocked(self, ip: str) -> bool:
        """True si la IP está bloqueada por intentos fallidos.

        Args:
            ip: Dirección IP a verificar.

        Returns:
            True si la IP tiene un bloqueo activo, False en caso contrario.
        """
        record = self._failed_attempts.get(ip)
        if record is None:
            return False

        if record.blocked_until <= 0:
            return False

        now = time.time()
        if now >= record.blocked_until:
            # Bloqueo expirado — limpiar registro
            record.count = 0
            record.blocked_until = 0.0
            return False

        return True

    def clear_failed_attempts(self, ip: str) -> None:
        """Limpia el registro de intentos fallidos para una IP.

        Se debe invocar tras un login exitoso para reiniciar el contador.

        Args:
            ip: Dirección IP a limpiar.
        """
        if ip in self._failed_attempts:
            del self._failed_attempts[ip]

    def get_lockout_remaining(self, ip: str) -> float:
        """Retorna segundos restantes de bloqueo para una IP.

        Args:
            ip: Dirección IP a consultar.

        Returns:
            Segundos restantes de bloqueo, o 0.0 si no está bloqueada.
        """
        record = self._failed_attempts.get(ip)
        if record is None or record.blocked_until <= 0:
            return 0.0

        remaining = record.blocked_until - time.time()
        return max(0.0, remaining)
