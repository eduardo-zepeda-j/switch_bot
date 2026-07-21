"""Tests unitarios para el serializador EDL CMX 3600.

Valida serialización, parsing, round-trip y auto-numeración.
"""

import pytest

from switch_bot.models.enums import EDLColor, MarkerType
from switch_bot.models.timecode import SMPTETimecode
from switch_bot.serializers.edl_serializer import EDLDocument, EDLEvent


class TestEDLEventToCmx3600:
    """Tests para EDLEvent.to_cmx3600()."""

    def test_basic_event_format(self):
        """Formato de evento básico con alineación correcta de columnas."""
        tc_in = SMPTETimecode(10, 42, 4, 3, False)
        tc_out = SMPTETimecode(10, 42, 4, 4, False)
        event = EDLEvent(
            event_number=1,
            tc_in=tc_in,
            tc_out=tc_out,
            rec_in=tc_in,
            rec_out=tc_out,
            color=EDLColor.Cyan,
            marker_type=MarkerType.ENTRADA,
        )
        result = event.to_cmx3600()
        lines = result.split("\n")
        assert lines[0] == "001  001      V     C        10:42:04:03 10:42:04:04 10:42:04:03 10:42:04:04"
        assert lines[1] == " |C:ResolveColorCyan |M:ENTRADA |D:1"

    def test_three_digit_event_number(self):
        """Números de evento con formato 3 dígitos (013)."""
        tc_in = SMPTETimecode(11, 5, 48, 10, False)
        tc_out = SMPTETimecode(11, 5, 48, 11, False)
        event = EDLEvent(
            event_number=13,
            tc_in=tc_in,
            tc_out=tc_out,
            rec_in=tc_in,
            rec_out=tc_out,
            color=EDLColor.Green,
            marker_type=MarkerType.IMAGEN,
        )
        result = event.to_cmx3600()
        assert result.startswith("013  001")

    def test_different_colors_and_markers(self):
        """Cada combinación de color y marcador se serializa correctamente."""
        tc_in = SMPTETimecode(0, 0, 0, 0, False)
        tc_out = SMPTETimecode(0, 0, 0, 1, False)

        test_cases = [
            (EDLColor.Red, MarkerType.MANUAL_NOTE, "ResolveColorRed", "MANUAL_NOTE"),
            (EDLColor.Green, MarkerType.SCRIPT_MATCH, "ResolveColorGreen", "SCRIPT_MATCH"),
            (EDLColor.Magenta, MarkerType.AI_PROMPT, "ResolveColorMagenta", "AI_PROMPT"),
            (EDLColor.Yellow, MarkerType.SALIDA, "ResolveColorYellow", "SALIDA"),
        ]

        for color, mtype, expected_color, expected_mtype in test_cases:
            event = EDLEvent(
                event_number=1,
                tc_in=tc_in,
                tc_out=tc_out,
                rec_in=tc_in,
                rec_out=tc_out,
                color=color,
                marker_type=mtype,
            )
            result = event.to_cmx3600()
            line2 = result.split("\n")[1]
            assert f"|C:{expected_color}" in line2
            assert f"|M:{expected_mtype}" in line2

    def test_drop_frame_timecodes(self):
        """Timecodes Drop Frame usan separador `;`."""
        tc_in = SMPTETimecode(10, 42, 4, 3, True)
        tc_out = SMPTETimecode(10, 42, 4, 4, True)
        event = EDLEvent(
            event_number=1,
            tc_in=tc_in,
            tc_out=tc_out,
            rec_in=tc_in,
            rec_out=tc_out,
            color=EDLColor.Cyan,
            marker_type=MarkerType.ENTRADA,
        )
        result = event.to_cmx3600()
        assert "10:42:04;03" in result
        assert "10:42:04;04" in result


class TestEDLEventFromCmx3600:
    """Tests para EDLEvent.from_cmx3600()."""

    def test_parse_basic_event(self):
        """Parsea un evento básico CMX 3600 correctamente."""
        line1 = "001  001      V     C        10:42:04:03 10:42:04:04 10:42:04:03 10:42:04:04"
        line2 = " |C:ResolveColorCyan |M:ENTRADA |D:1"

        event = EDLEvent.from_cmx3600(line1, line2)

        assert event.event_number == 1
        assert event.reel == "001"
        assert event.track == "V"
        assert event.edit_type == "C"
        assert event.tc_in.to_string() == "10:42:04:03"
        assert event.tc_out.to_string() == "10:42:04:04"
        assert event.color == EDLColor.Cyan
        assert event.marker_type == MarkerType.ENTRADA
        assert event.duration == 1

    def test_parse_high_event_number(self):
        """Parsea evento con número alto (038)."""
        line1 = "038  001      V     C        11:11:26:24 11:11:26:25 11:11:26:24 11:11:26:25"
        line2 = " |C:ResolveColorYellow |M:SALIDA |D:1"

        event = EDLEvent.from_cmx3600(line1, line2)

        assert event.event_number == 38
        assert event.color == EDLColor.Yellow
        assert event.marker_type == MarkerType.SALIDA

    def test_invalid_event_line_raises(self):
        """Línea de evento inválida lanza ValueError."""
        with pytest.raises(ValueError, match="Formato de evento EDL"):
            EDLEvent.from_cmx3600("INVALID LINE", " |C:ResolveColorRed |M:MANUAL_NOTE |D:1")

    def test_invalid_comment_line_raises(self):
        """Línea de comentario inválida lanza ValueError."""
        line1 = "001  001      V     C        10:42:04:03 10:42:04:04 10:42:04:03 10:42:04:04"
        with pytest.raises(ValueError, match="Formato de comentario EDL"):
            EDLEvent.from_cmx3600(line1, "INVALID COMMENT")

    def test_roundtrip_single_event(self):
        """Serializar y parsear un evento produce el mismo resultado."""
        tc_in = SMPTETimecode(10, 42, 4, 3, False)
        tc_out = SMPTETimecode(10, 42, 4, 4, False)
        original = EDLEvent(
            event_number=5,
            tc_in=tc_in,
            tc_out=tc_out,
            rec_in=tc_in,
            rec_out=tc_out,
            color=EDLColor.Green,
            marker_type=MarkerType.IMAGEN,
        )

        serialized = original.to_cmx3600()
        lines = serialized.split("\n")
        parsed = EDLEvent.from_cmx3600(lines[0], lines[1])

        assert parsed.event_number == original.event_number
        assert parsed.tc_in == original.tc_in
        assert parsed.tc_out == original.tc_out
        assert parsed.color == original.color
        assert parsed.marker_type == original.marker_type
        assert parsed.duration == original.duration


