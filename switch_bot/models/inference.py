"""Modelos de resultado de inferencia para el sistema Switch_bot.

Define las estructuras de datos producidas por los motores de inferencia
(gaze tracking, VAD) y el motor de decisión.

Requisitos: 16.1
"""

from __future__ import annotations

from dataclasses import dataclass

from switch_bot.models.enums import SourceOrigin


@dataclass(frozen=True)
class GazeResult:
    """Resultado de MediaPipe gaze tracking por frame.

    Attributes:
        feed_index: Índice del feed de cámara analizado (0-3).
        looking_at: Índice de cámara a la que la persona mira, o None si
                    no se puede determinar.
        confidence: Score de confianza del tracking [0.0, 1.0].
    """

    feed_index: int  # Which camera feed (0-3)
    looking_at: int | None  # Camera index the person is looking at, or None
    confidence: float  # Confidence score [0.0, 1.0]

    def __post_init__(self) -> None:
        """Valida rangos de los campos."""
        if not (0 <= self.feed_index <= 3):
            raise ValueError(
                f"feed_index debe estar entre 0 y 3, recibido: {self.feed_index}"
            )
        if self.looking_at is not None and not (0 <= self.looking_at <= 3):
            raise ValueError(
                f"looking_at debe estar entre 0 y 3 o ser None, recibido: {self.looking_at}"
            )
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(
                f"confidence debe estar entre 0.0 y 1.0, recibido: {self.confidence}"
            )


@dataclass(frozen=True)
class VADResult:
    """Resultado de Voice Activity Detection.

    Attributes:
        is_speaking: True si se detectó actividad vocal.
        speaker_id: Identificador del hablante si está disponible, o None.
        confidence: Score de confianza de la detección [0.0, 1.0].
    """

    is_speaking: bool  # True if voice activity detected
    speaker_id: str | None  # Identified speaker if available
    confidence: float  # Confidence score [0.0, 1.0]

    def __post_init__(self) -> None:
        """Valida rangos de los campos."""
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(
                f"confidence debe estar entre 0.0 y 1.0, recibido: {self.confidence}"
            )


@dataclass(frozen=True)
class CameraDecision:
    """Decisión de salida del DecisionEngine.

    Attributes:
        target_cam: Cámara destino para conmutar (1-4).
        reason: Razón por la que se eligió esta cámara.
        source_origin: Origen de la decisión (MANUAL, AI, AUTO, ANOMALY).
    """

    target_cam: int  # Camera to switch to (1-4)
    reason: str  # Why this camera was chosen
    source_origin: SourceOrigin  # Origin of the decision

    def __post_init__(self) -> None:
        """Valida rangos de los campos."""
        if not (1 <= self.target_cam <= 4):
            raise ValueError(
                f"target_cam debe estar entre 1 y 4, recibido: {self.target_cam}"
            )
        if not self.reason:
            raise ValueError("reason no puede estar vacío")
