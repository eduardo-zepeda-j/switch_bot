"""Property-based tests para EnrichedPayload.

**Validates: Requirements 16.1**

Verifica las propiedades universales del Payload Enriquecido:
- Property 10: Todos los campos requeridos están presentes y no son nulos
- target_cam siempre entre 1 y 4
- marker_type siempre es miembro válido de MarkerType
- source_origin siempre es miembro válido de SourceOrigin
- color siempre es miembro válido de EDLColor
- personaje siempre es string no vacío
- EnrichedPayload es inmutable (frozen dataclass)
"""

import pytest
from hypothesis import given, assume
from hypothesis.strategies import composite, integers, sampled_from, text

from switch_bot.models.enums import EDLColor, MarkerType, SourceOrigin
from switch_bot.models.payload import EnrichedPayload
from switch_bot.models.timecode import SMPTETimecode


# --- Strategies ---


@composite
def valid_smpte_timecode(draw):
    """Genera instancias válidas de SMPTETimecode respetando reglas Drop Frame."""
    from hypothesis.strategies import booleans

    drop_frame = draw(booleans())
    hours = draw(integers(min_value=0, max_value=23))
    minutes = draw(integers(min_value=0, max_value=59))
    seconds = draw(integers(min_value=0, max_value=59))
    frames = draw(integers(min_value=0, max_value=29))

    # En Drop Frame, frames 0 y 1 no existen en segundo 0 de minutos no múltiplo de 10
    if drop_frame and seconds == 0 and minutes % 10 != 0:
        assume(frames >= 2)

    return SMPTETimecode(
        hours=hours,
        minutes=minutes,
        seconds=seconds,
        frames=frames,
        drop_frame=drop_frame,
    )


@composite
def valid_enriched_payload(draw):
    """Genera instancias válidas de EnrichedPayload con campos correctos."""
    personaje = draw(text(min_size=1, max_size=50, alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ áéíóúñÁÉÍÓÚÑ"))
    target_cam = draw(integers(min_value=1, max_value=4))
    marker_type = draw(sampled_from(list(MarkerType)))
    note = draw(text(min_size=0, max_size=200))
    tc_in = draw(valid_smpte_timecode())
    source_origin = draw(sampled_from(list(SourceOrigin)))
    color = draw(sampled_from(list(EDLColor)))

    return EnrichedPayload(
        personaje=personaje,
        target_cam=target_cam,
        marker_type=marker_type,
        note=note,
        tc_in=tc_in,
        source_origin=source_origin,
        color=color,
    )


# --- Property Tests ---


@given(payload=valid_enriched_payload())
def test_enriched_payload_all_required_fields_present(payload: EnrichedPayload):
    """Property 10: Todos los campos requeridos están presentes y no son nulos.

    **Validates: Requirements 16.1**
    """
    assert payload.personaje is not None
    assert payload.target_cam is not None
    assert payload.marker_type is not None
    assert payload.note is not None
    assert payload.tc_in is not None
    assert payload.source_origin is not None
    assert payload.color is not None


@given(payload=valid_enriched_payload())
def test_enriched_payload_target_cam_in_range(payload: EnrichedPayload):
    """target_cam siempre está entre 1 y 4 para todo payload válido.

    **Validates: Requirements 16.1**
    """
    assert 1 <= payload.target_cam <= 4, (
        f"target_cam debe estar entre 1 y 4, recibido: {payload.target_cam}"
    )


@given(payload=valid_enriched_payload())
def test_enriched_payload_marker_type_is_valid(payload: EnrichedPayload):
    """marker_type siempre es un miembro válido de MarkerType.

    **Validates: Requirements 16.1**
    """
    assert isinstance(payload.marker_type, MarkerType), (
        f"marker_type debe ser MarkerType, recibido: {type(payload.marker_type)}"
    )
    assert payload.marker_type in MarkerType


@given(payload=valid_enriched_payload())
def test_enriched_payload_source_origin_is_valid(payload: EnrichedPayload):
    """source_origin siempre es un miembro válido de SourceOrigin.

    **Validates: Requirements 16.1**
    """
    assert isinstance(payload.source_origin, SourceOrigin), (
        f"source_origin debe ser SourceOrigin, recibido: {type(payload.source_origin)}"
    )
    assert payload.source_origin in SourceOrigin


@given(payload=valid_enriched_payload())
def test_enriched_payload_color_is_valid(payload: EnrichedPayload):
    """color siempre es un miembro válido de EDLColor.

    **Validates: Requirements 16.1**
    """
    assert isinstance(payload.color, EDLColor), (
        f"color debe ser EDLColor, recibido: {type(payload.color)}"
    )
    assert payload.color in EDLColor


@given(payload=valid_enriched_payload())
def test_enriched_payload_personaje_non_empty(payload: EnrichedPayload):
    """personaje siempre es un string no vacío.

    **Validates: Requirements 16.1**
    """
    assert isinstance(payload.personaje, str), (
        f"personaje debe ser str, recibido: {type(payload.personaje)}"
    )
    assert len(payload.personaje) > 0, "personaje no puede estar vacío"


@given(payload=valid_enriched_payload())
def test_enriched_payload_is_immutable(payload: EnrichedPayload):
    """EnrichedPayload es inmutable (frozen dataclass).

    **Validates: Requirements 16.1**
    """
    with pytest.raises(AttributeError):
        payload.personaje = "otro_personaje"  # type: ignore[misc]

    with pytest.raises(AttributeError):
        payload.target_cam = 2  # type: ignore[misc]

    with pytest.raises(AttributeError):
        payload.marker_type = MarkerType.MANUAL_NOTE  # type: ignore[misc]
