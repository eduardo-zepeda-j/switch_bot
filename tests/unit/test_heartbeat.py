"""Tests unitarios para HeartbeatManager.

Verifica procesamiento de heartbeats, detección de seq out-of-order,
generación de ACK, detección de timeout, y lifecycle del monitor.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from switch_bot.web.heartbeat import HeartbeatManager
from switch_bot.web.protocol import CURRENT_PROTOCOL_VERSION, ChannelMessage


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_hub() -> AsyncMock:
    """Hub mock para verificar envíos."""
    hub = AsyncMock()
    hub.send_to_agent = AsyncMock(return_value=True)
    hub.broadcast_to_spas = AsyncMock()
    hub.unregister_agent = AsyncMock()
    return hub


@pytest.fixture
def disconnect_tracker() -> dict:
    """Tracker para verificar callbacks de desconexión."""
    tracker: dict[str, list[str]] = {"disconnected": []}
    return tracker


@pytest.fixture
def on_disconnect(disconnect_tracker: dict):
    """Callback async que registra desconexiones."""

    async def _callback(operator_id: str) -> None:
        disconnect_tracker["disconnected"].append(operator_id)

    return _callback


@pytest.fixture
def manager(mock_hub: AsyncMock, on_disconnect) -> HeartbeatManager:
    """HeartbeatManager configurado para tests."""
    return HeartbeatManager(hub=mock_hub, on_disconnect=on_disconnect)


def _make_heartbeat(seq: int, timestamp: str | None = None) -> ChannelMessage:
    """Crea un ChannelMessage de tipo heartbeat para testing."""
    ts = timestamp or datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    return ChannelMessage(
        type="heartbeat",
        timestamp=ts,
        seq=seq,
        version=CURRENT_PROTOCOL_VERSION,
        payload={
            "sender_timestamp": ts,
            "seq": seq,
        },
    )


# ---------------------------------------------------------------------------
# Tests de register/unregister
# ---------------------------------------------------------------------------


class TestAgentRegistration:
    def test_register_agent(self, manager: HeartbeatManager) -> None:
        manager.register_agent("op-1")
        assert manager.is_agent_alive("op-1") is True
        assert manager.get_last_seen("op-1") is not None

    def test_unregister_agent(self, manager: HeartbeatManager) -> None:
        manager.register_agent("op-1")
        manager.unregister_agent("op-1")
        assert manager.is_agent_alive("op-1") is False
        assert manager.get_last_seen("op-1") is None

    def test_unregister_nonexistent_agent(self, manager: HeartbeatManager) -> None:
        """Desregistrar un agente no registrado no falla."""
        manager.unregister_agent("ghost")  # No debe lanzar excepción


# ---------------------------------------------------------------------------
# Tests de process_heartbeat
# ---------------------------------------------------------------------------


class TestProcessHeartbeat:
    @pytest.mark.asyncio
    async def test_valid_heartbeat_returns_ack(
        self, manager: HeartbeatManager
    ) -> None:
        """Heartbeat válido retorna heartbeat_ack con timestamp."""
        manager.register_agent("op-1")
        msg = _make_heartbeat(seq=1)

        ack = await manager.process_heartbeat("op-1", msg)

        assert ack is not None
        assert ack.type == "heartbeat_ack"
        assert ack.seq == 1
        assert ack.version == CURRENT_PROTOCOL_VERSION
        assert "sender_timestamp" in ack.payload
        assert ack.payload["seq"] == 1

    @pytest.mark.asyncio
    async def test_heartbeat_updates_last_seen(
        self, manager: HeartbeatManager
    ) -> None:
        """Heartbeat válido actualiza el timestamp de última actividad."""
        manager.register_agent("op-1")
        before = manager.get_last_seen("op-1")

        # Pequeña espera para asegurar diferencia de timestamp
        await asyncio.sleep(0.01)
        msg = _make_heartbeat(seq=1)
        await manager.process_heartbeat("op-1", msg)

        after = manager.get_last_seen("op-1")
        assert after is not None
        assert before is not None
        assert after >= before

    @pytest.mark.asyncio
    async def test_out_of_order_heartbeat_discarded(
        self, manager: HeartbeatManager
    ) -> None:
        """Heartbeat con seq <= último procesado se descarta."""
        manager.register_agent("op-1")

        # Procesar seq=5
        msg1 = _make_heartbeat(seq=5)
        ack1 = await manager.process_heartbeat("op-1", msg1)
        assert ack1 is not None

        # Intentar procesar seq=3 (out-of-order) → descartado
        msg2 = _make_heartbeat(seq=3)
        ack2 = await manager.process_heartbeat("op-1", msg2)
        assert ack2 is None

    @pytest.mark.asyncio
    async def test_equal_seq_heartbeat_discarded(
        self, manager: HeartbeatManager
    ) -> None:
        """Heartbeat con seq == último procesado se descarta."""
        manager.register_agent("op-1")

        msg1 = _make_heartbeat(seq=10)
        await manager.process_heartbeat("op-1", msg1)

        # Mismo seq → descartado
        msg2 = _make_heartbeat(seq=10)
        ack = await manager.process_heartbeat("op-1", msg2)
        assert ack is None

    @pytest.mark.asyncio
    async def test_monotonically_increasing_seq_accepted(
        self, manager: HeartbeatManager
    ) -> None:
        """Heartbeats con seq monótonamente creciente son aceptados."""
        manager.register_agent("op-1")

        for seq in [1, 2, 3, 5, 10, 100]:
            msg = _make_heartbeat(seq=seq)
            ack = await manager.process_heartbeat("op-1", msg)
            assert ack is not None
            assert ack.seq == seq

    @pytest.mark.asyncio
    async def test_heartbeat_from_unregistered_agent(
        self, manager: HeartbeatManager
    ) -> None:
        """Heartbeat de agente no registrado usa seq -1 como base."""
        # No registramos el agente, pero procesamos heartbeat
        msg = _make_heartbeat(seq=0)
        ack = await manager.process_heartbeat("op-unknown", msg)
        # seq 0 > -1 (default), así que debe ser aceptado
        assert ack is not None

    @pytest.mark.asyncio
    async def test_multiple_agents_independent_seq(
        self, manager: HeartbeatManager
    ) -> None:
        """Cada agente tiene su propio tracking de seq independiente."""
        manager.register_agent("op-1")
        manager.register_agent("op-2")

        # op-1 envía seq=5
        ack1 = await manager.process_heartbeat("op-1", _make_heartbeat(seq=5))
        assert ack1 is not None

        # op-2 puede enviar seq=1 (independiente)
        ack2 = await manager.process_heartbeat("op-2", _make_heartbeat(seq=1))
        assert ack2 is not None


# ---------------------------------------------------------------------------
# Tests de is_agent_alive
# ---------------------------------------------------------------------------


class TestIsAgentAlive:
    def test_alive_after_register(self, manager: HeartbeatManager) -> None:
        manager.register_agent("op-1")
        assert manager.is_agent_alive("op-1") is True

    def test_not_alive_when_not_registered(
        self, manager: HeartbeatManager
    ) -> None:
        assert manager.is_agent_alive("ghost") is False

    def test_not_alive_after_timeout(self, manager: HeartbeatManager) -> None:
        """Agente marcado como no alive si excede timeout."""
        manager.register_agent("op-1")
        # Simular que el último heartbeat fue hace más de 5 segundos
        manager._last_heartbeat["op-1"] = datetime.now(
            timezone.utc
        ) - timedelta(seconds=6)
        assert manager.is_agent_alive("op-1") is False


# ---------------------------------------------------------------------------
# Tests de get_last_seen
# ---------------------------------------------------------------------------


class TestGetLastSeen:
    def test_returns_none_for_unknown_agent(
        self, manager: HeartbeatManager
    ) -> None:
        assert manager.get_last_seen("unknown") is None

    def test_returns_datetime_for_registered_agent(
        self, manager: HeartbeatManager
    ) -> None:
        manager.register_agent("op-1")
        last_seen = manager.get_last_seen("op-1")
        assert isinstance(last_seen, datetime)
        assert last_seen.tzinfo == timezone.utc


# ---------------------------------------------------------------------------
# Tests de timeout detection (monitoring loop)
# ---------------------------------------------------------------------------


class TestTimeoutDetection:
    @pytest.mark.asyncio
    async def test_disconnect_callback_on_timeout(
        self, manager: HeartbeatManager, disconnect_tracker: dict
    ) -> None:
        """Callback on_disconnect se invoca cuando un agente excede timeout."""
        manager.register_agent("op-1")
        # Simular timeout: último heartbeat fue hace 6 segundos
        manager._last_heartbeat["op-1"] = datetime.now(
            timezone.utc
        ) - timedelta(seconds=6)

        # Ejecutar _check_timeouts directamente (sin iniciar el loop)
        await manager._check_timeouts()

        assert "op-1" in disconnect_tracker["disconnected"]

    @pytest.mark.asyncio
    async def test_no_disconnect_within_timeout(
        self, manager: HeartbeatManager, disconnect_tracker: dict
    ) -> None:
        """No invoca callback si el agente está dentro del timeout."""
        manager.register_agent("op-1")
        # Último heartbeat hace 2 segundos (dentro de los 5s)
        manager._last_heartbeat["op-1"] = datetime.now(
            timezone.utc
        ) - timedelta(seconds=2)

        await manager._check_timeouts()

        assert disconnect_tracker["disconnected"] == []

    @pytest.mark.asyncio
    async def test_agent_removed_after_timeout(
        self, manager: HeartbeatManager, disconnect_tracker: dict
    ) -> None:
        """Agente es removido del tracking tras timeout."""
        manager.register_agent("op-1")
        manager._last_heartbeat["op-1"] = datetime.now(
            timezone.utc
        ) - timedelta(seconds=6)

        await manager._check_timeouts()

        assert manager.get_last_seen("op-1") is None
        assert manager.is_agent_alive("op-1") is False

    @pytest.mark.asyncio
    async def test_multiple_agents_timeout_independently(
        self, manager: HeartbeatManager, disconnect_tracker: dict
    ) -> None:
        """Solo los agentes que exceden timeout son desconectados."""
        manager.register_agent("op-1")
        manager.register_agent("op-2")

        # op-1: timeout (6s), op-2: alive (1s)
        manager._last_heartbeat["op-1"] = datetime.now(
            timezone.utc
        ) - timedelta(seconds=6)
        manager._last_heartbeat["op-2"] = datetime.now(
            timezone.utc
        ) - timedelta(seconds=1)

        await manager._check_timeouts()

        assert "op-1" in disconnect_tracker["disconnected"]
        assert "op-2" not in disconnect_tracker["disconnected"]
        assert manager.is_agent_alive("op-2") is True


# ---------------------------------------------------------------------------
# Tests de lifecycle (start/stop monitoring)
# ---------------------------------------------------------------------------


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_monitoring(self, manager: HeartbeatManager) -> None:
        """start_monitoring crea una tarea de monitoreo."""
        await manager.start_monitoring()
        assert manager._running is True
        assert manager._monitoring_task is not None
        # Cleanup
        await manager.stop_monitoring()

    @pytest.mark.asyncio
    async def test_stop_monitoring(self, manager: HeartbeatManager) -> None:
        """stop_monitoring cancela la tarea de monitoreo."""
        await manager.start_monitoring()
        await manager.stop_monitoring()
        assert manager._running is False
        assert manager._monitoring_task is None

    @pytest.mark.asyncio
    async def test_double_start_is_safe(
        self, manager: HeartbeatManager
    ) -> None:
        """Llamar start_monitoring dos veces no crea tareas duplicadas."""
        await manager.start_monitoring()
        task1 = manager._monitoring_task
        await manager.start_monitoring()  # Segunda llamada
        task2 = manager._monitoring_task
        # Debe ser la misma tarea
        assert task1 is task2
        await manager.stop_monitoring()

    @pytest.mark.asyncio
    async def test_monitoring_detects_timeout(
        self, manager: HeartbeatManager, disconnect_tracker: dict
    ) -> None:
        """El loop de monitoreo detecta timeouts en ejecución."""
        manager.register_agent("op-1")
        # Simular agente que ya expiró
        manager._last_heartbeat["op-1"] = datetime.now(
            timezone.utc
        ) - timedelta(seconds=6)

        await manager.start_monitoring()
        # Esperar un poco más que INTERVAL_SECONDS para que el loop ejecute
        await asyncio.sleep(1.5)
        await manager.stop_monitoring()

        assert "op-1" in disconnect_tracker["disconnected"]
