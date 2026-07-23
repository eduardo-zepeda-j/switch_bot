"""Tests unitarios para FallbackManager (SQLite WAL)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from switch_bot.web.fallback import FallbackManager, MAX_EVENTS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_engine():
    """Motor de decisión local mockeado."""
    engine = MagicMock()
    engine.start = MagicMock()
    engine.stop = MagicMock()
    return engine


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Ruta temporal para la DB de fallback."""
    return tmp_path / "fallback_test.db"


@pytest.fixture
def manager(db_path: Path, mock_engine) -> FallbackManager:
    """FallbackManager con DB temporal."""
    mgr = FallbackManager(
        db_path=db_path,
        local_decision_engine=mock_engine,
    )
    yield mgr
    mgr.close()


# ---------------------------------------------------------------------------
# Tests: Inicialización DB
# ---------------------------------------------------------------------------


class TestDBInit:
    """Tests de inicialización de la base de datos."""

    def test_creates_db_file(self, db_path: Path, mock_engine):
        """La DB se crea en la ruta especificada."""
        mgr = FallbackManager(db_path=db_path, local_decision_engine=mock_engine)
        assert db_path.exists()
        mgr.close()

    def test_creates_parent_directories(self, tmp_path: Path, mock_engine):
        """Crea directorios padre si no existen."""
        nested_path = tmp_path / "sub" / "dir" / "fallback.db"
        mgr = FallbackManager(
            db_path=nested_path, local_decision_engine=mock_engine
        )
        assert nested_path.exists()
        mgr.close()

    def test_wal_mode_enabled(self, db_path: Path, mock_engine):
        """SQLite WAL mode está habilitado."""
        mgr = FallbackManager(db_path=db_path, local_decision_engine=mock_engine)
        conn = sqlite3.connect(str(db_path))
        result = conn.execute("PRAGMA journal_mode").fetchone()
        assert result[0] == "wal"
        conn.close()
        mgr.close()

    def test_table_schema(self, db_path: Path, mock_engine):
        """La tabla fallback_events tiene la estructura correcta."""
        mgr = FallbackManager(db_path=db_path, local_decision_engine=mock_engine)
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("PRAGMA table_info(fallback_events)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}
        assert "id" in columns
        assert "smpte_tc" in columns
        assert "event_type" in columns
        assert "payload" in columns
        assert "created_at" in columns
        assert "synced" in columns
        assert "sync_attempts" in columns
        conn.close()
        mgr.close()


# ---------------------------------------------------------------------------
# Tests: Activación / Desactivación
# ---------------------------------------------------------------------------


class TestActivation:
    """Tests de activación y desactivación del Modo Fallback."""

    def test_activate_starts_local_engine(self, manager, mock_engine):
        """activate() inicia el Motor_Decisión local."""
        manager.activate()
        mock_engine.start.assert_called_once()
        assert manager.is_active is True

    def test_activate_idempotent(self, manager, mock_engine):
        """activate() repetido no reinicia el motor."""
        manager.activate()
        manager.activate()
        mock_engine.start.assert_called_once()

    def test_deactivate_stops_engine(self, manager, mock_engine):
        """deactivate() detiene el Motor_Decisión local."""
        manager.activate()
        manager.deactivate()
        mock_engine.stop.assert_called_once()
        assert manager.is_active is False

    def test_deactivate_calls_callback(self, db_path, mock_engine):
        """deactivate() invoca el callback on_deactivate."""
        callback = MagicMock()
        mgr = FallbackManager(
            db_path=db_path,
            local_decision_engine=mock_engine,
            on_deactivate=callback,
        )
        mgr.activate()
        mgr.deactivate()
        callback.assert_called_once()
        mgr.close()

    def test_deactivate_without_activate_is_noop(self, manager, mock_engine):
        """deactivate() sin activate previo no hace nada."""
        manager.deactivate()
        mock_engine.stop.assert_not_called()

    def test_is_active_initially_false(self, manager):
        """is_active es False al inicio."""
        assert manager.is_active is False


# ---------------------------------------------------------------------------
# Tests: Almacenamiento de eventos
# ---------------------------------------------------------------------------


class TestStoreEvent:
    """Tests de almacenamiento de eventos."""

    def test_store_single_event(self, manager):
        """store_event almacena correctamente un evento."""
        event = {"type": "inference_result", "data": "test"}
        manager.store_event(event, smpte_tc="01:00:00:00")
        assert manager.pending_count == 1

    def test_store_preserves_payload(self, manager):
        """El payload se preserva tras serialización/deserialización."""
        event = {"type": "switch_command", "target_cam": 2, "nested": {"key": "val"}}
        manager.store_event(event, smpte_tc="01:00:05:15")

        pending = manager.get_pending_events()
        assert len(pending) == 1
        assert pending[0]["payload"] == event

    def test_store_event_type_extracted(self, manager):
        """El event_type se extrae del campo 'type' del evento."""
        event = {"type": "state_update", "data": 123}
        manager.store_event(event, smpte_tc="00:59:59:29")

        pending = manager.get_pending_events()
        assert pending[0]["event_type"] == "state_update"

    def test_store_event_unknown_type(self, manager):
        """Eventos sin campo 'type' se almacenan con type='unknown'."""
        event = {"data": "no type field"}
        manager.store_event(event, smpte_tc="01:00:00:00")

        pending = manager.get_pending_events()
        assert pending[0]["event_type"] == "unknown"

    def test_store_multiple_events(self, manager):
        """Se pueden almacenar múltiples eventos."""
        for i in range(10):
            manager.store_event(
                {"type": "test", "seq": i},
                smpte_tc=f"01:00:00:{i:02d}",
            )
        assert manager.pending_count == 10


# ---------------------------------------------------------------------------
# Tests: Descarte FIFO (Req 11.8)
# ---------------------------------------------------------------------------


class TestFIFOEviction:
    """Tests de descarte FIFO cuando se alcanza MAX_EVENTS."""

    def test_eviction_at_max_events(self, db_path, mock_engine):
        """Al alcanzar MAX_EVENTS, se descarta el más antiguo."""
        mgr = FallbackManager(db_path=db_path, local_decision_engine=mock_engine)

        # Insertar MAX_EVENTS eventos directamente para velocidad
        conn = sqlite3.connect(str(db_path))
        conn.executemany(
            """
            INSERT INTO fallback_events (smpte_tc, event_type, payload, created_at, synced, sync_attempts)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (f"01:00:{i // 30:02d}:{i % 30:02d}", "test", json.dumps({"seq": i}), "2024-01-01T00:00:00Z", 0, 0)
                for i in range(MAX_EVENTS)
            ],
        )
        conn.commit()
        conn.close()

        # Reconectar el manager para que vea los datos
        mgr.close()
        mgr = FallbackManager(db_path=db_path, local_decision_engine=mock_engine)

        assert mgr.total_event_count == MAX_EVENTS

        # Insertar uno más → debería descartar el más antiguo
        mgr.store_event({"type": "new", "seq": MAX_EVENTS}, smpte_tc="02:00:00:00")

        assert mgr.total_event_count == MAX_EVENTS

        # El evento más antiguo (seq=0) ya no debería existir
        pending = mgr.get_pending_events(batch_size=MAX_EVENTS)
        seqs = [e["payload"]["seq"] for e in pending]
        assert 0 not in seqs
        assert MAX_EVENTS in seqs

        mgr.close()

    def test_total_never_exceeds_max(self, db_path, mock_engine):
        """El total nunca excede MAX_EVENTS."""
        # Usamos un manager con MAX_EVENTS reducido para test rápido
        mgr = FallbackManager(db_path=db_path, local_decision_engine=mock_engine)
        original_max = FallbackManager.MAX_EVENTS
        FallbackManager.MAX_EVENTS = 5

        try:
            for i in range(10):
                mgr.store_event({"type": "test", "i": i}, smpte_tc=f"01:00:00:{i:02d}")

            assert mgr.total_event_count == 5
        finally:
            FallbackManager.MAX_EVENTS = original_max
            mgr.close()


# ---------------------------------------------------------------------------
# Tests: Recuperación de eventos pendientes
# ---------------------------------------------------------------------------


class TestGetPendingEvents:
    """Tests de get_pending_events."""

    def test_returns_empty_when_no_events(self, manager):
        """Retorna lista vacía sin eventos."""
        assert manager.get_pending_events() == []

    def test_respects_batch_size(self, manager):
        """Respeta el límite de batch_size."""
        for i in range(10):
            manager.store_event(
                {"type": "test", "i": i}, smpte_tc=f"01:00:00:{i:02d}"
            )

        batch = manager.get_pending_events(batch_size=3)
        assert len(batch) == 3

    def test_ordered_by_smpte_tc(self, manager):
        """Eventos ordenados por SMPTE TC ascendente."""
        tcs = ["01:00:00:15", "01:00:00:05", "01:00:00:25", "01:00:00:10"]
        for i, tc in enumerate(tcs):
            manager.store_event({"type": "test", "i": i}, smpte_tc=tc)

        pending = manager.get_pending_events()
        smpte_values = [e["smpte_tc"] for e in pending]
        assert smpte_values == sorted(smpte_values)

    def test_excludes_synced_events(self, manager):
        """No retorna eventos ya sincronizados."""
        manager.store_event({"type": "a"}, smpte_tc="01:00:00:00")
        manager.store_event({"type": "b"}, smpte_tc="01:00:00:01")

        pending = manager.get_pending_events()
        ids_to_sync = [pending[0]["id"]]
        manager.mark_synced(ids_to_sync)

        remaining = manager.get_pending_events()
        assert len(remaining) == 1
        assert remaining[0]["payload"]["type"] == "b"

    def test_event_structure(self, manager):
        """Cada evento tiene la estructura esperada."""
        manager.store_event(
            {"type": "inference_result", "gaze_x": 0.5},
            smpte_tc="01:00:00:00",
        )

        events = manager.get_pending_events()
        event = events[0]

        assert "id" in event
        assert "smpte_tc" in event
        assert "event_type" in event
        assert "payload" in event
        assert "created_at" in event
        assert "sync_attempts" in event


# ---------------------------------------------------------------------------
# Tests: Marcado de sincronización
# ---------------------------------------------------------------------------


class TestMarkSynced:
    """Tests de mark_synced."""

    def test_mark_synced_reduces_pending(self, manager):
        """mark_synced reduce el contador de pendientes."""
        for i in range(5):
            manager.store_event({"type": "t", "i": i}, smpte_tc=f"01:00:00:{i:02d}")

        pending = manager.get_pending_events()
        ids = [e["id"] for e in pending[:3]]
        manager.mark_synced(ids)

        assert manager.pending_count == 2

    def test_mark_synced_empty_list_is_noop(self, manager):
        """mark_synced con lista vacía no falla."""
        manager.mark_synced([])  # No debe lanzar excepción

    def test_mark_synced_nonexistent_ids(self, manager):
        """mark_synced con IDs inexistentes no falla."""
        manager.mark_synced([999, 1000, 1001])  # No debe lanzar excepción


# ---------------------------------------------------------------------------
# Tests: Incremento de sync_attempts
# ---------------------------------------------------------------------------


class TestIncrementSyncAttempts:
    """Tests de increment_sync_attempts."""

    def test_increments_counter(self, manager):
        """increment_sync_attempts incrementa el contador."""
        manager.store_event({"type": "t"}, smpte_tc="01:00:00:00")

        pending = manager.get_pending_events()
        event_id = pending[0]["id"]
        assert pending[0]["sync_attempts"] == 0

        manager.increment_sync_attempts([event_id])

        pending2 = manager.get_pending_events()
        assert pending2[0]["sync_attempts"] == 1


# ---------------------------------------------------------------------------
# Tests: Propiedades
# ---------------------------------------------------------------------------


class TestProperties:
    """Tests de propiedades del manager."""

    def test_pending_count_zero_initially(self, manager):
        """pending_count es 0 sin eventos."""
        assert manager.pending_count == 0

    def test_total_event_count(self, manager):
        """total_event_count incluye synced y pending."""
        manager.store_event({"type": "a"}, smpte_tc="01:00:00:00")
        manager.store_event({"type": "b"}, smpte_tc="01:00:00:01")

        pending = manager.get_pending_events()
        manager.mark_synced([pending[0]["id"]])

        # 1 synced + 1 pending = 2 total
        assert manager.total_event_count == 2
        assert manager.pending_count == 1


# ---------------------------------------------------------------------------
# Tests: Cierre y persistencia
# ---------------------------------------------------------------------------


class TestPersistence:
    """Tests de persistencia entre instancias."""

    def test_events_survive_restart(self, db_path, mock_engine):
        """Eventos persisten tras cerrar y reabrir el manager."""
        mgr1 = FallbackManager(db_path=db_path, local_decision_engine=mock_engine)
        mgr1.store_event({"type": "persistent"}, smpte_tc="01:00:00:00")
        mgr1.close()

        mgr2 = FallbackManager(db_path=db_path, local_decision_engine=mock_engine)
        assert mgr2.pending_count == 1
        pending = mgr2.get_pending_events()
        assert pending[0]["payload"]["type"] == "persistent"
        mgr2.close()
