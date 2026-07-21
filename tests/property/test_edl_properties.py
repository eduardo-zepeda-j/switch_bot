"""Property-based tests para EDLDocument — Round-trip de serialización EDL.

**Validates: Requirements 15.1, 15.2, 15.3, 15.4, 13.4, 13.6**

Verifica las propiedades universales del formato EDL CMX 3600:
- Property 2: Round-trip de serialización — serializar → parsear → serializar produce output idéntico
- Cada línea serializada cumple formato CMX 3600 válido
- Parsing preserva todos los campos de evento (event_number, timecodes, colors, marker_types)
- Alineación de columnas preservada en todas las operaciones
- Property 6: Cada evento añadido via add_event() tiene tc_out = tc_in + 1 frame
- Property 6: Los eventos se numeran secuencialmente comenzando en 001
- Property 6: Los números de evento en la salida serializada tienen formato 3 dígitos zero-padded
"""

import re

from hypothesis import given, assume
from hypothesis.strategies import (
    booleans,
    composite,
    integers,
    lists,
    sampled_from,
    text,
)

from switch_bot.models.enums import EDLColor, MARKER_COLOR_MAP, MarkerType
from switch_bot.models.timecode import SMPTETimecode
from switch_bot.serializers.edl_serializer import EDLDocument, EDLEvent


# --- Strategies ---


@composite
def valid_smpte_timecode(draw, drop_frame: bool | None = None):
    """Genera un SMPTETimecode válido respetando reglas Drop Frame.

    Si drop_frame es None, genera aleatoriamente DF o NDF.
    """
    if drop_frame is None:
        df = draw(sampled_from([True, False]))
    else:
        df = drop_frame

    hours = draw(integers(min_value=0, max_value=23))
    minutes = draw(integers(min_value=0, max_value=59))
    seconds = draw(integers(min_value=0, max_value=59))
    frames = draw(integers(min_value=0, max_value=29))

    # En Drop Frame, frames 0 y 1 no existen en segundo 0 de minutos no múltiplo de 10
    if df and seconds == 0 and minutes % 10 != 0:
        assume(frames >= 2)

    return SMPTETimecode(
        hours=hours,
        minutes=minutes,
        seconds=seconds,
        frames=frames,
        drop_frame=df,
    )


@composite
def valid_edl_event(draw, event_number: int = 1):
    """Genera un EDLEvent válido con campos coherentes para round-trip.

    Todos los timecodes del documento deben usar el mismo modo (DF o NDF)
    para que el FCM sea consistente.
    """
    # Para simplificar round-trip, usamos Non-Drop Frame (FCM: NON-DROP FRAME)
    # ya que el documento tiene un solo FCM que aplica a todos los timecodes
    df = draw(sampled_from([True, False]))

    tc_in = draw(valid_smpte_timecode(drop_frame=df))
    duration = draw(integers(min_value=1, max_value=30))

    # Calcular tc_out como tc_in + duration frames
    tc_out = tc_in.advance_frames(duration)

    color = draw(sampled_from(list(EDLColor)))
    marker_type = draw(sampled_from(list(MarkerType)))

    return EDLEvent(
        event_number=event_number,
        reel="001",
        track="V",
        edit_type="C",
        tc_in=tc_in,
        tc_out=tc_out,
        rec_in=tc_in,
        rec_out=tc_out,
        color=color,
        marker_type=marker_type,
        duration=duration,
    )


@composite
def valid_edl_document(draw):
    """Genera un EDLDocument válido con título y eventos coherentes."""
    # Título seguro ASCII sin espacios iniciales/finales (el parser usa strip())
    title = draw(text(
        min_size=1,
        max_size=30,
        alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-",
    ))

    # Decidir si usar Drop Frame o Non-Drop Frame para todo el doc
    use_df = draw(sampled_from([True, False]))
    fcm = "DROP FRAME" if use_df else "NON-DROP FRAME"

    # Generar eventos con numeración secuencial y mismo modo DF
    num_events = draw(integers(min_value=0, max_value=10))
    events: list[EDLEvent] = []

    for i in range(num_events):
        tc_in = draw(valid_smpte_timecode(drop_frame=use_df))
        duration = draw(integers(min_value=1, max_value=30))
        tc_out = tc_in.advance_frames(duration)
        color = draw(sampled_from(list(EDLColor)))
        marker_type = draw(sampled_from(list(MarkerType)))

        event = EDLEvent(
            event_number=i + 1,
            reel="001",
            track="V",
            edit_type="C",
            tc_in=tc_in,
            tc_out=tc_out,
            rec_in=tc_in,
            rec_out=tc_out,
            color=color,
            marker_type=marker_type,
            duration=duration,
        )
        events.append(event)

    return EDLDocument(title=title, fcm=fcm, events=events)


