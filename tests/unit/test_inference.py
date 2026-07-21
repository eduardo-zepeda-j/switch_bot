"""Tests unitarios para modelos de inferencia (GazeResult, VADResult, CameraDecision)."""

import pytest

from switch_bot.models.enums import SourceOrigin
from switch_bot.models.inference import CameraDecision, GazeResult, VADResult


class TestGazeResult:
    """Tests para GazeResult."""

    def test_create_valid_gaze_looking_at_camera(self) -> None:
        result = GazeResult(feed_index=0, looking_at=2, confidence=0.95)
        assert result.feed_index == 0
        assert result.looking_at == 2
        assert result.confidence == 0.95

    def test_create_gaze_looking_at_none(self) -> None:
        result = GazeResult(feed_index=1, looking_at=None, confidence=0.3)
        assert result.looking_at is None

    def test_gaze_is_frozen(self) -> None:
        result = GazeResult(feed_index=0, looking_at=1, confidence=0.8)
        with pytest.raises(AttributeError):
            result.feed_index = 2  # type: ignore[misc]

    def test_feed_index_below_range(self) -> None:
        with pytest.raises(ValueError, match="feed_index debe estar entre 0 y 3"):
            GazeResult(feed_index=-1, looking_at=0, confidence=0.5)

    def test_feed_index_above_range(self) -> None:
        with pytest.raises(ValueError, match="feed_index debe estar entre 0 y 3"):
            GazeResult(feed_index=4, looking_at=0, confidence=0.5)

    def test_looking_at_below_range(self) -> None:
        with pytest.raises(ValueError, match="looking_at debe estar entre 0 y 3"):
            GazeResult(feed_index=0, looking_at=-1, confidence=0.5)

    def test_looking_at_above_range(self) -> None:
        with pytest.raises(ValueError, match="looking_at debe estar entre 0 y 3"):
            GazeResult(feed_index=0, looking_at=4, confidence=0.5)

    def test_confidence_below_range(self) -> None:
        with pytest.raises(ValueError, match="confidence debe estar entre 0.0 y 1.0"):
            GazeResult(feed_index=0, looking_at=1, confidence=-0.1)

    def test_confidence_above_range(self) -> None:
        with pytest.raises(ValueError, match="confidence debe estar entre 0.0 y 1.0"):
            GazeResult(feed_index=0, looking_at=1, confidence=1.1)

    def test_boundary_values(self) -> None:
        # Min values
        g1 = GazeResult(feed_index=0, looking_at=0, confidence=0.0)
        assert g1.confidence == 0.0
        # Max values
        g2 = GazeResult(feed_index=3, looking_at=3, confidence=1.0)
        assert g2.feed_index == 3


class TestVADResult:
    """Tests para VADResult."""

    def test_create_speaking_with_speaker(self) -> None:
        result = VADResult(is_speaking=True, speaker_id="Carlos", confidence=0.9)
        assert result.is_speaking is True
        assert result.speaker_id == "Carlos"
        assert result.confidence == 0.9

    def test_create_not_speaking(self) -> None:
        result = VADResult(is_speaking=False, speaker_id=None, confidence=0.85)
        assert result.is_speaking is False
        assert result.speaker_id is None

    def test_vad_is_frozen(self) -> None:
        result = VADResult(is_speaking=True, speaker_id="Ana", confidence=0.7)
        with pytest.raises(AttributeError):
            result.is_speaking = False  # type: ignore[misc]

    def test_confidence_below_range(self) -> None:
        with pytest.raises(ValueError, match="confidence debe estar entre 0.0 y 1.0"):
            VADResult(is_speaking=True, speaker_id=None, confidence=-0.01)

    def test_confidence_above_range(self) -> None:
        with pytest.raises(ValueError, match="confidence debe estar entre 0.0 y 1.0"):
            VADResult(is_speaking=True, speaker_id=None, confidence=1.01)

    def test_boundary_confidence(self) -> None:
        v1 = VADResult(is_speaking=False, speaker_id=None, confidence=0.0)
        assert v1.confidence == 0.0
        v2 = VADResult(is_speaking=True, speaker_id="X", confidence=1.0)
        assert v2.confidence == 1.0


class TestCameraDecision:
    """Tests para CameraDecision."""

    def test_create_valid_decision(self) -> None:
        decision = CameraDecision(
            target_cam=3,
            reason="Speaker detected on camera 3",
            source_origin=SourceOrigin.AUTO,
        )
        assert decision.target_cam == 3
        assert decision.reason == "Speaker detected on camera 3"
        assert decision.source_origin == SourceOrigin.AUTO

    def test_decision_is_frozen(self) -> None:
        decision = CameraDecision(
            target_cam=1, reason="Manual", source_origin=SourceOrigin.MANUAL
        )
        with pytest.raises(AttributeError):
            decision.target_cam = 2  # type: ignore[misc]

    def test_target_cam_below_range(self) -> None:
        with pytest.raises(ValueError, match="target_cam debe estar entre 1 y 4"):
            CameraDecision(
                target_cam=0, reason="test", source_origin=SourceOrigin.AUTO
            )

    def test_target_cam_above_range(self) -> None:
        with pytest.raises(ValueError, match="target_cam debe estar entre 1 y 4"):
            CameraDecision(
                target_cam=5, reason="test", source_origin=SourceOrigin.AUTO
            )

    def test_empty_reason_raises(self) -> None:
        with pytest.raises(ValueError, match="reason no puede estar vacío"):
            CameraDecision(
                target_cam=1, reason="", source_origin=SourceOrigin.MANUAL
            )

    def test_all_source_origins(self) -> None:
        for origin in SourceOrigin:
            decision = CameraDecision(
                target_cam=2, reason="test reason", source_origin=origin
            )
            assert decision.source_origin == origin

    def test_all_valid_cameras(self) -> None:
        for cam in range(1, 5):
            decision = CameraDecision(
                target_cam=cam, reason="reason", source_origin=SourceOrigin.AUTO
            )
            assert decision.target_cam == cam
