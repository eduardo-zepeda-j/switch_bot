"""Unit tests para CaptureManager.

Verifica el ciclo de vida, manejo de desconexión de feeds y
correcta inicialización del manager de captura multicanal.

Requisitos: 1.1, 1.2, 1.3, 1.4, 5.1, 5.2, 5.3
"""

from __future__ import annotations

import multiprocessing as mp
import threading
import time
from unittest.mock import MagicMock, patch, PropertyMock

import numpy as np
import pytest

from switch_bot.capture.capture_manager import (
    AudioPacket,
    CaptureManager,
    FramePacket,
    _VideoWorker,
    _AudioWorker,
)
from switch_bot.models.config import SystemConfig


@pytest.fixture
def config_30fps() -> SystemConfig:
    """SystemConfig a 30 fps."""
    return SystemConfig(fps=30.0, num_cameras=4, drop_frame=False)


@pytest.fixture
def config_2997fps() -> SystemConfig:
    """SystemConfig a 29.97 fps."""
    return SystemConfig(fps=29.97, num_cameras=4, drop_frame=True)


@pytest.fixture
def config_60fps() -> SystemConfig:
    """SystemConfig a 60 fps."""
    return SystemConfig(fps=60.0, num_cameras=4, drop_frame=False)


@pytest.fixture
def output_queue() -> mp.Queue:
    """multiprocessing.Queue para tests."""
    q = mp.Queue()
    yield q
    # Cancel the background thread join to avoid deadlocks in tests
    q.cancel_join_thread()
    q.close()


class TestCaptureManagerInit:
    """Tests de inicialización del CaptureManager."""

    def test_creation_with_valid_config(
        self, config_30fps: SystemConfig, output_queue: mp.Queue
    ) -> None:
        """CaptureManager se crea correctamente con config válida."""
        manager = CaptureManager(config_30fps, output_queue)
        assert manager.is_running is False
        assert manager.active_feed_count == 0
        assert manager.disconnected_feeds == set()

    def test_creation_supports_all_fps(self, output_queue: mp.Queue) -> None:
        """CaptureManager soporta 60, 30 y 29.97 fps (Req 1.4)."""
        for fps in (60.0, 30.0, 29.97):
            config = SystemConfig(fps=fps)
            manager = CaptureManager(config, output_queue)
            assert manager.is_running is False


class TestCaptureManagerLifecycle:
    """Tests del ciclo de vida start/stop."""

    @patch("switch_bot.capture.capture_manager._AudioWorker.start", return_value=False)
    @patch("switch_bot.capture.capture_manager._VideoWorker.start", return_value=False)
    def test_start_capture_sets_running(
        self,
        mock_video_start: MagicMock,
        mock_audio_start: MagicMock,
        config_30fps: SystemConfig,
        output_queue: mp.Queue,
    ) -> None:
        """start_capture() marca el manager como running."""
        manager = CaptureManager(config_30fps, output_queue)
        manager.start_capture()
        assert manager.is_running is True
        manager.stop_capture()

    @patch("switch_bot.capture.capture_manager._AudioWorker.start", return_value=False)
    @patch("switch_bot.capture.capture_manager._VideoWorker.start", return_value=False)
    def test_stop_capture_cleans_up(
        self,
        mock_video_start: MagicMock,
        mock_audio_start: MagicMock,
        config_30fps: SystemConfig,
        output_queue: mp.Queue,
    ) -> None:
        """stop_capture() limpia estado y marca como no running."""
        manager = CaptureManager(config_30fps, output_queue)
        manager.start_capture()
        manager.stop_capture()
        assert manager.is_running is False

    @patch("switch_bot.capture.capture_manager._AudioWorker.start", return_value=False)
    @patch("switch_bot.capture.capture_manager._VideoWorker.start", return_value=False)
    def test_double_start_is_noop(
        self,
        mock_video_start: MagicMock,
        mock_audio_start: MagicMock,
        config_30fps: SystemConfig,
        output_queue: mp.Queue,
    ) -> None:
        """Llamar start_capture() dos veces no duplica workers."""
        manager = CaptureManager(config_30fps, output_queue)
        manager.start_capture()
        manager.start_capture()  # segunda llamada — noop
        assert manager.is_running is True
        manager.stop_capture()

    @patch("switch_bot.capture.capture_manager._AudioWorker.start", return_value=False)
    @patch("switch_bot.capture.capture_manager._VideoWorker.start", return_value=False)
    def test_stop_without_start_is_noop(
        self,
        mock_video_start: MagicMock,
        mock_audio_start: MagicMock,
        config_30fps: SystemConfig,
        output_queue: mp.Queue,
    ) -> None:
        """stop_capture() sin start previo no lanza error."""
        manager = CaptureManager(config_30fps, output_queue)
        manager.stop_capture()  # No debe lanzar excepción
        assert manager.is_running is False


