"""Tests unitarios para DecisionEngine.

Verifica la lógica de prioridades: habla activa, reacción, sin habla.
"""

import pytest

from switch_bot.engines.decision_engine import DecisionEngine
from switch_bot.models.config import SystemConfig
from switch_bot.models.enums import SourceOrigin
from switch_bot.models.inference import CameraDecision, GazeResult, VADResult


@pytest.fixture
def character_map() -> dict[str, int]:
    """Mapeo de personajes a cámaras (1-4)."""
    return {
        "Alice": 1,
        "Bob": 2,
        "Charlie": 3,
        "Diana": 4,
    }


@pytest.fixture
def config() -> SystemConfig:
    """Configuración por defecto del sistema."""
    return SystemConfig()


@pytest.fixture
def engine(config: SystemConfig, character_map: dict[str, int]) -> DecisionEngine:
    """Motor de decisión con configuración y mapeo de prueba."""
    return DecisionEngine(config=config, character_map=character_map)


class TestNoSpeech:
    """Cuando no hay actividad vocal, no se cambia de cámara."""

    def test_no_speech_returns_none(self, engine: DecisionEngine) -> None:
        gaze = GazeResult(feed_index=0, looking_at=1, confidence=0.9)
        vad = VADResult(is_speaking=False, speaker_id=None, confidence=0.8)

        result = engine.evaluate(gaze, vad)

        assert result is None

    def test_no_speech_with_speaker_id_returns_none(self, engine: DecisionEngine) -> None:
        """Incluso si hay speaker_id pero is_speaking es False."""
        gaze = GazeResult(feed_index=0, looking_at=2, confidence=0.95)
        vad = VADResult(is_speaking=False, speaker_id="Alice", confidence=0.3)

        result = engine.evaluate(gaze, vad)

        assert result is None


class TestSpeakerActive:
    """Cuando hay habla activa sin mirada a otro, se selecciona cámara del hablante."""

    def test_speaker_active_alice(self, engine: DecisionEngine) -> None:
        gaze = GazeResult(feed_index=0, looking_at=None, confidence=0.5)
        vad = VADResult(is_speaking=True, speaker_id="Alice", confidence=0.9)

        result = engine.evaluate(gaze, vad)

        assert result is not None
        assert result.target_cam == 1
        assert result.reason == "SPEAKER_ACTIVE"
        assert result.source_origin == SourceOrigin.AUTO

    def test_speaker_active_bob(self, engine: DecisionEngine) -> None:
        gaze = GazeResult(feed_index=1, looking_at=None, confidence=0.7)
        vad = VADResult(is_speaking=True, speaker_id="Bob", confidence=0.85)

        result = engine.evaluate(gaze, vad)

        assert result is not None
        assert result.target_cam == 2
        assert result.reason == "SPEAKER_ACTIVE"

    def test_speaker_looking_at_own_camera(self, engine: DecisionEngine) -> None:
        """Si el hablante mira a su propia cámara, es SPEAKER_ACTIVE."""
        # Alice está en cámara 1. gaze.looking_at=0 → cámara 0+1=1 (su propia)
        gaze = GazeResult(feed_index=0, looking_at=0, confidence=0.9)
        vad = VADResult(is_speaking=True, speaker_id="Alice", confidence=0.9)

        result = engine.evaluate(gaze, vad)

        assert result is not None
        assert result.target_cam == 1
        assert result.reason == "SPEAKER_ACTIVE"


class TestReactionShot:
    """Cuando el hablante mira a otra cámara, se genera un shot de reacción."""

    def test_reaction_shot_alice_looks_at_bob(self, engine: DecisionEngine) -> None:
        """Alice habla y mira a la cámara de Bob (índice 1 → cam 2)."""
        gaze = GazeResult(feed_index=0, looking_at=1, confidence=0.9)
        vad = VADResult(is_speaking=True, speaker_id="Alice", confidence=0.9)

        result = engine.evaluate(gaze, vad)

        assert result is not None
        assert result.target_cam == 2  # gaze.looking_at=1 → cam 2
        assert result.reason == "REACTION_SHOT"
        assert result.source_origin == SourceOrigin.AUTO

    def test_reaction_shot_bob_looks_at_charlie(self, engine: DecisionEngine) -> None:
        """Bob habla y mira a la cámara de Charlie (índice 2 → cam 3)."""
        gaze = GazeResult(feed_index=1, looking_at=2, confidence=0.85)
        vad = VADResult(is_speaking=True, speaker_id="Bob", confidence=0.9)

        result = engine.evaluate(gaze, vad)

        assert result is not None
        assert result.target_cam == 3
        assert result.reason == "REACTION_SHOT"

    def test_reaction_shot_charlie_looks_at_diana(self, engine: DecisionEngine) -> None:
        """Charlie habla y mira a cámara de Diana (índice 3 → cam 4)."""
        gaze = GazeResult(feed_index=2, looking_at=3, confidence=0.8)
        vad = VADResult(is_speaking=True, speaker_id="Charlie", confidence=0.92)

        result = engine.evaluate(gaze, vad)

        assert result is not None
        assert result.target_cam == 4
        assert result.reason == "REACTION_SHOT"


class TestEdgeCases:
    """Casos límite del motor de decisión."""

    def test_unknown_speaker_id_returns_none(self, engine: DecisionEngine) -> None:
        """Si el speaker_id no está en el mapeo, retorna None."""
        gaze = GazeResult(feed_index=0, looking_at=1, confidence=0.9)
        vad = VADResult(is_speaking=True, speaker_id="Unknown", confidence=0.9)

        result = engine.evaluate(gaze, vad)

        assert result is None

    def test_speaker_id_none_returns_none(self, engine: DecisionEngine) -> None:
        """Si speaker_id es None aunque is_speaking es True, retorna None."""
        gaze = GazeResult(feed_index=0, looking_at=1, confidence=0.9)
        vad = VADResult(is_speaking=True, speaker_id=None, confidence=0.9)

        result = engine.evaluate(gaze, vad)

        assert result is None

    def test_character_camera_map_property(self, engine: DecisionEngine) -> None:
        """Verifica que el mapeo es accesible vía property."""
        assert engine.character_camera_map == {
            "Alice": 1,
            "Bob": 2,
            "Charlie": 3,
            "Diana": 4,
        }
