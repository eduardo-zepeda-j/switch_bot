"""Filtro de histéresis con cooldown configurable para conmutaciones de cámara.

Implementa un cooldown entre conmutaciones automáticas de cámara para
prevenir cambios erráticos. Los marcadores manuales, de IA y de anomalías
vocales bypasean el filtro.

Requisitos: 8.2, 8.3, 8.4
"""

from __future__ import annotations

from switch_bot.models.enums import SourceOrigin
from switch_bot.models.inference import CameraDecision


# Orígenes que bypasean el cooldown de histéresis
_BYPASS_ORIGINS: frozenset[SourceOrigin] = frozenset(
    {SourceOrigin.MANUAL, SourceOrigin.AI, SourceOrigin.ANOMALY}
)


class HysteresisFilter:
    """Filtro de histéresis con cooldown configurable.

    Impone un cooldown mínimo entre conmutaciones automáticas de cámara.
    Las decisiones con origen MANUAL, AI o ANOMALY bypasean el filtro
    y se procesan inmediatamente.

    El filtro mantiene un contador de frames interno. Cada llamada a
    `should_allow_switch()` o `tick()` avanza el contador en 1 frame.

    Attributes:
        cooldown_frames: Número de frames de cooldown entre conmutaciones
                         automáticas (default 90 = 3 segundos a 30 fps).
        fps: Frecuencia del sistema en frames por segundo.
    """

    def __init__(self, cooldown_frames: int = 90, fps: float = 30.0) -> None:
        """Inicializa el filtro de histéresis.

        Args:
            cooldown_frames: Frames de cooldown entre switches automáticos.
                             Default 90 (3 segundos a 30 fps).
            fps: Frecuencia del sistema. Usado para cálculos de tiempo.
        """
        if cooldown_frames < 0:
            raise ValueError(
                f"cooldown_frames debe ser >= 0, recibido: {cooldown_frames}"
            )
        if fps <= 0:
            raise ValueError(f"fps debe ser > 0, recibido: {fps}")

        self._cooldown_frames: int = cooldown_frames
        self._fps: float = fps
        self._current_frame: int = 0
        self._last_switch_frame: int = -cooldown_frames  # Allow first switch
        self._forced: bool = False

    @property
    def cooldown_frames(self) -> int:
        """Número de frames de cooldown configurado."""
        return self._cooldown_frames

    @property
    def fps(self) -> float:
        """Frecuencia del sistema en fps."""
        return self._fps

    @property
    def current_frame(self) -> int:
        """Frame actual del sistema."""
        return self._current_frame

    @property
    def is_cooling_down(self) -> bool:
        """True si el cooldown está activo (no se permiten switches automáticos).

        El cooldown está activo cuando no han transcurrido suficientes frames
        desde la última conmutación permitida.
        """
        elapsed = self._current_frame - self._last_switch_frame
        return elapsed < self._cooldown_frames

    @property
    def frames_remaining(self) -> int:
        """Frames restantes de cooldown. 0 si no hay cooldown activo."""
        elapsed = self._current_frame - self._last_switch_frame
        remaining = self._cooldown_frames - elapsed
        return max(0, remaining)

    def should_allow_switch(self, decision: CameraDecision) -> bool:
        """Evalúa si se permite la conmutación según el cooldown.

        Las decisiones con origen MANUAL, AI o ANOMALY siempre se permiten
        (bypasean el cooldown). Las decisiones AUTO solo se permiten si
        el cooldown ha expirado.

        Cada llamada avanza el frame counter interno en 1.

        Cuando una conmutación es permitida, el frame de último switch se
        actualiza al frame actual.

        Args:
            decision: Decisión de cámara del DecisionEngine.

        Returns:
            True si la conmutación se permite, False si está bloqueada
            por el cooldown.
        """
        self._current_frame += 1

        # Marcadores manuales, IA y anomalías bypasean siempre
        if decision.source_origin in _BYPASS_ORIGINS:
            self._last_switch_frame = self._current_frame
            return True

        # Check si fue forzado con force_allow()
        if self._forced:
            self._forced = False
            self._last_switch_frame = self._current_frame
            return True

        # Decisiones automáticas: verificar si el cooldown expiró
        elapsed = self._current_frame - self._last_switch_frame
        if elapsed >= self._cooldown_frames:
            self._last_switch_frame = self._current_frame
            return True

        return False

    def force_allow(self) -> None:
        """Bypassa el filtro para la próxima evaluación.

        Usado para marcadores manuales/IA/anomalías que necesitan
        procesamiento inmediato sin esperar el cooldown.
        Resetea el estado de cooldown inmediatamente.
        """
        self._forced = True
        # Also reset cooldown state so is_cooling_down returns False
        self._last_switch_frame = self._current_frame - self._cooldown_frames

    def tick(self) -> None:
        """Avanza el contador de frames en 1.

        Debe ser llamado una vez por frame del sistema para mantener
        el tracking del cooldown actualizado cuando no se evalúa una
        decisión de conmutación.
        """
        self._current_frame += 1

    def reset(self) -> None:
        """Reinicia el filtro al estado inicial (cooldown expirado)."""
        self._current_frame = 0
        self._last_switch_frame = -self._cooldown_frames
        self._forced = False

    @property
    def cooldown_seconds(self) -> float:
        """Cooldown expresado en segundos."""
        return self._cooldown_frames / self._fps
