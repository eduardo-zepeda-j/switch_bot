"""Tests unitarios para PanicButton.

Verifica activate/deactivate, propiedad is_active,
inyección de marcador PANIC en EDL, y respuesta sub-frame.
"""

import threading
import time

from switch_bot.engines.panic_button import PanicButton
from switch_bot.models.enums import EDLColor, MarkerType
from switch_bot.models.timecode import SMPTETimecode
from switch_bot.serializers.edl_serializer import EDLDocument


def _make_tc(h: int = 1, m: int = 0, s: int = 0, f: int = 0) -> SMPTETimecode:
    return SMPTETimecode(hours=h, minutes=m, seconds=s, frames=f, drop_frame=False)


class TestPanicButtonBasic:
    """Tests básicos de activación y desactivación."""

    def test_initially_inactive(self) -> None:
        pb = PanicButton()
        assert pb.is_active is False

    def test_activate_sets_active(self) -> None:
        pb = PanicButton()
        pb.activate(_make_tc())
        assert pb.is_active is True

    def test_deactivate_clears_active(self) -> None:
        pb = PanicButton()
        pb.activate(_make_tc())
        pb.deactivate()
        assert pb.is_active is False

    def test_multiple_activate_deactivate_cycles(self) -> None:
        pb = PanicButton()
        for _ in range(5):
            pb.activate(_make_tc())
            assert pb.is_active is True
            pb.deactivate()
            assert pb.is_active is False

    def test_activation_timecode_stored(self) -> None:
        pb = PanicButton()
        tc = _make_tc(2, 30, 15, 10)
        pb.activate(tc)
        assert pb.activation_timecode == tc

    def test_activation_timecode_none_initially(self) -> None:
        pb = PanicButton()
        assert pb.activation_timecode is None


class TestPanicButtonEDLIntegration:
    """Tests de integración con EDLDocument."""

    def test_activate_adds_panic_marker_to_edl(self) -> None:
        edl = EDLDocument(title="Test Session")
        pb = PanicButton(edl_document=edl)
        tc = _make_tc(1, 15, 30, 20)

        pb.activate(tc)

        assert len(edl.events) == 1
        event = edl.events[0]
        assert event.marker_type == MarkerType.PANIC
        assert event.color == EDLColor.Red
        assert event.tc_in == tc

    def test_activate_without_edl_does_not_raise(self) -> None:
        pb = PanicButton(edl_document=None)
        pb.activate(_make_tc())
        assert pb.is_active is True

    def test_multiple_activations_add_multiple_markers(self) -> None:
        edl = EDLDocument(title="Test Session")
        pb = PanicButton(edl_document=edl)

        pb.activate(_make_tc(1, 0, 0, 0))
        pb.deactivate()
        pb.activate(_make_tc(1, 5, 0, 0))

        assert len(edl.events) == 2
        assert edl.events[0].tc_in == _make_tc(1, 0, 0, 0)
        assert edl.events[1].tc_in == _make_tc(1, 5, 0, 0)

    def test_panic_marker_event_number_sequential(self) -> None:
        edl = EDLDocument(title="Test Session")
        pb = PanicButton(edl_document=edl)

        pb.activate(_make_tc(0, 0, 0, 5))
        pb.deactivate()
        pb.activate(_make_tc(0, 0, 1, 10))

        assert edl.events[0].event_number == 1
        assert edl.events[1].event_number == 2


class TestPanicButtonResponseTime:
    """Tests de rendimiento — respuesta < 1 frame time (33.33 ms)."""

    def test_activate_response_under_frame_time(self) -> None:
        pb = PanicButton()
        tc = _make_tc()

        start = time.perf_counter()
        pb.activate(tc)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 33.33, f"activate() took {elapsed_ms:.2f} ms (> 33.33 ms)"

    def test_deactivate_response_under_frame_time(self) -> None:
        pb = PanicButton()
        pb.activate(_make_tc())

        start = time.perf_counter()
        pb.deactivate()
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 33.33, f"deactivate() took {elapsed_ms:.2f} ms (> 33.33 ms)"

    def test_is_active_check_under_frame_time(self) -> None:
        pb = PanicButton()
        pb.activate(_make_tc())

        start = time.perf_counter()
        _ = pb.is_active
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 33.33, f"is_active took {elapsed_ms:.2f} ms (> 33.33 ms)"


class TestPanicButtonThreadSafety:
    """Tests de concurrencia — verifica que la flag se propaga entre threads."""

    def test_activation_visible_from_another_thread(self) -> None:
        pb = PanicButton()
        result: list[bool] = []

        def check_active() -> None:
            result.append(pb.is_active)

        pb.activate(_make_tc())
        t = threading.Thread(target=check_active)
        t.start()
        t.join()

        assert result[0] is True

    def test_deactivation_visible_from_another_thread(self) -> None:
        pb = PanicButton()
        result: list[bool] = []

        def check_active() -> None:
            result.append(pb.is_active)

        pb.activate(_make_tc())
        pb.deactivate()
        t = threading.Thread(target=check_active)
        t.start()
        t.join()

        assert result[0] is False
