"""FallbackManager — Gestión del Modo Fallback autónomo del Agente_Local.

Implementa almacenamiento persistente de eventos en SQLite con WAL mode
para garantizar durabilidad ante desconexiones. El agente opera autónomamente
con Motor_Decisión local mientras se restablece la conexión con el Servidor_EC2.

Requirements cubiertos:
- 4.1: 3 Heartbeats consecutivos fallan → activar Modo_Fallback automáticamente
- 4.2: En Modo_Fallback → mantener captura, inferencia, VAD, ATEM con Motor_Decisión local
- 4.3: Almacenar eventos en buffer persistente en disco (sobrevive reinicios),
       capacidad 24h, descarte FIFO de más antiguos si se alcanza límite
- 4.7: Si State_Sync falla → conservar eventos no transmitidos y reintentar
- 11.8: MAX 10,000 eventos; si se alcanza, sobrescribir más antiguos y registrar aviso
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

MAX_EVENTS: int = 10_000
MAX_DURATION_HOURS: int = 24

# ---------------------------------------------------------------------------
# Protocolo para Motor_Decisión local
# ---------------------------------------------------------------------------


class LocalDecisionEngine(Protocol):
    """Protocolo para el Motor_Decisión local del Agente."""

    def start(self) -> None:
        """Inicia el motor de decisión local."""
        ...

    def stop(self) -> None:
        """Detiene el motor de decisión local."""
        ...


# Tipo callback para notificar deactivation (inicia StateSyncProtocol)
OnDeactivateCallback = Callable[[], None]

# ---------------------------------------------------------------------------
# FallbackManager
# ---------------------------------------------------------------------------


class FallbackManager:
    """Gestiona el Modo Fallback autónomo del Agente_Local.

    Utiliza SQLite con WAL mode para persistencia de eventos durante
    desconexiones. Soporta hasta MAX_EVENTS (10,000) eventos con descarte
    FIFO de los más antiguos cuando se alcanza el límite.

    El buffer persistente sobrevive reinicios del proceso y tiene capacidad
    para almacenar hasta 24 horas de eventos de operación normal.
    """

    MAX_EVENTS: int = MAX_EVENTS
    MAX_DURATION_HOURS: int = MAX_DURATION_HOURS

    def __init__(
        self,
        db_path: Path,
        local_decision_engine: LocalDecisionEngine,
        on_deactivate: OnDeactivateCallback | None = None,
    ) -> None:
        """Inicializa el FallbackManager.

        Args:
            db_path: Ruta al archivo SQLite para persistencia de eventos.
            local_decision_engine: Motor de decisión local para operación autónoma.
            on_deactivate: Callback invocado al desactivar fallback para iniciar
                          State_Sync. Patrón callback para evitar acoplamiento
                          con módulo state_sync.
        """
        self._db_path = db_path
        self._local_engine = local_decision_engine
        self._on_deactivate = on_deactivate
        self._is_active: bool = False
        self._conn: sqlite3.Connection | None = None

        self._init_db()

    # ------------------------------------------------------------------
    # Inicialización de base de datos
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        """Inicializa la base de datos SQLite con WAL mode y crea tabla."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row

        # Activar WAL mode para mayor durabilidad y rendimiento concurrente
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")

        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS fallback_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                smpte_tc TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL,
                synced INTEGER NOT NULL DEFAULT 0,
                sync_attempts INTEGER NOT NULL DEFAULT 0
            )
        """)

        # Índice para consultas de pendientes ordenados por SMPTE TC
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_fallback_events_pending
            ON fallback_events (synced, smpte_tc)
        """)

        self._conn.commit()
        logger.info(
            "FallbackManager DB inicializada: %s (WAL mode)", self._db_path
        )

    # ------------------------------------------------------------------
    # Propiedades
    # ------------------------------------------------------------------

    @property
    def is_active(self) -> bool:
        """Indica si el Modo Fallback está activo."""
        return self._is_active

    @property
    def pending_count(self) -> int:
        """Número de eventos pendientes de sincronización."""
        if self._conn is None:
            return 0
        cursor = self._conn.execute(
            "SELECT COUNT(*) FROM fallback_events WHERE synced = 0"
        )
        row = cursor.fetchone()
        return row[0] if row else 0

    @property
    def total_event_count(self) -> int:
        """Número total de eventos almacenados (synced + pending)."""
        if self._conn is None:
            return 0
        cursor = self._conn.execute("SELECT COUNT(*) FROM fallback_events")
        row = cursor.fetchone()
        return row[0] if row else 0

    # ------------------------------------------------------------------
    # Activación / Desactivación
    # ------------------------------------------------------------------

    def activate(self) -> None:
        """Activa Modo Fallback. Inicia Motor_Decisión local.

        Se invoca cuando se detectan 3 heartbeats consecutivos fallidos.
        El agente pasa a operar autónomamente con el motor de decisión local.
        """
        if self._is_active:
            logger.warning("FallbackManager ya está activo, ignorando activate()")
            return

        self._is_active = True
        self._local_engine.start()
        logger.info(
            "Modo Fallback ACTIVADO — Motor_Decisión local iniciado. "
            "Eventos pendientes: %d",
            self.pending_count,
        )

    def deactivate(self) -> None:
        """Desactiva Modo Fallback. Inicia State_Sync via callback.

        Se invoca cuando se restablece la conexión con el servidor.
        Señaliza al StateSyncProtocol que inicie la reconciliación de eventos.
        """
        if not self._is_active:
            logger.warning(
                "FallbackManager no está activo, ignorando deactivate()"
            )
            return

        self._is_active = False
        self._local_engine.stop()
        logger.info(
            "Modo Fallback DESACTIVADO — Eventos pendientes para sync: %d",
            self.pending_count,
        )

        if self._on_deactivate is not None:
            self._on_deactivate()

    # ------------------------------------------------------------------
    # Almacenamiento de eventos
    # ------------------------------------------------------------------

    def store_event(self, event: dict[str, Any], smpte_tc: str) -> None:
        """Almacena evento en buffer persistente.

        Si se alcanza MAX_EVENTS, descarta los eventos más antiguos (FIFO)
        antes de insertar el nuevo evento. Registra aviso cuando se activa
        el descarte (Req 11.8).

        Args:
            event: Diccionario con datos del evento (será serializado a JSON).
            smpte_tc: Timecode SMPTE del frame asociado al evento.
        """
        if self._conn is None:
            logger.error("store_event: conexión DB no disponible")
            return

        event_type = event.get("type", "unknown")
        payload_json = json.dumps(event)
        created_at = datetime.now(timezone.utc).isoformat()

        # Verificar límite y aplicar descarte FIFO si es necesario
        current_count = self.total_event_count
        if current_count >= self.MAX_EVENTS:
            self._evict_oldest()

        self._conn.execute(
            """
            INSERT INTO fallback_events (smpte_tc, event_type, payload, created_at, synced, sync_attempts)
            VALUES (?, ?, ?, ?, 0, 0)
            """,
            (smpte_tc, event_type, payload_json, created_at),
        )
        self._conn.commit()

        logger.debug(
            "Evento almacenado: type=%s, tc=%s, total=%d",
            event_type,
            smpte_tc,
            self.total_event_count,
        )

    def _evict_oldest(self) -> None:
        """Descarta el evento más antiguo (FIFO) para liberar espacio.

        Registra un aviso en el log cuando se activa el descarte (Req 11.8).
        """
        if self._conn is None:
            return

        # Eliminar el registro más antiguo por id (autoincrement = orden de inserción)
        self._conn.execute("""
            DELETE FROM fallback_events
            WHERE id = (SELECT id FROM fallback_events ORDER BY id ASC LIMIT 1)
        """)
        self._conn.commit()

        logger.warning(
            "Descarte FIFO activado: MAX_EVENTS=%d alcanzado, "
            "evento más antiguo eliminado",
            self.MAX_EVENTS,
        )

    # ------------------------------------------------------------------
    # Recuperación de eventos pendientes
    # ------------------------------------------------------------------

    def get_pending_events(self, batch_size: int = 50) -> list[dict[str, Any]]:
        """Retorna lote de eventos pendientes de sincronización.

        Los eventos se ordenan por SMPTE TC ascendente para garantizar
        que la reconciliación con el servidor respeta el orden temporal.

        Args:
            batch_size: Número máximo de eventos a retornar por lote.

        Returns:
            Lista de diccionarios con id, smpte_tc, event_type, payload,
            created_at y sync_attempts de cada evento pendiente.
        """
        if self._conn is None:
            return []

        cursor = self._conn.execute(
            """
            SELECT id, smpte_tc, event_type, payload, created_at, sync_attempts
            FROM fallback_events
            WHERE synced = 0
            ORDER BY smpte_tc ASC
            LIMIT ?
            """,
            (batch_size,),
        )

        events: list[dict[str, Any]] = []
        for row in cursor.fetchall():
            events.append({
                "id": row["id"],
                "smpte_tc": row["smpte_tc"],
                "event_type": row["event_type"],
                "payload": json.loads(row["payload"]),
                "created_at": row["created_at"],
                "sync_attempts": row["sync_attempts"],
            })

        return events

    # ------------------------------------------------------------------
    # Marcado de eventos sincronizados
    # ------------------------------------------------------------------

    def mark_synced(self, event_ids: list[int]) -> None:
        """Marca eventos como sincronizados exitosamente.

        Args:
            event_ids: Lista de IDs de eventos que fueron transmitidos
                      y confirmados por el servidor.
        """
        if self._conn is None:
            logger.error("mark_synced: conexión DB no disponible")
            return

        if not event_ids:
            return

        placeholders = ",".join("?" for _ in event_ids)
        self._conn.execute(
            f"UPDATE fallback_events SET synced = 1 WHERE id IN ({placeholders})",
            event_ids,
        )
        self._conn.commit()

        logger.info(
            "Eventos marcados como sincronizados: %d IDs", len(event_ids)
        )

    # ------------------------------------------------------------------
    # Incremento de intentos de sync
    # ------------------------------------------------------------------

    def increment_sync_attempts(self, event_ids: list[int]) -> None:
        """Incrementa el contador de intentos de sincronización.

        Útil para tracking de reintentos cuando State_Sync falla (Req 4.7).

        Args:
            event_ids: Lista de IDs de eventos cuyos intentos se incrementan.
        """
        if self._conn is None:
            return

        if not event_ids:
            return

        placeholders = ",".join("?" for _ in event_ids)
        self._conn.execute(
            f"""
            UPDATE fallback_events
            SET sync_attempts = sync_attempts + 1
            WHERE id IN ({placeholders})
            """,
            event_ids,
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Limpieza
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Cierra la conexión a la base de datos."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
            logger.info("FallbackManager DB cerrada")
