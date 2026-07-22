"""VocalAnomalyDetector — Detecta anomalías vocales en segmentos de audio.

Detecta tos, errores de dicción, confusiones y repeticiones usando
el IAEnricher para comparación contra patrones conocidos y el guión.
Las anomalías generan marcadores sin cooldown (bypass de histéresis).

Requisitos: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from switch_bot.engines.script_parser import ScriptDocument
from switch_bot.ia.backend_base import BackendConnectionError, BackendTimeoutError
from switch_bot.ia.ia_enricher import IAEnricher
from switch_bot.models.enums import EDLColor, MarkerType, SourceOrigin

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------


@dataclass
class AudioFeatures:
    """Características de audio extraídas de un segmento.

    Attributes:
        energy_level: Nivel de energía del segmento [0.0, 1.0].
        has_silence_gap: True si hay un hueco de silencio prolongado.
        duration_ms: Duración del segmento en milisegundos.
        pitch_variance: Varianza del pitch (opcional, para detección de tos).
    """

    energy_level: float
    has_silence_gap: bool
    duration_ms: int
    pitch_variance: float = 0.0


@dataclass
class VocalAnomaly:
    """Anomalía vocal detectada en un segmento de audio.

    Todas las anomalías tienen SourceOrigin.ANOMALY y bypass de histéresis
    (Requisito 7.6).

    Attributes:
        anomaly_type: Tipo de marcador (TOS, ERROR_DICCION, CONFUSION, REPETICION).
        confidence: Nivel de confianza de la detección [0.0, 1.0].
        description: Descripción legible de la anomalía detectada.
        source_origin: Siempre ANOMALY — bypass de histéresis.
        color: Siempre Red para anomalías vocales.
    """

    anomaly_type: MarkerType
    confidence: float
    description: str
    source_origin: SourceOrigin = field(default=SourceOrigin.ANOMALY, init=False)
    color: EDLColor = field(default=EDLColor.Red, init=False)


# ---------------------------------------------------------------------------
# Patrones de detección
# ---------------------------------------------------------------------------

# Palabras/sonidos que indican tos en transcripciones
_COUGH_PATTERNS: list[str] = [
    "tos", "cof", "ejem", "[tos]", "[cough]", "*tos*", "*cough*",
    "[ejem]", "carraspeo", "[carraspeo]",
]

# Patrones de tartamudeo / error de dicción
_STUTTER_PATTERN = re.compile(
    r"\b(\w{1,4})\s*[-–]\s*\1\w*\b"  # "pa-palabra", "re-repetir"
    r"|"
    r"\b(\w+)\s+\2\b"  # Palabra repetida inmediata: "la la"
    r"|"
    r"\b(eh|ehm|um|uhm|mmm|ahh|eee)\b",  # Muletillas / hesitación
    re.IGNORECASE,
)

# Umbral de similitud para considerar repetición
_REPETITION_SIMILARITY_THRESHOLD: float = 0.75

# Umbral mínimo de similitud con el guión para no ser confusión
_CONFUSION_SIMILARITY_THRESHOLD: float = 0.3

# Umbral para considerar un error de dicción basado en la diferencia con el guión
_DICTION_SIMILARITY_THRESHOLD: float = 0.6


# ---------------------------------------------------------------------------
# VocalAnomalyDetector
# ---------------------------------------------------------------------------


class VocalAnomalyDetector:
    """Detecta anomalías vocales: tos, errores de dicción, confusiones, repeticiones.

    Usa IAEnricher para comparar transcripciones contra el guión y
    detectar patrones de error. Las anomalías se generan SIN cooldown,
    permitiendo marcadores consecutivos (Requisito 7.6).

    Requisitos: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6
    """

    def __init__(self, enricher: IAEnricher, script_context: ScriptDocument) -> None:
        """Inicializa el detector de anomalías vocales.

        Args:
            enricher: Instancia de IAEnricher para comparación semántica.
            script_context: Documento de guión para referencia.
        """
        self._enricher = enricher
        self._script_context = script_context
        self._previous_segments: list[str] = []

    async def analyze_segment(
        self, transcript: str, audio_features: AudioFeatures
    ) -> list[VocalAnomaly]:
        """Analiza un segmento de audio para detectar anomalías.

        Ejecuta detección en paralelo de:
        - Tos (Req 7.1): silencio prolongado + burst de energía
        - Error de dicción (Req 7.2): tartamudeo, comparación contra guión
        - Confusión (Req 7.3): texto incoherente fuera de contexto del guión
        - Repetición (Req 7.4): frase que repite bloques previos

        Las anomalías NO aplican histéresis (Req 7.6).

        Args:
            transcript: Texto transcrito del segmento de audio.
            audio_features: Características de audio del segmento.

        Returns:
            Lista de VocalAnomaly detectadas (puede estar vacía).
        """
        anomalies: list[VocalAnomaly] = []

        # Req 7.1 — Detección de tos
        cough = self._detect_cough(transcript, audio_features)
        if cough is not None:
            anomalies.append(cough)

        # Req 7.2 — Error de dicción
        diction_error = await self._detect_diction_error(transcript)
        if diction_error is not None:
            anomalies.append(diction_error)

        # Req 7.3 — Confusión
        confusion = await self._detect_confusion(transcript)
        if confusion is not None:
            anomalies.append(confusion)

        # Req 7.4 — Repetición
        repetition = self._detect_repetition(transcript)
        if repetition is not None:
            anomalies.append(repetition)

        # Guardar segmento para detección de repeticiones futuras
        if transcript.strip():
            self._previous_segments.append(transcript.strip())

        return anomalies

    # ------------------------------------------------------------------
    # Detección de tos (Req 7.1)
    # ------------------------------------------------------------------

    def _detect_cough(
        self, transcript: str, audio_features: AudioFeatures
    ) -> VocalAnomaly | None:
        """Detecta patrón de tos: silencio prolongado + burst de energía.

        Condiciones:
        - Hay un gap de silencio (has_silence_gap=True)
        - Energía alta (burst después del silencio)
        - O transcripción contiene patrón de tos explícito

        Args:
            transcript: Texto transcrito.
            audio_features: Características de audio.

        Returns:
            VocalAnomaly de tipo TOS si se detecta, None si no.
        """
        transcript_lower = transcript.lower().strip()

        # Patrón 1: Transcripción contiene indicador de tos
        has_cough_text = any(
            pattern in transcript_lower for pattern in _COUGH_PATTERNS
        )

        # Patrón 2: Silencio + burst de energía (patrón acústico de tos)
        has_cough_audio = (
            audio_features.has_silence_gap and audio_features.energy_level > 0.7
        )

        if has_cough_text or has_cough_audio:
            confidence = 0.9 if has_cough_text else 0.7
            if has_cough_text and has_cough_audio:
                confidence = 0.95

            return VocalAnomaly(
                anomaly_type=MarkerType.TOS,
                confidence=confidence,
                description="Pausa prolongada con tos detectada",
            )

        return None

    # ------------------------------------------------------------------
    # Detección de error de dicción (Req 7.2)
    # ------------------------------------------------------------------

    async def _detect_diction_error(
        self, transcript: str
    ) -> VocalAnomaly | None:
        """Detecta errores de dicción: tartamudeo, mala pronunciación.

        Usa patrones locales de tartamudeo y comparación con el guión
        vía IAEnricher para detectar palabras mal pronunciadas.

        Args:
            transcript: Texto transcrito.

        Returns:
            VocalAnomaly de tipo ERROR_DICCION si se detecta, None si no.
        """
        if not transcript.strip():
            return None

        # Patrón local: tartamudeo / hesitación
        stutter_match = _STUTTER_PATTERN.search(transcript)
        if stutter_match:
            return VocalAnomaly(
                anomaly_type=MarkerType.ERROR_DICCION,
                confidence=0.85,
                description=(
                    f"Error de dicción detectado: '{stutter_match.group()}'"
                ),
            )

        # Comparación con guión vía IAEnricher (Req 7.5)
        closest_block = self._find_closest_script_block(transcript)
        if closest_block is not None:
            try:
                similarity = await self._enricher.active_backend.compute_similarity(
                    transcript, closest_block.text
                )
            except (BackendConnectionError, BackendTimeoutError) as e:
                logger.error(
                    "Error backend detectando error de dicción: %s", e
                )
                return None

            # Similitud intermedia: probablemente misma frase pero mal dicha
            if _CONFUSION_SIMILARITY_THRESHOLD < similarity < _DICTION_SIMILARITY_THRESHOLD:
                return VocalAnomaly(
                    anomaly_type=MarkerType.ERROR_DICCION,
                    confidence=min(0.9, 1.0 - similarity),
                    description=(
                        f"Posible error de dicción — similitud con guión: {similarity:.2f}"
                    ),
                )

        return None

    # ------------------------------------------------------------------
    # Detección de confusión (Req 7.3)
    # ------------------------------------------------------------------

    async def _detect_confusion(
        self, transcript: str
    ) -> VocalAnomaly | None:
        """Detecta confusión: cambio involuntario de tema, frase incoherente.

        Compara la transcripción contra todo el guión usando IAEnricher.
        Si la similitud es muy baja con todos los bloques, indica confusión.

        Args:
            transcript: Texto transcrito.

        Returns:
            VocalAnomaly de tipo CONFUSION si se detecta, None si no.
        """
        if not transcript.strip() or len(transcript.strip().split()) < 3:
            return None

        # Usar IAEnricher para comparar contra el contexto del guión (Req 7.5)
        closest_block = self._find_closest_script_block(transcript)
        if closest_block is None:
            return None

        try:
            similarity = await self._enricher.active_backend.compute_similarity(
                transcript, closest_block.text
            )
        except (BackendConnectionError, BackendTimeoutError) as e:
            logger.error("Error backend detectando confusión: %s", e)
            return None

        # Si la similitud es muy baja con el bloque más cercano, es confusión
        if similarity < _CONFUSION_SIMILARITY_THRESHOLD:
            return VocalAnomaly(
                anomaly_type=MarkerType.CONFUSION,
                confidence=min(0.9, 1.0 - similarity),
                description=(
                    f"Confusión detectada — texto fuera de contexto del guión "
                    f"(similitud: {similarity:.2f})"
                ),
            )

        return None

    # ------------------------------------------------------------------
    # Detección de repetición (Req 7.4)
    # ------------------------------------------------------------------

    def _detect_repetition(self, transcript: str) -> VocalAnomaly | None:
        """Detecta repetición: el hablante repite una frase/bloque previo.

        Compara el segmento actual contra los segmentos previos
        y los bloques del guión ya dichos.

        Args:
            transcript: Texto transcrito.

        Returns:
            VocalAnomaly de tipo REPETICION si se detecta, None si no.
        """
        if not transcript.strip() or len(transcript.strip().split()) < 3:
            return None

        transcript_normalized = transcript.strip().lower()

        # Comparar contra segmentos previos
        for prev_segment in self._previous_segments:
            prev_normalized = prev_segment.lower()
            ratio = SequenceMatcher(
                None, transcript_normalized, prev_normalized
            ).ratio()

            if ratio >= _REPETITION_SIMILARITY_THRESHOLD:
                return VocalAnomaly(
                    anomaly_type=MarkerType.REPETICION,
                    confidence=ratio,
                    description=(
                        f"Repetición detectada — texto similar a segmento previo "
                        f"(similitud: {ratio:.2f})"
                    ),
                )

        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_closest_script_block(self, transcript: str):
        """Encuentra el bloque del guión más similar al transcript.

        Usa SequenceMatcher para búsqueda rápida local sin requerir backend.

        Args:
            transcript: Texto a comparar.

        Returns:
            ScriptBlock más similar o None si no hay bloques.
        """
        if not self._script_context.blocks:
            return None

        best_block = None
        best_ratio = 0.0

        transcript_lower = transcript.strip().lower()

        for block in self._script_context.blocks:
            ratio = SequenceMatcher(
                None, transcript_lower, block.text.lower()
            ).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_block = block

        return best_block
