"""Property-based tests para consistencia de estructura de salida entre backends.

**Validates: Requirements 19.8**

Verifica que:
- FOR ALL valid inputs (scores, transcripts), cuando dos backends distintos
  (simulando "bedrock" y "local") retornan el mismo score para el mismo input,
  IAEnricher produce EnrichmentResult con estructura idéntica.
- El campo backend_type en metadata NO afecta la estructura lógica del resultado.
- Ambos backends producen EnrichmentResult válidos (no None, campos requeridos poblados).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, PropertyMock

from hypothesis import given
from hypothesis.strategies import (
    floats,
    text,
)

from switch_bot.engines.script_parser import ScriptBlock, ScriptDocument
from switch_bot.ia.backend_base import IABackend
from switch_bot.ia.enrichment_result import EnrichmentResult
from switch_bot.ia.ia_enricher import IAEnricher
from switch_bot.models.enums import EDLColor, MarkerType


# --- Strategies ---

# Scores válidos en el rango [0.0, 1.0]
valid_scores = floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)

# Texto no vacío para transcripciones
transcript_text = text(min_size=1, max_size=200)

# Texto no vacío para contenido de guión esperado
expected_text = text(min_size=1, max_size=200)


# --- Helpers ---


def _make_mock_backend(similarity_return: float, backend_type: str) -> IABackend:
    """Crea un mock de IABackend que simula un tipo de backend específico.

    Args:
        similarity_return: Score fijo que retorna compute_similarity.
        backend_type: Tipo de backend simulado ("bedrock" o "local").
    """
    backend = AsyncMock(spec=IABackend)
    backend.compute_similarity = AsyncMock(return_value=similarity_return)
    type(backend).backend_type = PropertyMock(return_value=backend_type)
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


class TestProperty17BackendConsistency:
    """Property 17: Consistencia de estructura de salida entre backends.

    **Validates: Requirements 19.8**

    Verifica que IAEnricher produce resultados con estructura idéntica
    independientemente de si el backend activo es Bedrock o Local,
    siempre que ambos retornen el mismo score para la misma entrada.
    """

    @given(score=valid_scores, transcript=transcript_text)
    def test_same_score_produces_identical_structure(
        self, score: float, transcript: str
    ) -> None:
        """FOR ALL scores in [0.0, 1.0] and valid transcripts,
        bedrock and local backends produce EnrichmentResult con
        campos estructurales idénticos (is_deviation, marker_type, color)."""
        # Crear dos backends simulando bedrock y local con mismo score
        bedrock_backend = _make_mock_backend(score, "bedrock")
        local_backend = _make_mock_backend(score, "local")

        script_doc = _make_script_doc()
        context = _make_context_block()

        # Ejecutar con backend bedrock
        enricher_bedrock = IAEnricher(backend=bedrock_backend, script_doc=script_doc)
        result_bedrock = asyncio.run(
            enricher_bedrock.compare_live_audio(transcript=transcript, context=context)
        )

        # Ejecutar con backend local
        enricher_local = IAEnricher(backend=local_backend, script_doc=script_doc)
        result_local = asyncio.run(
            enricher_local.compare_live_audio(transcript=transcript, context=context)
        )

        # Estructura idéntica: mismos campos lógicos
        assert result_bedrock.is_deviation == result_local.is_deviation
        assert result_bedrock.marker_type == result_local.marker_type
        assert result_bedrock.color == result_local.color
        assert result_bedrock.similarity_score == result_local.similarity_score

    @given(score=valid_scores, transcript=transcript_text)
    def test_same_is_deviation_flag(
        self, score: float, transcript: str
    ) -> None:
        """FOR ALL scores, el flag is_deviation es idéntico entre backends."""
        bedrock_backend = _make_mock_backend(score, "bedrock")
        local_backend = _make_mock_backend(score, "local")

        script_doc = _make_script_doc()
        context = _make_context_block()

        result_bedrock = asyncio.run(
            IAEnricher(backend=bedrock_backend, script_doc=script_doc)
            .compare_live_audio(transcript=transcript, context=context)
        )
        result_local = asyncio.run(
            IAEnricher(backend=local_backend, script_doc=script_doc)
            .compare_live_audio(transcript=transcript, context=context)
        )

        assert result_bedrock.is_deviation == result_local.is_deviation

    @given(score=valid_scores, transcript=transcript_text)
    def test_same_marker_type(
        self, score: float, transcript: str
    ) -> None:
        """FOR ALL scores, el marker_type es idéntico entre backends."""
        bedrock_backend = _make_mock_backend(score, "bedrock")
        local_backend = _make_mock_backend(score, "local")

        script_doc = _make_script_doc()
        context = _make_context_block()

        result_bedrock = asyncio.run(
            IAEnricher(backend=bedrock_backend, script_doc=script_doc)
            .compare_live_audio(transcript=transcript, context=context)
        )
        result_local = asyncio.run(
            IAEnricher(backend=local_backend, script_doc=script_doc)
            .compare_live_audio(transcript=transcript, context=context)
        )

        assert result_bedrock.marker_type == result_local.marker_type

    @given(score=valid_scores, transcript=transcript_text)
    def test_same_color(
        self, score: float, transcript: str
    ) -> None:
        """FOR ALL scores, el color del marcador es idéntico entre backends."""
        bedrock_backend = _make_mock_backend(score, "bedrock")
        local_backend = _make_mock_backend(score, "local")

        script_doc = _make_script_doc()
        context = _make_context_block()

        result_bedrock = asyncio.run(
            IAEnricher(backend=bedrock_backend, script_doc=script_doc)
            .compare_live_audio(transcript=transcript, context=context)
        )
        result_local = asyncio.run(
            IAEnricher(backend=local_backend, script_doc=script_doc)
            .compare_live_audio(transcript=transcript, context=context)
        )

        assert result_bedrock.color == result_local.color

    @given(score=valid_scores, transcript=transcript_text)
    def test_text_preservation_across_backends(
        self, score: float, transcript: str
    ) -> None:
        """FOR ALL inputs, detected_text y expected_text se preservan
        idénticamente en ambos backends."""
        bedrock_backend = _make_mock_backend(score, "bedrock")
        local_backend = _make_mock_backend(score, "local")

        script_doc = _make_script_doc()
        context = _make_context_block()

        result_bedrock = asyncio.run(
            IAEnricher(backend=bedrock_backend, script_doc=script_doc)
            .compare_live_audio(transcript=transcript, context=context)
        )
        result_local = asyncio.run(
            IAEnricher(backend=local_backend, script_doc=script_doc)
            .compare_live_audio(transcript=transcript, context=context)
        )

        assert result_bedrock.detected_text == result_local.detected_text
        assert result_bedrock.expected_text == result_local.expected_text

    @given(score=valid_scores, transcript=transcript_text)
    def test_backend_type_in_metadata_does_not_affect_logic(
        self, score: float, transcript: str
    ) -> None:
        """FOR ALL inputs, la diferencia de backend_type en metadata
        no afecta la estructura lógica del resultado (is_deviation,
        marker_type, color, score)."""
        bedrock_backend = _make_mock_backend(score, "bedrock")
        local_backend = _make_mock_backend(score, "local")

        script_doc = _make_script_doc()
        context = _make_context_block()

        result_bedrock = asyncio.run(
            IAEnricher(backend=bedrock_backend, script_doc=script_doc)
            .compare_live_audio(transcript=transcript, context=context)
        )
        result_local = asyncio.run(
            IAEnricher(backend=local_backend, script_doc=script_doc)
            .compare_live_audio(transcript=transcript, context=context)
        )

        # Metadata difiere en backend_type pero la lógica es idéntica
        assert result_bedrock.metadata is not None
        assert result_local.metadata is not None
        assert result_bedrock.metadata["backend_type"] == "bedrock"
        assert result_local.metadata["backend_type"] == "local"

        # Pero la estructura lógica es la misma
        assert result_bedrock.similarity_score == result_local.similarity_score
        assert result_bedrock.is_deviation == result_local.is_deviation
        assert result_bedrock.marker_type == result_local.marker_type
        assert result_bedrock.color == result_local.color

    @given(score=valid_scores, transcript=transcript_text)
    def test_both_backends_produce_valid_results(
        self, score: float, transcript: str
    ) -> None:
        """FOR ALL inputs, ambos backends producen EnrichmentResult válidos
        (no None, campos requeridos poblados, score en rango)."""
        bedrock_backend = _make_mock_backend(score, "bedrock")
        local_backend = _make_mock_backend(score, "local")

        script_doc = _make_script_doc()
        context = _make_context_block()

        result_bedrock = asyncio.run(
            IAEnricher(backend=bedrock_backend, script_doc=script_doc)
            .compare_live_audio(transcript=transcript, context=context)
        )
        result_local = asyncio.run(
            IAEnricher(backend=local_backend, script_doc=script_doc)
            .compare_live_audio(transcript=transcript, context=context)
        )

        # Ambos no son None
        assert result_bedrock is not None
        assert result_local is not None

        # Ambos son instancias de EnrichmentResult
        assert isinstance(result_bedrock, EnrichmentResult)
        assert isinstance(result_local, EnrichmentResult)

        # Campos requeridos poblados en ambos
        for result in (result_bedrock, result_local):
            assert 0.0 <= result.similarity_score <= 1.0
            assert isinstance(result.is_deviation, bool)
            assert result.detected_text == transcript
            assert result.expected_text == context.text
            assert result.marker_type in (
                MarkerType.SCRIPT_MATCH,
                MarkerType.SCRIPT_DEVIATION,
            )
            assert result.color in (EDLColor.Green, EDLColor.Magenta)
            assert result.metadata is not None