class TestEDLDocumentSerialize:
    """Tests para EDLDocument.serialize()."""

    def test_empty_document(self):
        """Documento vacío tiene cabecera pero sin eventos."""
        doc = EDLDocument(title="Empty Test")
        result = doc.serialize()
        assert "TITLE: Empty Test" in result
        assert "FCM: NON-DROP FRAME" in result

    def test_document_with_events(self):
        """Documento con eventos se serializa correctamente."""
        doc = EDLDocument(title="Test Session")
        tc = SMPTETimecode(10, 42, 4, 3, False)
        doc.add_event(tc, EDLColor.Cyan, MarkerType.ENTRADA)

        result = doc.serialize()
        assert "TITLE: Test Session" in result
        assert "001  001" in result
        assert "|C:ResolveColorCyan" in result

    def test_drop_frame_fcm(self):
        """FCM DROP FRAME se serializa correctamente."""
        doc = EDLDocument(title="DF Test", fcm="DROP FRAME")
        result = doc.serialize()
        assert "FCM: DROP FRAME" in result


class TestEDLDocumentParse:
    """Tests para EDLDocument.parse()."""

    def test_parse_real_file(self):
        """Parsea el archivo EDL real del proyecto correctamente."""
        with open("TEMA 10 - CREES ESTO_edl.edl", "r") as f:
            content = f.read()

        doc = EDLDocument.parse(content)

        assert doc.title == "TEMA 10 - CREES ESTO"
        assert doc.fcm == "NON-DROP FRAME"
        assert len(doc.events) == 38
        assert doc.events[0].event_number == 1
        assert doc.events[0].color == EDLColor.Cyan
        assert doc.events[-1].event_number == 38
        assert doc.events[-1].marker_type == MarkerType.SALIDA

    def test_roundtrip_real_file(self):
        """Round-trip del archivo real: parse -> serialize = original."""
        with open("TEMA 10 - CREES ESTO_edl.edl", "r") as f:
            content = f.read()

        doc = EDLDocument.parse(content)
        serialized = doc.serialize()
        doc2 = EDLDocument.parse(serialized)
        serialized2 = doc2.serialize()

        assert serialized == serialized2


class TestEDLDocumentAddEvent:
    """Tests para EDLDocument.add_event()."""

    def test_auto_numbering_starts_at_one(self):
        """Primer evento tiene número 001."""
        doc = EDLDocument(title="Test")
        tc = SMPTETimecode(0, 0, 0, 0, False)
        event = doc.add_event(tc, EDLColor.Red, MarkerType.MANUAL_NOTE)
        assert event.event_number == 1

    def test_auto_numbering_sequential(self):
        """Eventos se numeran secuencialmente."""
        doc = EDLDocument(title="Test")
        tc = SMPTETimecode(0, 0, 0, 0, False)

        for i in range(5):
            event = doc.add_event(tc, EDLColor.Red, MarkerType.MANUAL_NOTE)
            assert event.event_number == i + 1

    def test_tc_out_is_tc_in_plus_one_frame(self):
        """tc_out es tc_in + 1 frame."""
        doc = EDLDocument(title="Test")
        tc = SMPTETimecode(10, 42, 4, 3, False)
        event = doc.add_event(tc, EDLColor.Cyan, MarkerType.ENTRADA)

        assert event.tc_in == tc
        assert event.tc_out == SMPTETimecode(10, 42, 4, 4, False)

    def test_rec_equals_source(self):
        """rec_in = tc_in y rec_out = tc_out."""
        doc = EDLDocument(title="Test")
        tc = SMPTETimecode(10, 42, 4, 3, False)
        event = doc.add_event(tc, EDLColor.Cyan, MarkerType.ENTRADA)

        assert event.rec_in == event.tc_in
        assert event.rec_out == event.tc_out

    def test_frame_wrap_at_second_boundary(self):
        """tc_out wraps correctamente al cambio de segundo."""
        doc = EDLDocument(title="Test")
        tc = SMPTETimecode(11, 11, 10, 29, False)
        event = doc.add_event(tc, EDLColor.Green, MarkerType.IMAGEN)

        assert event.tc_out == SMPTETimecode(11, 11, 11, 0, False)
