"""Tests unitarios para AgentWebSocketClient.

Verifica conexión, heartbeat, detección de desconexión,
buffer local, reconexión con backoff y flush de mensajes.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from switch_bot.web.agent_client import (
    HEARTBEAT_INTERVAL_SECONDS,
    INITIAL_BACKOFF_SECONDS,
    MAX_BACKOFF_SECONDS,
    MAX_BUFFER_BYTES,
    MAX_BUFFER_MESSAGES,
    MAX_MISSED_HEARTBEATS,
    MAX_RECONNECT_ATTEMPTS,
    AgentWebSocketClient,
)
from switch_bot.web.protocol import CURRENT_PROTOCOL_VERSION, ChannelMessage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_message(msg_type: str = "state_update", seq: int = 1) -> ChannelMessage:
    """Crea un ChannelMessage genérico para testing."""
    return ChannelMessage(
        type=msg_type,
        timestamp=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        seq=seq,
        version=CURRENT_PROTOCOL_VERSION,
        payload={"test": "data"},
    )


def _make_heartbeat_ack(seq: int) -> ChannelMessage:
    """Crea un heartbeat_ack para testing."""
    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    return ChannelMessage(
        type="heartbeat_ack",
        timestamp=ts,
        seq=seq,
        version=CURRENT_PROTOCOL_VERSION,
        payload={"sender_timestamp": ts, "seq": seq},
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fallback_tracker() -> dict:
    """Tracker para callbacks de fallback."""
    return {"activated": False, "restored": False}


@pytest.fixture
def on_fallback(fallback_tracker: dict):
    async def _cb() -> None:
        fallback_tracker["activated"] = True

    return _cb


@pytest.fixture
def on_restored(fallback_tracker: dict):
    async def _cb() -> None:
        fallback_tracker["restored"] = True

    return _cb


@pytest.fixture
def client(on_fallback, on_restored) -> AgentWebSocketClient:
    """AgentWebSocketClient configurado para tests."""
    return AgentWebSocketClient(
        server_url="ws://localhost:8080/ws/agent",
        operator_id="op-test-1",
        auth_token="test-jwt-token",
        on_fallback_activated=on_fallback,
        on_connection_restored=on_restored,
    )


# ---------------------------------------------------------------------------
# Tests de inicialización
# ---------------------------------------------------------------------------


class TestInitialization:
    def test_initial_state(self, client: AgentWebSocketClient) -> None:
        """Estado inicial del cliente es desconectado."""
        assert client.is_connected is False
        assert client.missed_heartbeats == 0
        assert client.in_fallback is False
        assert client.buffer_count == 0
        assert client.buffer_size_bytes == 0

    def test_initial_seq_counter(self, client: AgentWebSocketClient) -> None:
        """El seq counter inicia en 0."""
        assert client._seq_counter == 0


# ---------------------------------------------------------------------------
# Tests de send_message (buffer)
# ---------------------------------------------------------------------------


class TestSendMessage:
    @pytest.mark.asyncio
    async def test_send_when_disconnected_buffers_message(
        self, client: AgentWebSocketClient
    ) -> None:
        """Enviar un mensaje cuando está desconectado lo encola en buffer."""
        msg = _make_message()
        result = await client.send_message(msg)
        assert result is False
        assert client.buffer_count == 1
        assert client.buffer_size_bytes > 0

    @pytest.mark.asyncio
    async def test_buffer_respects_max_messages(
        self, client: AgentWebSocketClient
    ) -> None:
        """Buffer no excede MAX_BUFFER_MESSAGES."""
        for i in range(MAX_BUFFER_MESSAGES + 10):
            msg = _make_message(seq=i)
            await client.send_message(msg)

        assert client.buffer_count == MAX_BUFFER_MESSAGES

    @pytest.mark.asyncio
    async def test_buffer_fifo_order(
        self, client: AgentWebSocketClient
    ) -> None:
        """Buffer mantiene orden FIFO."""
        # Enviar 3 mensajes
        for i in range(3):
            msg = _make_message(seq=i)
            await client.send_message(msg)

        assert client.buffer_count == 3
        # El primer mensaje en el buffer es el primero enviado
        first_bytes = client._buffer[0]
        first_msg = ChannelMessage.decode(first_bytes)
        assert first_msg.seq == 0

    @pytest.mark.asyncio
    async def test_buffer_discards_oldest_when_full(
        self, client: AgentWebSocketClient
    ) -> None:
        """Al exceder límite, se descartan los mensajes más antiguos."""
        # Llenar buffer
        for i in range(MAX_BUFFER_MESSAGES):
            await client.send_message(_make_message(seq=i))

        # Enviar uno más → descarta el más antiguo
        await client.send_message(_make_message(seq=9999))

        assert client.buffer_count == MAX_BUFFER_MESSAGES
        # El primer mensaje ya no es seq=0 sino seq=1
        first_msg = ChannelMessage.decode(client._buffer[0])
        assert first_msg.seq == 1

    @pytest.mark.asyncio
    async def test_send_when_connected_sends_directly(
        self, client: AgentWebSocketClient
    ) -> None:
        """Enviar un mensaje cuando está conectado envía directamente."""
        # Simular conexión activa
        client._connected = True
        mock_ws = AsyncMock()
        mock_ws.send_bytes = AsyncMock()
        client._ws = mock_ws

        msg = _make_message()
        result = await client.send_message(msg)

        assert result is True
        assert client.buffer_count == 0
        mock_ws.send_bytes.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_failure_when_connected_buffers(
        self, client: AgentWebSocketClient
    ) -> None:
        """Si el envío falla estando conectado, se encola en buffer."""
        client._connected = True
        mock_ws = AsyncMock()
        mock_ws.send_bytes = AsyncMock(side_effect=ConnectionError("broken"))
        client._ws = mock_ws

        msg = _make_message()
        result = await client.send_message(msg)

        assert result is False
        assert client.buffer_count == 1


# ---------------------------------------------------------------------------
# Tests de heartbeat timeout
# ---------------------------------------------------------------------------


class TestHeartbeatTimeout:
    @pytest.mark.asyncio
    async def test_on_heartbeat_timeout_activates_fallback(
        self, client: AgentWebSocketClient
    ) -> None:
        """on_heartbeat_timeout marca como desconectado y activa fallback."""
        client._connected = True
        client._running = True
        client.on_heartbeat_timeout()

        assert client.is_connected is False
        assert client.in_fallback is True

    @pytest.mark.asyncio
    async def test_fallback_callback_invoked(
        self, client: AgentWebSocketClient, fallback_tracker: dict
    ) -> None:
        """El callback on_fallback_activated se invoca en timeout."""
        client._connected = True
        client._running = True
        client.on_heartbeat_timeout()

        # Dar tiempo al create_task para ejecutar
        await asyncio.sleep(0.1)
        assert fallback_tracker["activated"] is True


# ---------------------------------------------------------------------------
# Tests de heartbeat ACK processing
# ---------------------------------------------------------------------------


class TestHeartbeatAckProcessing:
    def test_valid_ack_resets_missed_count(
        self, client: AgentWebSocketClient
    ) -> None:
        """ACK válido resetea el contador de heartbeats fallidos."""
        client._missed_heartbeats = 2
        ack = _make_heartbeat_ack(seq=5)
        client._process_heartbeat_ack(ack)

        assert client.missed_heartbeats == 0
        assert client._last_ack_seq == 5

    def test_out_of_order_ack_discarded(
        self, client: AgentWebSocketClient
    ) -> None:
        """ACK con seq <= último procesado se descarta."""
        client._last_ack_seq = 10
        client._missed_heartbeats = 2

        ack = _make_heartbeat_ack(seq=8)
        client._process_heartbeat_ack(ack)

        # No se reseteó
        assert client.missed_heartbeats == 2
        assert client._last_ack_seq == 10

    def test_equal_seq_ack_discarded(
        self, client: AgentWebSocketClient
    ) -> None:
        """ACK con seq == último procesado se descarta."""
        client._last_ack_seq = 5
        client._missed_heartbeats = 1

        ack = _make_heartbeat_ack(seq=5)
        client._process_heartbeat_ack(ack)

        assert client.missed_heartbeats == 1
        assert client._last_ack_seq == 5

    def test_monotonically_increasing_ack_accepted(
        self, client: AgentWebSocketClient
    ) -> None:
        """ACKs con seq monotónicamente creciente son aceptados."""
        for seq in [1, 2, 5, 10, 100]:
            client._missed_heartbeats = 3
            ack = _make_heartbeat_ack(seq=seq)
            client._process_heartbeat_ack(ack)
            assert client._last_ack_seq == seq
            assert client.missed_heartbeats == 0


# ---------------------------------------------------------------------------
# Tests de reconnect_with_backoff
# ---------------------------------------------------------------------------


class TestReconnectWithBackoff:
    @pytest.mark.asyncio
    async def test_successful_reconnection(
        self, client: AgentWebSocketClient
    ) -> None:
        """Reconexión exitosa al primer intento."""
        client._running = True

        with patch.object(client, "connect", new_callable=AsyncMock) as mock_connect:
            mock_connect.return_value = True
            result = await client.reconnect_with_backoff()

        assert result is True
        mock_connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_failed_reconnection_exhausts_attempts(
        self, client: AgentWebSocketClient
    ) -> None:
        """Reconexión fallida agota todos los intentos."""
        client._running = True

        with patch.object(client, "connect", new_callable=AsyncMock) as mock_connect:
            mock_connect.return_value = False
            # Patch sleep to speed up test
            with patch("switch_bot.web.agent_client.asyncio.sleep", new_callable=AsyncMock):
                result = await client.reconnect_with_backoff()

        assert result is False
        assert mock_connect.call_count == MAX_RECONNECT_ATTEMPTS

    @pytest.mark.asyncio
    async def test_cancelled_when_not_running(
        self, client: AgentWebSocketClient
    ) -> None:
        """Reconexión se cancela si _running es False."""
        client._running = False

        with patch.object(client, "connect", new_callable=AsyncMock) as mock_connect:
            result = await client.reconnect_with_backoff()

        assert result is False
        mock_connect.assert_not_called()

    @pytest.mark.asyncio
    async def test_backoff_increases_exponentially(
        self, client: AgentWebSocketClient
    ) -> None:
        """El backoff se duplica en cada intento hasta MAX_BACKOFF_SECONDS."""
        client._running = True
        sleep_values: list[float] = []

        async def capture_sleep(seconds: float) -> None:
            sleep_values.append(seconds)

        with patch.object(client, "connect", new_callable=AsyncMock) as mock_connect:
            mock_connect.return_value = False
            with patch(
                "switch_bot.web.agent_client.asyncio.sleep",
                side_effect=capture_sleep,
            ):
                await client.reconnect_with_backoff()

        # Verificar patrón exponencial: 1, 2, 4, 8, 16, 30, 30, ...
        expected_backoff = INITIAL_BACKOFF_SECONDS
        for i, actual in enumerate(sleep_values):
            assert actual == expected_backoff, (
                f"Intento {i+1}: esperado {expected_backoff}, obtuvo {actual}"
            )
            expected_backoff = min(expected_backoff * 2, MAX_BACKOFF_SECONDS)


# ---------------------------------------------------------------------------
# Tests de flush buffer
# ---------------------------------------------------------------------------


class TestFlushBuffer:
    @pytest.mark.asyncio
    async def test_flush_sends_all_buffered_messages(
        self, client: AgentWebSocketClient
    ) -> None:
        """Flush envía todos los mensajes del buffer al servidor."""
        # Encolar 3 mensajes
        for i in range(3):
            await client.send_message(_make_message(seq=i))

        assert client.buffer_count == 3

        # Simular conexión
        client._connected = True
        mock_ws = AsyncMock()
        mock_ws.send_bytes = AsyncMock()
        client._ws = mock_ws

        await client._flush_buffer()

        assert client.buffer_count == 0
        assert mock_ws.send_bytes.call_count == 3

    @pytest.mark.asyncio
    async def test_flush_preserves_fifo_order(
        self, client: AgentWebSocketClient
    ) -> None:
        """Flush envía mensajes en orden FIFO."""
        for i in range(3):
            await client.send_message(_make_message(seq=i))

        client._connected = True
        sent_data: list[bytes] = []
        mock_ws = AsyncMock()

        async def capture_send(data: bytes) -> None:
            sent_data.append(data)

        mock_ws.send_bytes = capture_send
        client._ws = mock_ws

        await client._flush_buffer()

        # Verificar orden
        for i, data in enumerate(sent_data):
            msg = ChannelMessage.decode(data)
            assert msg.seq == i

    @pytest.mark.asyncio
    async def test_flush_stops_on_send_error(
        self, client: AgentWebSocketClient
    ) -> None:
        """Flush se detiene si hay error de envío, preservando el resto."""
        for i in range(5):
            await client.send_message(_make_message(seq=i))

        client._connected = True
        call_count = 0
        mock_ws = AsyncMock()

        async def fail_on_third(data: bytes) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                raise ConnectionError("broken")

        mock_ws.send_bytes = fail_on_third
        client._ws = mock_ws

        await client._flush_buffer()

        # 2 enviados exitosamente, falla en el 3ro
        assert client.buffer_count == 3  # 5 - 2 = 3 pendientes


# ---------------------------------------------------------------------------
# Tests de constantes del protocolo
# ---------------------------------------------------------------------------


class TestProtocolConstants:
    def test_heartbeat_interval(self) -> None:
        assert HEARTBEAT_INTERVAL_SECONDS == 1.0

    def test_max_missed_heartbeats(self) -> None:
        assert MAX_MISSED_HEARTBEATS == 3

    def test_backoff_range(self) -> None:
        assert INITIAL_BACKOFF_SECONDS == 1.0
        assert MAX_BACKOFF_SECONDS == 30.0

    def test_max_reconnect_attempts(self) -> None:
        assert MAX_RECONNECT_ATTEMPTS == 20

    def test_buffer_limits(self) -> None:
        assert MAX_BUFFER_MESSAGES == 500
        assert MAX_BUFFER_BYTES == 10 * 1024 * 1024
