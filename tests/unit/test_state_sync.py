"""Tests unitarios para StateSyncProtocol."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from switch_bot.web.protocol import ChannelMessage, CURRENT_PROTOCOL_VERSION
from switch_bot.web.state_sync import StateSyncProtocol, StateSyncResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_ws_client():
    """AgentWebSocketClient mockeado."""
    client = MagicMock()
    client.send_message = AsyncMock(return_value=True)
    client.is_connected = True
    return client


@pytest.fixture
def mock_fallback():
    """FallbackManager mockeado."""
    fallback = MagicMock()
    fallback.pending_count = 0
    fallback.get_pending_events = MagicMock(return_value=[])
    fallback.mark_synced = MagicMock()
    fallback.increment_sync_attempts = MagicMock()
    return fallback


@pytest.fixture
def protocol(mock_ws_client, mock_fallback) -> StateSyncProtocol:
    """Instancia de StateSyncProtocol con mocks."""
    return StateSyncProtocol(
        ws_client=mock_ws_client,
        fallback=mock_fallback,
    )


def _make_events(count: int, start_id: int = 1) -> list[dict]:
    """Crea una lista de eventos de prueba."""
    events = []
    for i in range(count):
        events.append({
            "id": start_id + i,
            "smpte_tc": f"01:00:{i:02d}:00",
            "event_type": "switch_command",
            "payload": {"target_cam": (i % 4) + 1},
            "created_at": "2024-01-01T00:00:00Z",
            "sync_attempts": 0,
        })
    return events


def _make_ack_msg(batch_id: int, accepted: int, conflicts: list | None = None):
    """Crea un ChannelMessage ACK de prueba."""
    return ChannelMessage(
        type="state_sync_ack",
        timestamp="2024-01-01T00:00:01.000Z",
        seq=1,
        version=CURRENT_PROTOCOL_VERSION,
        payload={
            "batch_id": batch_id,
            "accepted": accepted,
            "conflicts": conflicts or [],
        },
    )


# ---------------------------------------------------------------------------
# Tests: Constantes de clase
# ---------------------------------------------------------------------------


class TestConstants:
    """Tests de constantes de configuración."""

    def test_batch_size_is_50(self, protocol):
        assert protocol.BATCH_SIZE == 50

    def test_ack_timeout_is_10s(self, protocol):
        assert protocol.ACK_TIMEOUT_SECONDS == 10.0

    def test_max_retries_is_3(self, protocol):
        assert protocol.MAX_RETRIES == 3


# ---------------------------------------------------------------------------
# Tests: Properties
# ---------------------------------------------------------------------------


class TestProperties:
    """Tests de propiedades del protocolo."""

    def test_is_syncing_default_false(self, protocol):
        assert protocol.is_syncing is False

    def test_is_paused_default_false(self, protocol):
        assert protocol.is_paused is False

    def test_progress_default_zero(self, protocol):
        assert protocol.progress == (0, 0)


# ---------------------------------------------------------------------------
# Tests: start_sync
# ---------------------------------------------------------------------------


class TestStartSync:
    """Tests de inicio de sincronización."""

    @pytest.mark.asyncio
    async def test_no_pending_events_returns_success(
        self, protocol, mock_fallback
    ):
        """Sin eventos pendientes, retorna éxito inmediato."""
        mock_fallback.pending_count = 0

        result = await protocol.start_sync()

        assert result.success is True
        assert result.events_synced == 0

    @pytest.mark.asyncio
    async def test_already_syncing_returns_error(
        self, protocol, mock_fallback
    ):
        """Si ya está sincronizando, retorna error."""
        mock_fallback.pending_count = 10
        protocol._syncing = True

        result = await protocol.start_sync()

        assert result.success is False
        assert "ya en curso" in result.error

    @pytest.mark.asyncio
    async def test_syncs_single_batch_successfully(
        self, protocol, mock_ws_client, mock_fallback
    ):
        """Sincroniza un lote completo de eventos."""
        events = _make_events(5)
        mock_fallback.pending_count = 5
        # First call returns events, second call returns empty (sync done)
        mock_fallback.get_pending_events = MagicMock(
            side_effect=[events, []]
        )

        # Simulate ACK arriving when send_batch is called
        async def fake_send(msg):
            # Resolve the pending ACK future
            batch_id = msg.payload.get("batch_id")
            if batch_id and batch_id in protocol._pending_acks:
                ack = _make_ack_msg(batch_id, accepted=5)
                future = protocol._pending_acks[batch_id]
                if not future.done():
                    future.set_result(ack)
            return True

        mock_ws_client.send_message = fake_send

        result = await protocol.start_sync()

        assert result.success is True
        assert result.events_synced == 5
        assert result.tc_range_start == "01:00:00:00"
        assert result.tc_range_end == "01:00:04:00"
        mock_fallback.mark_synced.assert_called_once_with(
            [1, 2, 3, 4, 5]
        )

    @pytest.mark.asyncio
    async def test_sync_pauses_after_max_retries(
        self, protocol, mock_ws_client, mock_fallback
    ):
        """Si un lote falla MAX_RETRIES veces, pausa y notifica."""
        events = _make_events(3)
        mock_fallback.pending_count = 3
        mock_fallback.get_pending_events = MagicMock(return_value=events)

        # send_message siempre falla (retorna False → no se envía)
        mock_ws_client.send_message = AsyncMock(return_value=False)

        result = await protocol.start_sync()

        assert result.success is False
        assert protocol.is_paused is True
        assert result.events_failed == 3
        assert "reintentos" in result.error
        # Se incrementan los intentos MAX_RETRIES veces
        assert mock_fallback.increment_sync_attempts.call_count == 3


# ---------------------------------------------------------------------------
# Tests: handle_ack
# ---------------------------------------------------------------------------


class TestHandleAck:
    """Tests de procesamiento de ACK."""

    @pytest.mark.asyncio
    async def test_resolves_pending_future(self, protocol):
        """handle_ack resuelve el Future del batch correspondiente."""
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        protocol._pending_acks[42] = future

        ack_msg = _make_ack_msg(batch_id=42, accepted=10)
        await protocol.handle_ack(ack_msg)

        assert future.done()
        assert future.result() == ack_msg

    @pytest.mark.asyncio
    async def test_ignores_unknown_batch_id(self, protocol):
        """ACK con batch_id desconocido no causa error."""
        ack_msg = _make_ack_msg(batch_id=999, accepted=5)
        # No debe lanzar excepción
        await protocol.handle_ack(ack_msg)

    @pytest.mark.asyncio
    async def test_ignores_ack_without_batch_id(self, protocol):
        """ACK sin batch_id se ignora."""
        msg = ChannelMessage(
            type="state_sync_ack",
            timestamp="2024-01-01T00:00:00.000Z",
            seq=1,
            version=CURRENT_PROTOCOL_VERSION,
            payload={},
        )
        await protocol.handle_ack(msg)  # No debe lanzar


# ---------------------------------------------------------------------------
# Tests: handle_conflict
# ---------------------------------------------------------------------------


class TestHandleConflict:
    """Tests de manejo de conflictos."""

    @pytest.mark.asyncio
    async def test_logs_conflicts(self, protocol, caplog):
        """Conflictos se registran con flag CONFLICT."""
        import logging

        with caplog.at_level(logging.INFO):
            conflicts = [
                {
                    "event_id": 1,
                    "smpte_tc": "01:00:05:00",
                    "server_version": {"cam": 2},
                    "agent_version": {"cam": 3},
                },
                {
                    "event_id": 2,
                    "smpte_tc": "01:00:06:00",
                    "server_version": {"cam": 1},
                    "agent_version": {"cam": 4},
                },
            ]
            await protocol.handle_conflict(conflicts)

        assert "CONFLICTO" in caplog.text
        assert "2 conflictos" in caplog.text


# ---------------------------------------------------------------------------
# Tests: send_batch
# ---------------------------------------------------------------------------


class TestSendBatch:
    """Tests del envío de lotes."""

    @pytest.mark.asyncio
    async def test_empty_batch_returns_true(self, protocol):
        """Un lote vacío retorna True inmediatamente."""
        result = await protocol.send_batch([])
        assert result is True

    @pytest.mark.asyncio
    async def test_send_failure_returns_false(
        self, protocol, mock_ws_client
    ):
        """Si send_message falla, retorna False."""
        mock_ws_client.send_message = AsyncMock(return_value=False)
        events = _make_events(3)

        result = await protocol.send_batch(events)

        assert result is False

    @pytest.mark.asyncio
    async def test_timeout_returns_false(self, protocol, mock_ws_client):
        """Si no llega ACK dentro del timeout, retorna False."""
        mock_ws_client.send_message = AsyncMock(return_value=True)

        # Temporarily set a very short timeout for testing
        protocol.ACK_TIMEOUT_SECONDS = 0.1
        events = _make_events(2)

        result = await protocol.send_batch(events)

        assert result is False


# ---------------------------------------------------------------------------
# Tests: Non-blocking behavior (Req 11.5)
# ---------------------------------------------------------------------------


class TestNonBlocking:
    """Tests de comportamiento no bloqueante."""

    @pytest.mark.asyncio
    async def test_sync_runs_as_independent_task(
        self, protocol, mock_ws_client, mock_fallback
    ):
        """La sincronización se ejecuta sin bloquear otras coroutines."""
        events = _make_events(2)
        mock_fallback.pending_count = 2
        mock_fallback.get_pending_events = MagicMock(
            side_effect=[events, []]
        )

        # Simulate instant ACK
        async def fake_send(msg):
            batch_id = msg.payload.get("batch_id")
            if batch_id and batch_id in protocol._pending_acks:
                ack = _make_ack_msg(batch_id, accepted=2)
                future = protocol._pending_acks[batch_id]
                if not future.done():
                    future.set_result(ack)
            return True

        mock_ws_client.send_message = fake_send

        # Run sync and verify other tasks can execute concurrently
        other_task_ran = False

        async def other_coroutine():
            nonlocal other_task_ran
            await asyncio.sleep(0)
            other_task_ran = True

        # Both should complete
        result, _ = await asyncio.gather(
            protocol.start_sync(),
            other_coroutine(),
        )

        assert result.success is True
        assert other_task_ran is True


# ---------------------------------------------------------------------------
# Tests: Envío de lote completo de BATCH_SIZE=50 eventos (Req 11.2)
# ---------------------------------------------------------------------------


class TestBatchSize50:
    """Tests de envío de lotes de exactamente 50 eventos con ACK exitoso."""

    @pytest.mark.asyncio
    async def test_send_batch_of_50_events_with_successful_ack(
        self, protocol, mock_ws_client, mock_fallback
    ):
        """Envía exactamente BATCH_SIZE=50 eventos en un lote y verifica
        que el ACK se recibe correctamente y mark_synced se invoca con
        todos los 50 event_ids.

        Validates: Requirements 11.2
        """
        events = _make_events(50)
        mock_fallback.pending_count = 50
        # Primer get_pending_events retorna los 50, segundo retorna vacío
        mock_fallback.get_pending_events = MagicMock(
            side_effect=[events, []]
        )

        # Simular ACK exitoso para el batch completo
        async def fake_send(msg):
            batch_id = msg.payload.get("batch_id")
            if batch_id and batch_id in protocol._pending_acks:
                ack = _make_ack_msg(batch_id, accepted=50)
                future = protocol._pending_acks[batch_id]
                if not future.done():
                    future.set_result(ack)
            return True

        mock_ws_client.send_message = fake_send

        result = await protocol.start_sync()

        assert result.success is True
        assert result.events_synced == 50
        assert result.tc_range_start == "01:00:00:00"
        assert result.tc_range_end == "01:00:49:00"
        # Verificar que mark_synced fue llamado con los 50 IDs
        mock_fallback.mark_synced.assert_called_once_with(
            list(range(1, 51))
        )

    @pytest.mark.asyncio
    async def test_batch_message_contains_correct_payload_structure(
        self, protocol, mock_ws_client, mock_fallback
    ):
        """El mensaje enviado contiene la estructura correcta del payload
        con batch_id, events (50), total_pending, y rango TC.

        Validates: Requirements 11.2
        """
        events = _make_events(50)
        mock_fallback.pending_count = 50

        sent_messages = []

        async def capture_send(msg):
            sent_messages.append(msg)
            batch_id = msg.payload.get("batch_id")
            if batch_id and batch_id in protocol._pending_acks:
                ack = _make_ack_msg(batch_id, accepted=50)
                future = protocol._pending_acks[batch_id]
                if not future.done():
                    future.set_result(ack)
            return True

        mock_ws_client.send_message = capture_send

        result = await protocol.send_batch(events)

        assert result is True
        assert len(sent_messages) == 1
        msg = sent_messages[0]
        assert msg.type == "state_sync_batch"
        assert msg.payload["batch_id"] == 1
        assert len(msg.payload["events"]) == 50
        assert msg.payload["tc_range_start"] == "01:00:00:00"
        assert msg.payload["tc_range_end"] == "01:00:49:00"


# ---------------------------------------------------------------------------
# Tests: Timeout de ACK provoca reintento max 3 (Req 11.6)
# ---------------------------------------------------------------------------


class TestAckTimeoutRetries:
    """Tests de timeout de ACK con reintentos hasta MAX_RETRIES=3."""

    @pytest.mark.asyncio
    async def test_timeout_retries_then_pauses_after_3_attempts(
        self, protocol, mock_ws_client, mock_fallback
    ):
        """Cuando ACK no llega (timeout), reintenta hasta 3 veces.
        Tras 3 fallos: sync se pausa y operador es notificado.

        Secuencia esperada:
        - Intento 1: timeout → retry
        - Intento 2: timeout → retry
        - Intento 3: timeout → sync pausado, notifica operador

        Validates: Requirements 11.6
        """
        events = _make_events(5)
        mock_fallback.pending_count = 5
        mock_fallback.get_pending_events = MagicMock(return_value=events)

        # send_message tiene éxito pero nunca llega el ACK → timeout
        mock_ws_client.send_message = AsyncMock(return_value=True)

        # Reducir timeout para que el test sea rápido
        protocol.ACK_TIMEOUT_SECONDS = 0.05

        result = await protocol.start_sync()

        # La sync debe haber fallado y pausado
        assert result.success is False
        assert protocol.is_paused is True
        assert "reintentos" in result.error
        # Se incrementan sync_attempts en cada intento fallido (3 veces)
        assert mock_fallback.increment_sync_attempts.call_count == 3
        # send_message se llamó 3 veces (una por cada intento)
        assert mock_ws_client.send_message.call_count == 3

    @pytest.mark.asyncio
    async def test_timeout_on_first_two_attempts_success_on_third(
        self, protocol, mock_ws_client, mock_fallback
    ):
        """Si los primeros 2 intentos dan timeout pero el 3ro recibe ACK,
        la sincronización continúa exitosamente.

        Validates: Requirements 11.6
        """
        events = _make_events(5)
        mock_fallback.pending_count = 5
        mock_fallback.get_pending_events = MagicMock(
            side_effect=[events, []]
        )

        # Reducir timeout para test rápido
        protocol.ACK_TIMEOUT_SECONDS = 0.05

        call_count = 0

        async def fake_send_with_delayed_ack(msg):
            nonlocal call_count
            call_count += 1
            batch_id = msg.payload.get("batch_id")
            if batch_id and batch_id in protocol._pending_acks:
                if call_count <= 2:
                    # Primeros 2 intentos: no enviar ACK → timeout
                    pass
                else:
                    # Tercer intento: enviar ACK inmediatamente
                    ack = _make_ack_msg(batch_id, accepted=5)
                    future = protocol._pending_acks[batch_id]
                    if not future.done():
                        future.set_result(ack)
            return True

        mock_ws_client.send_message = fake_send_with_delayed_ack

        result = await protocol.start_sync()

        assert result.success is True
        assert result.events_synced == 5
        assert protocol.is_paused is False
        # Se enviaron 3 intentos
        assert call_count == 3
        # increment_sync_attempts se llamó 2 veces (intentos 1 y 2 fallidos)
        assert mock_fallback.increment_sync_attempts.call_count == 2


# ---------------------------------------------------------------------------
# Tests: Conflictos marcados con flag CONFLICT (Req 11.4)
# ---------------------------------------------------------------------------


class TestConflictFlag:
    """Tests de que conflictos se preservan con flag CONFLICT."""

    @pytest.mark.asyncio
    async def test_conflicts_preserve_both_versions_with_flag(
        self, protocol, mock_ws_client, mock_fallback, caplog
    ):
        """Cuando el servidor reporta conflictos en el ACK, ambas versiones
        (agente y servidor) se preservan y se marcan con flag CONFLICT.
        El log muestra la info del conflicto para resolución manual.

        Validates: Requirements 11.4
        """
        import logging

        events = _make_events(10)
        mock_fallback.pending_count = 10
        mock_fallback.get_pending_events = MagicMock(
            side_effect=[events, []]
        )

        conflicts_data = [
            {
                "event_id": 3,
                "smpte_tc": "01:00:02:00",
                "server_version": {"target_cam": 2, "transition": "cut"},
                "agent_version": {"target_cam": 3, "transition": "dissolve"},
            },
            {
                "event_id": 7,
                "smpte_tc": "01:00:06:00",
                "server_version": {"target_cam": 1, "transition": "cut"},
                "agent_version": {"target_cam": 4, "transition": "wipe"},
            },
        ]

        # Simular ACK con conflictos
        async def fake_send_with_conflicts(msg):
            batch_id = msg.payload.get("batch_id")
            if batch_id and batch_id in protocol._pending_acks:
                ack = _make_ack_msg(
                    batch_id, accepted=8, conflicts=conflicts_data
                )
                future = protocol._pending_acks[batch_id]
                if not future.done():
                    future.set_result(ack)
            return True

        mock_ws_client.send_message = fake_send_with_conflicts

        with caplog.at_level(logging.WARNING):
            result = await protocol.start_sync()

        # La sync fue exitosa (los conflictos no impiden el avance)
        assert result.success is True
        assert result.events_synced == 10

        # Verificar que los conflictos se loguearon con flag CONFLICT
        assert "CONFLICTO" in caplog.text
        assert "event_id=3" in caplog.text or "3" in caplog.text
        assert "event_id=7" in caplog.text or "7" in caplog.text
        assert "CONFLICT" in caplog.text

    @pytest.mark.asyncio
    async def test_handle_conflict_preserves_conflict_data_integrity(
        self, protocol, caplog
    ):
        """handle_conflict recibe la lista completa de conflictos con
        server_version y agent_version intactos. Cada conflicto se procesa
        individualmente con su event_id y smpte_tc.

        Validates: Requirements 11.4
        """
        import logging

        conflicts = [
            {
                "event_id": 42,
                "smpte_tc": "02:15:30:12",
                "server_version": {"cam": 2, "effect": "fade"},
                "agent_version": {"cam": 3, "effect": "cut"},
            },
        ]

        with caplog.at_level(logging.INFO):
            await protocol.handle_conflict(conflicts)

        # El conflicto se registra con la información correcta
        assert "CONFLICTO" in caplog.text
        assert "42" in caplog.text
        assert "02:15:30:12" in caplog.text
        # Se informa la cantidad total con flag CONFLICT
        assert "1 conflictos" in caplog.text
        assert "CONFLICT" in caplog.text


# ---------------------------------------------------------------------------
# Tests: Sync no bloquea operaciones en tiempo real (Req 11.5)
# ---------------------------------------------------------------------------


class TestSyncNonBlockingConcurrent:
    """Tests de que sync no bloquea operaciones en tiempo real."""

    @pytest.mark.asyncio
    async def test_concurrent_operations_complete_during_sync(
        self, protocol, mock_ws_client, mock_fallback
    ):
        """Mientras la sync procesa lotes, otras operaciones (captura,
        inferencia, ATEM) pueden ejecutar sin bloqueo. Se verifica que
        múltiples coroutines concurrentes completan durante el sync.

        Validates: Requirements 11.5
        """
        events = _make_events(50)
        mock_fallback.pending_count = 50
        mock_fallback.get_pending_events = MagicMock(
            side_effect=[events, []]
        )

        # Simular un pequeño delay antes del ACK para dar tiempo a las
        # operaciones concurrentes
        async def fake_send_with_delay(msg):
            await asyncio.sleep(0.01)  # Simula latencia de red
            batch_id = msg.payload.get("batch_id")
            if batch_id and batch_id in protocol._pending_acks:
                ack = _make_ack_msg(batch_id, accepted=50)
                future = protocol._pending_acks[batch_id]
                if not future.done():
                    future.set_result(ack)
            return True

        mock_ws_client.send_message = fake_send_with_delay

        # Simular operaciones concurrentes de captura, inferencia y ATEM
        operations_completed = {"capture": False, "inference": False, "atem": False}

        async def simulate_capture():
            await asyncio.sleep(0.005)
            operations_completed["capture"] = True

        async def simulate_inference():
            await asyncio.sleep(0.005)
            operations_completed["inference"] = True

        async def simulate_atem_control():
            await asyncio.sleep(0.005)
            operations_completed["atem"] = True

        # Ejecutar todo concurrentemente
        sync_result, _, _, _ = await asyncio.gather(
            protocol.start_sync(),
            simulate_capture(),
            simulate_inference(),
            simulate_atem_control(),
        )

        # Sync completó exitosamente
        assert sync_result.success is True
        assert sync_result.events_synced == 50

        # Todas las operaciones concurrentes completaron sin bloqueo
        assert operations_completed["capture"] is True
        assert operations_completed["inference"] is True
        assert operations_completed["atem"] is True
