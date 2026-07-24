"""SessionManagerWeb — Gestión centralizada de sesiones multi-operador web.

Extiende SessionManager para soportar múltiples operadores concurrentes,
persistencia periódica en SQLite, propagación de estado vía WebSocket,
resolución de conflictos first-write-wins y recuperación post-reinicio.

Requirements cubiertos: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from switch_bot.engines.session_manager import SessionManager
from switch_bot.web.hub import WebSocketHub
from switch_bot.web.protocol import ChannelMessage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enumeraciones y dataclasses
# ---------------------------------------------------------------------------


class SessionState(str, Enum):
    """Estados válidos del ciclo de vida de una sesión."""

    CREATED = "created"
    STARTED = "started"
    PAUSED = "paused"
    FINALIZED = "finalized"


# Transiciones de estado válidas: estado_actual → {estados_destino}
VALID_TRANSITIONS: dict[SessionState, set[SessionState]] = {
    SessionState.CREATED: {SessionState.STARTED},
    SessionState.STARTED: {SessionState.PAUSED, SessionState.FINALIZED},
    SessionState.PAUSED: {SessionState.STARTED, SessionState.FINALIZED},
    SessionState.FINALIZED: set(),
}


@dataclass
class Session:
    """Representa una sesión de producción multi-operador.

    Attributes:
        session_id: Identificador UUID v4 único de la sesión.
        state: Estado actual del ciclo de vida.
        config: Configuración inicial de la sesión.
        creator_role: Rol del usuario que creó la sesión.
        agents: IDs de operadores conectados a esta sesión.
        created_at: Timestamp de creación ISO 8601.
        updated_at: Timestamp de última modificación ISO 8601.
        events: Historial de eventos de la sesión.
        metadata: Metadata adicional de la sesión.
    """

    session_id: str
    state: SessionState
    config: dict
    creator_role: str
    agents: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="milliseconds"))
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="milliseconds"))
    events: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class ConsolidationResult:
    """Resultado de la consolidación de una sesión finalizada.

    Attributes:
        success: True si la consolidación fue exitosa.
        session_id: ID de la sesión consolidada.
        logs_path: Ruta al archivo de logs consolidado.
        edl_path: Ruta al archivo EDL consolidado.
        metadata_path: Ruta al archivo de metadata consolidado.
        error_message: Mensaje de error si la consolidación falló.
        attempts: Número de intentos realizados.
    """

    success: bool
    session_id: str
    logs_path: Path | None = None
    edl_path: Path | None = None
    metadata_path: Path | None = None
    error_message: str = ""
    attempts: int = 1


# ---------------------------------------------------------------------------
# Excepciones
# ---------------------------------------------------------------------------


class SessionCreationError(Exception):
    """Error al crear una sesión."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class InvalidStateTransitionError(Exception):
    """Error al intentar una transición de estado inválida."""

    def __init__(self, current: SessionState, target: SessionState) -> None:
        super().__init__(
            f"Transición inválida: {current.value} → {target.value}"
        )
        self.current = current
        self.target = target


class SessionNotFoundError(Exception):
    """Error cuando una sesión no existe."""

    def __init__(self, session_id: str) -> None:
        super().__init__(f"Sesión no encontrada: {session_id}")
        self.session_id = session_id


class SessionFullError(Exception):
    """Error cuando una sesión alcanzó el máximo de agentes."""

    def __init__(self, session_id: str, max_agents: int) -> None:
        super().__init__(
            f"Sesión {session_id} alcanzó el máximo de {max_agents} agentes"
        )
        self.session_id = session_id
        self.max_agents = max_agents


# ---------------------------------------------------------------------------
# SessionManagerWeb
# ---------------------------------------------------------------------------


