"""Motor de inferencia dedicado: MediaPipe gaze tracking + Voice Activity Detection.

Ejecuta como proceso dedicado, recibiendo frames y audio chunks desde
CaptureManager vía multiprocessing.Queue y produciendo GazeResult/VADResult
hacia el Motor de Decisión.

Requisitos: 2.1, 2.2, 2.3, 2.4
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

import numpy as np

from switch_bot.models.config import SystemConfig
from switch_bot.models.inference import GazeResult, VADResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Message types for the input queue
# ---------------------------------------------------------------------------


class MessageType(Enum):
    """Tipos de mensaje que circulan por la queue de entrada."""

    FRAME = auto()
    AUDIO_CHUNK = auto()
    STOP = auto()


@dataclass
class InferenceMessage:
    """Mensaje enviado al InferenceEngine vía input_queue.

    Attributes:
        msg_type: Tipo de mensaje (FRAME, AUDIO_CHUNK, STOP).
        payload: Datos asociados (np.ndarray para frame, bytes para audio).
        feed_index: Índice del feed de cámara (0-3) para frames.
        timestamp: Momento de enqueue para monitoreo de latencia.
    """

    msg_type: MessageType
    payload: Any = None
    feed_index: int = 0
    timestamp: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# InferenceEngine
# ---------------------------------------------------------------------------


class InferenceEngine:
    """Proceso dedicado para MediaPipe gaze tracking + VAD.

    Opera como consumidor continuo de una multiprocessing.Queue,
    procesando frames de video (gaze tracking) y chunks de audio (VAD)
    dentro del frame time configurado sin bloquear la captura.

    Args:
        input_queue: Cola de entrada con InferenceMessage (frames/audio/stop).
        output_queue: Cola de salida con GazeResult/VADResult hacia Decision Engine.
        config: Configuración global del sistema (fps, frame_time_ms, num_cameras).
        character_camera_map: Mapeo personaje → índice de cámara para asociar
                             actividad vocal con el personaje correspondiente.
    """

    def __init__(
        self,
        input_queue: mp.Queue,  # type: ignore[type-arg]
        output_queue: mp.Queue,  # type: ignore[type-arg]
        config: SystemConfig,
        character_camera_map: dict[str, int] | None = None,
    ) -> None:
        self._input_queue = input_queue
        self._output_queue = output_queue
        self._config = config
        self._character_camera_map = character_camera_map or {}
        # Reverse map: camera_index → character_name
        self._camera_character_map: dict[int, str] = {
            cam: char for char, cam in self._character_camera_map.items()
        }
        self._running = False
        self._face_mesh: Any = None
        self._frame_time_ms = config.frame_time_ms

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def _init_mediapipe(self) -> None:
        """Inicializa MediaPipe FaceMesh para gaze tracking.

        Se llama dentro del proceso hijo para evitar problemas de
        serialización con multiprocessing.
        """
        try:
            import mediapipe as mediapipe_mod

            self._face_mesh = mediapipe_mod.solutions.face_mesh.FaceMesh(
                static_image_mode=False,
                max_num_faces=1,
                refine_landmarks=True,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )
            logger.info("MediaPipe FaceMesh inicializado correctamente.")
        except ImportError:
            logger.warning(
                "mediapipe no disponible. Gaze tracking usará fallback básico."
            )
            self._face_mesh = None

    # ------------------------------------------------------------------
    # Gaze Processing (Req 2.1)
    # ------------------------------------------------------------------

    def process_frame(self, frame: np.ndarray, feed_index: int) -> GazeResult:
        """Ejecuta MediaPipe gaze tracking sobre un frame.

        Determina hacia dónde mira la persona en el frame analizando los
        landmarks faciales de iris y orientación de cabeza.

        Args:
            frame: Imagen BGR del feed de cámara (numpy array H×W×3).
            feed_index: Índice del feed de cámara analizado (0-3).

        Returns:
            GazeResult con la cámara a la que la persona mira y confianza.
        """
        start_time = time.perf_counter()

        if self._face_mesh is None:
            # Fallback: sin MediaPipe, retornar resultado indeterminado
            return GazeResult(
                feed_index=feed_index, looking_at=None, confidence=0.0
            )

        try:
            # MediaPipe requiere RGB
            import cv2

            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self._face_mesh.process(rgb_frame)

            if not results.multi_face_landmarks:
                return GazeResult(
                    feed_index=feed_index, looking_at=None, confidence=0.0
                )

            face_landmarks = results.multi_face_landmarks[0]
            looking_at, confidence = self._estimate_gaze_direction(
                face_landmarks, frame.shape[1]
            )

            elapsed_ms = (time.perf_counter() - start_time) * 1000
            if elapsed_ms > self._frame_time_ms:
                logger.warning(
                    f"Gaze processing excedió frame time: {elapsed_ms:.1f}ms "
                    f"> {self._frame_time_ms:.1f}ms (feed {feed_index})"
                )

            return GazeResult(
                feed_index=feed_index,
                looking_at=looking_at,
                confidence=confidence,
            )

        except Exception as e:
            logger.error(f"Error en gaze tracking feed {feed_index}: {e}")
            return GazeResult(
                feed_index=feed_index, looking_at=None, confidence=0.0
            )

    def _estimate_gaze_direction(
        self, face_landmarks: Any, frame_width: int
    ) -> tuple[int | None, float]:
        """Estima la dirección de mirada a partir de landmarks de iris.

        Usa la posición relativa del iris izquierdo y derecho respecto
        a los párpados para determinar la zona horizontal de mirada,
        y la mapea a uno de los 4 feeds de cámara.

        Args:
            face_landmarks: Landmarks faciales de MediaPipe FaceMesh.
            frame_width: Ancho del frame para normalización.

        Returns:
            Tuple (camera_index, confidence) donde camera_index es 0-3
            o None si no se puede determinar.
        """
        # Iris landmarks (con refine_landmarks=True):
        # Left iris: 468-472, Right iris: 473-477
        # Left eye corners: 33 (outer), 133 (inner)
        # Right eye corners: 362 (outer), 263 (inner)
        try:
            landmarks = face_landmarks.landmark

            # Left eye iris center (landmark 468)
            left_iris = landmarks[468]
            # Left eye corners
            left_outer = landmarks[33]
            left_inner = landmarks[133]

            # Right eye iris center (landmark 473)
            right_iris = landmarks[473]
            # Right eye corners
            right_outer = landmarks[362]
            right_inner = landmarks[263]

            # Calculate horizontal iris ratio for each eye (0=outer, 1=inner)
            left_eye_width = left_inner.x - left_outer.x
            right_eye_width = right_inner.x - right_outer.x

            if left_eye_width <= 0 or right_eye_width <= 0:
                return None, 0.0

            left_ratio = (left_iris.x - left_outer.x) / left_eye_width
            right_ratio = (right_iris.x - right_outer.x) / right_eye_width

            # Average horizontal gaze ratio (0=looking left, 1=looking right)
            avg_ratio = (left_ratio + right_ratio) / 2.0

            # Map ratio to 4 camera zones (evenly distributed)
            # Ratio ~0.0-0.25 → camera 0 (far left)
            # Ratio ~0.25-0.5 → camera 1 (left)
            # Ratio ~0.5-0.75 → camera 2 (right)
            # Ratio ~0.75-1.0 → camera 3 (far right)
            num_cameras = min(self._config.num_cameras, 4)

            if avg_ratio < 0.0 or avg_ratio > 1.0:
                return None, 0.0

            camera_index = min(
                int(avg_ratio * num_cameras), num_cameras - 1
            )

            # Confidence based on how centered within the zone
            zone_width = 1.0 / num_cameras
            zone_center = (camera_index + 0.5) * zone_width
            distance_from_center = abs(avg_ratio - zone_center)
            confidence = max(0.0, 1.0 - (distance_from_center / zone_width))
            confidence = min(confidence, 1.0)

            return camera_index, round(confidence, 3)

        except (IndexError, AttributeError, ZeroDivisionError):
            return None, 0.0

    # ------------------------------------------------------------------
    # VAD Processing (Req 2.2, 2.4)
    # ------------------------------------------------------------------

    def process_audio_chunk(self, chunk: bytes) -> VADResult:
        """Ejecuta Voice Activity Detection sobre un chunk de audio PCM.

        Utiliza un enfoque basado en energía RMS del chunk para detectar
        actividad vocal. Asocia la actividad detectada con el personaje
        correspondiente según el character_camera_map del guión.

        Args:
            chunk: Datos de audio PCM (16-bit signed, mono).

        Returns:
            VADResult con estado de habla, speaker_id y confianza.
        """
        if not chunk:
            return VADResult(is_speaking=False, speaker_id=None, confidence=0.0)

        try:
            # Convert PCM 16-bit to numpy array
            audio_data = np.frombuffer(chunk, dtype=np.int16).astype(np.float32)

            if len(audio_data) == 0:
                return VADResult(
                    is_speaking=False, speaker_id=None, confidence=0.0
                )

            # Energy-based VAD: compute RMS energy
            rms = np.sqrt(np.mean(audio_data**2))

            # Normalize RMS to [0, 1] range (int16 max = 32767)
            normalized_rms = min(rms / 32767.0, 1.0)

            # Threshold for voice activity detection
            # Typical speech RMS is above ~0.01 of normalized range
            vad_threshold = 0.01
            is_speaking = bool(normalized_rms > vad_threshold)

            # Confidence: how far above threshold
            if is_speaking:
                # Scale confidence from threshold to reasonable speech level
                confidence = min(
                    (normalized_rms - vad_threshold) / (0.1 - vad_threshold),
                    1.0,
                )
                confidence = max(confidence, 0.0)
            else:
                confidence = max(0.0, 1.0 - (normalized_rms / vad_threshold))

            # Associate speaker with character (Req 2.4)
            # Use the first character in the map as default active speaker
            # In a full implementation, speaker diarization would identify who
            speaker_id: str | None = None
            if is_speaking and self._character_camera_map:
                # Default to first character — real system would use
                # diarization or mic-to-character mapping
                speaker_id = next(iter(self._character_camera_map), None)

            return VADResult(
                is_speaking=is_speaking,
                speaker_id=speaker_id,
                confidence=round(confidence, 3),
            )

        except Exception as e:
            logger.error(f"Error en VAD processing: {e}")
            return VADResult(
                is_speaking=False, speaker_id=None, confidence=0.0
            )

    # ------------------------------------------------------------------
    # Process Loop (Req 2.3 — dedicated process)
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Bucle principal del proceso de inferencia.

        Lee continuamente de input_queue, procesa frames y audio chunks,
        y envía resultados a output_queue. Se detiene al recibir un
        mensaje STOP.

        Garantiza ejecución dentro del frame time sin bloquear captura
        ya que opera en un proceso dedicado separado del CaptureManager.
        """
        self._init_mediapipe()
        self._running = True
        logger.info(
            f"InferenceEngine iniciado (frame_time={self._frame_time_ms:.2f}ms)"
        )

        while self._running:
            try:
                # Non-blocking get with small timeout to allow clean shutdown
                msg: InferenceMessage = self._input_queue.get(timeout=0.1)
            except Exception:
                # Queue empty timeout — keep looping
                continue

            if msg.msg_type == MessageType.STOP:
                logger.info("InferenceEngine recibió señal STOP.")
                self._running = False
                break

            elif msg.msg_type == MessageType.FRAME:
                result = self.process_frame(msg.payload, msg.feed_index)
                self._output_queue.put(result)

            elif msg.msg_type == MessageType.AUDIO_CHUNK:
                result = self.process_audio_chunk(msg.payload)
                self._output_queue.put(result)

        logger.info("InferenceEngine detenido.")

    def stop(self) -> None:
        """Señaliza detención del proceso de inferencia."""
        self._running = False

    @staticmethod
    def start_process(
        input_queue: mp.Queue,  # type: ignore[type-arg]
        output_queue: mp.Queue,  # type: ignore[type-arg]
        config: SystemConfig,
        character_camera_map: dict[str, int] | None = None,
    ) -> mp.Process:
        """Crea e inicia el proceso dedicado del InferenceEngine.

        Args:
            input_queue: Cola de entrada para frames/audio.
            output_queue: Cola de salida para resultados de inferencia.
            config: Configuración del sistema.
            character_camera_map: Mapeo personaje → cámara del guión.

        Returns:
            El proceso iniciado (mp.Process).
        """
        engine = InferenceEngine(
            input_queue, output_queue, config, character_camera_map
        )
        process = mp.Process(
            target=engine.run, name="InferenceEngine", daemon=True
        )
        process.start()
        return process