@composite
def valid_event_params(draw):
    """Genera parámetros válidos para EDLDocument.add_event()."""
    tc_in = draw(valid_smpte_timecode())
    color = draw(sampled_from(list(EDLColor)))
    marker_type = draw(sampled_from(list(MarkerType)))
    return tc_in, color, marker_type


@composite
def valid_event_params_list(draw, min_size=1, max_size=10):
    """Genera una lista de parámetros válidos para múltiples add_event()."""
    params = draw(lists(valid_event_params(), min_size=min_size, max_size=max_size))
    return params


# --- Regex para validación CMX 3600 ---

# Línea principal de evento: NNN  001      V     C        HH:MM:SS:FF HH:MM:SS:FF ...
_CMX3600_EVENT_LINE = re.compile(
    r"^\d{3}\s+\S+\s+\S+\s+\S+\s+"
    r"\d{2}:\d{2}:\d{2}[;:]\d{2}\s+"
    r"\d{2}:\d{2}:\d{2}[;:]\d{2}\s+"
    r"\d{2}:\d{2}:\d{2}[;:]\d{2}\s+"
    r"\d{2}:\d{2}:\d{2}[;:]\d{2}\s*$"
)

# Línea de comentario:  |C:{color} |M:{tipo} |D:{duration}
_CMX3600_COMMENT_LINE = re.compile(
    r"^\s*\|C:\S+\s+\|M:\S+\s+\|D:\d+\s*$"
)


# --- Property Tests: Round-trip (Property 2) ---


@given(doc=valid_edl_document())
def test_edl_round_trip_serialize_parse_serialize(doc: EDLDocument):
    """Property 2: Round-trip de serialización EDL.

    Para todo documento EDL válido, serializar → parsear → serializar
    produce un resultado idéntico a la primera serialización.

    Esto verifica:
    - 15.1: Serialización a formato texto CMX 3600 válido
    - 15.2: Parsing reconstruye la lista de eventos con timecodes, colores y tipos
    - 15.3: Round-trip (parsear luego serializar = original)
    - 15.4: Preservación de alineación de columnas y formato SMPTE

    **Validates: Requirements 15.1, 15.2, 15.3, 15.4**
    """
    # Serializar
    serialized_1 = doc.serialize()

    # Parsear
    parsed = EDLDocument.parse(serialized_1)

    # Re-serializar
    serialized_2 = parsed.serialize()

    # Round-trip debe producir resultado idéntico
    assert serialized_1 == serialized_2, (
        f"Round-trip falló.\n"
        f"Original:\n{serialized_1}\n"
        f"Re-serializado:\n{serialized_2}"
    )


@given(doc=valid_edl_document())
def test_edl_serialize_produces_valid_cmx3600_lines(doc: EDLDocument):
    """Cada línea en el output serializado cumple formato CMX 3600 válido.

    Las líneas de contenido (no vacías, no cabecera) deben ser:
    - Líneas de evento: formato NNN  REEL TRACK EDIT TC TC TC TC
    - Líneas de comentario: |C:{color} |M:{tipo} |D:{duration}

    **Validates: Requirements 15.1, 15.4**
    """
    serialized = doc.serialize()
    lines = serialized.split("\n")

    for line in lines:
        # Saltar líneas vacías y cabecera
        if not line.strip():
            continue
        if line.startswith("TITLE:"):
            continue
        if line.startswith("FCM:"):
            continue

        # Debe ser línea de evento o de comentario
        is_event = _CMX3600_EVENT_LINE.match(line) is not None
        is_comment = _CMX3600_COMMENT_LINE.match(line) is not None

        assert is_event or is_comment, (
            f"Línea no cumple formato CMX 3600 válido: '{line}'"
        )


