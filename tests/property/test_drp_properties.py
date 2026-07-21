"""Property-based tests para DRPDocument — Round-trip de serialización DRP.

**Validates: Requirements 14.1, 14.2, 14.3, 14.4**

Verifica las propiedades universales del formato DRP:
- Property 1: Round-trip de serialización — parsear y serializar produce output equivalente
- Preservación de timecodes en orden y precisión
- Formato JSON Lines válido
"""

import json

from hypothesis import given, assume
from hypothesis.strategies import (
    composite,
    integers,
    text,
    lists,
    floats,
    booleans,
    sampled_from,
    fixed_dictionaries,
    just,
    one_of,
)

from switch_bot.serializers.drp_serializer import (
    DRPDocument,
    DRPProjectConfig,
    DRPSwitchEvent,
)


# --- Strategies ---


@composite
def valid_drp_timecode(draw):
    """Genera timecodes SMPTE Drop Frame válidos (formato HH:MM:SS;FF)."""
    hours = draw(integers(min_value=0, max_value=23))
    minutes = draw(integers(min_value=0, max_value=59))
    seconds = draw(integers(min_value=0, max_value=59))
    frames = draw(integers(min_value=0, max_value=29))

    # En Drop Frame, frames 0 y 1 no existen en segundo 0 de minutos no múltiplo de 10
    if seconds == 0 and minutes % 10 != 0:
        assume(frames >= 2)

    return f"{hours:02d}:{minutes:02d}:{seconds:02d};{frames:02d}"


@composite
def valid_source_data(draw):
    """Genera un diccionario de fuente DRP válido."""
    source_type = draw(sampled_from(["Video", "Color", "ColorBars", "Still"]))
    index = draw(integers(min_value=0, max_value=9))
    # Usar solo ASCII seguro para evitar problemas de serialización JSON
    name = draw(text(
        min_size=1,
        max_size=20,
        alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _-",
    ))

    data: dict = {
        "name": name,
        "type": source_type,
        "_index_": index,
    }

    # Agregar campos opcionales según tipo
    if source_type == "Color":
        data["color"] = {
            "h": draw(floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)),
            "s": draw(floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)),
            "l": draw(floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)),
        }
    elif source_type == "Video":
        data["volume"] = "ISO RECORD"
        data["projectPath"] = draw(text(
            min_size=1,
            max_size=30,
            alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _-",
        ))
        data["file"] = draw(text(
            min_size=1,
            max_size=40,
            alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _-./",
        ))
        data["startTimecode"] = draw(valid_drp_timecode())

    return data


@composite
def valid_mix_effect_block_data(draw):
    """Genera un diccionario de mix effect block DRP válido."""
    source = draw(integers(min_value=0, max_value=9))
    index = draw(integers(min_value=0, max_value=3))
    on_air = draw(booleans())

    data: dict = {
        "onAir": on_air,
        "source": source,
        "_index_": index,
    }

    return data


@composite
def valid_downstream_key_data(draw):
    """Genera un diccionario de downstream key DRP válido."""
    return {
        "onAir": draw(booleans()),
        "isTied": draw(booleans()),
        "fillSource": draw(integers(min_value=0, max_value=9)),
        "keySource": draw(integers(min_value=0, max_value=9)),
        "faderState": draw(sampled_from(["Idle", "Running"])),
        "_index_": draw(integers(min_value=0, max_value=3)),
    }


@composite
def valid_project_config_data(draw):
    """Genera un diccionario de configuración de proyecto DRP válido."""
    master_tc = draw(valid_drp_timecode())
    video_mode = draw(sampled_from(["1080p29.97", "1080p30", "1080p60", "720p29.97"]))
    sources = draw(lists(valid_source_data(), min_size=1, max_size=5))
    mix_effect_blocks = draw(lists(valid_mix_effect_block_data(), min_size=1, max_size=2))
    downstream_keys = draw(lists(valid_downstream_key_data(), min_size=0, max_size=2))
    # Simple hex recording ID
    recording_id = draw(text(
        min_size=8,
        max_size=8,
        alphabet="0123456789abcdef",
    ))

    return {
        "version": 1,
        "masterTimecode": master_tc,
        "videoMode": video_mode,
        "sources": sources,
        "mixEffectBlocks": mix_effect_blocks,
        "downstreamKeys": downstream_keys,
        "recordingId": recording_id,
    }


@composite
def valid_switch_event_data(draw):
    """Genera un diccionario de evento de conmutación DRP válido."""
    tc = draw(valid_drp_timecode())
    source = draw(integers(min_value=0, max_value=9))
    me_index = draw(integers(min_value=0, max_value=3))

    return {
        "masterTimecode": tc,
        "mixEffectBlocks": [{"source": source, "_index_": me_index}],
    }


