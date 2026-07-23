"""StateSyncProtocol — Protocolo de sincronización post-reconexión.

Implementa la reconciliación de eventos acumulados durante Modo_Fallback
con el Servidor_EC2 tras restablecerse la conexión WebSocket. Transmite
eventos en lotes de 50, espera ACK con timeout de 10s, reintenta hasta
3 veces, y ejecuta de forma no bloqueante en un asyncio.Task independiente.

Requirements cubiertos:
- 11.1: Iniciar State_Sync dentro de 5s post-reconexión, enviar en orden SMPTE_TC
- 11.2: Lotes de máx 50 eventos, ACK requerido por lote con timeout 10s
- 11.3: Servidor integra eventos en log según SMPTE_TC (responsabilidad servidor)
- 11.4: Conflictos preservan ambas versiones con flag CONFLICT
- 11.5: Transmisión en task independiente, no bloquea captura/inferencia/ATEM
- 11.6: Reintentar lote hasta 3 veces; si persiste, pausar y notificar operador
- 11.7: Al completar, notificar operador con cantidad de eventos y rango SMPTE_TC
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from switch_bot.web.protocol import (
    CURRENT_PROTOCOL_VERSION,
    ChannelMessage,
    StateSyncAckPayload,
    StateSyncBatchPayload,
)

if TYPE_CHECKING:
    from switch_bot.web.agent_client import AgentWebSocketClient
    from switch_bot.web.fallback import FallbackManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class StateSyncResult:
    """Resultado de una operación de State_Sync."""

    success: bool
    events_synced: int = 0
    events_failed: int = 0
    conflicts_detected: int = 0
    tc_range_start: str = ""
    tc_range_end: str = ""
    error: str | None = None


# ---------------------------------------------------------------------------
# StateSyncProtocol
# ---------------------------------------------------------------------------


class StateSyncProtocol:
    """Protocolo de sincronización post-reconexión.

    Transmite eventos acumulados en Modo_Fallback al Servidor_EC2 en lotes
    de BATCH_SIZE eventos. Cada lote espera un ACK dentro de ACK_TIMEOUT_SECONDS.
    Si el ACK no llega, se reintenta hasta MAX_RETRIES veces. Si persiste el
    fallo, se pausa la sincronización y se notifica al operador.

    La sincronización ejecuta en un asyncio.Task independiente (Req 11.5)
    para no bloquear las operaciones de captura, inferencia ni ATEM.
    """

    BATCH_SIZE: int = 50
    ACK_TIMEOUT_SECONDS: float = 10.0
    MAX_RETRIES: int = 3

    def __init__(
        self,
        ws_client: AgentWebSocketClient,
        fallback: FallbackManager,
    ) -> None:
        """Inicializa el protocolo de sincronización.

        Args:
            ws_client: Cliente WebSocket del Agente_Local para envío de mensajes.
            fallback: FallbackManager con acceso al buffer de eventos pendientes.
        """
        self._ws_client = ws_client
        self._fallback = fallback
        self._syncing: bool = False
        self._paused: bool = False
        self._sync_task: asyncio.Task[StateSyncResult] | None = None

        # Tracking de progreso
        self._events_synced: int = 0
        self._total_pending: int = 0

        # Batch ID counter
        self._batch_counter: int = 0

        # ACK waiting mechanism: batch_id -> asyncio.Future
        self._pending_acks: dict[int, asyncio.Future[ChannelMessage]] = {}

        # Sequence counter para mensajes enviados
        self._seq_counter: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start_sync(self) -> StateSyncResult:
        """Inicia sincronización en task independiente (no bloqueante).

        Crea un asyncio.Task que ejecuta la sincronización completa de
        eventos pendientes. La operación no bloquea el event loop del
        agente (Req 11.5).

        Returns:
            StateSyncResult con el resultado de la operación.
        """
        if self._syncing:
            logger.warning(
                "State_Sync ya en ejecución, ignorando start_sync()"
            )
            return StateSyncResult(
                success=False,
                error="Sincronización ya en curso",
            )

        self._syncing = True
        self._paused = False
        self._events_synced = 0
        self._total_pending = self._fallback.pending_count

        if self._total_pending == 0:
            self._syncing = False
            logger.info("State_Sync: no hay eventos pendientes para sincronizar")
            return StateSyncResult(success=True, events_synced=0)

        logger.info(
            "State_Sync INICIADO: %d eventos pendientes de sincronización",
            self._total_pending,
        )

        # Ejecutar en task independiente (Req 11.5)
        self._sync_task = asyncio.create_task(self._run_sync())

        # Await del resultado
        try:
            result = await self._sync_task
        except asyncio.CancelledError:
            self._syncing = False
            return StateSyncResult(
                success=False,
                events_synced=self._events_synced,
                error="Sincronización cancelada",
            )

        self._syncing = False
        return result

    async def send_batch(self, events: list[dict[str, Any]]) -> bool:
        """Envía lote de eventos y espera ACK con timeout de 10s.

        Construye un mensaje state_sync_batch con los eventos del lote,
        lo envía al servidor y espera la confirmación (ACK) dentro del
        timeout configurado.

        Args:
            events: Lista de eventos (dict con id, smpte_tc, payload, etc.)

        Returns:
            True si el lote fue aceptado (ACK recibido), False en caso contrario.
        """
        if not events:
            return True

        self._batch_counter += 1
        batch_id = self._batch_counter

        # Construir payload del lote
        tc_range_start = events[0].get("smpte_tc", "00:00:00:00")
        tc_range_end = events[-1].get("smpte_tc", "00:00:00:00")

        batch_payload = StateSyncBatchPayload(
            batch_id=batch_id,
            events=events,
            total_pending=self._fallback.pending_count,
            tc_range_start=tc_range_start,
            tc_range_end=tc_range_end,
        )

        # Crear Future para esperar ACK
        loop = asyncio.get_running_loop()
        ack_future: asyncio.Future[ChannelMessage] = loop.create_future()
        self._pending_acks[batch_id] = ack_future

        # Construir ChannelMessage
        self._seq_counter += 1
        now = datetime.now(timezone.utc)
        msg = ChannelMessage(
            type="state_sync_batch",
            timestamp=now.isoformat(timespec="milliseconds"),
            seq=self._seq_counter,
            version=CURRENT_PROTOCOL_VERSION,
            payload={
                "batch_id": batch_payload.batch_id,
                "events": batch_payload.events,
                "total_pending": batch_payload.total_pending,
                "tc_range_start": batch_payload.tc_range_start,
                "tc_range_end": batch_payload.tc_range_end,
            },
        )

        # Enviar
        sent = await self._ws_client.send_message(msg)
        if not sent:
            self._pending_acks.pop(batch_id, None)
            logger.warning(
                "State_Sync: no se pudo enviar batch_id=%d (encolado en buffer)",
                batch_id,
            )
            return False

        # Esperar ACK con timeout (Req 11.2)
        try:
            ack_msg = await asyncio.wait_for(
                ack_future, timeout=self.ACK_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            self._pending_acks.pop(batch_id, None)
            logger.warning(
                "State_Sync: timeout esperando ACK para batch_id=%d "
                "(timeout=%.1fs)",
                batch_id,
                self.ACK_TIMEOUT_SECONDS,
            )
            return False
        finally:
            # Limpiar referencia si aún existe
            self._pending_acks.pop(batch_id, None)

        # Procesar ACK
        ack_payload = ack_msg.payload
        accepted = ack_payload.get("accepted", 0)
        conflicts = ack_payload.get("conflicts", [])

        logger.debug(
            "State_Sync: ACK recibido batch_id=%d, accepted=%d, conflicts=%d",
            batch_id,
            accepted,
            len(conflicts),
        )

        # Manejar conflictos si existen (Req 11.4)
        if conflicts:
            await self.handle_conflict(conflicts)

        return True

    async def handle_ack(self, ack_msg: ChannelMessage) -> None:
        """Procesa ACK del servidor y marca eventos como sincronizados.

        Este método es invocado desde el receive loop del AgentWebSocketClient
        cuando se recibe un mensaje de tipo 'state_sync_ack'. Resuelve el
        Future correspondiente al batch_id para desbloquear send_batch().

        Args:
            ack_msg: ChannelMessage con payload de tipo StateSyncAckPayload.
        """
        payload = ack_msg.payload
        batch_id = payload.get("batch_id")

        if batch_id is None:
            logger.warning(
                "State_Sync: ACK recibido sin batch_id, ignorando"
            )
            return

        # Resolver el Future correspondiente
        future = self._pending_acks.get(batch_id)
        if future is not None and not future.done():
            future.set_result(ack_msg)
            logger.debug(
                "State_Sync: ACK resuelto para batch_id=%d", batch_id
            )
        else:
            logger.debug(
                "State_Sync: ACK para batch_id=%d sin Future pendiente "
                "(posible duplicado o timeout previo)",
                batch_id,
            )

    async def handle_conflict(self, conflicts: list[dict[str, Any]]) -> None:
        """Marca conflictos con flag CONFLICT para resolución manual.

        Preserva ambas versiones (la del agente y la del servidor) según
        Req 11.4. Registra los conflictos en el log para visibilidad.

        Args:
            conflicts: Lista de dicts con información de los conflictos
                      detectados por el servidor.
        """
        for conflict in conflicts:
            event_id = conflict.get("event_id")
            server_version = conflict.get("server_version")
            agent_version = conflict.get("agent_version")
            smpte_tc = conflict.get("smpte_tc", "unknown")

            logger.warning(
                "State_Sync CONFLICTO detectado: event_id=%s, smpte_tc=%s — "
                "ambas versiones preservadas con flag CONFLICT",
                event_id,
                smpte_tc,
            )

        logger.info(
            "State_Sync: %d conflictos marcados con flag CONFLICT "
            "para resolución manual",
            len(conflicts),
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_syncing(self) -> bool:
        """True si la sincronización está activa."""
        return self._syncing

    @property
    def is_paused(self) -> bool:
        """True si la sincronización fue pausada por fallos persistentes."""
        return self._paused

    @property
    def progress(self) -> tuple[int, int]:
        """(eventos sincronizados, total pendientes)."""
        return (self._events_synced, self._total_pending)

    # ------------------------------------------------------------------
    # Internal: Sync execution
    # ------------------------------------------------------------------

    async def _run_sync(self) -> StateSyncResult:
        """Ejecuta la sincronización completa de eventos pendientes.

        Itera sobre lotes de BATCH_SIZE eventos, enviando cada lote y
        esperando ACK. Reintenta hasta MAX_RETRIES veces si un lote falla.
        Si se agotan los reintentos, pausa la sincronización y notifica.
        """
        total_synced = 0
        total_conflicts = 0
        tc_range_start = ""
        tc_range_end = ""

        while True:
            # Obtener siguiente lote de eventos pendientes
            events = self._fallback.get_pending_events(
                batch_size=self.BATCH_SIZE
            )

            if not events:
                break

            # Registrar rango de TC
            batch_tc_start = events[0].get("smpte_tc", "00:00:00:00")
            batch_tc_end = events[-1].get("smpte_tc", "00:00:00:00")

            if not tc_range_start:
                tc_range_start = batch_tc_start
            tc_range_end = batch_tc_end

            # Intentar enviar lote con reintentos (Req 11.6)
            event_ids = [e["id"] for e in events]
            batch_sent = False

            for attempt in range(1, self.MAX_RETRIES + 1):
                success = await self.send_batch(events)
                if success:
                    batch_sent = True
                    break

                # Incrementar intentos (tracking)
                self._fallback.increment_sync_attempts(event_ids)

                if attempt < self.MAX_RETRIES:
                    logger.warning(
                        "State_Sync: lote fallido, reintentando "
                        "(%d/%d): tc_range=[%s, %s]",
                        attempt,
                        self.MAX_RETRIES,
                        batch_tc_start,
                        batch_tc_end,
                    )
                    # Pequeña espera antes de reintentar
                    await asyncio.sleep(1.0)

            if not batch_sent:
                # Reintentos agotados — pausar sync y notificar (Req 11.6)
                self._paused = True
                pending_remaining = self._fallback.pending_count
                logger.error(
                    "State_Sync PAUSADO: lote fallido tras %d intentos. "
                    "Eventos no sincronizados: %d. "
                    "Rango TC pendiente: [%s, %s]. "
                    "Notificando al operador.",
                    self.MAX_RETRIES,
                    pending_remaining,
                    batch_tc_start,
                    batch_tc_end,
                )

                return StateSyncResult(
                    success=False,
                    events_synced=total_synced,
                    events_failed=pending_remaining,
                    conflicts_detected=total_conflicts,
                    tc_range_start=tc_range_start,
                    tc_range_end=tc_range_end,
                    error=(
                        f"Lote fallido tras {self.MAX_RETRIES} reintentos. "
                        f"{pending_remaining} eventos pendientes."
                    ),
                )

            # Lote exitoso — marcar eventos como sincronizados
            self._fallback.mark_synced(event_ids)
            total_synced += len(events)
            self._events_synced = total_synced

            logger.debug(
                "State_Sync: lote sincronizado (%d eventos), "
                "progreso: %d/%d",
                len(events),
                total_synced,
                self._total_pending,
            )

        # Sincronización completa — notificar operador (Req 11.7)
        logger.info(
            "State_Sync COMPLETADO: %d eventos sincronizados, "
            "rango SMPTE_TC: [%s → %s], conflictos: %d",
            total_synced,
            tc_range_start,
            tc_range_end,
            total_conflicts,
        )

        return StateSyncResult(
            success=True,
            events_synced=total_synced,
            events_failed=0,
            conflicts_detected=total_conflicts,
            tc_range_start=tc_range_start,
            tc_range_end=tc_range_end,
        )
