"""Tests unitarios para EnrichedPayload."""

import pytest

from switch_bot.models.enums import EDLColor, MarkerType, SourceOrigin
from switch_bot.models.payload import EnrichedPayload
from switch_bot.models.timecode import SMPTETimecode


@pytest.fixture
def sample_tc() -> SMPTETimecode:
    """Timecode de ejemplo para tests."""
    return SMPTETimecode(hours=1, minutes=0, seconds=30, frames=15, drop_frame=False)


@pytest.fixture
def valid_payload(sample_tc: SMPTETimecode) -> EnrichedPayload:
    """Payload válido de ejemplo."""
    return EnrichedPayload(
        personaje="Carlos",
        target_cam=2,
        marker_type=MarkerType.SCRIPT_MATCH,
        note="Entrada de Carlos por puerta izquierda",
        tc_in=sample_tc,
        source_origin=SourceOrigin.AUTO,
        color=EDLColor.Green,
    )


class TestEnrichedPayloadCreation:
    """Tests de creación válida de EnrichedPayload."""

    def test_create_valid_payload(self, valid_payload: EnrichedPayload) -> None:
        assert valid_payload.personaje == "Carlos"
        assert valid_payload.target_cam == 2
        assert valid_payload.marker_type == MarkerType.SCRIPT_MATCH
        assert valid_payload.note == "Entrada de Carlos por puerta izquierda"
        assert valid_payload.tc_in.hours == 1
        assert valid_payload.source_origin == SourceOrigin.AUTO
        assert valid_payload.color == EDLColor.Green

    def test_payload_is_frozen(self, valid_payload: EnrichedPayload) -> None:
        with pytest.raises(AttributeError):
            valid_payload.personaje = "Otro"  # type: ignore[misc]

    def test_all_camera_indices(self, sample_tc: SMPTETimecode) -> None:
        for cam in range(1, 5):
            payload = EnrichedPayload(
                personaje="Ana",
                target_cam=cam,
                marker_type=MarkerType.ENTRADA,
                note="test",
                tc_in=sample_tc,
                source_origin=SourceOrigin.MANUAL,
                color=EDLColor.Cyan,
            )
            assert payload.target_cam == cam

    def test_all_source_origins(self, sample_tc: SMPTETimecode) -> None:
        for origin in SourceOrigin:
            payload = EnrichedPayload(
                personaje="Test",
                target_cam=1,
                marker_type=MarkerType.MANUAL_NOTE,
                note="nota",
                tc_in=sample_tc,
                source_origin=origin,
                color=EDLColor.Red,
            )
            assert payload.source_origin == origin

    def test_empty_note_is_allowed(self, sample_tc: SMPTETimecode) -> None:
        payload = EnrichedPayload(
            personaje="María",
            target_cam=3,
            marker_type=MarkerType.AI_PROMPT,
            note="",
            tc_in=sample_tc,
            source_origin=SourceOrigin.AI,
            color=EDLColor.Magenta,
        )
        assert payload.note == ""


class TestEnrichedPayloadValidation:
    """Tests de validación de campos de EnrichedPayload."""

    def test_empty_personaje_raises(self, sample_tc: SMPTETimecode) -> None:
        with pytest.raises(ValueError, match="personaje no puede estar vacío"):
            EnrichedPayload(
                personaje="",
                target_cam=1,
                marker_type=MarkerType.ENTRADA,
                note="test",
                tc_in=sample_tc,
                source_origin=SourceOrigin.AUTO,
                color=EDLColor.Cyan,
            )

    def test_target_cam_below_range(self, sample_tc: SMPTETimecode) -> None:
        with pytest.raises(ValueError, match="target_cam debe estar entre 1 y 4"):
            EnrichedPayload(
                personaje="Test",
                target_cam=0,
                marker_type=MarkerType.ENTRADA,
                note="test",
                tc_in=sample_tc,
                source_origin=SourceOrigin.AUTO,
                color=EDLColor.Cyan,
            )

    def test_target_cam_above_range(self, sample_tc: SMPTETimecode) -> None:
        with pytest.raises(ValueError, match="target_cam debe estar entre 1 y 4"):
            EnrichedPayload(
                personaje="Test",
                target_cam=5,
                marker_type=MarkerType.ENTRADA,
                note="test",
                tc_in=sample_tc,
                source_origin=SourceOrigin.AUTO,
                color=EDLColor.Cyan,
            )

    def test_equality(self, sample_tc: SMPTETimecode) -> None:
        p1 = EnrichedPayload(
            personaje="A",
            target_cam=1,
            marker_type=MarkerType.ENTRADA,
            note="x",
            tc_in=sample_tc,
            source_origin=SourceOrigin.AUTO,
            color=EDLColor.Cyan,
        )
        p2 = EnrichedPayload(
            personaje="A",
            target_cam=1,
            marker_type=MarkerType.ENTRADA,
            note="x",
            tc_in=sample_tc,
            source_origin=SourceOrigin.AUTO,
            color=EDLColor.Cyan,
        )
        assert p1 == p2