class TestFeedDisconnection:
    """Tests de manejo de desconexión de feeds (Req 1.3)."""

    @patch("switch_bot.capture.capture_manager._AudioWorker.start", return_value=False)
    @patch("switch_bot.capture.capture_manager._VideoWorker.start", return_value=False)
    def test_on_feed_disconnected_logs_and_continues(
        self,
        mock_video_start: MagicMock,
        mock_audio_start: MagicMock,
        config_30fps: SystemConfig,
        output_queue: mp.Queue,
    ) -> None:
        """on_feed_disconnected registra el feed y el manager sigue activo."""
        manager = CaptureManager(config_30fps, output_queue)
        manager.start_capture()

        manager.on_feed_disconnected(2)
        assert 2 in manager.disconnected_feeds
        assert manager.is_running is True
        manager.stop_capture()

    @patch("switch_bot.capture.capture_manager._AudioWorker.start", return_value=False)
    @patch("switch_bot.capture.capture_manager._VideoWorker.start", return_value=True)
    def test_multiple_feeds_can_disconnect(
        self,
        mock_video_start: MagicMock,
        mock_audio_start: MagicMock,
        config_30fps: SystemConfig,
        output_queue: mp.Queue,
    ) -> None:
        """Múltiples feeds pueden desconectarse y el sistema continúa."""
        manager = CaptureManager(config_30fps, output_queue)
        manager.start_capture()

        # Simular desconexión de feeds 0 y 3 durante la sesión
        manager.on_feed_disconnected(0)
        manager.on_feed_disconnected(3)
        assert 0 in manager.disconnected_feeds
        assert 3 in manager.disconnected_feeds
        assert manager.is_running is True
        manager.stop_capture()

    @patch("switch_bot.capture.capture_manager._AudioWorker.start", return_value=False)
    @patch("switch_bot.capture.capture_manager._VideoWorker.start", return_value=False)
    def test_all_feeds_disconnect_manager_still_runs(
        self,
        mock_video_start: MagicMock,
        mock_audio_start: MagicMock,
        config_30fps: SystemConfig,
        output_queue: mp.Queue,
    ) -> None:
        """Aunque todos los feeds se desconecten, el manager sigue (audio continúa)."""
        manager = CaptureManager(config_30fps, output_queue)
        manager.start_capture()

        for i in range(4):
            manager.on_feed_disconnected(i)

        assert len(manager.disconnected_feeds) == 4
        assert manager.is_running is True
        manager.stop_capture()

    @patch("switch_bot.capture.capture_manager._AudioWorker.start", return_value=False)
    @patch("switch_bot.capture.capture_manager._VideoWorker.start", return_value=False)
    def test_feeds_unavailable_at_start_are_registered(
        self,
        mock_video_start: MagicMock,
        mock_audio_start: MagicMock,
        config_30fps: SystemConfig,
        output_queue: mp.Queue,
    ) -> None:
        """Feeds que fallan al abrir se registran como desconectados."""
        manager = CaptureManager(config_30fps, output_queue)
        manager.start_capture()

        # Todos los video workers retornaron False al start → desconectados
        assert len(manager.disconnected_feeds) == 4
        manager.stop_capture()


class TestFramePacket:
    """Tests del modelo FramePacket."""

    def test_frame_packet_creation(self) -> None:
        """FramePacket se crea con los datos correctos."""
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        packet = FramePacket(feed_index=1, frame=frame, timestamp=1.0)
        assert packet.feed_index == 1
        assert packet.frame.shape == (480, 640, 3)
        assert packet.timestamp == 1.0


class TestAudioPacket:
    """Tests del modelo AudioPacket."""

    def test_audio_packet_creation(self) -> None:
        """AudioPacket se crea con datos PCM."""
        data = b"\x00" * 2048
        packet = AudioPacket(data=data, timestamp=2.5)
        assert packet.data == data
        assert packet.timestamp == 2.5
        assert len(packet.data) == 2048


