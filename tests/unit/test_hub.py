"""Tests unitarios para WebSocketHub.

Verifica registro/desregistro de agentes y SPAs, broadcast,
validación de token, y límites de conexión.
"""

from __future__ import annotations

import pytest

from switch_bot.web.hub import WebSocketHub
from switch_bot.web.protocol import ChannelMessage


# ---------------------------------------------------------------------------
# Fake WebSocket para testing
# ---------------------------------------------------------------------------


class FakeWebSocket:
    """WebSocket falso que registra mensajes enviados."""

    def __init__(self, *, should_fail: bool = False):
        self.sent: list[bytes] = []
        self.should_fail = should_fail

    async def send_bytes(self, data: bytes) -> None:
        if self.should_fail:
            raise ConnectionError("WebSocket closed")
        self.sent.append(data)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _valid_token_validator(token: str) -> dict | None:
    """Acepta tokens que comiencen con 'valid-'."""
    if token.startswith("valid-"):
        return {"user_id": "test-user", "role": "operador"}
    return None


@pytest.fixture
def hub() -> WebSocketHub:
    """Hub con validador de token permisivo para tests."""
    return WebSocketHub(
        max_agents=4,
        max_spa_clients=10,
        token_validator=_valid_token_validator,
    )


@pytest.fixture
def small_hub() -> WebSocketHub:
    """Hub con límites reducidos para tests de capacidad."""
    return WebSocketHub(
        max_agents=2,
        max_spa_clients=3,
        token_validator=_valid_token_validator,
    )


# ---------------------------------------------------------------------------
# Tests de registro de agentes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_agent_success(hub: WebSocketHub) -> None:
    ws = FakeWebSocket()
    result = await hub.register_agent("op-1", ws, "valid-token")
    assert result is True
    assert "op-1" in hub.connected_agents
    assert hub.agent_count == 1


@pytest.mark.asyncio
async def test_register_agent_invalid_token(hub: WebSocketHub) -> None:
    ws = FakeWebSocket()
    result = await hub.register_agent("op-1", ws, "bad-token")
    assert result is False
    assert "op-1" not in hub.connected_agents
    assert hub.agent_count == 0


@pytest.mark.asyncio
async def test_register_agent_exceeds_limit(small_hub: WebSocketHub) -> None:
    """No permite más agentes que max_agents."""
    ws1 = FakeWebSocket()
    ws2 = FakeWebSocket()
    ws3 = FakeWebSocket()

    assert await small_hub.register_agent("op-1", ws1, "valid-t") is True
    assert await small_hub.register_agent("op-2", ws2, "valid-t") is True
    # Tercer agente excede el límite de 2
    assert await small_hub.register_agent("op-3", ws3, "valid-t") is False
    assert small_hub.agent_count == 2


@pytest.mark.asyncio
async def test_register_agent_replace_existing(hub: WebSocketHub) -> None:
    """Re-registrar un agente existente actualiza la conexión."""
    ws1 = FakeWebSocket()
    ws2 = FakeWebSocket()

    await hub.register_agent("op-1", ws1, "valid-t")
    await hub.register_agent("op-1", ws2, "valid-t")
    # No incrementa el conteo, solo reemplaza
    assert hub.agent_count == 1
    assert "op-1" in hub.connected_agents


# ---------------------------------------------------------------------------
# Tests de registro de SPA
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_spa_success(hub: WebSocketHub) -> None:
    ws = FakeWebSocket()
    result = await hub.register_spa_client("spa-1", ws, "valid-token")
    assert result is True
    assert "spa-1" in hub.connected_spa_clients
    assert hub.spa_client_count == 1


@pytest.mark.asyncio
async def test_register_spa_invalid_token(hub: WebSocketHub) -> None:
    ws = FakeWebSocket()
    result = await hub.register_spa_client("spa-1", ws, "invalid")
    assert result is False
    assert hub.spa_client_count == 0


@pytest.mark.asyncio
async def test_register_spa_exceeds_limit(small_hub: WebSocketHub) -> None:
    """No permite más SPAs que max_spa_clients."""
    for i in range(3):
        ws = FakeWebSocket()
        assert await small_hub.register_spa_client(f"spa-{i}", ws, "valid-x") is True

    ws_extra = FakeWebSocket()
    assert await small_hub.register_spa_client("spa-extra", ws_extra, "valid-x") is False
    assert small_hub.spa_client_count == 3