@given(doc=valid_edl_document())
def test_edl_parse_preserves_all_event_fields(doc: EDLDocument):
    """Parsing preserva todos los campos de evento: event_number, timecodes, colors, marker_types.

    **Validates: Requirements 15.2, 15.3**
    """
    serialized = doc.serialize()
    parsed = EDLDocument.parse(serialized)

    # Mismo número de eventos
    assert len(parsed.events) == len(doc.events), (
        f"Cantidad de eventos difiere: {len(doc.events)} vs {len(parsed.events)}"
    )

    for i, (orig, parsed_evt) in enumerate(zip(doc.events, parsed.events)):
        # Event number preservado
        assert parsed_evt.event_number == orig.event_number, (
            f"Evento {i}: event_number difiere {orig.event_number} vs {parsed_evt.event_number}"
        )

        # Timecodes preservados
        assert parsed_evt.tc_in == orig.tc_in, (
            f"Evento {i}: tc_in difiere {orig.tc_in} vs {parsed_evt.tc_in}"
        )
        assert parsed_evt.tc_out == orig.tc_out, (
            f"Evento {i}: tc_out difiere {orig.tc_out} vs {parsed_evt.tc_out}"
        )
        assert parsed_evt.rec_in == orig.rec_in, (
            f"Evento {i}: rec_in difiere {orig.rec_in} vs {parsed_evt.rec_in}"
        )
        assert parsed_evt.rec_out == orig.rec_out, (
            f"Evento {i}: rec_out difiere {orig.rec_out} vs {parsed_evt.rec_out}"
        )

        # Color preservado
        assert parsed_evt.color == orig.color, (
            f"Evento {i}: color difiere {orig.color} vs {parsed_evt.color}"
        )

        # Marker type preservado
        assert parsed_evt.marker_type == orig.marker_type, (
            f"Evento {i}: marker_type difiere {orig.marker_type} vs {parsed_evt.marker_type}"
        )

        # Duration preservada
        assert parsed_evt.duration == orig.duration, (
            f"Evento {i}: duration difiere {orig.duration} vs {parsed_evt.duration}"
        )


@given(doc=valid_edl_document())
def test_edl_column_alignment_preserved(doc: EDLDocument):
    """Alineación de columnas preservada en todas las operaciones de serialización.

    Verifica que la estructura de columnas es consistente entre
    serialización original y re-serialización tras parsing.

    **Validates: Requirements 15.4**
    """
    if not doc.events:
        return  # Sin eventos no hay alineación que verificar

    serialized = doc.serialize()
    lines = serialized.split("\n")

    # Extraer solo las líneas de evento (no vacías, no cabecera, no comentario)
    event_lines = [
        line for line in lines
        if line.strip()
        and not line.startswith("TITLE:")
        and not line.startswith("FCM:")
        and _CMX3600_EVENT_LINE.match(line)
    ]

    # Verificar que todas las líneas de evento tienen la misma longitud
    # (alineación de columnas consistente cuando reel/track/edit son iguales)
    if event_lines:
        # Todas las líneas de evento deben tener estructura de columnas consistente
        # El separador antes del primer timecode debe estar en la misma posición
        tc_positions = []
        for line in event_lines:
            # Encontrar la posición del primer timecode (HH:MM:SS:FF o HH:MM:SS;FF)
            tc_match = re.search(r"\d{2}:\d{2}:\d{2}[;:]\d{2}", line)
            if tc_match:
                tc_positions.append(tc_match.start())

        # Todas las posiciones del primer TC deben ser iguales
        if tc_positions:
            assert all(pos == tc_positions[0] for pos in tc_positions), (
                f"Alineación de columnas inconsistente. "
                f"Posiciones del primer TC: {tc_positions}"
            )

    # Verificar round-trip preserva la alineación
    parsed = EDLDocument.parse(serialized)
    re_serialized = parsed.serialize()

    # Las líneas de evento deben mantener misma alineación
    re_event_lines = [
        line for line in re_serialized.split("\n")
        if line.strip()
        and not line.startswith("TITLE:")
        and not line.startswith("FCM:")
        and _CMX3600_EVENT_LINE.match(line)
    ]

    assert event_lines == re_event_lines, (
        "Alineación de columnas no preservada tras round-trip.\n"
        f"Original: {event_lines}\n"
        f"Re-serializado: {re_event_lines}"
    )


# --- Property Tests: Eventos de 1 frame con numeración secuencial (Property 6) ---


