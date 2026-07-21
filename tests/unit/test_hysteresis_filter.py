"""Tests unitarios para HysteresisFilter.

Valida: Requisitos 8.2, 8.3, 8.4
"""

import pytest

from switch_bot.engines.hysteresis_filter import HysteresisFilter
from switch_bot.models.enums import SourceOrigin
from switch_bot.models.inference import CameraDecision


def _auto_decision(target_cam: int = 1) -> CameraDecision:
    """Crea una decisión automática de prueba."""
    return CameraDecision(
        target_cam=target_cam,
        reason="auto switch",
        source_origin=SourceOrigin.AUTO,
    )


def _manual_decision(target_cam: int = 2) -> CameraDecision:
    """Crea una decisión manual de prueba."""
    return CameraDecision(
        target_cam=target_cam,
        reason="manual marker",
        source_origin=SourceOrigin.MANUAL,
    )


def _ai_decision(target_cam: int = 3) -> CameraDecision:
    """Crea una decisión de IA de prueba."""
    return CameraDecision(
        target_cam=target_cam,
        reason="ai prompt",
        source_origin=SourceOrigin.AI,
    )


def _anomaly_decision(target_cam: int = 4) -> CameraDecision:
    """Crea una decisión de anomalía de prueba."""
    return CameraDecision(
        target_cam=target_cam,
        reason="vocal anomaly detected",
        source_origin=SourceOrigin.ANOMALY,
    )


class TestHysteresisFilterInit:
    """Tests de inicialización del filtro."""

    def test_default_cooldown_is_90_frames(self) -> None:
        f = HysteresisFilter()
        assert f.cooldown_frames == 90

    def test_default_fps_is_30(self) -> None:
        f = HysteresisFilter()
        assert f.fps == 30.0

    def test_custom_cooldown(self) -> None:
        f = HysteresisFilter(cooldown_frames=60)
        assert f.cooldown_frames == 60

    def test_custom_fps(self) -> None:
        f = HysteresisFilter(fps=60.0)
        assert f.fps == 60.0

    def test_zero_cooldown_allowed(self) -> None:
        f = HysteresisFilter(cooldown_frames=0)
        assert f.cooldown_frames == 0

    def test_negative_cooldown_raises(self) -> None:
        with pytest.raises(ValueError, match="cooldown_frames"):
            HysteresisFilter(cooldown_frames=-1)

    def test_zero_fps_raises(self) -> None:
        with pytest.raises(ValueError, match="fps"):
            HysteresisFilter(fps=0)

    def test_negative_fps_raises(self) -> None:
        with pytest.raises(ValueError, match="fps"):
            HysteresisFilter(fps=-1.0)


class TestShouldAllowSwitch:
    """Tests de la lógica de cooldown para conmutaciones automáticas."""

    def test_first_auto_switch_is_allowed(self) -> None:
        """La primera conmutación automática siempre se permite."""
        f = HysteresisFilter(cooldown_frames=90)
        assert f.should_allow_switch(_auto_decision()) is True

    def test_second_auto_switch_within_cooldown_is_blocked(self) -> None:
        """Una segunda conmutación automática dentro del cooldown es bloqueada."""
        f = HysteresisFilter(cooldown_frames=90)
        f.should_allow_switch(_auto_decision())  # Permitida (frame 1)
        assert f.should_allow_switch(_auto_decision()) is False  # Frame 2, bloqueada

    def test_auto_switch_after_cooldown_expires(self) -> None:
        """Después de que expire el cooldown, se permite una nueva conmutación."""
        f = HysteresisFilter(cooldown_frames=5)
        f.should_allow_switch(_auto_decision())  # frame 1, allowed

        # Frames 2-5: bloqueados (4 llamadas dentro del cooldown)
        for _ in range(4):
            assert f.should_allow_switch(_auto_decision()) is False

        # Frame 6: cooldown expirado (5 frames transcurridos)
        assert f.should_allow_switch(_auto_decision()) is True

    def test_90_frame_cooldown_blocks_for_89_frames(self) -> None:
        """Con cooldown de 90, se bloquean 89 intentos consecutivos."""
        f = HysteresisFilter(cooldown_frames=90)
        f.should_allow_switch(_auto_decision())  # frame 1, allowed

        # Frames 2-90: bloqueados
        for i in range(89):
            assert f.should_allow_switch(_auto_decision()) is False, (
                f"Frame {i + 2} debería estar bloqueado"
            )

        # Frame 91: cooldown expirado
        assert f.should_allow_switch(_auto_decision()) is True


