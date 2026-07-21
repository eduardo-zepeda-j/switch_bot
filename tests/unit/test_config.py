"""Unit tests para SystemConfig."""

import pytest
from pathlib import Path

from switch_bot.models.config import SystemConfig, SUPPORTED_FPS


class TestSystemConfigDefaults:
    """Tests para valores por defecto de SystemConfig."""

    def test_default_video_mode(self) -> None:
        cfg = SystemConfig()
        assert cfg.video_mode == "1080p29.97"

    def test_default_fps(self) -> None:
        cfg = SystemConfig()
        assert cfg.fps == 29.97

    def test_default_drop_frame_true(self) -> None:
        """El modo por defecto 29.97 activa drop frame."""
        cfg = SystemConfig()
        assert cfg.drop_frame is True

    def test_default_hysteresis_frames(self) -> None:
        cfg = SystemConfig()
        assert cfg.hysteresis_frames == 90

    def test_default_num_cameras(self) -> None:
        cfg = SystemConfig()
        assert cfg.num_cameras == 4

    def test_default_obs_ws_url(self) -> None:
        cfg = SystemConfig()
        assert cfg.obs_ws_url == "ws://localhost:4455"

    def test_default_output_dir(self) -> None:
        cfg = SystemConfig()
        assert cfg.output_dir == Path("./output")

    def test_default_ia_backend_config_none(self) -> None:
        cfg = SystemConfig()
        assert cfg.ia_backend_config is None


class TestSystemConfigFrameTime:
    """Tests para el cálculo de frame_time_ms."""

    def test_frame_time_at_30fps(self) -> None:
        cfg = SystemConfig(fps=30.0, drop_frame=False)
        assert abs(cfg.frame_time_ms - 33.33) < 0.01

    def test_frame_time_at_29_97fps(self) -> None:
        cfg = SystemConfig(fps=29.97, drop_frame=True)
        expected = 1000.0 / 29.97
        assert abs(cfg.frame_time_ms - expected) < 0.001

    def test_frame_time_at_60fps(self) -> None:
        cfg = SystemConfig(fps=60.0, drop_frame=False)
        assert abs(cfg.frame_time_ms - 16.6667) < 0.001


class TestSystemConfigCooldown:
    """Tests para la propiedad cooldown_seconds."""

    def test_cooldown_at_30fps_90_frames(self) -> None:
        """90 frames / 30 fps = 3.0 segundos."""
        cfg = SystemConfig(fps=30.0, hysteresis_frames=90, drop_frame=False)
        assert cfg.cooldown_seconds == 3.0

    def test_cooldown_at_29_97fps_90_frames(self) -> None:
        """90 frames / 29.97 fps ≈ 3.003 segundos."""
        cfg = SystemConfig(fps=29.97, hysteresis_frames=90, drop_frame=True)
        expected = 90 / 29.97
        assert abs(cfg.cooldown_seconds - expected) < 0.001

    def test_cooldown_at_60fps_90_frames(self) -> None:
        """90 frames / 60 fps = 1.5 segundos."""
        cfg = SystemConfig(fps=60.0, hysteresis_frames=90, drop_frame=False)
        assert cfg.cooldown_seconds == 1.5

    def test_cooldown_custom_hysteresis(self) -> None:
        """180 frames / 30 fps = 6.0 segundos."""
        cfg = SystemConfig(fps=30.0, hysteresis_frames=180, drop_frame=False)
        assert cfg.cooldown_seconds == 6.0


class TestSystemConfigValidation:
    """Tests para validación de fps soportados."""

    def test_invalid_fps_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="FPS no soportado"):
            SystemConfig(fps=24.0)

    def test_invalid_fps_25_raises(self) -> None:
        with pytest.raises(ValueError, match="FPS no soportado"):
            SystemConfig(fps=25.0)

    def test_invalid_fps_0_raises(self) -> None:
        with pytest.raises(ValueError, match="FPS no soportado"):
            SystemConfig(fps=0.0)

    def test_supported_fps_tuple(self) -> None:
        assert SUPPORTED_FPS == (60.0, 30.0, 29.97)

    def test_all_supported_fps_valid(self) -> None:
        """Todas las fps soportadas crean instancias sin error."""
        for fps in SUPPORTED_FPS:
            cfg = SystemConfig(fps=fps, drop_frame=(fps == 29.97))
            assert cfg.fps == fps