class SessionManagerWeb(SessionManager):
    """Extiende SessionManager para gestión multi-operador web.

    Responsabilidades:
    - Crear sesiones con UUID v4 (solo rol 'director').
    - Gestionar unión de agentes con límite MAX_AGENTS=8.
    - Propagar estado a agentes y SPAs en <500ms.
    - Resolver conflictos con first-write-wins.
    - Consolidar logs/EDL/metadata al finalizar (retry 3x).
    - Persistir estado periódicamente cada 5s en SQLite.
    - Recuperar sesiones activas post-reinicio (máx 5s pérdida).
    - Validar transiciones de estado del ciclo de vida.

    Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9
    """

    PERSIST_INTERVAL_SECONDS: float = 5.0
    MAX_AGENTS: int = 8
    CONSOLIDATION_MAX_RETRIES: int = 3
    CONSOLIDATION_RETRY_DELAY: float = 2.0

    def __init__(self, hub: WebSocketHub, storage_path: Path) -> None:
        """Inicializa SessionManagerWeb.

        Args:
            hub: WebSocketHub para comunicación con agentes y SPAs.
            storage_path: Ruta al directorio de almacenamiento persistente.
        """
        super().__init__()
        self._hub = hub
        self._storage_path = storage_path
        self._active_sessions: dict[str, Session] = {}
        self._persist_task: asyncio.Task | None = None
        self._db_path = storage_path / "sessions.db"
        self._running = False

        # Asegurar directorio de almacenamiento
        self._storage_path.mkdir(parents=True, exist_ok=True)

        # Inicializar SQLite
        self._init_db()

    # ------------------------------------------------------------------
    # Inicialización de base de datos
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        """Crea la tabla de sesiones en SQLite si no existe."""
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    config TEXT NOT NULL,
                    creator_role TEXT NOT NULL,
                    agents TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    events TEXT NOT NULL,
                    metadata TEXT NOT NULL
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Ciclo de vida del persistence loop
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Inicia el loop de persistencia periódica."""
        if self._running:
            return
        self._running = True
        self._persist_task = asyncio.create_task(self._persistence_loop())
        logger.info("SessionManagerWeb iniciado (persist interval=%.1fs)", self.PERSIST_INTERVAL_SECONDS)

    async def stop(self) -> None:
        """Detiene el loop de persistencia periódica."""
        self._running = False
        if self._persist_task and not self._persist_task.done():
            self._persist_task.cancel()
            try:
                await self._persist_task
            except asyncio.CancelledError:
                pass
        self._persist_task = None
        # Persistir estado final
        self._persist_all_sessions()
        logger.info("SessionManagerWeb detenido")

    async def _persistence_loop(self) -> None:
        """Loop que persiste el estado de sesiones cada PERSIST_INTERVAL_SECONDS."""
        while self._running:
            try:
                await asyncio.sleep(self.PERSIST_INTERVAL_SECONDS)
                self._persist_all_sessions()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error en persistence loop")

    # ------------------------------------------------------------------
    # Persistencia SQLite
    # ------------------------------------------------------------------

    def _persist_all_sessions(self) -> None:
        """Persiste todas las sesiones activas en SQLite."""
        if not self._active_sessions:
            return

        conn = sqlite3.connect(str(self._db_path))
        try:
            for session in self._active_sessions.values():
                conn.execute(
                    """
                    INSERT OR REPLACE INTO sessions
                    (session_id, state, config, creator_role, agents,
                     created_at, updated_at, events, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session.session_id,
                        session.state.value,
                        json.dumps(session.config),
                        session.creator_role,
                        json.dumps(session.agents),
                        session.created_at,
                        session.updated_at,
                        json.dumps(session.events),
                        json.dumps(session.metadata),
                    ),
                )
            conn.commit()
            logger.debug(
                "Persistidas %d sesiones en SQLite", len(self._active_sessions)
            )
        except Exception:
            logger.exception("Error persistiendo sesiones en SQLite")
        finally:
            conn.close()

    def _persist_session(self, session: Session) -> None:
        """Persiste una sesión individual en SQLite."""
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO sessions
                (session_id, state, config, creator_role, agents,
                 created_at, updated_at, events, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.session_id,
                    session.state.value,
                    json.dumps(session.config),
                    session.creator_role,
                    json.dumps(session.agents),
                    session.created_at,
                    session.updated_at,
                    json.dumps(session.events),
                    json.dumps(session.metadata),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Creación de sesión (Req 8.3)
    # ------------------------------------------------------------------

    async def create_session(self, config: dict, creator_role: str) -> Session:
        """Crea una nueva sesión de producción.

        Solo los usuarios con rol 'director' o 'administrador' pueden crear
        sesiones. Se asigna un UUID v4 único.

        Args:
            config: Configuración inicial (modo video, backend IA, guión).
            creator_role: Rol del usuario que solicita la creación.

        Returns:
            Session creada con estado CREATED.

        Raises:
            SessionCreationError: Si el rol no tiene permisos.
        """
        if creator_role not in ("director", "administrador"):
            raise SessionCreationError(
                f"Rol '{creator_role}' no tiene permiso para crear sesiones. "
                "Solo 'director' o 'administrador' pueden crear sesiones."
            )

        session_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")

        session = Session(
            session_id=session_id,
            state=SessionState.CREATED,
            config=config,
            creator_role=creator_role,
            agents=[],
            created_at=now,
            updated_at=now,
            events=[],
            metadata={},
        )

        self._active_sessions[session_id] = session
        self._persist_session(session)

        logger.info(
            "Sesión creada: id=%s, rol=%s, config=%s",
            session_id,
            creator_role,
            config,
        )
        return session

    # ------------------------------------------------------------------
    # Unión de agentes (Req 8.4)
    # ------------------------------------------------------------------

    async def join_session(self, session_id: str, operator_id: str) -> bool:
        """Registra un agente en una sesión activa.

        Args:
            session_id: ID de la sesión a unirse.
            operator_id: ID del operador/agente.

        Returns:
            True si el agente se unió exitosamente.

        Raises:
            SessionNotFoundError: Si la sesión no existe.
            SessionFullError: Si se alcanzó MAX_AGENTS.
        """
        session = self._active_sessions.get(session_id)
        if session is None:
            raise SessionNotFoundError(session_id)

        if session.state == SessionState.FINALIZED:
            logger.warning(
                "Intento de unirse a sesión finalizada: session_id=%s, operator_id=%s",
                session_id,
                operator_id,
            )
            return False

        # Si el agente ya está en la sesión, retornar True sin duplicar
        if operator_id in session.agents:
            logger.debug(
                "Agente %s ya está en sesión %s", operator_id, session_id
            )
            return True

        if len(session.agents) >= self.MAX_AGENTS:
            raise SessionFullError(session_id, self.MAX_AGENTS)

        session.agents.append(operator_id)
        session.updated_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")

        logger.info(
            "Agente %s unido a sesión %s (%d/%d agentes)",
            operator_id,
            session_id,
            len(session.agents),
            self.MAX_AGENTS,
        )
        return True

    # ------------------------------------------------------------------
    # Propagación de estado (Req 8.2)
    # ------------------------------------------------------------------

    async def propagate_state(self, session_id: str) -> None:
        """Propaga el estado de la sesión a todos los conectados.

        Envía el estado actual a todos los agentes y SPAs conectados.
        Debe completarse en <500ms (Req 8.2).

        Args:
            session_id: ID de la sesión cuyo estado propagar.

        Raises:
            SessionNotFoundError: Si la sesión no existe.
        """
        session = self._active_sessions.get(session_id)
        if session is None:
            raise SessionNotFoundError(session_id)

        state_payload = {
            "session_id": session.session_id,
            "state": session.state.value,
            "agents": session.agents,
            "config": session.config,
            "updated_at": session.updated_at,
            "metadata": session.metadata,
        }

        message = ChannelMessage(
            type="state_update",
            timestamp=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            seq=0,
            version="1.0",
            payload=state_payload,
        )

        # Propagar a agentes y SPAs concurrentemente
        await asyncio.gather(
            self._hub.broadcast_to_agents(message),
            self._hub.broadcast_to_spas(message),
        )

        logger.debug("Estado propagado para sesión %s", session_id)

    # ------------------------------------------------------------------
    # Resolución de conflictos (Req 8.8)
    # ------------------------------------------------------------------

    async def handle_conflict(self, session_id: str, commands: list) -> dict:
        """Resuelve conflictos de comandos simultáneos con first-write-wins.

        Cuando dos o más operadores emiten comandos sobre el mismo recurso,
        se acepta el primero en llegar y se notifica rechazo a los demás.

        Args:
            session_id: ID de la sesión donde ocurre el conflicto.
            commands: Lista de comandos conflictivos, cada uno con
                      'operator_id', 'timestamp', 'resource' y 'action'.

        Returns:
            dict con 'accepted' (comando ganador) y 'rejected' (rechazados).

        Raises:
            SessionNotFoundError: Si la sesión no existe.
        """
        session = self._active_sessions.get(session_id)
        if session is None:
            raise SessionNotFoundError(session_id)

        if not commands:
            return {"accepted": None, "rejected": []}

        # Ordenar por timestamp (first-write-wins)
        sorted_commands = sorted(commands, key=lambda c: c.get("timestamp", ""))

        accepted = sorted_commands[0]
        rejected = sorted_commands[1:]

        # Registrar evento de conflicto
        session.events.append({
            "type": "conflict_resolved",
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "accepted_operator": accepted.get("operator_id"),
            "rejected_operators": [c.get("operator_id") for c in rejected],
            "resource": accepted.get("resource"),
        })
        session.updated_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")

        # Notificar a operadores rechazados
        for cmd in rejected:
            operator_id = cmd.get("operator_id")
            if operator_id:
                conflict_msg = ChannelMessage(
                    type="session_control",
                    timestamp=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                    seq=0,
                    version="1.0",
                    payload={
                        "event": "command_rejected",
                        "reason": "conflict_first_write_wins",
                        "accepted_operator": accepted.get("operator_id"),
                        "resource": accepted.get("resource"),
                    },
                )
                await self._hub.send_to_agent(operator_id, conflict_msg)

        logger.info(
            "Conflicto resuelto en sesión %s: aceptado=%s, rechazados=%d",
            session_id,
            accepted.get("operator_id"),
            len(rejected),
        )

        return {"accepted": accepted, "rejected": rejected}

    # ------------------------------------------------------------------
    # Finalización de sesión (Req 8.5, 8.9)
    # ------------------------------------------------------------------

    async def finalize_session(self, session_id: str) -> ConsolidationResult:
        """Finaliza una sesión y consolida logs/EDL/metadata.

        Realiza hasta 3 intentos de consolidación con intervalo de 2s
        entre reintentos. Notifica al operador si falla.

        Args:
            session_id: ID de la sesión a finalizar.

        Returns:
            ConsolidationResult con el resultado de la consolidación.

        Raises:
            SessionNotFoundError: Si la sesión no existe.
            InvalidStateTransitionError: Si la transición no es válida.
        """
        session = self._active_sessions.get(session_id)
        if session is None:
            raise SessionNotFoundError(session_id)

        # Validar transición de estado
        if SessionState.FINALIZED not in VALID_TRANSITIONS.get(session.state, set()):
            raise InvalidStateTransitionError(session.state, SessionState.FINALIZED)

        # Intentar consolidación con retry
        last_error = ""
        for attempt in range(1, self.CONSOLIDATION_MAX_RETRIES + 1):
            try:
                result = await self._consolidate(session, attempt)
                if result.success:
                    # Transición exitosa
                    session.state = SessionState.FINALIZED
                    session.updated_at = datetime.now(timezone.utc).isoformat(
                        timespec="milliseconds"
                    )
                    self._persist_session(session)

                    # Propagar estado finalizado
                    await self.propagate_state(session_id)

                    logger.info(
                        "Sesión %s finalizada exitosamente (intento %d)",
                        session_id,
                        attempt,
                    )
                    return result
            except Exception as e:
                last_error = str(e)
                logger.warning(
                    "Consolidación falló para sesión %s (intento %d/%d): %s",
                    session_id,
                    attempt,
                    self.CONSOLIDATION_MAX_RETRIES,
                    e,
                )
                if attempt < self.CONSOLIDATION_MAX_RETRIES:
                    await asyncio.sleep(self.CONSOLIDATION_RETRY_DELAY)

        # Todos los reintentos fallaron — notificar al operador
        logger.error(
            "Consolidación falló tras %d intentos para sesión %s: %s",
            self.CONSOLIDATION_MAX_RETRIES,
            session_id,
            last_error,
        )

        # Notificar a SPAs del fallo
        error_msg = ChannelMessage(
            type="session_control",
            timestamp=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            seq=0,
            version="1.0",
            payload={
                "event": "consolidation_failed",
                "session_id": session_id,
                "error": last_error,
                "attempts": self.CONSOLIDATION_MAX_RETRIES,
            },
        )
        await self._hub.broadcast_to_spas(error_msg)

        return ConsolidationResult(
            success=False,
            session_id=session_id,
            error_message=last_error,
            attempts=self.CONSOLIDATION_MAX_RETRIES,
        )

    async def _consolidate(self, session: Session, attempt: int) -> ConsolidationResult:
        """Ejecuta la consolidación de logs, EDL y metadata.

        Args:
            session: Sesión a consolidar.
            attempt: Número de intento actual.

        Returns:
            ConsolidationResult con rutas de archivos generados.
        """
        session_dir = self._storage_path / session.session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        # Escribir logs
        logs_path = session_dir / "session_log.jsonl"
        with open(logs_path, "w", encoding="utf-8") as f:
            for event in session.events:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")

        # Escribir EDL placeholder
        edl_path = session_dir / "session.edl"
        with open(edl_path, "w", encoding="utf-8") as f:
            f.write(f"TITLE: {session.session_id}\n")
            f.write("FCM: NON-DROP FRAME\n\n")

        # Escribir metadata
        metadata_path = session_dir / "metadata.json"
        with open(metadata_path, "w", encoding="utf-8") as f:
            metadata = {
                "session_id": session.session_id,
                "state": session.state.value,
                "config": session.config,
                "creator_role": session.creator_role,
                "agents": session.agents,
                "created_at": session.created_at,
                "finalized_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "total_events": len(session.events),
            }
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        return ConsolidationResult(
            success=True,
            session_id=session.session_id,
            logs_path=logs_path,
            edl_path=edl_path,
            metadata_path=metadata_path,
            attempts=attempt,
        )

    # ------------------------------------------------------------------
    # Recuperación post-reinicio (Req 8.6)
    # ------------------------------------------------------------------

    async def recover_sessions(self) -> list[Session]:
        """Recupera sesiones activas desde SQLite post-reinicio.

        Carga sesiones que no estén finalizadas del almacenamiento
        persistente. Máx 5s de pérdida de datos (Req 8.6).

        Returns:
            Lista de sesiones recuperadas.
        """
        recovered: list[Session] = []

        conn = sqlite3.connect(str(self._db_path))
        try:
            cursor = conn.execute(
                """
                SELECT session_id, state, config, creator_role, agents,
                       created_at, updated_at, events, metadata
                FROM sessions
                WHERE state != ?
                """,
                (SessionState.FINALIZED.value,),
            )

            for row in cursor.fetchall():
                try:
                    session = Session(
                        session_id=row[0],
                        state=SessionState(row[1]),
                        config=json.loads(row[2]),
                        creator_role=row[3],
                        agents=json.loads(row[4]),
                        created_at=row[5],
                        updated_at=row[6],
                        events=json.loads(row[7]),
                        metadata=json.loads(row[8]),
                    )
                    self._active_sessions[session.session_id] = session
                    recovered.append(session)
                except (json.JSONDecodeError, ValueError) as e:
                    logger.error(
                        "Error recuperando sesión %s: %s", row[0], e
                    )
        finally:
            conn.close()

        if recovered:
            logger.info(
                "Recuperadas %d sesiones activas post-reinicio",
                len(recovered),
            )
        else:
            logger.info("No hay sesiones activas para recuperar")

        return recovered

    # ------------------------------------------------------------------
    # Transiciones de estado (Req 8.1)
    # ------------------------------------------------------------------

    async def transition_state(
        self, session_id: str, target_state: SessionState
    ) -> Session:
        """Realiza una transición de estado validada.

        Args:
            session_id: ID de la sesión.
            target_state: Estado destino deseado.

        Returns:
            Session con el nuevo estado.

        Raises:
            SessionNotFoundError: Si la sesión no existe.
            InvalidStateTransitionError: Si la transición no es válida.
        """
        session = self._active_sessions.get(session_id)
        if session is None:
            raise SessionNotFoundError(session_id)

        valid_targets = VALID_TRANSITIONS.get(session.state, set())
        if target_state not in valid_targets:
            raise InvalidStateTransitionError(session.state, target_state)

        old_state = session.state
        session.state = target_state
        session.updated_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")

        # Registrar evento de transición
        session.events.append({
            "type": "state_transition",
            "timestamp": session.updated_at,
            "from_state": old_state.value,
            "to_state": target_state.value,
        })

        # Propagar nuevo estado
        await self.propagate_state(session_id)

        logger.info(
            "Sesión %s: transición %s → %s",
            session_id,
            old_state.value,
            target_state.value,
        )
        return session

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------

    def get_session(self, session_id: str) -> Session | None:
        """Retorna una sesión activa por su ID, o None si no existe."""
        return self._active_sessions.get(session_id)

    @property
    def active_session_count(self) -> int:
        """Número de sesiones activas (no finalizadas)."""
        return len(self._active_sessions)

    def remove_agent_from_session(
        self, session_id: str, operator_id: str
    ) -> bool:
        """Remueve un agente de una sesión (desconexión).

        Registra el evento de desconexión sin finalizar la sesión (Req 8.7).

        Args:
            session_id: ID de la sesión.
            operator_id: ID del operador a remover.

        Returns:
            True si el agente fue removido, False si no estaba.
        """
        session = self._active_sessions.get(session_id)
        if session is None:
            return False

        if operator_id not in session.agents:
            return False

        session.agents.remove(operator_id)
        session.updated_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")

        # Registrar evento de desconexión
        session.events.append({
            "type": "agent_disconnected",
            "timestamp": session.updated_at,
            "operator_id": operator_id,
        })

        logger.info(
            "Agente %s removido de sesión %s (%d agentes restantes)",
            operator_id,
            session_id,
            len(session.agents),
        )
        return True