class TestVideoWorker:
    """Tests unitarios del _VideoWorker."""

    def test_worker_not_active_before_start(self, output_queue: mp.Queue) -> None:
        """Worker no está activo antes de llamar start()."""
        stop_event = threading.Event()
        worker = _VideoWorker(
            feed_index=0,
            fps=30.0,
            output_queue=output_queue,
            stop_event=stop_event,
            disconnect_callback=lambda idx: None,
        )
        assert worker.is_active is False

    @patch("cv2.VideoCapture")
    def test_worker_start_with_unavailable_device(
        self, mock_cap_cls: MagicMock, output_queue: mp.Queue
    ) -> None:
        """Worker retorna False si el dispositivo no está disponible."""
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = False
        mock_cap_cls.return_value = mock_cap

        stop_event = threading.Event()
        worker = _VideoWorker(
            feed_index=0,
            fps=30.0,
            output_queue=output_queue,
            stop_event=stop_event,
            disconnect_callback=lambda idx: None,
        )
        result = worker.start()
        assert result is False
        assert worker.is_active is False

    @patch("cv2.VideoCapture")
    def test_worker_start_with_available_device(
        self, mock_cap_cls: MagicMock, output_queue: mp.Queue
    ) -> None:
        """Worker retorna True y se activa si el dispositivo está disponible."""
        call_count = [0]

        def read_side_effect():
            call_count[0] += 1
            if call_count[0] <= 2:
                return (True, np.zeros((480, 640, 3), dtype=np.uint8))
            return (False, None)

        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.read.side_effect = read_side_effect
        mock_cap_cls.return_value = mock_cap

        stop_event = threading.Event()
        worker = _VideoWorker(
            feed_index=0,
            fps=30.0,
            output_queue=output_queue,
            stop_event=stop_event,
            disconnect_callback=lambda idx: None,
        )
        result = worker.start()
        assert result is True
        assert worker.is_active is True

        # Wait for thread to finish (read returns False after 2 frames)
        time.sleep(0.3)
        worker.stop()

    @patch("cv2.VideoCapture")
    def test_worker_calls_disconnect_on_read_failure(
        self, mock_cap_cls: MagicMock, output_queue: mp.Queue
    ) -> None:
        """Worker llama disconnect_callback cuando read() falla."""
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.read.return_value = (False, None)  # Simula desconexión
        mock_cap_cls.return_value = mock_cap

        stop_event = threading.Event()
        disconnected: list[int] = []
        disconnect_event = threading.Event()

        def on_disconnect(idx: int) -> None:
            disconnected.append(idx)
            disconnect_event.set()

        worker = _VideoWorker(
            feed_index=2,
            fps=30.0,
            output_queue=output_queue,
            stop_event=stop_event,
            disconnect_callback=on_disconnect,
        )
        worker.start()
        disconnect_event.wait(timeout=2.0)
        worker.stop()

        assert 2 in disconnected

    @patch("cv2.VideoCapture")
    def test_worker_sends_frames_to_queue(
        self, mock_cap_cls: MagicMock, output_queue: mp.Queue
    ) -> None:
        """Worker envía FramePackets a la queue de salida."""
        test_frame = np.ones((480, 640, 3), dtype=np.uint8) * 128
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        # Retorna un frame y luego señala stop
        call_count = [0]

        def read_side_effect():
            call_count[0] += 1
            if call_count[0] <= 3:
                return (True, test_frame.copy())
            return (False, None)  # stop after a few frames

        mock_cap.read.side_effect = read_side_effect
        mock_cap_cls.return_value = mock_cap

        stop_event = threading.Event()
        worker = _VideoWorker(
            feed_index=1,
            fps=30.0,
            output_queue=output_queue,
            stop_event=stop_event,
            disconnect_callback=lambda idx: None,
        )
        worker.start()
        time.sleep(0.3)
        stop_event.set()
        worker.stop()

        # Verificar que al menos un frame llegó a la queue
        assert not output_queue.empty()
        packet = output_queue.get_nowait()
        assert isinstance(packet, FramePacket)
        assert packet.feed_index == 1
        assert np.array_equal(packet.frame, test_frame)


class TestCaptureManagerWithMockedDevices:
    """Tests de integración ligera con dispositivos mockeados."""

    @patch("switch_bot.capture.capture_manager._AudioWorker.start", return_value=True)
    @patch("switch_bot.capture.capture_manager._VideoWorker.start", return_value=True)
    def test_start_capture_initializes_4_video_workers(
        self,
        mock_video_start: MagicMock,
        mock_audio_start: MagicMock,
        config_30fps: SystemConfig,
        output_queue: mp.Queue,
    ) -> None:
        """start_capture crea 4 workers de video (Req 1.1)."""
        manager = CaptureManager(config_30fps, output_queue)
        manager.start_capture()

        # Con start mockeado retornando True, todos los workers se consideran activos
        # pero _active no se pone a True porque el mock reemplaza el método start
        # Verificamos que se crearon 4 workers
        assert len(manager._video_workers) == 4
        assert len(manager.disconnected_feeds) == 0
        manager.stop_capture()

    @patch("switch_bot.capture.capture_manager._AudioWorker.start", return_value=True)
    @patch("switch_bot.capture.capture_manager._VideoWorker.start", return_value=False)
    def test_partial_feeds_registered_on_start_failure(
        self,
        mock_video_start: MagicMock,
        mock_audio_start: MagicMock,
        config_30fps: SystemConfig,
        output_queue: mp.Queue,
    ) -> None:
        """Si video start retorna False, los feeds se marcan desconectados."""
        manager = CaptureManager(config_30fps, output_queue)
        manager.start_capture()

        # Todos los video workers retornaron False → todos desconectados
        assert manager.disconnected_feeds == {0, 1, 2, 3}
        assert manager.is_running is True
        manager.stop_capture()
