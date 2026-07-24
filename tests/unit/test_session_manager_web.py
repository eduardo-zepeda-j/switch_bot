"""Unit tests para SessionManagerWeb — gestión centralizada multi-operador.

Verifica:
- Creación de sesión con UUID v4 y validación de rol director.
- Unión de agentes con límite MAX_AGENTS=8.
- Propagación de estado a agentes + SPAs.
- Resolución de conflictos first-write-wins.
- Finalización con consolidación y retry 3x.
- Recuperación post-reinicio desde SQLite.
- Persistencia periódica.
- Transiciones de estado válidas e inválidas.

Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from switch_bot.web.session_manager import (
    ConsolidationResult,
    InvalidStateTransitionError,
    Session,
    SessionCreationError,
    SessionFullError,
    SessionManagerWeb,
    SessionNotFoundError,
    SessionState,
    VALID_TRANSITIONS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_hub():
    """Crea un mock de WebSocketHub."""
    hub = MagicMock()
    hub.broadcast_to_agents = AsyncMock()
    hub.broadcast_to_spas = AsyncMock()
    hub.send_to_agent = AsyncMock(return_value=True)
    hub.connected_agents = []
    hub.connected_spa_clients = []
    return hub


@pytest.fixture
def storage_path(tmp_path):
    """Directorio temporal para almacenamiento."""
    return tmp_path / "sessions_storage"


@pytest.fixture
def manager(mock_hub, storage_path):
    """Crea un SessionManagerWeb con dependencias mockeadas."""
    return SessionManagerWeb(hub=mock_hub, storage_path=storage_path)


# ---------------------------------------------------------------------------
# Tests: Creación de sesión (Req 8.3)
# ---------------------------------------------------------------------------


class TestCreateSession:
    """Tests para create_session()."""

    @pytest.mark.asyncio
    async def test_create_session_director(self, manager):
        """Director puede crear sesiones."""
        config = {"video_mode": "1080p", "backend_ia": "bedrock"}
        session = await manager.create_session(config, "director")

        assert session.session_id is not None
        # Validar que es UUID v4
        parsed_uuid = uuid.UUID(session.session_id, version=4)
        assert str(parsed_uuid) == session.session_id
        assert session.state == SessionState.CREATED
        assert session.config == config
        assert session.creator_role == "director"
        assert session.agents == []

    @pytest.mark.asyncio
    async def test_create_session_administrador(self, manager):
        """Administrador puede crear sesiones."""
        config = {"video_mode": "4K"}
        session = await manager.create_session(config, "administrador")

        assert session.state == SessionState.CREATED
        assert session.creator_role == "administrador"

    @pytest.mark.asyncio
    async def test_create_session_operador_rejected(self, manager):
        """Operador NO puede crear sesiones."""
        with pytest.raises(SessionCreationError):
            await manager.create_session({}, "operador")

    @pytest.mark.asyncio
    async def test_create_session_unknown_role_rejected(self, manager):
        """Rol desconocido NO puede crear sesiones."""
        with pytest.raises(SessionCreationError):
            await manager.create_session({}, "viewer")


    @pytest.mark.asyncio
    async def test_create_session_persists_to_sqlite(self, manager, storage_path):
        """La sesión creada se persiste en SQLite."""
        session = await manager.create_session({"mode": "test"}, "director")

        # Verificar que el archivo DB existe
        db_path = storage_path / "sessions.db"
        assert db_path.exists()

        # Verificar contenido en DB
        import sqlite3

        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT session_id, state FROM sessions WHERE session_id = ?",
            (session.session_id,),
        ).fetchone()
        conn.close()

        assert row is not None
        assert row[0] == session.session_id
        assert row[1] == "created"


# ---------------------------------------------------------------------------
# Tests: Unión de agentes (Req 8.4)
# ---------------------------------------------------------------------------


class TestJoinSession:
    """Tests para join_session()."""

    @pytest.mark.asyncio
    async def test_join_session_success(self, manager):
        """Agente se une a sesión existente."""
        session = await manager.create_session({}, "director")
        result = await manager.join_session(session.session_id, "op1")

        assert result is True
        assert "op1" in session.agents

    @pytest.mark.asyncio
    async def test_join_session_max_agents(self, manager):
        """No se puede exceder MAX_AGENTS=8."""
        session = await manager.create_session({}, "director")

        # Unir 8 agentes
        for i in range(8):
            await manager.join_session(session.session_id, f"op{i}")

        # El 9no debe fallar
        with pytest.raises(SessionFullError):
            await manager.join_session(session.session_id, "op_extra")

    @pytest.mark.asyncio
    async def test_join_session_not_found(self, manager):
        """Unirse a sesión inexistente lanza error."""
        with pytest.raises(SessionNotFoundError):
            await manager.join_session("nonexistent-id", "op1")


    @pytest.mark.asyncio
    async def test_join_session_duplicate_agent(self, manager):
        """Agente que ya está en la sesión no se duplica."""
        session = await manager.create_session({}, "director")
        await manager.join_session(session.session_id, "op1")
        result = await manager.join_session(session.session_id, "op1")

        assert result is True
        assert session.agents.count("op1") == 1

    @pytest.mark.asyncio
    async def test_join_finalized_session(self, manager):
        """No se puede unir a sesión finalizada."""
        session = await manager.create_session({}, "director")
        # Forzar estado finalizado directamente
        session.state = SessionState.FINALIZED

        result = await manager.join_session(session.session_id, "op1")
        assert result is False


# ---------------------------------------------------------------------------
# Tests: Propagación de estado (Req 8.2)
# ---------------------------------------------------------------------------


class TestPropagateState:
    """Tests para propagate_state()."""

    @pytest.mark.asyncio
    async def test_propagate_state_calls_hub(self, manager, mock_hub):
        """Propaga estado a agentes y SPAs vía hub."""
        session = await manager.create_session({}, "director")
        await manager.propagate_state(session.session_id)

        mock_hub.broadcast_to_agents.assert_called_once()
        mock_hub.broadcast_to_spas.assert_called_once()

    @pytest.mark.asyncio
    async def test_propagate_state_not_found(self, manager):
        """Propagar estado de sesión inexistente lanza error."""
        with pytest.raises(SessionNotFoundError):
            await manager.propagate_state("nonexistent")

    @pytest.mark.asyncio
    async def test_propagate_state_payload(self, manager, mock_hub):
        """El payload propagado contiene info de la sesión."""
        session = await manager.create_session({"mode": "test"}, "director")
        await manager.join_session(session.session_id, "op1")
        await manager.propagate_state(session.session_id)

        # Verificar que el mensaje enviado tiene los datos correctos
        call_args = mock_hub.broadcast_to_spas.call_args
        message = call_args[0][0]
        assert message.type == "state_update"
        assert message.payload["session_id"] == session.session_id
        assert message.payload["state"] == "created"
        assert "op1" in message.payload["agents"]


# ---------------------------------------------------------------------------
# Tests: Resolución de conflictos (Req 8.8)
# ---------------------------------------------------------------------------


class TestHandleConflict:
    """Tests para handle_conflict()."""

    @pytest.mark.asyncio
    async def test_first_write_wins(self, manager, mock_hub):
        """El comando con timestamp más temprano gana."""
        session = await manager.create_session({}, "director")
        commands = [
            {"operator_id": "op2", "timestamp": "2024-01-01T00:00:01.000Z", "resource": "cam1", "action": "switch"},
            {"operator_id": "op1", "timestamp": "2024-01-01T00:00:00.500Z", "resource": "cam1", "action": "switch"},
        ]

        result = await manager.handle_conflict(session.session_id, commands)

        assert result["accepted"]["operator_id"] == "op1"
        assert len(result["rejected"]) == 1
        assert result["rejected"][0]["operator_id"] == "op2"

    @pytest.mark.asyncio
    async def test_conflict_notifies_rejected(self, manager, mock_hub):
        """Operadores rechazados reciben notificación."""
        session = await manager.create_session({}, "director")
        commands = [
            {"operator_id": "op1", "timestamp": "2024-01-01T00:00:00.000Z", "resource": "cam1"},
            {"operator_id": "op2", "timestamp": "2024-01-01T00:00:00.100Z", "resource": "cam1"},
        ]

        await manager.handle_conflict(session.session_id, commands)

        mock_hub.send_to_agent.assert_called_once()
        call_args = mock_hub.send_to_agent.call_args
        assert call_args[0][0] == "op2"  # Operador rechazado

    @pytest.mark.asyncio
    async def test_conflict_empty_commands(self, manager):
        """Lista vacía de comandos retorna None."""
        session = await manager.create_session({}, "director")
        result = await manager.handle_conflict(session.session_id, [])

        assert result["accepted"] is None
        assert result["rejected"] == []

    @pytest.mark.asyncio
    async def test_conflict_records_event(self, manager, mock_hub):
        """El conflicto se registra en los eventos de la sesión."""
        session = await manager.create_session({}, "director")
        commands = [
            {"operator_id": "op1", "timestamp": "2024-01-01T00:00:00.000Z", "resource": "cam1"},
            {"operator_id": "op2", "timestamp": "2024-01-01T00:00:00.100Z", "resource": "cam1"},
        ]

        await manager.handle_conflict(session.session_id, commands)

        conflict_events = [e for e in session.events if e["type"] == "conflict_resolved"]
        assert len(conflict_events) == 1
        assert conflict_events[0]["accepted_operator"] == "op1"


# ---------------------------------------------------------------------------
# Tests: Finalización de sesión (Req 8.5, 8.9)
# ---------------------------------------------------------------------------


class TestFinalizeSession:
    """Tests para finalize_session()."""

    @pytest.mark.asyncio
    async def test_finalize_started_session(self, manager, mock_hub):
        """Sesión started se puede finalizar con consolidación."""
        session = await manager.create_session({}, "director")
        # Transicionar a started
        session.state = SessionState.STARTED

        result = await manager.finalize_session(session.session_id)

        assert result.success is True
        assert result.session_id == session.session_id
        assert result.logs_path is not None
        assert result.edl_path is not None
        assert result.metadata_path is not None
        assert session.state == SessionState.FINALIZED

    @pytest.mark.asyncio
    async def test_finalize_paused_session(self, manager, mock_hub):
        """Sesión paused se puede finalizar."""
        session = await manager.create_session({}, "director")
        session.state = SessionState.PAUSED

        result = await manager.finalize_session(session.session_id)

        assert result.success is True
        assert session.state == SessionState.FINALIZED

    @pytest.mark.asyncio
    async def test_finalize_created_session_invalid(self, manager):
        """Sesión created NO se puede finalizar directamente."""
        session = await manager.create_session({}, "director")

        with pytest.raises(InvalidStateTransitionError):
            await manager.finalize_session(session.session_id)

    @pytest.mark.asyncio
    async def test_finalize_writes_files(self, manager, mock_hub, storage_path):
        """La consolidación escribe logs, EDL y metadata."""
        session = await manager.create_session({}, "director")
        session.state = SessionState.STARTED
        session.events.append({"type": "test_event", "data": "hello"})

        result = await manager.finalize_session(session.session_id)

        assert result.logs_path.exists()
        assert result.edl_path.exists()
        assert result.metadata_path.exists()

        # Verificar contenido del log
        with open(result.logs_path) as f:
            lines = f.readlines()
        assert len(lines) >= 1

    @pytest.mark.asyncio
    async def test_consolidation_retry_then_success(self, manager, mock_hub):
        """Consolidación falla en primer intento, reintenta y tiene éxito (Req 8.9).

        Simula que _consolidate lanza excepción en los primeros intentos
        pero tiene éxito en el tercero. Verifica que el retry funciona.
        """
        session = await manager.create_session({}, "director")
        session.state = SessionState.STARTED

        call_count = {"n": 0}
        original_consolidate = manager._consolidate

        async def mock_consolidate(sess, attempt):
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise RuntimeError("I/O error simulado")
            return await original_consolidate(sess, attempt)

        # Reducir delay de retry para que el test sea rápido
        manager.CONSOLIDATION_RETRY_DELAY = 0.01

        with patch.object(manager, "_consolidate", side_effect=mock_consolidate):
            result = await manager.finalize_session(session.session_id)

        assert result.success is True
        assert result.attempts == 3
        assert session.state == SessionState.FINALIZED
        assert call_count["n"] == 3

    @pytest.mark.asyncio
    async def test_consolidation_retry_all_fail(self, manager, mock_hub):
        """Consolidación falla en todos los reintentos (3x) y notifica al operador (Req 8.9).

        Verifica que tras 3 intentos fallidos:
        - Se retorna ConsolidationResult con success=False.
        - Se notifica a SPAs del fallo vía hub.
        - La sesión NO transiciona a FINALIZED.
        """
        session = await manager.create_session({}, "director")
        session.state = SessionState.STARTED

        # Reducir delay de retry para que el test sea rápido
        manager.CONSOLIDATION_RETRY_DELAY = 0.01

        async def failing_consolidate(sess, attempt):
            raise RuntimeError("Disk full")

        with patch.object(manager, "_consolidate", side_effect=failing_consolidate):
            result = await manager.finalize_session(session.session_id)

        assert result.success is False
        assert result.attempts == 3
        assert "Disk full" in result.error_message
        # La sesión NO debe haber transitado a FINALIZED
        assert session.state == SessionState.STARTED

        # Verificar notificación a SPAs
        mock_hub.broadcast_to_spas.assert_called()
        last_call = mock_hub.broadcast_to_spas.call_args
        message = last_call[0][0]
        assert message.type == "session_control"
        assert message.payload["event"] == "consolidation_failed"
        assert message.payload["session_id"] == session.session_id
        assert message.payload["attempts"] == 3

    @pytest.mark.asyncio
    async def test_consolidation_retry_succeeds_on_second_attempt(self, manager, mock_hub):
        """Consolidación falla en primer intento pero tiene éxito en el segundo (Req 8.9)."""
        session = await manager.create_session({}, "director")
        session.state = SessionState.STARTED

        call_count = {"n": 0}
        original_consolidate = manager._consolidate

        async def mock_consolidate(sess, attempt):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("Temporary network error")
            return await original_consolidate(sess, attempt)

        manager.CONSOLIDATION_RETRY_DELAY = 0.01

        with patch.object(manager, "_consolidate", side_effect=mock_consolidate):
            result = await manager.finalize_session(session.session_id)

        assert result.success is True
        assert result.attempts == 2
        assert session.state == SessionState.FINALIZED
        assert call_count["n"] == 2


# ---------------------------------------------------------------------------
# Tests: Recuperación post-reinicio (Req 8.6)
# ---------------------------------------------------------------------------


class TestRecoverSessions:
    """Tests para recover_sessions()."""

    @pytest.mark.asyncio
    async def test_recover_persisted_sessions(self, mock_hub, storage_path):
        """Sesiones activas se recuperan desde SQLite."""
        # Crear y persistir una sesión
        manager1 = SessionManagerWeb(hub=mock_hub, storage_path=storage_path)
        session = await manager1.create_session({"mode": "test"}, "director")
        session.state = SessionState.STARTED
        manager1._persist_session(session)

        # Simular reinicio: nuevo manager que recupera
        manager2 = SessionManagerWeb(hub=mock_hub, storage_path=storage_path)
        recovered = await manager2.recover_sessions()

        assert len(recovered) == 1
        assert recovered[0].session_id == session.session_id
        assert recovered[0].state == SessionState.STARTED

    @pytest.mark.asyncio
    async def test_finalized_sessions_not_recovered(self, mock_hub, storage_path):
        """Sesiones finalizadas NO se recuperan."""
        manager1 = SessionManagerWeb(hub=mock_hub, storage_path=storage_path)
        session = await manager1.create_session({}, "director")
        session.state = SessionState.FINALIZED
        manager1._persist_session(session)

        manager2 = SessionManagerWeb(hub=mock_hub, storage_path=storage_path)
        recovered = await manager2.recover_sessions()

        assert len(recovered) == 0

    @pytest.mark.asyncio
    async def test_recover_empty_db(self, manager):
        """Recuperar sin sesiones retorna lista vacía."""
        recovered = await manager.recover_sessions()
        assert recovered == []


# ---------------------------------------------------------------------------
# Tests: Transiciones de estado (Req 8.1)
# ---------------------------------------------------------------------------


class TestStateTransitions:
    """Tests para transition_state() y VALID_TRANSITIONS."""

    @pytest.mark.asyncio
    async def test_created_to_started(self, manager, mock_hub):
        """Transición created → started es válida."""
        session = await manager.create_session({}, "director")
        result = await manager.transition_state(
            session.session_id, SessionState.STARTED
        )
        assert result.state == SessionState.STARTED

    @pytest.mark.asyncio
    async def test_started_to_paused(self, manager, mock_hub):
        """Transición started → paused es válida."""
        session = await manager.create_session({}, "director")
        await manager.transition_state(session.session_id, SessionState.STARTED)
        result = await manager.transition_state(
            session.session_id, SessionState.PAUSED
        )
        assert result.state == SessionState.PAUSED


    @pytest.mark.asyncio
    async def test_paused_to_started(self, manager, mock_hub):
        """Transición paused → started es válida."""
        session = await manager.create_session({}, "director")
        await manager.transition_state(session.session_id, SessionState.STARTED)
        await manager.transition_state(session.session_id, SessionState.PAUSED)
        result = await manager.transition_state(
            session.session_id, SessionState.STARTED
        )
        assert result.state == SessionState.STARTED

    @pytest.mark.asyncio
    async def test_started_to_finalized(self, manager, mock_hub):
        """Transición started → finalized es válida."""
        session = await manager.create_session({}, "director")
        await manager.transition_state(session.session_id, SessionState.STARTED)
        result = await manager.transition_state(
            session.session_id, SessionState.FINALIZED
        )
        assert result.state == SessionState.FINALIZED

    @pytest.mark.asyncio
    async def test_paused_to_finalized(self, manager, mock_hub):
        """Transición paused → finalized es válida."""
        session = await manager.create_session({}, "director")
        await manager.transition_state(session.session_id, SessionState.STARTED)
        await manager.transition_state(session.session_id, SessionState.PAUSED)
        result = await manager.transition_state(
            session.session_id, SessionState.FINALIZED
        )
        assert result.state == SessionState.FINALIZED

    @pytest.mark.asyncio
    async def test_invalid_created_to_paused(self, manager):
        """Transición created → paused es inválida."""
        session = await manager.create_session({}, "director")
        with pytest.raises(InvalidStateTransitionError):
            await manager.transition_state(
                session.session_id, SessionState.PAUSED
            )

    @pytest.mark.asyncio
    async def test_invalid_created_to_finalized(self, manager):
        """Transición created → finalized es inválida."""
        session = await manager.create_session({}, "director")
        with pytest.raises(InvalidStateTransitionError):
            await manager.transition_state(
                session.session_id, SessionState.FINALIZED
            )

    @pytest.mark.asyncio
    async def test_invalid_finalized_to_any(self, manager, mock_hub):
        """Desde finalized no se puede transicionar a ningún estado."""
        session = await manager.create_session({}, "director")
        await manager.transition_state(session.session_id, SessionState.STARTED)
        await manager.transition_state(session.session_id, SessionState.FINALIZED)

        with pytest.raises(InvalidStateTransitionError):
            await manager.transition_state(
                session.session_id, SessionState.STARTED
            )

    @pytest.mark.asyncio
    async def test_transition_records_event(self, manager, mock_hub):
        """Las transiciones se registran como eventos."""
        session = await manager.create_session({}, "director")
        await manager.transition_state(session.session_id, SessionState.STARTED)

        transition_events = [
            e for e in session.events if e["type"] == "state_transition"
        ]
        assert len(transition_events) == 1
        assert transition_events[0]["from_state"] == "created"
        assert transition_events[0]["to_state"] == "started"

    @pytest.mark.asyncio
    async def test_transition_propagates_state(self, manager, mock_hub):
        """Las transiciones propagan estado vía hub."""
        session = await manager.create_session({}, "director")
        await manager.transition_state(session.session_id, SessionState.STARTED)

        # propagate_state llama broadcast_to_agents y broadcast_to_spas
        assert mock_hub.broadcast_to_agents.called
        assert mock_hub.broadcast_to_spas.called


# ---------------------------------------------------------------------------
# Tests: Utilidades y desconexión (Req 8.7)
# ---------------------------------------------------------------------------


class TestUtilities:
    """Tests para utilidades y remove_agent_from_session."""

    @pytest.mark.asyncio
    async def test_get_session(self, manager):
        """get_session retorna la sesión por ID."""
        session = await manager.create_session({}, "director")
        found = manager.get_session(session.session_id)
        assert found is session

    @pytest.mark.asyncio
    async def test_get_session_not_found(self, manager):
        """get_session retorna None si no existe."""
        assert manager.get_session("nonexistent") is None

    @pytest.mark.asyncio
    async def test_active_session_count(self, manager):
        """active_session_count refleja sesiones creadas."""
        assert manager.active_session_count == 0
        await manager.create_session({}, "director")
        assert manager.active_session_count == 1
        await manager.create_session({}, "director")
        assert manager.active_session_count == 2

    @pytest.mark.asyncio
    async def test_remove_agent_from_session(self, manager):
        """Agente removido de sesión registra evento."""
        session = await manager.create_session({}, "director")
        await manager.join_session(session.session_id, "op1")

        result = manager.remove_agent_from_session(session.session_id, "op1")

        assert result is True
        assert "op1" not in session.agents
        disconnect_events = [
            e for e in session.events if e["type"] == "agent_disconnected"
        ]
        assert len(disconnect_events) == 1
        assert disconnect_events[0]["operator_id"] == "op1"

    @pytest.mark.asyncio
    async def test_remove_agent_not_in_session(self, manager):
        """Remover agente que no está en la sesión retorna False."""
        session = await manager.create_session({}, "director")
        result = manager.remove_agent_from_session(session.session_id, "op1")
        assert result is False

    @pytest.mark.asyncio
    async def test_remove_agent_session_not_found(self, manager):
        """Remover agente de sesión inexistente retorna False."""
        result = manager.remove_agent_from_session("nonexistent", "op1")
        assert result is False

    @pytest.mark.asyncio
    async def test_inherits_session_manager(self, manager):
        """SessionManagerWeb hereda de SessionManager."""
        from switch_bot.engines.session_manager import SessionManager

        assert isinstance(manager, SessionManager)
