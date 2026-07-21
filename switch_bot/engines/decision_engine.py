"""Motor de Decisión del sistema Switch_bot.

Evalúa los datos de inferencia (gaze tracking, VAD) y el contexto del guión
para determinar la cámara destino óptima.

Lógica de prioridad:
1. Sin habla activa → no cambio de cámara (None)
2. Habla activa + mirada a otra cámara → shot de reacción (REACTION_SHOT)
3. Habla activa + mirada a propia cámara o sin mirada → cámara del hablante (SPEAKER_ACTIVE)
4. Speaker desconocido → no cambio (None)

Requisitos: 8.1, 2.4
"""

from __future__ import annotations

from switch_bot.models.config import SystemConfig
from switch_bot.models.enums import SourceOrigin
from switch_bot.models.inference import CameraDecision, GazeResult, VADResult


class DecisionEngine:
    """Evalúa datos de inferencia y determina la cámara destino.

    Utiliza el character_camera_map del guión para resolver la relación
    entre personajes y sus cámaras asignadas.

    Attributes:
        _config: Configuración del sistema.
        _character_map: Mapeo personaje → cámara (1-4).
    """

    def __init__(self, config: SystemConfig, character_map: dict[str, int]) -> None:
        """Inicializa el motor de decisión.

        Args:
            config: Configuración global del sistema.
            character_map: Mapeo de nombre de personaje a índice de cámara (1-4).
        """
        self._config = config
        self._character_map = character_map

    @property
    def character_camera_map(self) -> dict[str, int]:
        """Retorna el mapeo personaje → cámara (solo lectura)."""
        return self._character_map

    def evaluate(self, gaze: GazeResult, vad: VADResult) -> CameraDecision | None:
        """Determina la cámara óptima basándose en gaze, voz y contexto.

        Aplica la siguiente lógica de prioridad:
        1. Si no hay habla activa (is_speaking=False) → None (no switch)
        2. Si hay habla activa pero el speaker_id es desconocido o None → None
        3. Si el hablante mira a otra cámara (distinta a la suya) → REACTION_SHOT
        4. Si el hablante mira a su propia cámara o no mira a ninguna → SPEAKER_ACTIVE

        Args:
            gaze: Resultado del gaze tracking del frame actual.
            vad: Resultado de la detección de actividad vocal.

        Returns:
            CameraDecision con la cámara destino y razón, o None si no hay cambio.
        """
        # Prioridad 1: Sin habla → no cambio
        if not vad.is_speaking:
            return None

        # Prioridad 2: Speaker desconocido → no cambio
        if vad.speaker_id is None or vad.speaker_id not in self._character_map:
            return None

        # Obtener cámara asignada al hablante
        speaker_cam = self._character_map[vad.speaker_id]

        # Prioridad 3: Mirada a otra cámara → reacción
        if gaze.looking_at is not None:
            # looking_at es un feed index (0-3), convertir a cámara (1-4)
            gaze_target_cam = gaze.looking_at + 1

            if gaze_target_cam != speaker_cam:
                return CameraDecision(
                    target_cam=gaze_target_cam,
                    reason="REACTION_SHOT",
                    source_origin=SourceOrigin.AUTO,
                )

        # Prioridad 4: Habla activa sin mirada a otra cámara → cámara del hablante
        return CameraDecision(
            target_cam=speaker_cam,
            reason="SPEAKER_ACTIVE",
            source_origin=SourceOrigin.AUTO,
        )