@given(event_params=valid_event_params_list(min_size=1, max_size=20))
def test_every_event_has_tc_out_equals_tc_in_plus_one_frame(event_params):
    """Property 6: Cada evento añadido via add_event() tiene tc_out = tc_in + 1 frame.

    Para todo evento creado por add_event(), tc_out debe ser exactamente
    tc_in avanzado 1 frame, garantizando que cada evento es un evento de 1 frame.

    **Validates: Requirements 13.4, 13.6**
    """
    doc = EDLDocument(title="Test")

    for tc_in, color, marker_type in event_params:
        event = doc.add_event(tc_in=tc_in, color=color, marker_type=marker_type)

        expected_tc_out = tc_in.advance_frames(1)
        assert event.tc_out == expected_tc_out, (
            f"tc_out debería ser tc_in + 1 frame.\n"
            f"tc_in: {tc_in.to_string()}\n"
            f"tc_out esperado: {expected_tc_out.to_string()}\n"
            f"tc_out obtenido: {event.tc_out.to_string()}"
        )


@given(event_params=valid_event_params_list(min_size=1, max_size=20))
def test_events_numbered_sequentially_starting_at_001(event_params):
    """Property 6: Los eventos se numeran secuencialmente comenzando en 001.

    Para toda lista de eventos añadidos a un EDLDocument, el event_number
    del evento en posición i debe ser i + 1 (comenzando en 1).

    **Validates: Requirements 13.4, 13.6**
    """
    doc = EDLDocument(title="Test")

    for i, (tc_in, color, marker_type) in enumerate(event_params):
        event = doc.add_event(tc_in=tc_in, color=color, marker_type=marker_type)
        expected_number = i + 1

        assert event.event_number == expected_number, (
            f"Evento en posición {i} debería tener event_number={expected_number}, "
            f"pero tiene event_number={event.event_number}"
        )

    # Verificar también la lista completa
    for i, event in enumerate(doc.events):
        assert event.event_number == i + 1, (
            f"Después de agregar todos los eventos, evento[{i}] tiene "
            f"event_number={event.event_number}, esperado={i + 1}"
        )


@given(event_params=valid_event_params_list(min_size=1, max_size=15))
def test_event_numbers_in_serialized_output_are_zero_padded_3_digits(event_params):
    """Property 6: Los números de evento en la salida serializada tienen formato 3 dígitos.

    En el texto serializado CMX 3600, cada número de evento debe aparecer
    con formato de 3 dígitos con ceros a la izquierda (001, 002, ..., 999).

    **Validates: Requirements 13.4, 13.6**
    """
    doc = EDLDocument(title="Test")

    for tc_in, color, marker_type in event_params:
        doc.add_event(tc_in=tc_in, color=color, marker_type=marker_type)

    serialized = doc.serialize()
    lines = serialized.split("\n")

    # Filtrar líneas de eventos (comienzan con 3 dígitos seguidos de espacio)
    event_line_index = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("TITLE:") or stripped.startswith("FCM:"):
            continue
        if stripped.startswith("|C:"):
            continue

        # Las líneas de evento comienzan con NNN (3 dígitos)
        if len(stripped) >= 3 and stripped[:3].isdigit():
            event_line_index += 1
            event_num_str = stripped[:3]

            # Verificar formato 3 dígitos zero-padded
            assert len(event_num_str) == 3, (
                f"Número de evento debería ser 3 dígitos: '{event_num_str}'"
            )
            assert event_num_str == f"{event_line_index:03d}", (
                f"Evento {event_line_index} debería aparecer como "
                f"'{event_line_index:03d}' pero apareció como '{event_num_str}'"
            )

    # Verificar que encontramos todos los eventos esperados
    assert event_line_index == len(event_params), (
        f"Se esperaban {len(event_params)} líneas de evento en la salida serializada, "
        f"pero se encontraron {event_line_index}"
    )


# --- Property Tests: Mapeo MarkerType → EDLColor (Property 5) ---

# Mapeo esperado según la especificación
_EXPECTED_RED = {
    MarkerType.MANUAL_NOTE,
    MarkerType.TOS,
    MarkerType.ERROR_DICCION,
    MarkerType.CONFUSION,
    MarkerType.REPETICION,
    MarkerType.PANIC,
}
_EXPECTED_GREEN = {MarkerType.SCRIPT_MATCH, MarkerType.IMAGEN}
_EXPECTED_MAGENTA = {MarkerType.AI_PROMPT}
_EXPECTED_CYAN = {MarkerType.ENTRADA}
_EXPECTED_YELLOW = {MarkerType.SALIDA}


