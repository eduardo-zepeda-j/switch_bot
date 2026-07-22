"""Tests unitarios para InferenceEngine (MediaPipe gaze + VAD).

Valida el procesamiento de frames y audio sin depender de hardware real
ni de MediaPipe instalado (usa fallback cuando no está disponible).
"""

import multiprocessing as mp
import struct
import time

import numpy as np
import pytest

from switch_bot.inference.inference_engine import (
    InferenceEngine,
    InferenceMessage,
    MessageType,
)
from switch_bot.models.config import SystemConfig
from switch_bot.models.inference import GazeResult, VADResult


@pytest.fixture
def config() -> SystemConfig:
    """Configuración de sistema para tests."""
    return SystemConfig(fps=30.0, num_cameras=4)


@pytest.fixture
def queues() -> tuple[mp.Queue, mp.Queue]:
    """Par de colas para input/output."""
    return mp.Queue(), mp.Queue()


@pytest.fixture
def character_map() -> dict[str, int]:
    """Mapeo personaje → cámara para tests."""
    return {"Carlos": 0, "Ana": 1, "Pedro": 2, "Lucia": 3}


@pytest.fixture
def engine(
    queues: tuple[mp.Queue, mp.Queue],
    config: SystemConfig,
    character_map: dict[str, int],
) -> InferenceEngine:
    """InferenceEngine configurado para tests."""
    input_q, output_q = queues
    return InferenceEngine(input_q, output_q, config, character_map)


class TestInferenceEngineInit:
    """Tests de inicialización del InferenceEngine."""

    def test_creates_with_required_args(self, config: SystemConfig) -> None:
        engine = InferenceEngine(mp.Queue(), mp.Queue(), config)
        assert engine._config is config
        assert engine._running is False

    def test_creates_with_character_map(
        self, config: SystemConfig, character_map: dict[str, int]
    ) -> None:
        engine = InferenceEngine(
            mp.Queue(), mp.Queue(), config, character_map
        )
        assert engine._character_camera_map == character_map
        assert engine._camera_character_map == {
            0: "Carlos",
            1: "Ana",
            2: "Pedro",
            3: "Lucia",
        }

    def test_creates_without_character_map(self, config: SystemConfig) -> None:
        engine = InferenceEngine(mp.Queue(), mp.Queue(), config)
        assert engine._character_camera_map == {}
        assert engine._camera_character_map == {}

    def test_frame_time_from_config(self, config: SystemConfig) -> None:
        engine = InferenceEngine(mp.Queue(), mp.Queue(), config)
        # 30fps → 33.33ms
        assert abs(engine._frame_time_ms - 33.33) < 0.1


class TestProcessFrame:
    """Tests para process_frame (gaze tracking)."""

    def test_returns_gaze_result(self, engine: InferenceEngine) -> None:
        """process_frame siempre retorna un GazeResult válido."""
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        result = engine.process_frame(frame, feed_index=0)
        assert isinstance(result, GazeResult)
        assert result.feed_index == 0

    def test_without_mediapipe_returns_none_looking(
        self, engine: InferenceEngine
    ) -> None:
        """Sin MediaPipe inicializado, looking_at es None con confidence 0."""
        # _face_mesh is None by default (no _init_mediapipe called)
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        result = engine.process_frame(frame, feed_index=2)
        assert result.looking_at is None
        assert result.confidence == 0.0
        assert result.feed_index == 2

    def test_feed_index_preserved(self, engine: InferenceEngine) -> None:
        """El feed_index pasado se preserva en el resultado."""
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        for idx in range(4):
            result = engine.process_frame(frame, feed_index=idx)
            assert result.feed_index == idx

    def test_handles_invalid_frame_gracefully(
        self, engine: InferenceEngine
    ) -> None:
        """Frames con forma inesperada no causan crash."""
        # 1D array (invalid shape)
        frame = np.zeros((100,), dtype=np.uint8)
        result = engine.process_frame(frame, feed_index=0)
        assert isinstance(result, GazeResult)
        assert result.confidence == 0.0


