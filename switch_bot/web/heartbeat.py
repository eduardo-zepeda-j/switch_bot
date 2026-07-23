"""HeartbeatManager — Detección de conectividad del servidor.

Monitorea heartbeats recibidos de Agentes_Locales, genera ACKs con timestamp,
y detecta desconexiones cuando un agente no envía heartbeat dentro del timeout.

Requirements cubiertos:
- 10.1: Agente_Local envía heartbeat cada 1 segundo
- 10.2: Servidor responde heartbeat_ack dentro de 500ms
- 10.4: Servidor marca agente como desconectado tras 5s sin heartbeat
- 10.5: Heartbeat incluye timestamp ISO 8601 ms y seq monotónicamente creciente
- 10.6: Descartar heartbeats con seq <= último procesado (out-of-order)
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from datetime import datetime, timezone
from typing import Any

from switch_bot.web.protocol import (
    CURRENT_PROTOCOL_VERSION,
    ChannelMessage,
)

logger = logging.getLogger(__name__)


class HeartbeatManager:
    """Gestiona heartbeats bidireccionales y detección de conectividad.

    El servidor monitorea heartbeats entrantes de cada agente y:
    - Genera ACKs con timestamp para cada heartbeat válido
    - Detecta agentes desconectados si no recibe heartbeat en 5 segundos
    - Descarta heartbeats con seq <= último procesado (out-of-order)

    Args:
        hub: WebSocketHub para enviar mensajes a agentes/SPAs.
        on_disconnect: Callback async invocado con operator_id cuando se
            detecta pérdida de conectividad.
    """

    INTERVAL_SECONDS: float = 1.0
    TIMEOUT_CYCLES: int = 3  # 3 ciclos fallidos = desconexión (client-side)
    SERVER_TIMEOUT_SECONDS: float = 5.0  # Servidor detecta en 5s

    def __init__(
        self,
        hub: Any,
        on_disconnect: Callable[[str], Coroutine[Any, Any, None]],
    ):
        self._hub = hub
        self._on_disconnect = on_disconnect
        self._last_heartbeat: dict[str, datetime] = {}
        self._sequence_numbers: dict[str, int] = {}
        self._monitoring_task: asyncio.Task[None] | None = None
        self._running: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start_monitoring(self) -> None:
        """Inicia tarea periódica de verificación de heartbeats.

        Ejecuta un loop asyncio que cada INTERVAL_SECONDS verifica si
        algún agente ha excedido SERVER_TIMEOUT_SECONDS sin enviar heartbeat.
        """
        if self._running:
            logger.warning("HeartbeatManager ya está en ejecución")
            return

        self._running = True
        self._monitoring_task = asyncio.create_task(self._monitor_loop())
        logger.info(
            "HeartbeatManager iniciado (intervalo=%.1fs, timeout=%.1fs)",
            self.INTERVAL_SECONDS,
            self.SERVER_TIMEOUT_SECONDS,
        )

    async def stop_monitoring(self) -> None:
        """Detiene el monitoreo y cancela la tarea periódica."""
        self._running = False
        if self._monitoring_task is not None:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass
            self._monitoring_task = None
        logger.info("HeartbeatManager detenido")

    # ------------------------------------------------------------------
    # Agent registration
    # ------------------------------------------------------------------

    def register_agent(self, operator_id: str) -> None:
        """Registra un agente para monitoreo de heartbeat.

        Inicializa el timestamp de último heartbeat al momento actual
        y el seq number a -1 (acepta cualquier seq >= 0 como primer heartbeat).

        Args:
            operator_id: ID único del operador/agente.
        """
        self._last_heartbeat[operator_id] = datetime.now(timezone.utc)
        self._sequence_numbers[operator_id] = -1
        logger.info("Agente registrado para heartbeat: %s", operator_id)

    def unregister_agent(self, operator_id: str) -> None:
        """Desregistra un agente del monitoreo de heartbeat.

        Se usa cuando un agente se desconecta explícitamente (no por timeout).

        Args:
            operator_id: ID único del operador/agente.
        """
        self._last_heartbeat.pop(operator_id, None)
        self._sequence_numbers.pop(operator_id, None)
        logger.info("Agente desregistrado de heartbeat: %s", operator_id)

    # ------------------------------------------------------------------
    # Heartbeat processing
    # ------------------------------------------------------------------

    async def process_heartbeat(
        self, operator_id: str, msg: ChannelMessage
    ) -> ChannelMessage | None:
        """Procesa heartbeat recibido y genera ACK con timestamp.

        Valida el número de secuencia contra el último procesado para
        detectar paquetes fuera de orden. Si el seq es válido, actualiza
        el último timestamp visto y retorna un heartbeat_ack.

        Args:
            operator_id: ID del operador que envió el heartbeat.
            msg: ChannelMessage de tipo heartbeat recibido.

        Returns:
            ChannelMessage de tipo heartbeat_ack si el heartbeat es válido,
            None si se descarta por seq out-of-order.
        """
        incoming_seq = msg.seq

        # Verificar out-of-order: descartar si seq <= último procesado
        last_seq = self._sequence_numbers.get(operator_id, -1)
        if incoming_seq <= last_seq:
            logger.debug(
                "Heartbeat out-of-order descartado: operator_id=%s, "
                "seq=%d <= last_seq=%d",
                operator_id,
                incoming_seq,
                last_seq,
            )
            return None

        # Actualizar estado
        now = datetime.now(timezone.utc)
        self._last_heartbeat[operator_id] = now
        self._sequence_numbers[operator_id] = incoming_seq

        # Generar ACK con timestamp del servidor
        ack = ChannelMessage(
            type="heartbeat_ack",
            timestamp=now.isoformat(timespec="milliseconds"),
            seq=incoming_seq,
            version=CURRENT_PROTOCOL_VERSION,
            payload={
                "sender_timestamp": now.isoformat(timespec="milliseconds"),
                "seq": incoming_seq,
            },
        )

        logger.debug(
            "Heartbeat procesado: operator_id=%s, seq=%d",
            operator_id,
            incoming_seq,
        )
        return ack

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def is_agent_alive(self, operator_id: str) -> bool:
        """True si el agente ha respondido dentro del timeout.

        Args:
            operator_id: ID del operador a verificar.

        Returns:
            True si el último heartbeat fue recibido hace menos de
            SERVER_TIMEOUT_SECONDS, False en caso contrario o si el
            agente no está registrado.
        """
        last_seen = self._last_heartbeat.get(operator_id)
        if last_seen is None:
            return False

        elapsed = (datetime.now(timezone.utc) - last_seen).total_seconds()
        return elapsed < self.SERVER_TIMEOUT_SECONDS

    def get_last_seen(self, operator_id: str) -> datetime | None:
        """Timestamp del último heartbeat válido recibido.

        Args:
            operator_id: ID del operador.

        Returns:
            datetime UTC del último heartbeat, o None si no está registrado.
        """
        return self._last_heartbeat.get(operator_id)

    # ------------------------------------------------------------------
    # Internal monitoring loop
    # ------------------------------------------------------------------

    async def _monitor_loop(self) -> None:
        """Loop interno que verifica timeouts cada INTERVAL_SECONDS."""
        while self._running:
            try:
                await asyncio.sleep(self.INTERVAL_SECONDS)
                await self._check_timeouts()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error en monitor loop de heartbeat")

    async def _check_timeouts(self) -> None:
        """Verifica si algún agente ha excedido el timeout.

        Para cada agente que excede SERVER_TIMEOUT_SECONDS sin heartbeat,
        invoca el callback on_disconnect y lo desregistra del monitoreo.
        """
        now = datetime.now(timezone.utc)
        disconnected: list[str] = []

        for operator_id, last_seen in self._last_heartbeat.items():
            elapsed = (now - last_seen).total_seconds()
            if elapsed >= self.SERVER_TIMEOUT_SECONDS:
                logger.warning(
                    "Agente timeout detectado: operator_id=%s, "
                    "última vez visto hace %.1fs",
                    operator_id,
                    elapsed,
                )
                disconnected.append(operator_id)

        for operator_id in disconnected:
            # Remover del tracking antes de invocar callback
            self._last_heartbeat.pop(operator_id, None)
            self._sequence_numbers.pop(operator_id, None)
            try:
                await self._on_disconnect(operator_id)
            except Exception:
                logger.exception(
                    "Error en callback on_disconnect para operator_id=%s",
                    operator_id,
                )
