"""AgentWebSocketClient — Cliente WebSocket del Agente_Local.

Implementa conexión autenticada con JWT, heartbeat periódico cada 1s,
detección de desconexión tras 3 heartbeats fallidos, reconexión con
backoff exponencial (1s→30s max, 20 intentos), y buffer local de mensajes
para transmisión FIFO al restablecerse la conexión.

Requirements cubiertos:
- 1.4: Agente_Local opera como proceso autónomo, comunicándose via WebSocket
- 1.5: Reconexión automática si la conexión se interrumpe
- 2.4: Reconexión con backoff exponencial 1s→30s max, 20 intentos
- 2.5: Buffer local max 500 mensajes o 10 MB, transmisión FIFO
- 10.1: Agente envía heartbeat cada 1 segundo
- 10.3: 3 ciclos sin respuesta → marca conexión como perdida, activa Fallback
- 10.5: Heartbeat incluye timestamp ISO 8601 ms y seq int64 monotónico
- 10.7: En Modo_Fallback, al recibir heartbeat válido → conexión restablecida
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine

import aiohttp
import msgspec

from switch_bot.web.protocol import (
    CURRENT_PROTOCOL_VERSION,
    ChannelMessage,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

HEARTBEAT_INTERVAL_SECONDS: float = 1.0
MAX_MISSED_HEARTBEATS: int = 3  # 3 ciclos fallidos → desconexión

# Reconnection backoff
INITIAL_BACKOFF_SECONDS: float = 1.0
MAX_BACKOFF_SECONDS: float = 30.0
MAX_RECONNECT_ATTEMPTS: int = 20

# Buffer constraints (Req 2.5)
MAX_BUFFER_MESSAGES: int = 500
MAX_BUFFER_BYTES: int = 10 * 1024 * 1024  # 10 MB


class AgentWebSocketClient:
    """Cliente WebSocket del Agente_Local con reconnection y heartbeat.

    Gestiona la conexión WebSocket persistente con el Servidor_EC2,
    incluyendo:
    - Autenticación JWT al conectar
    - Heartbeat periódico cada 1s con seq monotónico
    - Detección de desconexión tras 3 heartbeats sin respuesta
    - Reconexión con backoff exponencial (1s→30s, max 20 intentos)
    - Buffer local de mensajes si está desconectado (500 msgs / 10 MB)
    - Flush FIFO del buffer al reconectar

    Args:
        server_url: URL del WebSocket del Servidor_EC2 (ws:// o wss://).
        operator_id: ID único del operador/agente.
        auth_token: Token JWT para autenticación.
        on_fallback_activated: Callback async invocado cuando se activa
            Modo_Fallback (3 heartbeats fallidos). Puede ser None.
        on_connection_restored: Callback async invocado cuando la conexión
            se restablece desde Modo_Fallback. Puede ser None.
        on_message_received: Callback async invocado con cada ChannelMessage
            recibido del servidor. Puede ser None.
    """

    def __init__(
        self,
        server_url: str,
        operator_id: str,
        auth_token: str,
        on_fallback_activated: (
            Callable[[], Coroutine[Any, Any, None]] | None
        ) = None,
        on_connection_restored: (
            Callable[[], Coroutine[Any, Any, None]] | None
        ) = None,
        on_message_received: (
            Callable[[ChannelMessage], Coroutine[Any, Any, None]] | None
        ) = None,
    ):
        self._server_url = server_url
        self._operator_id = operator_id
        self._auth_token = auth_token
        self._on_fallback_activated = on_fallback_activated
        self._on_connection_restored = on_connection_restored
        self._on_message_received = on_message_received

        # Connection state
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._session: aiohttp.ClientSession | None = None
        self._connected: bool = False
        self._in_fallback: bool = False

        # Heartbeat state
        self._seq_counter: int = 0
        self._missed_heartbeats: int = 0
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._receive_task: asyncio.Task[None] | None = None
        self._last_ack_seq: int = -1

        # Message buffer (Req 2.5: max 500 msgs or 10 MB, FIFO)
        self._buffer: deque[bytes] = deque()
        self._buffer_size_bytes: int = 0

        # Control
        self._running: bool = False
        self._reconnect_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        """Establece conexión WebSocket con autenticación JWT.

        Envía el token JWT como header de autorización durante el handshake.

        Returns:
            True si la conexión se estableció exitosamente, False en caso
            contrario.
        """
        try:
            self._session = aiohttp.ClientSession()
            headers = {
                "Authorization": f"Bearer {self._auth_token}",
                "X-Operator-ID": self._operator_id,
            }
            self._ws = await self._session.ws_connect(
                self._server_url,
                headers=headers,
                heartbeat=None,  # Usamos nuestro propio heartbeat
            )
            self._connected = True
            self._missed_heartbeats = 0
            self._running = True

            # Si estábamos en fallback, notificar restauración
            if self._in_fallback:
                self._in_fallback = False
                logger.info(
                    "Conexión restablecida desde Modo_Fallback: "
                    "operator_id=%s, iniciando State_Sync",
                    self._operator_id,
                )
                if self._on_connection_restored:
                    try:
                        await self._on_connection_restored()
                    except Exception:
                        logger.exception(
                            "Error en callback on_connection_restored"
                        )

            # Flush buffer pendiente
            await self._flush_buffer()

            # Iniciar tareas de heartbeat y recepción
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            self._receive_task = asyncio.create_task(self._receive_loop())

            logger.info(
                "Conexión WebSocket establecida: server=%s, operator_id=%s",
                self._server_url,
                self._operator_id,
            )
            return True

        except Exception:
            logger.exception(
                "Error al conectar WebSocket: server=%s, operator_id=%s",
                self._server_url,
                self._operator_id,
            )
            await self._cleanup_connection()
            return False

    async def disconnect(self) -> None:
        """Cierra la conexión WebSocket y detiene tareas."""
        self._running = False
        await self._cancel_tasks()
        await self._cleanup_connection()
        self._connected = False
        logger.info(
            "Conexión WebSocket cerrada: operator_id=%s", self._operator_id
        )

    async def reconnect_with_backoff(self) -> bool:
        """Reconexión con backoff exponencial (1s → 30s max, 20 intentos).

        Intenta reconectar al servidor incrementando el delay exponencialmente
        desde INITIAL_BACKOFF_SECONDS hasta MAX_BACKOFF_SECONDS. Se detiene
        tras MAX_RECONNECT_ATTEMPTS intentos fallidos.

        Returns:
            True si la reconexión fue exitosa, False si se agotaron los
            intentos.
        """
        backoff = INITIAL_BACKOFF_SECONDS

        for attempt in range(1, MAX_RECONNECT_ATTEMPTS + 1):
            if not self._running:
                logger.info(
                    "Reconexión cancelada (cliente detenido): operator_id=%s",
                    self._operator_id,
                )
                return False

            logger.info(
                "Intento de reconexión %d/%d (backoff=%.1fs): operator_id=%s",
                attempt,
                MAX_RECONNECT_ATTEMPTS,
                backoff,
                self._operator_id,
            )

            await asyncio.sleep(backoff)

            if await self.connect():
                logger.info(
                    "Reconexión exitosa en intento %d: operator_id=%s",
                    attempt,
                    self._operator_id,
                )
                return True

            # Backoff exponencial: duplicar hasta max
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)

        logger.error(
            "Reconexión fallida tras %d intentos: operator_id=%s",
            MAX_RECONNECT_ATTEMPTS,
            self._operator_id,
        )
        return False

    async def send_message(self, msg: ChannelMessage) -> bool:
        """Envía mensaje al servidor. Si desconectado, encola en buffer local.

        El buffer respeta los límites de Req 2.5: max 500 mensajes o 10 MB.
        Si el buffer está lleno, descarta el mensaje más antiguo (FIFO).

        Args:
            msg: ChannelMessage a enviar.

        Returns:
            True si se envió directamente, False si se encoló en buffer.
        """
        encoded = msg.encode()

        if self._connected and self._ws is not None:
            try:
                await self._ws.send_bytes(encoded)
                return True
            except Exception:
                logger.warning(
                    "Error enviando mensaje, encolando en buffer: "
                    "operator_id=%s, type=%s",
                    self._operator_id,
                    msg.type,
                )
                self._enqueue_to_buffer(encoded)
                return False
        else:
            self._enqueue_to_buffer(encoded)
            logger.debug(
                "Mensaje encolado en buffer (desconectado): "
                "operator_id=%s, type=%s, buffer_size=%d",
                self._operator_id,
                msg.type,
                len(self._buffer),
            )
            return False

    async def start_heartbeat(self) -> None:
        """Inicia heartbeat cada 1s. Detecta desconexión tras 3 fallos.

        Si ya hay un heartbeat en ejecución, no inicia otro.
        """
        if self._heartbeat_task is not None and not self._heartbeat_task.done():
            logger.debug("Heartbeat ya en ejecución, ignorando start_heartbeat")
            return
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    def on_heartbeat_timeout(self) -> None:
        """Callback invocado cuando se detectan 3 heartbeats fallidos.

        Marca la conexión como perdida y activa Modo_Fallback. Si hay un
        callback on_fallback_activated configurado, programa su ejecución.
        """
        self._connected = False
        self._in_fallback = True
        logger.warning(
            "Heartbeat timeout: %d heartbeats consecutivos sin respuesta. "
            "Activando Modo_Fallback: operator_id=%s",
            MAX_MISSED_HEARTBEATS,
            self._operator_id,
        )

        # Programar callback de fallback y reconexión (requiere loop activo)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No hay loop activo (e.g., llamado desde sync context)
            logger.debug(
                "No hay event loop activo para programar fallback callback"
            )
            return

        if self._on_fallback_activated:
            loop.create_task(self._safe_fallback_callback())

        # Iniciar reconexión en background
        if self._reconnect_task is None or self._reconnect_task.done():
            self._reconnect_task = loop.create_task(
                self.reconnect_with_backoff()
            )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        """True si la conexión WebSocket está activa."""
        return self._connected

    @property
    def missed_heartbeats(self) -> int:
        """Número de heartbeats consecutivos sin respuesta."""
        return self._missed_heartbeats

    @property
    def in_fallback(self) -> bool:
        """True si el cliente está en Modo_Fallback."""
        return self._in_fallback

    @property
    def buffer_count(self) -> int:
        """Número de mensajes en el buffer local."""
        return len(self._buffer)

    @property
    def buffer_size_bytes(self) -> int:
        """Tamaño total del buffer en bytes."""
        return self._buffer_size_bytes

    # ------------------------------------------------------------------
    # Internal: Heartbeat
    # ------------------------------------------------------------------

    async def _heartbeat_loop(self) -> None:
        """Loop interno de heartbeat: envía cada 1s, cuenta fallos."""
        while self._running and self._connected:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)

                if not self._connected or self._ws is None:
                    break

                # Incrementar seq (monotónicamente creciente)
                self._seq_counter += 1
                now = datetime.now(timezone.utc)

                heartbeat = ChannelMessage(
                    type="heartbeat",
                    timestamp=now.isoformat(timespec="milliseconds"),
                    seq=self._seq_counter,
                    version=CURRENT_PROTOCOL_VERSION,
                    payload={
                        "sender_timestamp": now.isoformat(
                            timespec="milliseconds"
                        ),
                        "seq": self._seq_counter,
                    },
                )

                try:
                    await self._ws.send_bytes(heartbeat.encode())
                except Exception:
                    logger.warning(
                        "Error enviando heartbeat seq=%d: operator_id=%s",
                        self._seq_counter,
                        self._operator_id,
                    )
                    self._missed_heartbeats += 1
                else:
                    # Verificar si recibimos ACK del heartbeat anterior
                    if self._last_ack_seq < self._seq_counter - 1:
                        self._missed_heartbeats += 1
                    else:
                        self._missed_heartbeats = 0

                # Verificar threshold de desconexión
                if self._missed_heartbeats >= MAX_MISSED_HEARTBEATS:
                    self.on_heartbeat_timeout()
                    break

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception(
                    "Error en heartbeat loop: operator_id=%s",
                    self._operator_id,
                )

    # ------------------------------------------------------------------
    # Internal: Receive loop
    # ------------------------------------------------------------------

    async def _receive_loop(self) -> None:
        """Loop de recepción de mensajes del servidor."""
        while self._running and self._connected and self._ws is not None:
            try:
                msg = await self._ws.receive()

                if msg.type == aiohttp.WSMsgType.BINARY:
                    await self._handle_binary_message(msg.data)
                elif msg.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_binary_message(msg.data.encode())
                elif msg.type in (
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSING,
                    aiohttp.WSMsgType.CLOSED,
                ):
                    logger.info(
                        "WebSocket cerrado por servidor: operator_id=%s",
                        self._operator_id,
                    )
                    self._connected = False
                    break
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(
                        "Error WebSocket: operator_id=%s, error=%s",
                        self._operator_id,
                        self._ws.exception(),
                    )
                    self._connected = False
                    break

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception(
                    "Error en receive loop: operator_id=%s",
                    self._operator_id,
                )
                self._connected = False
                break

        # Si salimos del loop y seguimos ejecutándose, intentar reconectar
        if self._running and not self._connected:
            self.on_heartbeat_timeout()

    async def _handle_binary_message(self, data: bytes) -> None:
        """Procesa un mensaje binario recibido del servidor."""
        try:
            channel_msg = ChannelMessage.decode(data)
        except Exception:
            logger.warning(
                "Mensaje recibido no decodificable: operator_id=%s",
                self._operator_id,
            )
            return

        # Procesar heartbeat_ack
        if channel_msg.type == "heartbeat_ack":
            self._process_heartbeat_ack(channel_msg)
            return

        # Delegar otros mensajes al callback
        if self._on_message_received:
            try:
                await self._on_message_received(channel_msg)
            except Exception:
                logger.exception(
                    "Error en callback on_message_received: type=%s",
                    channel_msg.type,
                )

    def _process_heartbeat_ack(self, msg: ChannelMessage) -> None:
        """Procesa un heartbeat_ack recibido del servidor.

        Valida que el seq sea mayor al último ACK procesado (Req 10.6).
        Si es válido, resetea el contador de heartbeats fallidos.
        Si estábamos en fallback y recibimos ACK válido, marca conexión
        como restablecida (Req 10.7).
        """
        ack_seq = msg.seq

        # Req 10.6: Descartar ACK con seq <= último procesado
        if ack_seq <= self._last_ack_seq:
            logger.debug(
                "Heartbeat ACK descartado (out-of-order): seq=%d <= last=%d",
                ack_seq,
                self._last_ack_seq,
            )
            return

        self._last_ack_seq = ack_seq
        self._missed_heartbeats = 0

        logger.debug(
            "Heartbeat ACK recibido: seq=%d, operator_id=%s",
            ack_seq,
            self._operator_id,
        )

    # ------------------------------------------------------------------
    # Internal: Buffer management
    # ------------------------------------------------------------------

    def _enqueue_to_buffer(self, encoded_msg: bytes) -> None:
        """Encola un mensaje serializado en el buffer local.

        Respeta límites de Req 2.5: max 500 mensajes o 10 MB.
        Si se excede el límite, descarta mensajes más antiguos.
        """
        msg_size = len(encoded_msg)

        # Descartar mensajes antiguos si excedemos límites
        while (
            len(self._buffer) >= MAX_BUFFER_MESSAGES
            or (
                self._buffer_size_bytes + msg_size > MAX_BUFFER_BYTES
                and len(self._buffer) > 0
            )
        ):
            discarded = self._buffer.popleft()
            self._buffer_size_bytes -= len(discarded)
            logger.debug(
                "Buffer lleno: descartado mensaje antiguo "
                "(count=%d, bytes=%d)",
                len(self._buffer),
                self._buffer_size_bytes,
            )

        self._buffer.append(encoded_msg)
        self._buffer_size_bytes += msg_size

    async def _flush_buffer(self) -> None:
        """Transmite mensajes del buffer en orden FIFO al servidor.

        Se ejecuta al restablecerse la conexión. Los mensajes que no
        se puedan enviar se mantienen en el buffer.
        """
        if not self._buffer:
            return

        flushed = 0
        total = len(self._buffer)

        logger.info(
            "Flush de buffer iniciado: %d mensajes pendientes, "
            "operator_id=%s",
            total,
            self._operator_id,
        )

        while self._buffer and self._connected and self._ws is not None:
            encoded_msg = self._buffer[0]  # Peek
            try:
                await self._ws.send_bytes(encoded_msg)
                self._buffer.popleft()
                self._buffer_size_bytes -= len(encoded_msg)
                flushed += 1
            except Exception:
                logger.warning(
                    "Error durante flush de buffer en mensaje %d/%d: "
                    "operator_id=%s",
                    flushed + 1,
                    total,
                    self._operator_id,
                )
                break

        logger.info(
            "Flush de buffer completado: %d/%d mensajes enviados, "
            "%d pendientes, operator_id=%s",
            flushed,
            total,
            len(self._buffer),
            self._operator_id,
        )

    # ------------------------------------------------------------------
    # Internal: Connection management
    # ------------------------------------------------------------------

    async def _cancel_tasks(self) -> None:
        """Cancela las tareas de heartbeat y recepción."""
        tasks = [self._heartbeat_task, self._receive_task]
        for task in tasks:
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._heartbeat_task = None
        self._receive_task = None

    async def _cleanup_connection(self) -> None:
        """Cierra WebSocket y session de aiohttp."""
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        if self._session is not None:
            try:
                await self._session.close()
            except Exception:
                pass
            self._session = None

    async def _safe_fallback_callback(self) -> None:
        """Ejecuta el callback de fallback de forma segura."""
        try:
            if self._on_fallback_activated:
                await self._on_fallback_activated()
        except Exception:
            logger.exception("Error en callback on_fallback_activated")
