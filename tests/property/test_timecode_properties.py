"""Property-based tests para SMPTETimecode.

**Validates: Requirements 12.5, 18.3**

Verifica las propiedades universales del timecode SMPTE:
- Property 7: Separador Drop Frame (;) vs Non-Drop Frame (:)
- Round-trip: from_string(tc.to_string()) == tc
- advance_frames(0) es identidad
- advance_frames(n) seguido de advance_frames(-n) retorna al original
"""

from hypothesis import given, settings, assume
from hypothesis.strategies import booleans, composite, integers

from switch_bot.models.timecode import SMPTETimecode


# --- Strategies ---


@composite
def valid_smpte_timecode(draw):
    """Genera instancias válidas de SMPTETimecode respetando reglas Drop Frame."""
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


# --- Property Tests ---


@given(tc=valid_smpte_timecode())
def test_drop_frame_uses_semicolon_separator(tc: SMPTETimecode):
    """Property 7: Si drop_frame=True usa ';', si drop_frame=False usa ':'.

    **Validates: Requirements 12.5, 18.3**
    """
    result = tc.to_string()
    # El separador entre SS y FF (posición 8) indica drop frame
    frame_separator = result[8]

    if tc.drop_frame:
        assert frame_separator == ";", (
            f"Drop Frame timecode debería usar ';' pero usó '{frame_separator}': {result}"
        )
    else:
        assert frame_separator == ":", (
            f"Non-Drop Frame timecode debería usar ':' pero usó '{frame_separator}': {result}"
        )


@given(tc=valid_smpte_timecode())
def test_round_trip_string_conversion(tc: SMPTETimecode):
    """Round-trip: from_string(tc.to_string()) == tc para todo timecode válido.

    **Validates: Requirements 12.5, 18.3**
    """
    serialized = tc.to_string()
    reconstructed = SMPTETimecode.from_string(serialized)
    assert reconstructed == tc, (
        f"Round-trip falló: original={tc}, serialized='{serialized}', reconstructed={reconstructed}"
    )


@given(tc=valid_smpte_timecode())
def test_advance_frames_zero_is_identity(tc: SMPTETimecode):
    """advance_frames(0) retorna el mismo timecode.

    **Validates: Requirements 12.5, 18.3**
    """
    result = tc.advance_frames(0)
    assert result == tc, (
        f"advance_frames(0) debería ser identidad: original={tc}, result={result}"
    )


@given(tc=valid_smpte_timecode(), n=integers(min_value=1, max_value=1000))
def test_advance_frames_roundtrip(tc: SMPTETimecode, n: int):
    """advance_frames(n) seguido de advance_frames(-n) retorna al original.

    **Validates: Requirements 12.5, 18.3**
    """
    advanced = tc.advance_frames(n)
    back = advanced.advance_frames(-n)
    assert back == tc, (
        f"advance_frames round-trip falló: original={tc}, n={n}, "
        f"advanced={advanced}, back={back}"
    )
