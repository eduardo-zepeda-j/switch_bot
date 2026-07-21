"""Property-based tests: marcadores manuales/IA/anomalías bypasean histéresis.

**Validates: Requirements 4.4, 7.6, 8.3**

Property 4: Para cualquier estado del HysteresisFilter (activo o expirado),
y para cualquier marcador cuyo SourceOrigin sea MANUAL, AI o ANOMALY,
el filtro debe permitir el procesamiento inmediato sin aplicar cooldown,
incluyendo marcadores consecutivos sin intervalo mínimo.
"""

from __future__ import annotations

from hypothesis import given, settings, assume
from hypothesis.strategies import (
    integers,
    sampled_from,
    lists,
    composite,
    floats,
    text,
)

from switch_bot.engines.hysteresis_filter import HysteresisFilter
from switch_bot.models.enums import SourceOrigin
from switch_bot.models.inference import CameraDecision


# --- Strategies ---

# Orígenes que deben bypasear el filtro
bypass_origins = sampled_from([SourceOrigin.MANUAL, SourceOrigin.AI, SourceOrigin.ANOMALY])

# Cámara destino válida (1-4)
valid_target_cam = integers(min_value=1, max_value=4)

# Cooldown frames válidos
valid_cooldown = integers(min_value=1, max_value=500)

# FPS válidos
valid_fps = sampled_from([60.0, 30.0, 29.97])

# Número de ticks para simular frames transcurridos (0 = el cooldown acaba de activarse)
elapsed_frames = integers(min_value=0, max_value=200)


@composite
def bypass_decision(draw) -> CameraDecision:
    """Genera una decisión de cámara con origen que bypasea el filtro."""
    origin = draw(bypass_origins)
    cam = draw(valid_target_cam)
    return CameraDecision(
        target_cam=cam,
        reason="bypass marker",
        source_origin=origin,
    )


@composite
def filter_with_active_cooldown(draw):
    """Genera un HysteresisFilter con cooldown activo.

    Primero permite un switch automático, luego opcionalmente avanza
    algunos frames (pero siempre menos que el cooldown total).
    """
    cooldown = draw(valid_cooldown)
    fps = draw(valid_fps)
    ticks_after = draw(integers(min_value=0, max_value=max(0, cooldown - 2)))

    f = HysteresisFilter(cooldown_frames=cooldown, fps=fps)
    # Trigger cooldown con un switch automático
    auto = CameraDecision(
        target_cam=1, reason="auto switch", source_origin=SourceOrigin.AUTO
    )
    f.should_allow_switch(auto)

    # Avanzar algunos frames (pero no los suficientes para expirar el cooldown)
    for _ in range(ticks_after):
        f.tick()

    assert f.is_cooling_down, "Filter should be in cooldown state"
    return f


@composite
def filter_with_expired_cooldown(draw):
    """Genera un HysteresisFilter con cooldown expirado."""
    cooldown = draw(valid_cooldown)
    fps = draw(valid_fps)

    f = HysteresisFilter(cooldown_frames=cooldown, fps=fps)
    # Trigger cooldown y luego expirar
    auto = CameraDecision(
        target_cam=1, reason="auto switch", source_origin=SourceOrigin.AUTO
    )
    f.should_allow_switch(auto)

    # Avanzar suficientes frames para expirar el cooldown
    for _ in range(cooldown):
        f.tick()

    assert not f.is_cooling_down, "Filter cooldown should be expired"
    return f


class TestProperty4BypassHysteresis:
    """Property 4: Marcadores manuales, de IA y de anomalías vocales bypasean
    el filtro de histéresis.

    **Validates: Requirements 4.4, 7.6, 8.3**
    """

    @given(
        filt=filter_with_active_cooldown(),
        decision=bypass_decision(),
    )
    def test_bypass_during_active_cooldown(
        self, filt: HysteresisFilter, decision: CameraDecision
    ) -> None:
        """FOR ALL filter states with active cooldown and bypass-origin decisions,
        should_allow_switch returns True (immediate processing without cooldown)."""
        assert filt.should_allow_switch(decision) is True

    @given(
        filt=filter_with_expired_cooldown(),
        decision=bypass_decision(),
    )
    def test_bypass_during_expired_cooldown(
        self, filt: HysteresisFilter, decision: CameraDecision
    ) -> None:
        """FOR ALL filter states with expired cooldown and bypass-origin decisions,
        should_allow_switch returns True."""
        assert filt.should_allow_switch(decision) is True

    @given(
        cooldown=valid_cooldown,
        fps=valid_fps,
        num_consecutive=integers(min_value=2, max_value=20),
        origin=bypass_origins,
    )
    def test_consecutive_bypass_markers_all_allowed(
        self,
        cooldown: int,
        fps: float,
        num_consecutive: int,
        origin: SourceOrigin,
    ) -> None:
        """FOR ALL sequences of consecutive bypass-origin markers (no ticks between),
        every single one is allowed — no minimum interval is enforced."""
        f = HysteresisFilter(cooldown_frames=cooldown, fps=fps)

        for i in range(num_consecutive):
            decision = CameraDecision(
                target_cam=(i % 4) + 1,
                reason=f"consecutive marker {i}",
                source_origin=origin,
            )
            result = f.should_allow_switch(decision)
            assert result is True, (
                f"Marker {i} with origin {origin.value} should bypass, "
                f"but was blocked at frame {f.current_frame}"
            )

    @given(
        cooldown=valid_cooldown,
        fps=valid_fps,
        decision=bypass_decision(),
    )
    def test_bypass_on_fresh_filter(
        self, cooldown: int, fps: float, decision: CameraDecision
    ) -> None:
        """FOR ALL fresh filters and bypass-origin decisions,
        should_allow_switch returns True (no prior state matters)."""
        f = HysteresisFilter(cooldown_frames=cooldown, fps=fps)
        assert f.should_allow_switch(decision) is True

    @given(
        cooldown=valid_cooldown,
        fps=valid_fps,
        pre_auto_count=integers(min_value=1, max_value=5),
        decision=bypass_decision(),
    )
    def test_bypass_after_multiple_auto_blocks(
        self,
        cooldown: int,
        fps: float,
        pre_auto_count: int,
        decision: CameraDecision,
    ) -> None:
        """After several auto decisions have been blocked by cooldown,
        a bypass-origin marker still passes immediately."""
        f = HysteresisFilter(cooldown_frames=cooldown, fps=fps)

        # First auto triggers cooldown
        auto = CameraDecision(
            target_cam=1, reason="auto", source_origin=SourceOrigin.AUTO
        )
        f.should_allow_switch(auto)

        # Subsequent autos are blocked
        for _ in range(pre_auto_count):
            f.should_allow_switch(auto)

        # Bypass marker still passes
        assert f.should_allow_switch(decision) is True
