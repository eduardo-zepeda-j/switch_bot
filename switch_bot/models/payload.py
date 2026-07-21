"""EnrichedPayload — Payload unificado para despacho cuádruple.

Representa el paquete de datos enriquecido que se envía simultáneamente
a los 4 pipelines (ATEM, OBS, Metadata, EDL) tras una decisión aprobada
por el Motor de Decisión.

Requisitos: 16.1
"""

from __future__ import annotations

from dataclasses import dataclass

from switch_bot.models.enums import EDLColor, MarkerType, SourceOrigin
from switch_bot.models.timecode import SMPTETimecode


@dataclass(frozen=True)
class EnrichedPayload:
    """Payload unificado despachado a los 4 pipelines.

    Attributes:
        personaje: Nombre del personaje activo.
        target_cam: Índice de cámara destino (1-4).
        marker_type: Tipo de marcador EDL.
        note: Nota descriptiva del evento.
        tc_in: Timecode SMPTE de entrada.
        source_origin: Origen del evento (MANUAL, AI, AUTO, ANOMALY).
        color: Color del marcador para EDL/DaVinci Resolve.
    """

    personaje: str  # Nombre del personaje activo
    target_cam: int  # Índice de cámara destino (1-4)
    marker_type: MarkerType  # Tipo de marcador
    note: str  # Nota descriptiva
    tc_in: SMPTETimecode  # Timecode de entrada
    source_origin: SourceOrigin  # Origen del evento (MANUAL, AI, AUTO, ANOMALY)
    color: EDLColor  # Color del marcador para EDL

    def __post_init__(self) -> None:
        """Valida rangos y tipos de los campos del payload."""
        if not self.personaje:
            raise ValueError("personaje no puede estar vacío")
        if not (1 <= self.target_cam <= 4):
            raise ValueError(
                f"target_cam debe estar entre 1 y 4, recibido: {self.target_cam}"
            )
        if not isinstance(self.marker_type, MarkerType):
            raise TypeError(
                f"marker_type debe ser MarkerType, recibido: {type(self.marker_type)}"
            )
        if not isinstance(self.tc_in, SMPTETimecode):
            raise TypeError(
                f"tc_in debe ser SMPTETimecode, recibido: {type(self.tc_in)}"
            )
        if not isinstance(self.source_origin, SourceOrigin):
            raise TypeError(
                f"source_origin debe ser SourceOrigin, recibido: {type(self.source_origin)}"
            )
        if not isinstance(self.color, EDLColor):
            raise TypeError(
                f"color debe ser EDLColor, recibido: {type(self.color)}"
            )
