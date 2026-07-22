"""Property-based tests para score de similitud semántica acotado [0.0, 1.0].

**Validates: Requirements 6.2**

Verifica que:
- EnrichmentResult rechaza scores fuera de [0.0, 1.0]
- EnrichmentResult acepta cualquier score válido en [0.0, 1.0]
- IAEnricher.compare_live_audio() siempre produce scores en [0.0, 1.0],
  incluso cuando el backend retorna valores fuera de rango.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, PropertyMock

import pytest
from hypothesis import given, assume
from hypothesis.strategies import (
    floats,
    integers,
    text,
    one_of,
    just,
)

from switch_bot.engines.script_parser import ScriptBlock, ScriptDocument
from switch_bot.ia.backend_base import IABackend
from switch_bot.ia.enrichment_result import EnrichmentResult
from switch_bot.ia.ia_enricher import IAEnricher
from switch_bot.models.enums import EDLColor, MarkerType


# --- Strategies ---

# Scores válidos en el rango [0.0, 1.0]
valid_scores = floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)

# Scores inválidos fuera del rango [0.0, 1.0]
invalid_scores_above = floats(
    min_value=1.0 + 1e-10, max_value=1e6, allow_nan=False, allow_infinity=False
)
invalid_scores_below = floats(
    min_value=-1e6, max_value=-1e-10, allow_nan=False, allow_infinity=False
)
invalid_scores = one_of(invalid_scores_above, invalid_scores_below)

# Scores extendidos que el backend podría retornar (incluyendo fuera de rango)
extended_scores = floats(
    min_value=-1.0, max_value=2.0, allow_nan=False, allow_infinity=False
)

# Texto no vacío para transcripciones
transcript_text = text(min_size=1, max_size=200)


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


class TestProperty18SimilarityScoreBounded:
    """Property 18: Score de similitud semántica está acotado entre 0.0 y 1.0.

    **Validates: Requirements 6.2**

    Verifica que el score de similitud producido por el sistema siempre
    está en el rango [0.0, 1.0], tanto a nivel de validación de dataclass
    como a nivel de clamping en IAEnricher.
    """

    @given(score=valid_scores)
    def test_enrichment_result_accepts_valid_scores(self, score: float) -> None:
        """FOR ALL score in [0.0, 1.0], EnrichmentResult construction succeeds."""
        result = EnrichmentResult(
            similarity_score=score,
            is_deviation=score < 0.7,
            detected_text="detected",
            expected_text="expected",
            marker_type=MarkerType.SCRIPT_MATCH,
            color=EDLColor.Green,
        )
        assert 0.0 <= result.similarity_score <= 1.0

    @given(score=invalid_scores)
    def test_enrichment_result_rejects_invalid_scores(self, score: float) -> None:
        """FOR ALL score outside [0.0, 1.0], EnrichmentResult raises ValueError."""
        with pytest.raises(ValueError):
            EnrichmentResult(
                similarity_score=score,
                is_deviation=True,
                detected_text="detected",
                expected_text="expected",
                marker_type=MarkerType.SCRIPT_DEVIATION,
                color=EDLColor.Magenta,
            )

    @given(score=extended_scores)
    def test_ia_enricher_clamps_score_to_valid_range(self, score: float) -> None:
        """FOR ALL scores returned by backend (even out of range),
        IAEnricher.compare_live_audio() produces result with score in [0.0, 1.0].
        """
        backend = _make_mock_backend(score)
        script_doc = _make_script_doc()
        enricher = IAEnricher(backend=backend, script_doc=script_doc)
        context = _make_context_block()

        result = asyncio.run(
            enricher.compare_live_audio(transcript="prueba", context=context)
        )

        assert 0.0 <= result.similarity_score <= 1.0

    @given(score=valid_scores, transcript=transcript_text)
    def test_compare_live_audio_bounded_with_varied_inputs(
        self, score: float, transcript: str
    ) -> None:
        """FOR ALL valid transcripts and backend scores,
        compare_live_audio() always produces score in [0.0, 1.0].
        """
        backend = _make_mock_backend(score)
        script_doc = _make_script_doc()
        enricher = IAEnricher(backend=backend, script_doc=script_doc)
        context = _make_context_block()

        result = asyncio.run(
            enricher.compare_live_audio(transcript=transcript, context=context)
        )

        assert 0.0 <= result.similarity_score <= 1.0

    @given(score=valid_scores)
    def test_from_match_factory_preserves_bounded_score(self, score: float) -> None:
        """FOR ALL score in [0.0, 1.0], from_match() preserves the score unchanged."""
        assume(score >= 0.7)  # from_match is for scores above threshold
        result = EnrichmentResult.from_match(
            similarity_score=score,
            detected_text="detected",
            expected_text="expected",
        )
        assert result.similarity_score == score
        assert 0.0 <= result.similarity_score <= 1.0

    @given(score=valid_scores)
    def test_from_deviation_factory_preserves_bounded_score(self, score: float) -> None:
        """FOR ALL score in [0.0, 1.0], from_deviation() preserves the score unchanged."""
        assume(score < 0.7)  # from_deviation is for scores below threshold
        result = EnrichmentResult.from_deviation(
            similarity_score=score,
            detected_text="detected",
            expected_text="expected",
        )
        assert result.similarity_score == score
        assert 0.0 <= result.similarity_score <= 1.0