@composite
def valid_drp_document(draw):
    """Genera un DRPDocument válido con configuración y eventos."""
    config_data = draw(valid_project_config_data())
    events_data = draw(lists(valid_switch_event_data(), min_size=0, max_size=10))

    config = DRPProjectConfig(data=config_data)
    events = [DRPSwitchEvent(data=e) for e in events_data]

    return DRPDocument(config=config, events=events)


# --- Property Tests ---


@given(doc=valid_drp_document())
def test_drp_round_trip_serialize_parse_serialize(doc: DRPDocument):
    """Property 1: Round-trip de serialización DRP.

    Para todo documento DRP válido, serializar → parsear → serializar
    produce un resultado idéntico a la primera serialización.

    Esto verifica:
    - 14.1: Serialización a JSON Lines válido
    - 14.2: Parsing reconstruye configuración y eventos
    - 14.3: Round-trip produce archivo equivalente al original
    - 14.4: Preservación de timecodes en lectura/escritura

    **Validates: Requirements 14.1, 14.2, 14.3, 14.4**
    """
    # Serializar
    serialized_1 = doc.serialize()

    # Parsear
    parsed = DRPDocument.parse(serialized_1)

    # Re-serializar
    serialized_2 = parsed.serialize()

    # Round-trip debe producir resultado idéntico
    assert serialized_1 == serialized_2, (
        f"Round-trip falló.\nOriginal:\n{serialized_1}\nRe-serializado:\n{serialized_2}"
    )


@given(doc=valid_drp_document())
def test_drp_parse_preserves_config_fields(doc: DRPDocument):
    """Parsear un DRP preserva todos los campos de configuración.

    **Validates: Requirements 14.2, 14.3**
    """
    serialized = doc.serialize()
    parsed = DRPDocument.parse(serialized)

    # Los datos de configuración deben ser idénticos
    assert parsed.config.data == doc.config.data, (
        f"Config data difiere.\nOriginal: {doc.config.data}\nParseado: {parsed.config.data}"
    )


@given(doc=valid_drp_document())
def test_drp_parse_preserves_event_count_and_order(doc: DRPDocument):
    """Parsear un DRP preserva la cantidad y orden de eventos.

    **Validates: Requirements 14.2, 14.4**
    """
    serialized = doc.serialize()
    parsed = DRPDocument.parse(serialized)

    # Mismo número de eventos
    assert len(parsed.events) == len(doc.events), (
        f"Cantidad de eventos difiere: {len(doc.events)} vs {len(parsed.events)}"
    )

    # Orden y contenido preservados
    for i, (orig, parsed_evt) in enumerate(zip(doc.events, parsed.events)):
        assert orig.data == parsed_evt.data, (
            f"Evento {i} difiere.\nOriginal: {orig.data}\nParseado: {parsed_evt.data}"
        )


@given(doc=valid_drp_document())
def test_drp_serialize_produces_valid_json_lines(doc: DRPDocument):
    """Serializar produce formato JSON Lines válido (cada línea es JSON parseable).

    **Validates: Requirements 14.1**
    """
    serialized = doc.serialize()
    lines = [line for line in serialized.split("\n") if line.strip()]

    # Debe haber al menos 1 línea (config)
    assert len(lines) >= 1, "El DRP serializado debe tener al menos la línea de config"

    # Cada línea debe ser JSON válido
    for i, line in enumerate(lines):
        try:
            json.loads(line)
        except json.JSONDecodeError as e:
            raise AssertionError(
                f"Línea {i} no es JSON válido: {line!r}\nError: {e}"
            )


@given(doc=valid_drp_document())
def test_drp_timecodes_preserved_exactly(doc: DRPDocument):
    """Los timecodes se preservan con precisión exacta en round-trip.

    **Validates: Requirements 14.4**
    """
    serialized = doc.serialize()
    parsed = DRPDocument.parse(serialized)

    # Timecode master del config
    assert parsed.config.master_timecode == doc.config.master_timecode, (
        f"masterTimecode difiere: {doc.config.master_timecode} vs {parsed.config.master_timecode}"
    )

    # Timecodes de eventos
    for i, (orig, parsed_evt) in enumerate(zip(doc.events, parsed.events)):
        assert orig.master_timecode == parsed_evt.master_timecode, (
            f"Evento {i} masterTimecode difiere: "
            f"{orig.master_timecode} vs {parsed_evt.master_timecode}"
        )