class TestProcessAudioChunk:
    """Tests para process_audio_chunk (VAD)."""

    def test_silence_returns_not_speaking(
        self, engine: InferenceEngine
    ) -> None:
        """Audio silencioso (ceros) → is_speaking=False."""
        # 1600 samples of silence (100ms at 16kHz)
        silence = b"\x00" * 3200
        result = engine.process_audio_chunk(silence)
        assert isinstance(result, VADResult)
        assert result.is_speaking is False
        assert result.speaker_id is None

    def test_loud_audio_returns_speaking(
        self, engine: InferenceEngine
    ) -> None:
        """Audio con energía alta → is_speaking=True."""
        # Generate loud sine wave PCM 16-bit
        samples = 1600
        freq = 440.0
        sample_rate = 16000
        t = np.linspace(0, samples / sample_rate, samples, endpoint=False)
        sine_wave = (np.sin(2 * np.pi * freq * t) * 16000).astype(np.int16)
        chunk = sine_wave.tobytes()

        result = engine.process_audio_chunk(chunk)
        assert isinstance(result, VADResult)
        assert result.is_speaking is True
        assert result.confidence > 0.0

    def test_speaking_assigns_speaker_id(
        self, engine: InferenceEngine
    ) -> None:
        """Cuando se detecta habla y hay character_map, asigna speaker_id."""
        # Loud audio
        samples = 1600
        loud = (np.ones(samples) * 5000).astype(np.int16)
        chunk = loud.tobytes()

        result = engine.process_audio_chunk(chunk)
        assert result.is_speaking is True
        assert result.speaker_id is not None
        # Should be one of the characters in the map
        assert result.speaker_id in engine._character_camera_map

    def test_no_character_map_speaker_is_none(
        self, config: SystemConfig
    ) -> None:
        """Sin character_map, speaker_id es None aun con habla detectada."""
        engine = InferenceEngine(mp.Queue(), mp.Queue(), config)
        samples = 1600
        loud = (np.ones(samples) * 5000).astype(np.int16)
        chunk = loud.tobytes()

        result = engine.process_audio_chunk(chunk)
        assert result.is_speaking is True
        assert result.speaker_id is None

    def test_empty_chunk_returns_not_speaking(
        self, engine: InferenceEngine
    ) -> None:
        """Chunk vacío → is_speaking=False con confidence 0."""
        result = engine.process_audio_chunk(b"")
        assert result.is_speaking is False
        assert result.confidence == 0.0

    def test_confidence_bounded(self, engine: InferenceEngine) -> None:
        """Confidence siempre entre 0.0 y 1.0."""
        # Very loud audio (max amplitude)
        samples = 1600
        max_loud = (np.ones(samples) * 32767).astype(np.int16)
        chunk = max_loud.tobytes()

        result = engine.process_audio_chunk(chunk)
        assert 0.0 <= result.confidence <= 1.0


class TestInferenceMessage:
    """Tests para InferenceMessage."""

    def test_create_frame_message(self) -> None:
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        msg = InferenceMessage(
            msg_type=MessageType.FRAME, payload=frame, feed_index=1
        )
        assert msg.msg_type == MessageType.FRAME
        assert msg.feed_index == 1
        assert msg.payload is frame

    def test_create_audio_message(self) -> None:
        chunk = b"\x00" * 3200
        msg = InferenceMessage(
            msg_type=MessageType.AUDIO_CHUNK, payload=chunk
        )
        assert msg.msg_type == MessageType.AUDIO_CHUNK
        assert msg.payload == chunk

    def test_create_stop_message(self) -> None:
        msg = InferenceMessage(msg_type=MessageType.STOP)
        assert msg.msg_type == MessageType.STOP

    def test_timestamp_auto_populated(self) -> None:
        before = time.time()
        msg = InferenceMessage(msg_type=MessageType.STOP)
        after = time.time()
        assert before <= msg.timestamp <= after


class TestProcessLoop:
    """Tests para el bucle run() del InferenceEngine."""

    def test_stop_message_terminates_loop(
        self, engine: InferenceEngine, queues: tuple[mp.Queue, mp.Queue]
    ) -> None:
        """El mensaje STOP detiene el bucle run()."""
        input_q, output_q = queues
        input_q.put(InferenceMessage(msg_type=MessageType.STOP))

        # run() should terminate
        engine.run()
        assert engine._running is False

    def test_frame_message_produces_gaze_result(
        self, engine: InferenceEngine, queues: tuple[mp.Queue, mp.Queue]
    ) -> None:
        """Un frame en input produce un GazeResult en output."""
        input_q, output_q = queues
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        input_q.put(
            InferenceMessage(
                msg_type=MessageType.FRAME, payload=frame, feed_index=0
            )
        )
        input_q.put(InferenceMessage(msg_type=MessageType.STOP))

        engine.run()

        result = output_q.get(timeout=1.0)
        assert isinstance(result, GazeResult)

    def test_audio_message_produces_vad_result(
        self, engine: InferenceEngine, queues: tuple[mp.Queue, mp.Queue]
    ) -> None:
        """Un audio chunk en input produce un VADResult en output."""
        input_q, output_q = queues
        chunk = b"\x00" * 3200
        input_q.put(
            InferenceMessage(msg_type=MessageType.AUDIO_CHUNK, payload=chunk)
        )
        input_q.put(InferenceMessage(msg_type=MessageType.STOP))

        engine.run()

        result = output_q.get(timeout=1.0)
        assert isinstance(result, VADResult)

    def test_stop_method_sets_running_false(
        self, engine: InferenceEngine
    ) -> None:
        """stop() establece _running=False."""
        engine._running = True
        engine.stop()
        assert engine._running is False
