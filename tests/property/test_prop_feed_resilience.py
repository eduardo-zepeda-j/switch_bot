"""Property-based tests: Resiliencia ante desconexión parcial de feeds de video.

**Validates: Requirements 1.3**

Property 13: Para cualquier subconjunto de feeds (0-3) que se desconecten durante
una sesión, el CaptureManager continúa ejecutándose y maneja la desconexión
de forma graceful.
"""

from __future__ import annotations

import multiprocessing as mp
from itertools import permutations
from unittest.mock import patch, MagicMock

import pytest
from hypothesis import given, settings, assume
from hypothesis.strategies import (
    sets,
    integers,
    lists,
    sampled_from,
    permutations as st_permutations,
)

from switch_bot.capture.capture_manager import CaptureManager
from switch_bot.models.config import SystemConfig


# --- Strategies ---

# Genera subconjuntos aleatorios de índices de feeds (0 a 3)
feed_subsets = sets(integers(min_value=0, max_value=3), min_size=0, max_size=4)

# Genera listas ordenadas aleatorias de feeds que se desconectan (permutaciones)
feed_disconnect_sequences = lists(
    integers(min_value=0, max_value=3), min_size=0, max_size=4, unique=True
)


@pytest.fixture
def config() -> SystemConfig:
    """SystemConfig estándar para tests de resiliencia."""
    return SystemConfig(fps=30.0, num_cameras=4, drop_frame=False)


@pytest.fixture
def output_queue() -> mp.Queue:
    """multiprocessing.Queue para tests."""
    q = mp.Queue()
    yield q
    q.cancel_join_thread()
    q.close()


class TestProperty13FeedResilience:
    """Property 13: Resiliencia ante desconexión parcial de feeds de video.

    **Validates: Requirements 1.3**

    WHEN un feed de video se desconecta, THE Switch_bot SHALL registrar el evento
    en el log y continuar operando con los feeds restantes.
    """

    @given(disconnecting_feeds=feed_subsets)
    def test_manager_remains_running_after_any_subset_disconnects(
        self, disconnecting_feeds: set[int]
    ) -> None:
        """FOR ANY subset of feeds that disconnect, CaptureManager.is_running remains True.

        **Validates: Requirements 1.3**
        """
        queue = mp.Queue()
        try:
            config = SystemConfig(fps=30.0, num_cameras=4, drop_frame=False)

            with patch(
                "switch_bot.capture.capture_manager._VideoWorker.start",
                return_value=True,
            ), patch(
                "switch_bot.capture.capture_manager._AudioWorker.start",
                return_value=False,
            ):
                manager = CaptureManager(config, queue)
                manager.start_capture()

            # Simular desconexión del subconjunto de feeds
            for feed_idx in disconnecting_feeds:
                manager.on_feed_disconnected(feed_idx)

            # Invariante: el manager sigue corriendo sin importar cuántos feeds se desconecten
            assert manager.is_running is True

            manager.stop_capture()
        finally:
            queue.cancel_join_thread()
            queue.close()

    @given(disconnect_order=feed_disconnect_sequences)
    def test_disconnected_feeds_tracks_all_disconnections(
        self, disconnect_order: list[int]
    ) -> None:
        """FOR ANY disconnection order, disconnected_feeds contains exactly those indices.

        **Validates: Requirements 1.3**
        """
        queue = mp.Queue()
        try:
            config = SystemConfig(fps=30.0, num_cameras=4, drop_frame=False)

            with patch(
                "switch_bot.capture.capture_manager._VideoWorker.start",
                return_value=True,
            ), patch(
                "switch_bot.capture.capture_manager._AudioWorker.start",
                return_value=False,
            ):
                manager = CaptureManager(config, queue)
                manager.start_capture()

            # Desconectar feeds en el orden generado
            for feed_idx in disconnect_order:
                manager.on_feed_disconnected(feed_idx)

            # Invariante: disconnected_feeds contiene exactamente los feeds desconectados
            assert manager.disconnected_feeds == set(disconnect_order)

            manager.stop_capture()
        finally:
            queue.cancel_join_thread()
            queue.close()

    @given(disconnect_order=feed_disconnect_sequences)
    def test_no_exception_on_any_disconnection_sequence(
        self, disconnect_order: list[int]
    ) -> None:
        """FOR ANY disconnection sequence, the system never crashes or raises.

        **Validates: Requirements 1.3**
        """
        queue = mp.Queue()
        try:
            config = SystemConfig(fps=30.0, num_cameras=4, drop_frame=False)

            with patch(
                "switch_bot.capture.capture_manager._VideoWorker.start",
                return_value=True,
            ), patch(
                "switch_bot.capture.capture_manager._AudioWorker.start",
                return_value=False,
            ):
                manager = CaptureManager(config, queue)
                manager.start_capture()

            # No debe lanzar ninguna excepción para cualquier orden de desconexión
            for feed_idx in disconnect_order:
                manager.on_feed_disconnected(feed_idx)

            # Verificar estado consistente después de todas las desconexiones
            assert manager.is_running is True
            assert isinstance(manager.disconnected_feeds, set)
            assert all(
                isinstance(idx, int) for idx in manager.disconnected_feeds
            )

            manager.stop_capture()
        finally:
            queue.cancel_join_thread()
            queue.close()

    @given(disconnecting_feeds=feed_subsets)
    def test_feeds_unavailable_at_start_tracked_correctly(
        self, disconnecting_feeds: set[int]
    ) -> None:
        """FOR ANY subset of feeds that fail at start, they are tracked as disconnected.

        **Validates: Requirements 1.3**

        Simula feeds que no están disponibles al iniciar la captura (start retorna False).
        """
        queue = mp.Queue()
        try:
            config = SystemConfig(fps=30.0, num_cameras=4, drop_frame=False)

            def selective_start(self_worker: object) -> bool:
                """Retorna False solo para los feeds en disconnecting_feeds."""
                # Access feed_index through name mangling
                feed_idx = self_worker._feed_index  # type: ignore[attr-defined]
                return feed_idx not in disconnecting_feeds

            with patch(
                "switch_bot.capture.capture_manager._VideoWorker.start",
                selective_start,
            ), patch(
                "switch_bot.capture.capture_manager._AudioWorker.start",
                return_value=False,
            ):
                manager = CaptureManager(config, queue)
                manager.start_capture()

            # Invariante: los feeds que fallaron al inicio están en disconnected_feeds
            assert disconnecting_feeds.issubset(manager.disconnected_feeds)
            # El manager sigue corriendo
            assert manager.is_running is True

            manager.stop_capture()
        finally:
            queue.cancel_join_thread()
            queue.close()
