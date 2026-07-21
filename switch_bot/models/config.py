"""Configuración global del sistema Switch_bot."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


# FPS soportados por el sistema
SUPPORTED_FPS: tuple[float, ...] = (60.0, 30.0, 29.97)


@dataclass
class SystemConfig:
    """Configuración global del sistema.

    Attributes:
        video_mode: Modo de video activo (e.g. "1080p29.97").
        fps: Frecuencia del sistema en frames por segundo.
        frame_time_ms: Tiempo por frame en milisegundos (calculado en __post_init__).
        hysteresis_frames: Número de frames de cooldown para histéresis.
        drop_frame: True si fps == 29.97 (modo drop frame SMPTE).
        num_cameras: Número de cámaras activas.
        atem_ip: Dirección IP del switcher ATEM.
        obs_ws_url: URL WebSocket de OBS Studio.
        output_dir: Directorio de salida para archivos generados.
        ia_backend_config: Configuración del backend IA activo (None si no configurado).
    """

    video_mode: str = "1080p29.97"
    fps: float = 29.97
    frame_time_ms: float = field(init=False, default=0.0)
    hysteresis_frames: int = 90
    drop_frame: bool = True
    num_cameras: int = 4
    atem_ip: str = ""
    obs_ws_url: str = "ws://localhost:4455"
    output_dir: Path = field(default_factory=lambda: Path("./output"))
    ia_backend_config: IABackendConfig | None = None  # noqa: F821

    def __post_init__(self) -> None:
        """Valida fps soportados y calcula frame_time_ms a partir de fps."""
        if self.fps not in SUPPORTED_FPS:
            raise ValueError(
                f"FPS no soportado: {self.fps}. "
                f"Valores válidos: {SUPPORTED_FPS}"
            )
        self.frame_time_ms = 1000.0 / self.fps

    @property
    def cooldown_seconds(self) -> float:
        """Calcula el cooldown de histéresis en segundos."""
        return self.hysteresis_frames / self.fps
