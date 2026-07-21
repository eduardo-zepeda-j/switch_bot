"""Property-based tests para SystemConfig — Cálculo correcto de frame_time y cooldown.

**Validates: Requirements 18.3**
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings, assume
from hypothesis.strategies import sampled_from, integers, floats

from switch_bot.models.config import SystemConfig, SUPPORTED_FPS


# --- Strategies ---
valid_fps = sampled_from(list(SUPPORTED_FPS))
valid_hysteresis_frames = integers(min_value=1, max_value=1000)
invalid_fps = floats(min_value=0.1, max_value=1000.0).filter(
    lambda x: x not in SUPPORTED_FPS
)


class TestProperty12FrameTimeAndCooldown:
    """Property 12: Cálculo correcto de frame_time y cooldown a partir de fps.

    **Validates: Requirements 18.3**
    """

    @given(fps=valid_fps)
    def test_frame_time_equals_1000_div_fps(self, fps: float) -> None:
        """FOR ALL valid fps, SystemConfig.frame_time_ms == 1000.0 / fps."""
        config = SystemConfig(fps=fps)
        assert config.frame_time_ms == pytest.approx(1000.0 / fps)

    @given(fps=valid_fps, hysteresis_frames=valid_hysteresis_frames)
    def test_cooldown_seconds_equals_hysteresis_frames_div_fps(
        self, fps: float, hysteresis_frames: int
    ) -> None:
        """FOR ALL valid fps and hysteresis_frames, cooldown_seconds == hysteresis_frames / fps."""
        config = SystemConfig(fps=fps, hysteresis_frames=hysteresis_frames)
        expected = hysteresis_frames / fps
        assert config.cooldown_seconds == pytest.approx(expected)

    @given(fps=invalid_fps)
    def test_invalid_fps_raises_value_error(self, fps: float) -> None:
        """FOR ALL fps not in SUPPORTED_FPS, SystemConfig raises ValueError."""
        with pytest.raises(ValueError, match="FPS no soportado"):
            SystemConfig(fps=fps)

    @given(fps=valid_fps)
    def test_frame_time_is_always_positive(self, fps: float) -> None:
        """frame_time_ms is always positive for valid fps."""
        config = SystemConfig(fps=fps)
        assert config.frame_time_ms > 0

    @given(fps=valid_fps, hysteresis_frames=valid_hysteresis_frames)
    def test_cooldown_seconds_is_always_positive(
        self, fps: float, hysteresis_frames: int
    ) -> None:
        """cooldown_seconds is always positive when hysteresis_frames > 0."""
        config = SystemConfig(fps=fps, hysteresis_frames=hysteresis_frames)
        assert config.cooldown_seconds > 0
