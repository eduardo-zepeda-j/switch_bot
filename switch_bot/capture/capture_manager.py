"""CaptureManager — Proceso dedicado para captura multicanal de video y audio.

Implementa la captura simultánea de 4 feeds de video (CSD/DSHOW) y 1 stream
de audio PCM en un proceso dedicado, enviando frames al proceso de inferencia
mediante multiprocessing.Queue.

Requisitos: 1.1, 1.2, 1.3, 1.4, 5.1, 5.2, 5.3
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import platform
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from switch_bot.models.config import SystemConfig

logger = logging.getLogger(__name__)


# Backend de captura según plataforma
_IS_WINDOWS = platform.system() == "Windows"
_VIDEO_BACKEND = cv2.CAP_DSHOW if _IS_WINDOWS else cv2.CAP_V4L2


@dataclass
class FramePacket:
    """Paquete de frame enviado al proceso de inferencia via Queue.

    Attributes:
        feed_index: Índice del feed de cámara (0-3).
        frame: Frame capturado como numpy array BGR.
        timestamp: Timestamp de captura (time.monotonic()).
    """

    feed_index: int
    frame: np.ndarray
    timestamp: float


@dataclass
class AudioPacket:
    """Paquete de audio PCM enviado al proceso de inferencia via Queue.

    Attributes:
        data: Bytes de audio PCM crudo.
        timestamp: Timestamp de captura (time.monotonic()).
    """

    data: bytes
    timestamp: float


class _VideoWorker:
    """Worker thread que captura frames de un feed de video individual."""

    def __init__(
        self,
        feed_index: int,
        fps: float,
        output_queue: mp.Queue,
        stop_event: threading.Event,
        disconnect_callback: Any,
    ) -> None:
        self._feed_index = feed_index
        self._fps = fps
        self._frame_interval = 1.0 / fps
        self._output_queue = output_queue
        self._stop_event = stop_event
        self._disconnect_callback = disconnect_callback
        self._cap: cv2.VideoCapture | None = None
        self._thread: threading.Thread | None = None
        self._active = False

    @property
    def is_active(self) -> bool:
        """True si el worker está capturando activamente."""
        return self._active

    def start(self) -> bool:
        """Inicia la captura de video para este feed.

        Returns:
            True si se pudo abrir el dispositivo, False en caso contrario.
        """
        self._cap = cv2.VideoCapture(self._feed_index, _VIDEO_BACKEND)
        if not self._cap.isOpened():
            logger.warning(
                "Feed %d: No se pudo abrir dispositivo de captura (backend=%s)",
                self._feed_index,
                "DSHOW" if _IS_WINDOWS else "V4L2",
            )
            return False

        # Configurar FPS del dispositivo
        self._cap.set(cv2.CAP_PROP_FPS, self._fps)
        self._active = True
        self._thread = threading.Thread(
            target=self._capture_loop,
            name=f"VideoWorker-{self._feed_index}",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Feed %d: Captura iniciada a %.2f fps", self._feed_index, self._fps
        )
        return True

    def stop(self) -> None:
        """Detiene la captura de este feed."""
        self._active = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def _capture_loop(self) -> None:
        """Loop principal de captura de frames."""
        while self._active and not self._stop_event.is_set():
            loop_start = time.monotonic()

            if self._cap is None or not self._cap.isOpened():
                self._handle_disconnect()
                return

            ret, frame = self._cap.read()
            if not ret:
                self._handle_disconnect()
                return

            packet = FramePacket(
                feed_index=self._feed_index,
                frame=frame,
                timestamp=time.monotonic(),
            )

            try:
                self._output_queue.put_nowait(packet)
            except Exception:
                # Queue llena — drop frame para no bloquear captura (Req 5.3)
                logger.debug(
                    "Feed %d: Frame dropped — queue llena", self._feed_index
                )

            # Mantener cadencia de fps
            elapsed = time.monotonic() - loop_start
            sleep_time = self._frame_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def _handle_disconnect(self) -> None:
        """Maneja la desconexión del feed."""
        self._active = False
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self._disconnect_callback(self._feed_index)


class _AudioWorker:
    """Worker thread que captura audio PCM continuamente."""

    # Configuración de audio por defecto
    _SAMPLE_RATE = 16000
    _CHANNELS = 1
    _CHUNK_SIZE = 1024  # samples per chunk

    def __init__(
        self,
        output_queue: mp.Queue,
        stop_event: threading.Event,
    ) -> None:
        self._output_queue = output_queue
        self._stop_event = stop_event
        self._thread: threading.Thread | None = None
        self._active = False
        self._stream: Any = None

    @property
    def is_active(self) -> bool:
        """True si el worker está capturando audio."""
        return self._active

    def start(self) -> bool:
        """Inicia la captura de audio PCM.

        Returns:
            True si se pudo iniciar la captura de audio.
        """
        try:
            import pyaudio  # noqa: F401 — importación tardía para no requerir en tests

            self._pa = pyaudio.PyAudio()
            self._stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=self._CHANNELS,
                rate=self._SAMPLE_RATE,
                input=True,
                frames_per_buffer=self._CHUNK_SIZE,
            )
        except Exception as exc:
            logger.warning("Audio: No se pudo iniciar captura PCM: %s", exc)
            # Captura de audio es best-effort; el sistema continúa sin audio
            return False

        self._active = True
        self._thread = threading.Thread(
            target=self._capture_loop,
            name="AudioWorker-PCM",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Audio: Captura PCM iniciada (rate=%d, channels=%d)",
            self._SAMPLE_RATE,
            self._CHANNELS,
        )
        return True

    def stop(self) -> None:
        """Detiene la captura de audio."""
        self._active = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if hasattr(self, "_pa") and self._pa is not None:
            try:
                self._pa.terminate()
            except Exception:
                pass
            self._pa = None

    def _capture_loop(self) -> None:
        """Loop principal de captura de audio PCM."""
        while self._active and not self._stop_event.is_set():
            try:
                data = self._stream.read(
                    self._CHUNK_SIZE, exception_on_overflow=False
                )
                packet = AudioPacket(
                    data=data,
                    timestamp=time.monotonic(),
                )
                try:
                    self._output_queue.put_nowait(packet)
                except Exception:
                    # Queue llena — drop audio chunk (Req 5.3: no bloquear)
                    logger.debug("Audio: Chunk dropped — queue llena")
            except Exception as exc:
                logger.error("Audio: Error en captura PCM: %s", exc)
                self._active = False
                return


class CaptureManager:
    """Proceso dedicado para captura multicanal de video y audio.

    Captura simultáneamente 4 feeds de video mediante interfaces CSD/DSHOW
    y 1 stream de audio PCM continuo. Envía los datos al proceso de inferencia
    mediante multiprocessing.Queue.

    Args:
        config: Configuración del sistema (fps, num_cameras, etc.).
        output_queue: Queue de multiprocessing para enviar frames/audio al
                      proceso de inferencia.

    Example:
        >>> import multiprocessing as mp
        >>> from switch_bot.models.config import SystemConfig
        >>> queue = mp.Queue()
        >>> config = SystemConfig(fps=30.0, num_cameras=4)
        >>> manager = CaptureManager(config, queue)
        >>> manager.start_capture()
        >>> # ... captura en progreso ...
        >>> manager.stop_capture()
    """

    def __init__(self, config: SystemConfig, output_queue: mp.Queue) -> None:
        self._config = config
        self._output_queue = output_queue
        self._stop_event = threading.Event()
        self._video_workers: list[_VideoWorker] = []
        self._audio_worker: _AudioWorker | None = None
        self._is_running = False
        self._lock = threading.Lock()
        self._disconnected_feeds: set[int] = set()

    @property
    def is_running(self) -> bool:
        """True si la captura está activa."""
        return self._is_running

    @property
    def active_feed_count(self) -> int:
        """Número de feeds de video activos."""
        return sum(1 for w in self._video_workers if w.is_active)

    @property
    def disconnected_feeds(self) -> set[int]:
        """Conjunto de índices de feeds desconectados."""
        return self._disconnected_feeds.copy()

    def start_capture(self) -> None:
        """Inicia captura de 4 feeds de video + 1 stream de audio PCM.

        Crea un worker thread por cada feed de video y uno para audio.
        Si un feed no se puede abrir, se registra pero la captura continúa
        con los feeds disponibles.
        """
        if self._is_running:
            logger.warning("CaptureManager: La captura ya está en ejecución")
            return

        self._stop_event.clear()
        self._disconnected_feeds.clear()

        # Iniciar workers de video (Req 1.1: 4 feeds CSD/DSHOW)
        for i in range(self._config.num_cameras):
            worker = _VideoWorker(
                feed_index=i,
                fps=self._config.fps,
                output_queue=self._output_queue,
                stop_event=self._stop_event,
                disconnect_callback=self.on_feed_disconnected,
            )
            self._video_workers.append(worker)
            if not worker.start():
                # Feed no disponible al inicio — registrar y continuar (Req 1.3)
                self.on_feed_disconnected(i)

        # Iniciar worker de audio PCM (Req 1.2: audio continuo)
        self._audio_worker = _AudioWorker(
            output_queue=self._output_queue,
            stop_event=self._stop_event,
        )
        self._audio_worker.start()

        self._is_running = True
        logger.info(
            "CaptureManager: Captura iniciada — %d/%d feeds de video activos, "
            "audio=%s, fps=%.2f",
            self.active_feed_count,
            self._config.num_cameras,
            "activo" if self._audio_worker.is_active else "inactivo",
            self._config.fps,
        )

    def stop_capture(self) -> None:
        """Detiene la captura limpiamente.

        Señala a todos los workers que paren y espera a que finalicen.
        """
        if not self._is_running:
            return

        logger.info("CaptureManager: Deteniendo captura...")
        self._stop_event.set()

        # Detener workers de video
        for worker in self._video_workers:
            worker.stop()
        self._video_workers.clear()

        # Detener worker de audio
        if self._audio_worker is not None:
            self._audio_worker.stop()
            self._audio_worker = None

        self._is_running = False
        logger.info("CaptureManager: Captura detenida correctamente")

    def on_feed_disconnected(self, feed_index: int) -> None:
        """Maneja la desconexión de un feed — log + continuación.

        Registra el evento y el sistema continúa operando con los feeds
        restantes (Req 1.3).

        Args:
            feed_index: Índice del feed desconectado (0 a num_cameras-1).
        """
        with self._lock:
            self._disconnected_feeds.add(feed_index)

        active = self.active_feed_count
        logger.warning(
            "CaptureManager: Feed %d desconectado. "
            "Continuando con %d/%d feeds activos.",
            feed_index,
            active,
            self._config.num_cameras,
        )
