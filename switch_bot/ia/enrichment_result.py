"""Resultado normalizado del enriquecimiento semántico.

Define la dataclass inmutable EnrichmentResult que encapsula el resultado
de comparar un segmento de audio transcrito contra el guión esperado.
Garantiza estructura idéntica independientemente del backend de IA activo.

Requisitos: 6.2, 6.3, 19.8
"""

from __future__ import annotations

from dataclasses import dataclass, field

from switch_bot.models.enums import EDLColor, MarkerType

# Umbral por defecto para considerar una desviación del guión.
DEFAULT_DEVIATION_THRESHOLD: float = 0.7


@dataclass(frozen=True)
class EnrichmentResult:
    """Resultado del enriquecimiento semántico de un segmento de audio.

    Dataclass inmutable (frozen) que garantiza consistencia estructural
    sin importar qué backend de IA generó el resultado.

    Attributes:
        similarity_score: Score de similitud semántica en rango [0.0, 1.0].
        is_deviation: True si el score está por debajo del umbral (0.7).
        detected_text: Texto del segmento transcrito (STT).
        expected_text: Texto esperado del guión de referencia.
        marker_type: SCRIPT_DEVIATION si es desviación, SCRIPT_MATCH si
            coincide, None si no aplica.
        color: Color del marcador EDL generado.
        metadata: Metadatos adicionales del análisis (backend, modelo, etc.).
    """

    similarity_score: float
    is_deviation: bool
    detected_text: str
    expected_text: str
    marker_type: MarkerType | None
    color: EDLColor | None
    metadata: dict | None = field(default=None)

    def __post_init__(self) -> None:
        """Valida que similarity_score esté en el rango [0.0, 1.0]."""
        if not isinstance(self.similarity_score, (int, float)):
            raise TypeError(
                f"similarity_score debe ser numérico, recibido: "
                f"{type(self.similarity_score).__name__}"
            )
        if self.similarity_score < 0.0 or self.similarity_score > 1.0:
            raise ValueError(
                f"similarity_score debe estar en [0.0, 1.0], "
                f"recibido: {self.similarity_score}"
            )

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @classmethod
    def from_match(
        cls,
        similarity_score: float,
        detected_text: str,
        expected_text: str,
        metadata: dict | None = None,
    ) -> EnrichmentResult:
        """Crea un resultado para un segmento que coincide con el guión.

        Atajo para cuando similarity_score >= threshold (match).

        Args:
            similarity_score: Score de similitud [0.0, 1.0].
            detected_text: Texto transcrito del segmento.
            expected_text: Texto esperado del guión.
            metadata: Metadatos opcionales del análisis.

        Returns:
            EnrichmentResult con is_deviation=False y marker SCRIPT_MATCH.
        """
        return cls(
            similarity_score=similarity_score,
            is_deviation=False,
            detected_text=detected_text,
            expected_text=expected_text,
            marker_type=MarkerType.SCRIPT_MATCH,
            color=EDLColor.Green,
            metadata=metadata,
        )

    @classmethod
    def from_deviation(
        cls,
        similarity_score: float,
        detected_text: str,
        expected_text: str,
        metadata: dict | None = None,
    ) -> EnrichmentResult:
        """Crea un resultado para un segmento que se desvía del guión.

        Atajo para cuando similarity_score < threshold (desviación).

        Args:
            similarity_score: Score de similitud [0.0, 1.0].
            detected_text: Texto transcrito del segmento.
            expected_text: Texto esperado del guión.
            metadata: Metadatos opcionales del análisis.

        Returns:
            EnrichmentResult con is_deviation=True y marker SCRIPT_DEVIATION.
        """
        return cls(
            similarity_score=similarity_score,
            is_deviation=True,
            detected_text=detected_text,
            expected_text=expected_text,
            marker_type=MarkerType.SCRIPT_DEVIATION,
            color=EDLColor.Magenta,
            metadata=metadata,
        )