class TestMarkerColorMapping:
    """Property 5: MARKER_COLOR_MAP asigna el color correcto a cada tipo de marcador.

    **Validates: Requirements 6.3, 6.4, 6.5, 7.1, 7.2, 7.3, 7.4, 13.3**
    """

    @given(marker_type=sampled_from(list(MARKER_COLOR_MAP.keys())))
    def test_marker_color_map_assigns_correct_color(self, marker_type: MarkerType) -> None:
        """Para cada MarkerType en MARKER_COLOR_MAP, el color asignado coincide con la spec.

        **Validates: Requirements 6.3, 6.4, 7.1, 7.2, 7.3, 7.4, 13.3**
        """
        color = MARKER_COLOR_MAP[marker_type]

        if marker_type in _EXPECTED_RED:
            assert color == EDLColor.Red, (
                f"{marker_type.value} debería ser Red, pero es {color.value}"
            )
        elif marker_type in _EXPECTED_GREEN:
            assert color == EDLColor.Green, (
                f"{marker_type.value} debería ser Green, pero es {color.value}"
            )
        elif marker_type in _EXPECTED_MAGENTA:
            assert color == EDLColor.Magenta, (
                f"{marker_type.value} debería ser Magenta, pero es {color.value}"
            )
        elif marker_type in _EXPECTED_CYAN:
            assert color == EDLColor.Cyan, (
                f"{marker_type.value} debería ser Cyan, pero es {color.value}"
            )
        elif marker_type in _EXPECTED_YELLOW:
            assert color == EDLColor.Yellow, (
                f"{marker_type.value} debería ser Yellow, pero es {color.value}"
            )
        else:
            raise AssertionError(
                f"MarkerType {marker_type.value} tiene mapeo a {color.value} "
                f"pero no está en ningún grupo esperado de la spec"
            )

    @given(marker_type=sampled_from(list(MARKER_COLOR_MAP.keys())))
    def test_serialized_edl_contains_correct_color(self, marker_type: MarkerType) -> None:
        """Al serializar con add_event(), el comentario EDL contiene el color correcto.

        **Validates: Requirements 6.5, 13.3**
        """
        color = MARKER_COLOR_MAP[marker_type]
        tc_in = SMPTETimecode(0, 1, 0, 0, False)

        doc = EDLDocument(title="test")
        event = doc.add_event(tc_in=tc_in, color=color, marker_type=marker_type)

        serialized = event.to_cmx3600()

        # La línea de comentario debe contener |C:{color.value}
        assert f"|C:{color.value}" in serialized, (
            f"Serialización no contiene |C:{color.value} para {marker_type.value}.\n"
            f"Output: {serialized}"
        )
        # También debe contener |M:{marker_type.value}
        assert f"|M:{marker_type.value}" in serialized, (
            f"Serialización no contiene |M:{marker_type.value}.\n"
            f"Output: {serialized}"
        )

    @given(marker_type=sampled_from(list(MARKER_COLOR_MAP.keys())))
    def test_all_mapped_markers_produce_valid_edl_round_trip(self, marker_type: MarkerType) -> None:
        """Todos los MarkerType con mapeo producen eventos EDL válidos con round-trip correcto.

        **Validates: Requirements 6.3, 6.4, 6.5, 7.1, 7.2, 7.3, 7.4, 13.3**
        """
        color = MARKER_COLOR_MAP[marker_type]
        tc_in = SMPTETimecode(1, 30, 45, 10, False)

        doc = EDLDocument(title="property_test")
        event = doc.add_event(tc_in=tc_in, color=color, marker_type=marker_type)

        serialized = event.to_cmx3600()

        # El evento debe tener exactamente 2 líneas
        lines = serialized.split("\n")
        assert len(lines) == 2, (
            f"Evento EDL debe tener 2 líneas, tiene {len(lines)}"
        )

        # Formato de línea 2: |C:{color} |M:{type} |D:{duration}
        comment_line = lines[1].strip()
        assert comment_line.startswith("|C:"), (
            f"Línea de comentario debe iniciar con |C:, pero es: '{comment_line}'"
        )
        assert "|D:1" in comment_line, (
            f"Duración debe ser 1, output: '{comment_line}'"
        )

        # Round-trip a nivel de evento individual: parsear debe recuperar color y marker_type
        parsed_event = EDLEvent.from_cmx3600(lines[0], lines[1])
        assert parsed_event.color == color, (
            f"Round-trip: color esperado {color.value}, obtenido {parsed_event.color.value}"
        )
        assert parsed_event.marker_type == marker_type, (
            f"Round-trip: marker_type esperado {marker_type.value}, "
            f"obtenido {parsed_event.marker_type.value}"
        )
