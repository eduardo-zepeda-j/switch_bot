"""Property-based tests para umbral de similitud y marcadores de desviación.

**Validates: Requirements 6.3**

Verifica que:
- FOR ALL scores < 0.7: IAEnricher produce SCRIPT_DEVIATION con color Magenta
- FOR ALL scores >= 0.7: IAEnricher produce SCRIPT_MATCH con color Green
- El caso frontera exacto 0.7 produce SCRIPT_MATCH (no desviación)
- EnrichmentResult.from_deviation() siempre produce campos correctos
- EnrichmentResult.from_match() siempre produce campos correctos
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, PropertyMock

from hypothesis import given, assume
from hypothesis.strategies import (
    floats,
    text,
)

from switch_bot.engines.script_parser import ScriptBlock, ScriptDocument
from switch_bot.ia.backend_base import IABackend
from switch_bot.ia.enrichment_result import (
    DEFAULT_DEVIATION_THRESHOLD,
    EnrichmentResult,
)
from switch_bot.ia.ia_enricher import IAEnricher
from switch_bot.models.enums import EDLColor, MarkerType


# --- Strategies ---

# Scores por debajo del umbral de desviación (estrictamente < 0.7)
scores_below_threshold = floats(
    min_value=0.0, max_value=0.7 - 1e-10, allow_nan=False, allow_infinity=False
)

# Scores en o por encima del umbral (>= 0.7)
scores_at_or_above_threshold = floats(
    min_value=0.7, max_value=1.0, allow_nan=False, allow_infinity=False
)

# Scores válidos en el rango [0.0, 1.0]
valid_scores = floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)

# Texto no vacío para transcripciones y textos esperados
non_empty_text = text(min_size=1, max_size=200)


# --- Helpers ---

def _make_mock_backend(similarity_return: float) -> IABackend:
    """Crea un mock de IABackend que retorna un score fijo de compute_similarity."""
    backend = AsyncMock(spec=IABackend)
    backend.compute_similarity = AsyncMock(return_value=similarity_return)
    type(backend).backend_type = PropertyMock(return_value="mock")
    type(backend).is_connected = PropertyMock(return_value=True)
    return backend


def _make_script_doc() -> ScriptDocument:
    """Crea un ScriptDocument mínimo para testing."""
    return ScriptDocument(
        title="Test Script",
        blocks=[
            ScriptBlock(index=0, character="ACTOR", text="Texto de prueba"),
        ],
        character_camera_map={"ACTOR": 1},
    )


def _make_context_block(text_content: str = "Texto esperado") -> ScriptBlock:
    """Crea un ScriptBlock de contexto para compare_live_audio."""
    return ScriptBlock(index=0, character="ACTOR", text=text_content)


# --- Test Classes ---


class TestProperty19DeviationThreshold:
    """Property 19: Umbral de similitud genera marcadores de desviación correctamente.

    **Validates: Requirements 6.3**

    Verifica que el umbral de desviación 0.7 genera correctamente
    marcadores SCRIPT_DEVIATION (score < 0.7) o SCRIPT_MATCH (score >= 0.7)
    con los colores y metadatos apropiados.
    """

    @given(score=scores_below_threshold, transcript=non_empty_text)
    def test_below_threshold_produces_deviation(
        self, score: float, transcript: str
    ) -> None:
        """FOR ALL scores < 0.7, compare_live_audio() produce SCRIPT_DEVIATION
        con is_deviation=True, color=Magenta, y textos preservados."""
        backend = _make_mock_backend(score)
        script_doc = _make_script_doc()
        enricher = IAEnricher(backend=backend, script_doc=script_doc)
        context = _make_context_block()

        result = asyncio.run(
            enricher.compare_live_audio(transcript=transcript, context=context)
        )

        assert result.is_deviation is True
        assert result.marker_type == MarkerType.SCRIPT_DEVIATION
        assert result.color == EDLColor.Magenta
        assert result.detected_text == transcript
        assert result.expected_text == context.text
        assert result.metadata is not None
        assert "score" in result.metadata

    @given(score=scores_at_or_above_threshold, transcript=non_empty_text)
    def test_at_or_above_threshold_produces_match(
        self, score: float, transcript: str
    ) -> None:
        """FOR ALL scores >= 0.7, compare_live_audio() produce SCRIPT_MATCH
        con is_deviation=False y color=Green."""
        backend = _make_mock_backend(score)
        script_doc = _make_script_doc()
        enricher = IAEnricher(backend=backend, script_doc=script_doc)
        context = _make_context_block()

        result = asyncio.run(
            enricher.compare_live_audio(transcript=transcript, context=context)
        )

        assert result.is_deviation is False
        assert result.marker_type == MarkerType.SCRIPT_MATCH
        assert result.color == EDLColor.Green

    def test_boundary_exactly_0_7_produces_match(self) -> None:
        """El caso frontera score=0.7 produce SCRIPT_MATCH (no desviación),
        ya que la condición es score < 0.7."""
        score = 0.7
        backend = _make_mock_backend(score)
        script_doc = _make_script_doc()
        enricher = IAEnricher(backend=backend, script_doc=script_doc)
        context = _make_context_block()

        result = asyncio.run(
            enricher.compare_live_audio(transcript="prueba", context=context)
        )

        assert result.is_deviation is False
        assert result.marker_type == MarkerType.SCRIPT_MATCH
        assert result.color == EDLColor.Green
        assert result.similarity_score == 0.7

    @given(score=valid_scores, detected=non_empty_text, expected=non_empty_text)
    def test_from_deviation_factory_produces_correct_fields(
        self, score: float, detected: str, expected: str
    ) -> None:
        """FOR ALL valid scores, from_deviation() produce resultado con
        is_deviation=True, marker_type=SCRIPT_DEVIATION, color=Magenta,
        y textos preservados."""
        assume(score < DEFAULT_DEVIATION_THRESHOLD)

        result = EnrichmentResult.from_deviation(
            similarity_score=score,
            detected_text=detected,
            expected_text=expected,
            metadata={"score": score},
        )

        assert result.is_deviation is True
        assert result.marker_type == MarkerType.SCRIPT_DEVIATION
        assert result.color == EDLColor.Magenta
        assert result.detected_text == detected
        assert result.expected_text == expected
        assert result.similarity_score == score
        assert result.metadata == {"score": score}

    @given(score=valid_scores, detected=non_empty_text, expected=non_empty_text)
    def test_from_match_factory_produces_correct_fields(
        self, score: float, detected: str, expected: str
    ) -> None:
        """FOR ALL valid scores, from_match() produce resultado con
        is_deviation=False, marker_type=SCRIPT_MATCH, color=Green,
        y textos preservados."""
        assume(score >= DEFAULT_DEVIATION_THRESHOLD)

        result = EnrichmentResult.from_match(
            similarity_score=score,
            detected_text=detected,
            expected_text=expected,
            metadata={"score": score},
        )

        assert result.is_deviation is False
        assert result.marker_type == MarkerType.SCRIPT_MATCH
        assert result.color == EDLColor.Green
        assert result.detected_text == detected
        assert result.expected_text == expected
        assert result.similarity_score == score
        assert result.metadata == {"score": score}