class TestBypassOrigins:
    """Tests del bypass para marcadores manuales, IA y anomalías (Req 8.3)."""

    def test_manual_bypasses_cooldown(self) -> None:
        """Marcadores manuales bypasean el filtro de histéresis."""
        f = HysteresisFilter(cooldown_frames=90)
        f.should_allow_switch(_auto_decision())  # Activa cooldown
        assert f.should_allow_switch(_manual_decision()) is True

    def test_ai_bypasses_cooldown(self) -> None:
        """Marcadores de IA bypasean el filtro de histéresis."""
        f = HysteresisFilter(cooldown_frames=90)
        f.should_allow_switch(_auto_decision())  # Activa cooldown
        assert f.should_allow_switch(_ai_decision()) is True

    def test_anomaly_bypasses_cooldown(self) -> None:
        """Anomalías vocales bypasean el filtro de histéresis."""
        f = HysteresisFilter(cooldown_frames=90)
        f.should_allow_switch(_auto_decision())  # Activa cooldown
        assert f.should_allow_switch(_anomaly_decision()) is True

    def test_multiple_manual_in_sequence(self) -> None:
        """Múltiples marcadores manuales consecutivos se permiten."""
        f = HysteresisFilter(cooldown_frames=90)
        for _ in range(5):
            assert f.should_allow_switch(_manual_decision()) is True

    def test_bypass_resets_cooldown_for_auto(self) -> None:
        """Después de un bypass, el cooldown se reinicia para AUTO."""
        f = HysteresisFilter(cooldown_frames=5)
        f.should_allow_switch(_auto_decision())  # frame 1
        f.should_allow_switch(_manual_decision())  # frame 2, bypass

        # El cooldown se reinició en frame 2, así que auto está bloqueado
        assert f.should_allow_switch(_auto_decision()) is False  # frame 3


class TestForceAllow:
    """Tests del método force_allow."""

    def test_force_allow_permits_next_auto(self) -> None:
        """Después de force_allow, la siguiente auto es permitida."""
        f = HysteresisFilter(cooldown_frames=90)
        f.should_allow_switch(_auto_decision())  # Activa cooldown
        f.force_allow()
        assert f.should_allow_switch(_auto_decision()) is True

    def test_force_allow_deactivates_cooling_down(self) -> None:
        """force_allow desactiva el estado de cooling_down."""
        f = HysteresisFilter(cooldown_frames=90)
        f.should_allow_switch(_auto_decision())
        assert f.is_cooling_down is True
        f.force_allow()
        assert f.is_cooling_down is False


class TestIsCoolingDown:
    """Tests de la propiedad is_cooling_down."""

    def test_not_cooling_initially(self) -> None:
        """No hay cooldown activo al inicializar."""
        f = HysteresisFilter(cooldown_frames=90)
        assert f.is_cooling_down is False

    def test_cooling_after_auto_switch(self) -> None:
        """Cooldown activo después de una conmutación automática."""
        f = HysteresisFilter(cooldown_frames=90)
        f.should_allow_switch(_auto_decision())
        assert f.is_cooling_down is True

    def test_cooling_after_bypass_switch(self) -> None:
        """Cooldown activo después de un bypass (manual/AI/anomalía)."""
        f = HysteresisFilter(cooldown_frames=90)
        f.should_allow_switch(_manual_decision())
        assert f.is_cooling_down is True

    def test_not_cooling_after_full_cooldown(self) -> None:
        """No hay cooldown después de que expiren todos los frames."""
        f = HysteresisFilter(cooldown_frames=3)
        f.should_allow_switch(_auto_decision())  # frame 1
        # Avanzar 3 frames más (tick no evalúa decisión)
        f.tick()  # frame 2
        f.tick()  # frame 3
        f.tick()  # frame 4
        assert f.is_cooling_down is False


class TestTick:
    """Tests del método tick."""

    def test_tick_advances_frame(self) -> None:
        """tick avanza el frame counter."""
        f = HysteresisFilter()
        assert f.current_frame == 0
        f.tick()
        assert f.current_frame == 1

    def test_tick_helps_expire_cooldown(self) -> None:
        """tick puede usarse para expirar el cooldown sin decisiones."""
        f = HysteresisFilter(cooldown_frames=3)
        f.should_allow_switch(_auto_decision())  # frame 1, allowed
        f.tick()  # frame 2
        f.tick()  # frame 3
        f.tick()  # frame 4
        assert f.should_allow_switch(_auto_decision()) is True  # frame 5


class TestFramesRemaining:
    """Tests de la propiedad frames_remaining."""

    def test_zero_when_no_cooldown(self) -> None:
        """0 frames restantes cuando no hay cooldown."""
        f = HysteresisFilter(cooldown_frames=90)
        assert f.frames_remaining == 0

    def test_full_cooldown_after_switch(self) -> None:
        """Cooldown completo restante justo después de un switch."""
        f = HysteresisFilter(cooldown_frames=90)
        f.should_allow_switch(_auto_decision())
        # Restantes: 90 - (1 - 1) = 90... Calculemos:
        # _current_frame = 1, _last_switch_frame = 1
        # remaining = 90 - (1 - 1) = 90
        assert f.frames_remaining == 90

    def test_decreases_with_ticks(self) -> None:
        """frames_remaining decrece con cada tick."""
        f = HysteresisFilter(cooldown_frames=5)
        f.should_allow_switch(_auto_decision())  # frame 1
        assert f.frames_remaining == 5
        f.tick()  # frame 2
        assert f.frames_remaining == 4
        f.tick()  # frame 3
        assert f.frames_remaining == 3