# ---------------------------------------------------------------------------
# Tests de desregistro de agentes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unregister_agent_notifies_spas(hub: WebSocketHub) -> None:
    """Al desregistrar un agente, los SPAs reciben notificación."""
    ws_agent = FakeWebSocket()
    ws_spa = FakeWebSocket()

    await hub.register_agent("op-1", ws_agent, "valid-t")
    await hub.register_spa_client("spa-1", ws_spa, "valid-t")

    await hub.unregister_agent("op-1")

    assert "op-1" not in hub.connected_agents
    assert hub.agent_count == 0
    # SPA debe haber recibido la notificación
    assert len(ws_spa.sent) == 1
    msg = ChannelMessage.decode(ws_spa.sent[0])
    assert msg.type == "state_update"
    assert msg.payload["event"] == "agent_disconnected"
    assert msg.payload["operator_id"] == "op-1"


@pytest.mark.asyncio
async def test_unregister_nonexistent_agent(hub: WebSocketHub) -> None:
    """Desregistrar un agente inexistente no falla."""
    await hub.unregister_agent("ghost")
    assert hub.agent_count == 0


# ---------------------------------------------------------------------------
# Tests de desregistro de SPA
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unregister_spa_client(hub: WebSocketHub) -> None:
    ws = FakeWebSocket()
    await hub.register_spa_client("spa-1", ws, "valid-t")
    await hub.unregister_spa_client("spa-1")
    assert "spa-1" not in hub.connected_spa_clients


@pytest.mark.asyncio
async def test_unregister_nonexistent_spa(hub: WebSocketHub) -> None:
    """Desregistrar un SPA inexistente no falla."""
    await hub.unregister_spa_client("ghost")


# ---------------------------------------------------------------------------
# Tests de broadcast_to_spas
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_broadcast_to_spas(hub: WebSocketHub) -> None:
    ws1 = FakeWebSocket()
    ws2 = FakeWebSocket()
    await hub.register_spa_client("spa-1", ws1, "valid-t")
    await hub.register_spa_client("spa-2", ws2, "valid-t")

    msg = ChannelMessage(
        type="state_update",
        timestamp="2024-01-01T00:00:00.000Z",
        seq=1,
        version="1.0",
        payload={"active_cam": 2},
    )
    await hub.broadcast_to_spas(msg)

    assert len(ws1.sent) == 1
    assert len(ws2.sent) == 1
    # Verificar que el contenido es correcto
    decoded = ChannelMessage.decode(ws1.sent[0])
    assert decoded.type == "state_update"
    assert decoded.payload["active_cam"] == 2


@pytest.mark.asyncio
async def test_broadcast_to_spas_handles_error(hub: WebSocketHub) -> None:
    """Si un SPA falla durante broadcast, se elimina y los demás reciben."""
    ws_ok = FakeWebSocket()
    ws_broken = FakeWebSocket(should_fail=True)
    await hub.register_spa_client("spa-ok", ws_ok, "valid-t")
    await hub.register_spa_client("spa-broken", ws_broken, "valid-t")

    msg = ChannelMessage(
        type="state_update",
        timestamp="2024-01-01T00:00:00.000Z",
        seq=1,
        version="1.0",
        payload={},
    )
    await hub.broadcast_to_spas(msg)

    # El cliente bueno recibió el mensaje
    assert len(ws_ok.sent) == 1
    # El cliente roto fue eliminado
    assert "spa-broken" not in hub.connected_spa_clients
    assert hub.spa_client_count == 1


# ---------------------------------------------------------------------------
# Tests de send_to_agent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_to_agent_success(hub: WebSocketHub) -> None:
    ws = FakeWebSocket()
    await hub.register_agent("op-1", ws, "valid-t")

    msg = ChannelMessage(
        type="switch_command",
        timestamp="2024-01-01T00:00:00.000Z",
        seq=5,
        version="1.0",
        payload={"target_cam": 3},
    )
    result = await hub.send_to_agent("op-1", msg)

    assert result is True
    assert len(ws.sent) == 1


@pytest.mark.asyncio
async def test_send_to_agent_not_connected(hub: WebSocketHub) -> None:
    msg = ChannelMessage(
        type="switch_command",
        timestamp="2024-01-01T00:00:00.000Z",
        seq=5,
        version="1.0",
        payload={},
    )
    result = await hub.send_to_agent("nonexistent", msg)
    assert result is False


