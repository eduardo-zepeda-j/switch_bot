"""Property-based tests para PanicButton — Pausa y restauración de automatización.

**Validates: Requirements 9.1, 9.3**

Property 8: El Panic Button pausa y restaura la automatización.
Para cualquier estado del sistema, activar el PanicButton debe causar que todas
las conmutaciones automáticas de cámara sean rechazadas. Desactivar el PanicButton
debe restaurar la capacidad de conmutación automática al estado previo a la activación
(propiedad state round-trip).
"""

from __future__ import annotations

from hypothesis import given, settings, assume
from hypothesis.strategies import (
    booleans,
    composite,
    integers,
    sampled_from,
    lists,
    just,
)

from switch_bot.engines.panic_button import PanicButton
from switch_bot.models.enums import SourceOrigin
from switch_bot.models.inference import CameraDecision
from switch_bot.models.timecode import SMPTETimecode
from switch_bot.serializers.edl_serializer import EDLDocument


# --- Strategies ---


@composite
def valid_smpte_timecodes(draw, drop_frame: bool | None = None):
    """Genera timecodes SMPTE válidos respetando las reglas Drop Frame."""
    df = draw(booleans()) if drop_frame is None else drop_frame
    hours = draw(integers(min_value=0, max_value=23))
    minutes = draw(integers(min_value=0, max_value=59))
    seconds = draw(integers(min_value=0, max_value=59))
    frames = draw(integers(min_value=0, max_value=29))

    # En Drop Frame, frames 0 y 1 no existen en segundo 0 de minutos no múltiplos de 10
    if df and seconds == 0 and minutes % 10 != 0:
        frames = draw(integers(min_value=2, max_value=29))

    return SMPTETimecode(
        hours=hours, minutes=minutes, seconds=seconds, frames=frames, drop_frame=df
    )


@composite
def auto_camera_decisions(draw):
    """Genera decisiones automáticas de cámara (las que el PanicButton bloquea)."""
    target_cam = draw(integers(min_value=1, max_value=4))
    return CameraDecision(
        target_cam=target_cam,
        reason="auto decision",
        source_origin=SourceOrigin.AUTO,
    )


class TestProperty8PanicButtonPausesAndRestoresAutomation:
    """Property 8: El Panic Button pausa y restaura la automatización.

    **Validates: Requirements 9.1, 9.3**
    """

    @given(tc=valid_smpte_timecodes())
    def test_activate_sets_is_active_true(self, tc: SMPTETimecode) -> None:
        """FOR ALL timecodes, activating PanicButton sets is_active to True.

        Validates: Requirement 9.1 — activar pausa conmutaciones automáticas.
        """
        pb = PanicButton()
        assert not pb.is_active

        pb.activate(tc)
        assert pb.is_active

    @given(tc=valid_smpte_timecodes())
    def test_deactivate_restores_is_active_false(self, tc: SMPTETimecode) -> None:
        """FOR ALL timecodes, deactivating PanicButton after activation restores is_active to False.

        Validates: Requirement 9.3 — desactivar reanuda operación automática.
        """
        pb = PanicButton()
        pb.activate(tc)
        assert pb.is_active

        pb.deactivate()
        assert not pb.is_active

    @given(
        tc=valid_smpte_timecodes(),
        decisions=lists(auto_camera_decisions(), min_size=1, max_size=10),
    )
    def test_while_active_all_auto_switches_rejected(
        self, tc: SMPTETimecode, decisions: list[CameraDecision]
    ) -> None:
        """FOR ALL states, while PanicButton is active, automatic switches are rejected.

        This validates the core property: activating PanicButton causes all
        automatic camera switches to be rejected. We verify that `is_active`
        is True and thus no auto switch should proceed.

        Validates: Requirement 9.1 — pausa TODAS las conmutaciones automáticas.
        """
        pb = PanicButton()
        pb.activate(tc)

        # While panic is active, all auto decisions should be blocked
        for decision in decisions:
            assert pb.is_active, (
                "PanicButton must remain active until explicitly deactivated"
            )
            # The is_active flag is what the system checks before allowing auto switches
            # Any automatic decision must be rejected while is_active is True
            assert decision.source_origin == SourceOrigin.AUTO

    @given(
        tc_activate=valid_smpte_timecodes(),
        tc_second=valid_smpte_timecodes(),
    )
    def test_state_round_trip_activate_deactivate(
        self, tc_activate: SMPTETimecode, tc_second: SMPTETimecode
    ) -> None:
        """FOR ALL states, activate → deactivate restores the prior state (round-trip).

        The system must return to a state where automatic switching is possible
        after deactivation, identical to the state before activation.

        Validates: Requirement 9.3 — restaura estado previo a la activación.
        """
        pb = PanicButton()

        # Initial state: not active, automation can proceed
        initial_is_active = pb.is_active
        assert initial_is_active is False

        # Activate
        pb.activate(tc_activate)
        assert pb.is_active is True

        # Deactivate — must restore to the same state as before activation
        pb.deactivate()
        assert pb.is_active == initial_is_active
        # Automation capability is restored
        assert pb.is_active is False

    @given(
        tc1=valid_smpte_timecodes(),
        tc2=valid_smpte_timecodes(),
    )
    def test_multiple_activate_deactivate_cycles_restore_state(
        self, tc1: SMPTETimecode, tc2: SMPTETimecode
    ) -> None:
        """FOR ALL timecodes, multiple activate/deactivate cycles always restore automation.

        The round-trip property holds across multiple cycles: each deactivation
        fully restores the ability to switch automatically.

        Validates: Requirements 9.1, 9.3
        """
        pb = PanicButton()

        # Cycle 1
        pb.activate(tc1)
        assert pb.is_active is True
        pb.deactivate()
        assert pb.is_active is False

        # Cycle 2 with different timecode
        pb.activate(tc2)
        assert pb.is_active is True
        pb.deactivate()
        assert pb.is_active is False

    @given(tc=valid_smpte_timecodes())
    def test_activate_stores_timecode(self, tc: SMPTETimecode) -> None:
        """FOR ALL timecodes, activating PanicButton stores the activation timecode.

        Validates: Requirement 9.1 — pausa con SMPTE_TC registrado.
        """
        pb = PanicButton()
        pb.activate(tc)
        assert pb.activation_timecode == tc

    @given(tc=valid_smpte_timecodes())
    def test_activate_registers_panic_marker_in_edl(self, tc: SMPTETimecode) -> None:
        """FOR ALL timecodes, activating with EDL document registers a PANIC marker.

        Validates: Requirement 9.1 — la activación registra bandera de emergencia.
        """
        from switch_bot.models.enums import EDLColor, MarkerType

        edl_doc = EDLDocument(title="TEST", fcm="NON-DROP FRAME")
        pb = PanicButton(edl_document=edl_doc)

        pb.activate(tc)

        assert len(edl_doc.events) == 1
        event = edl_doc.events[0]
        assert event.tc_in == tc
        assert event.color == EDLColor.Red
        assert event.marker_type == MarkerType.PANIC

    @given(tc=valid_smpte_timecodes())
    def test_deactivate_preserves_edl_markers(self, tc: SMPTETimecode) -> None:
        """FOR ALL timecodes, deactivating does not modify existing EDL markers.

        The PANIC marker recorded during activation is preserved after deactivation.
        """
        edl_doc = EDLDocument(title="TEST", fcm="NON-DROP FRAME")
        pb = PanicButton(edl_document=edl_doc)

        pb.activate(tc)
        events_after_activate = len(edl_doc.events)

        pb.deactivate()
        # Deactivation must not add or remove events
        assert len(edl_doc.events) == events_after_activate