@pytest.mark.asyncio
async def test_send_to_agent_error(hub: WebSocketHub) -> None:
    ws = FakeWebSocket(should_fail=True)
    await hub.register_agent("op-1", ws, "valid-t")

    msg = ChannelMessage(
        type="switch_command",
        timestamp="2024-01-01T00:00:00.000Z",
        seq=5,
        version="1.0",
        payload={},
    )
    result = await hub.send_to_agent("op-1", msg)
    assert result is False


# ---------------------------------------------------------------------------
# Tests de broadcast_to_agents
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_broadcast_to_agents(hub: WebSocketHub) -> None:
    ws1 = FakeWebSocket()
    ws2 = FakeWebSocket()
    await hub.register_agent("op-1", ws1, "valid-t")
    await hub.register_agent("op-2", ws2, "valid-t")

    msg = ChannelMessage(
        type="switch_command",
        timestamp="2024-01-01T00:00:00.000Z",
        seq=10,
        version="1.0",
        payload={"target_cam": 1},
    )
    await hub.broadcast_to_agents(msg)

    assert len(ws1.sent) == 1
    assert len(ws2.sent) == 1


@pytest.mark.asyncio
async def test_broadcast_to_agents_handles_error(hub: WebSocketHub) -> None:
    """Si un agente falla durante broadcast, se elimina del hub."""
    ws_ok = FakeWebSocket()
    ws_broken = FakeWebSocket(should_fail=True)
    await hub.register_agent("op-ok", ws_ok, "valid-t")
    await hub.register_agent("op-broken", ws_broken, "valid-t")

    msg = ChannelMessage(
        type="switch_command",
        timestamp="2024-01-01T00:00:00.000Z",
        seq=1,
        version="1.0",
        payload={},
    )
    await hub.broadcast_to_agents(msg)

    assert len(ws_ok.sent) == 1
    assert "op-broken" not in hub.connected_agents
    assert hub.agent_count == 1


# ---------------------------------------------------------------------------
# Tests de separación de canales
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_channel_separation(hub: WebSocketHub) -> None:
    """Mensajes enviados a agentes no llegan a SPAs y viceversa."""
    ws_agent = FakeWebSocket()
    ws_spa = FakeWebSocket()
    await hub.register_agent("op-1", ws_agent, "valid-t")
    await hub.register_spa_client("spa-1", ws_spa, "valid-t")

    agent_msg = ChannelMessage(
        type="switch_command",
        timestamp="2024-01-01T00:00:00.000Z",
        seq=1,
        version="1.0",
        payload={"for": "agents"},
    )
    spa_msg = ChannelMessage(
        type="state_update",
        timestamp="2024-01-01T00:00:00.000Z",
        seq=2,
        version="1.0",
        payload={"for": "spas"},
    )

    await hub.broadcast_to_agents(agent_msg)
    await hub.broadcast_to_spas(spa_msg)

    # Agent only received agent message
    assert len(ws_agent.sent) == 1
    decoded_agent = ChannelMessage.decode(ws_agent.sent[0])
    assert decoded_agent.payload["for"] == "agents"

    # SPA only received SPA message
    assert len(ws_spa.sent) == 1
    decoded_spa = ChannelMessage.decode(ws_spa.sent[0])
    assert decoded_spa.payload["for"] == "spas"


# ---------------------------------------------------------------------------
# Tests de propiedades
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connected_agents_property(hub: WebSocketHub) -> None:
    assert hub.connected_agents == []
    ws = FakeWebSocket()
    await hub.register_agent("op-1", ws, "valid-t")
    assert hub.connected_agents == ["op-1"]


@pytest.mark.asyncio
async def test_connected_spa_clients_property(hub: WebSocketHub) -> None:
    assert hub.connected_spa_clients == []
    ws = FakeWebSocket()
    await hub.register_spa_client("spa-1", ws, "valid-t")
    assert hub.connected_spa_clients == ["spa-1"]


# ---------------------------------------------------------------------------
# Tests default token_validator
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_validator_rejects_all() -> None:
    """Sin token_validator inyectado, todos los registros fallan."""
    hub = WebSocketHub()
    ws = FakeWebSocket()
    assert await hub.register_agent("op-1", ws, "any-token") is False
    assert await hub.register_spa_client("spa-1", ws, "any-token") is False
