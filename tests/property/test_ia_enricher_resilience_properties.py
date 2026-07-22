"""Property-based tests para resiliencia del IAEnricher ante errores de backend.

**Validates: Requirements 6.8**

Verifica que:
- Cuando el backend lanza BackendConnectionError o BackendTimeoutError,
  IAEnricher NO propaga la excepción y retorna resultados válidos.
- compare_live_audio() retorna EnrichmentResult con metadata["backend_failure"] == True.
- process_manual_prompt() retorna MarkerEvent con nota conteniendo [ERROR] o [TIMEOUT].
- generate_ad_suggestions() retorna exactamente 3 AdSuggestion incluso con errores.
- La sesión continúa procesando segmentos subsiguientes sin detenerse.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, PropertyMock, patch

import pytest
from hypothesis import given, settings, assume
from hypothesis.strategies import (
    text,
    integers,
    lists,
    sampled_from,
)

from switch_bot.engines.script_parser import ScriptBlock, ScriptDocument
from switch_bot.ia.backend_base import (
    BackendConnectionError,
    BackendTimeoutError,
    IABackend,
)
from switch_bot.ia.enrichment_result import EnrichmentResult
from switch_bot.ia.ia_enricher import IAEnricher, MarkerEvent, AdSuggestion
from switch_bot.models.enums import EDLColor, MarkerType, SourceOrigin
from switch_bot.models.timecode import SMPTETimecode


# --- Strategies ---

# Texto no vacío para transcripciones y prompts
transcript_text = text(min_size=1, max_size=200)

# Mensajes de error variados
error_messages = text(min_size=1, max_size=100)

# Índices de bloque válidos
block_indices = integers(min_value=0, max_value=99)

# Nombres de personajes para ScriptBlock
character_names = sampled_from(["ACTOR", "PRESENTADOR", "INVITADO", "REPORTERO"])


# --- Helpers ---


def _make_failing_backend(error: Exception) -> IABackend:
    """Crea un mock de IABackend cuyo compute_similarity lanza un error."""
    backend = AsyncMock(spec=IABackend)
    backend.compute_similarity = AsyncMock(side_effect=error)
    backend.analyze_context = AsyncMock(side_effect=error)
    type(backend).backend_type = PropertyMock(return_value="mock")
    type(backend).is_connected = PropertyMock(return_value=True)
    return backend


def _make_script_doc(title: str = "Test Script") -> ScriptDocument:
    """Crea un ScriptDocument mínimo para testing."""
    return ScriptDocument(
        title=title,
        blocks=[
            ScriptBlock(index=0, character="ACTOR", text="Texto de prueba"),
        ],
        character_camera_map={"ACTOR": 1},
    )


def _make_context_block(
    index: int = 0, character: str = "ACTOR", text_content: str = "Texto esperado"
) -> ScriptBlock:
    """Crea un ScriptBlock de contexto para compare_live_audio."""
    return ScriptBlock(index=index, character=character, text=text_content)


def _make_timecode(minutes: int = 5, seconds: int = 30) -> SMPTETimecode:
    """Crea un SMPTETimecode válido para testing."""
    return SMPTETimecode(
        hours=0,
        minutes=min(59, max(0, minutes)),
        seconds=min(59, max(0, seconds)),
        frames=0,
        drop_frame=False,
    )


# --- Test Classes ---


class TestProperty20BackendConnectionErrorOnCompare:
    """Property 20.1: compare_live_audio() maneja BackendConnectionError sin propagar.

    **Validates: Requirements 6.8**

    FOR ALL transcripciones y bloques de contexto,
    WHEN compute_similarity() lanza BackendConnectionError,
    THEN compare_live_audio() retorna un EnrichmentResult válido
    con metadata["backend_failure"] == True (no lanza excepción).
    """

    @given(transcript=transcript_text, error_msg=error_messages)
    def test_connection_error_returns_valid_result(
        self, transcript: str, error_msg: str
    ) -> None:
        """BackendConnectionError produce EnrichmentResult con backend_failure=True."""
        error = BackendConnectionError(error_msg)
        backend = _make_failing_backend(error)
        script_doc = _make_script_doc()
        enricher = IAEnricher(backend=backend, script_doc=script_doc)
        context = _make_context_block()

        result = asyncio.run(
            enricher.compare_live_audio(transcript=transcript, context=context)
        )

        # No lanzó excepción — tenemos un resultado válido
        assert isinstance(result, EnrichmentResult)
        assert 0.0 <= result.similarity_score <= 1.0
        assert result.metadata is not None
        assert result.metadata["backend_failure"] is True


class TestProperty20BackendTimeoutErrorOnCompare:
    """Property 20.2: compare_live_audio() maneja BackendTimeoutError sin propagar.

    **Validates: Requirements 6.8**

    FOR ALL transcripciones y bloques de contexto,
    WHEN compute_similarity() lanza BackendTimeoutError,
    THEN compare_live_audio() retorna un EnrichmentResult válido
    con metadata["backend_failure"] == True (no lanza excepción).
    """

    @given(transcript=transcript_text, error_msg=error_messages)
    def test_timeout_error_returns_valid_result(
        self, transcript: str, error_msg: str
    ) -> None:
        """BackendTimeoutError produce EnrichmentResult con backend_failure=True."""
        error = BackendTimeoutError(error_msg)
        backend = _make_failing_backend(error)
        script_doc = _make_script_doc()
        enricher = IAEnricher(backend=backend, script_doc=script_doc)
        context = _make_context_block()

        result = asyncio.run(
            enricher.compare_live_audio(transcript=transcript, context=context)
        )

        assert isinstance(result, EnrichmentResult)
        assert 0.0 <= result.similarity_score <= 1.0
        assert result.metadata is not None
        assert result.metadata["backend_failure"] is True


class TestProperty20ConnectionErrorOnManualPrompt:
    """Property 20.3: process_manual_prompt() maneja BackendConnectionError.

    **Validates: Requirements 6.8**

    FOR ALL prompts del operador,
    WHEN analyze_context() lanza BackendConnectionError,
    THEN process_manual_prompt() retorna un MarkerEvent válido
    con nota conteniendo [ERROR] (no lanza excepción).
    """

    @given(prompt=transcript_text)
    def test_connection_error_returns_marker_with_error_tag(
        self, prompt: str
    ) -> None:
        """BackendConnectionError en prompt produce MarkerEvent con [ERROR]."""
        error = BackendConnectionError("connection lost")
        backend = _make_failing_backend(error)
        script_doc = _make_script_doc()
        enricher = IAEnricher(backend=backend, script_doc=script_doc)
        tc = _make_timecode()

        result = asyncio.run(
            enricher.process_manual_prompt(prompt=prompt, tc=tc)
        )

        assert isinstance(result, MarkerEvent)
        assert "[ERROR]" in result.note
        assert result.marker_type == MarkerType.AI_PROMPT
        assert result.color == EDLColor.Magenta


class TestProperty20TimeoutErrorOnManualPrompt:
    """Property 20.4: process_manual_prompt() maneja asyncio.TimeoutError.

    **Validates: Requirements 6.8**

    FOR ALL prompts del operador,
    WHEN analyze_context() excede el timeout (asyncio.TimeoutError),
    THEN process_manual_prompt() retorna un MarkerEvent válido
    con nota conteniendo [TIMEOUT] (no lanza excepción).
    """

    @given(prompt=transcript_text)
    def test_timeout_error_returns_marker_with_timeout_tag(
        self, prompt: str
    ) -> None:
        """Timeout en prompt produce MarkerEvent con [TIMEOUT]."""
        # asyncio.TimeoutError is raised by asyncio.wait_for
        backend = AsyncMock(spec=IABackend)
        # analyze_context never returns (simulates infinite hang triggering timeout)
        backend.analyze_context = AsyncMock(side_effect=asyncio.TimeoutError())
        type(backend).backend_type = PropertyMock(return_value="mock")
        type(backend).is_connected = PropertyMock(return_value=True)

        script_doc = _make_script_doc()
        enricher = IAEnricher(backend=backend, script_doc=script_doc)
        tc = _make_timecode()

        result = asyncio.run(
            enricher.process_manual_prompt(prompt=prompt, tc=tc)
        )

        assert isinstance(result, MarkerEvent)
        assert "[TIMEOUT]" in result.note
        assert result.marker_type == MarkerType.AI_PROMPT
        assert result.color == EDLColor.Magenta


class TestProperty20AdSuggestionsResilient:
    """Property 20.5: generate_ad_suggestions() retorna 3 sugerencias pese a errores.

    **Validates: Requirements 6.8**

    WHEN analyze_context() lanza BackendConnectionError para todas las sugerencias,
    THEN generate_ad_suggestions() aún retorna exactamente 3 AdSuggestion
    sin propagar excepciones.
    """

    @given(error_msg=error_messages)
    def test_ad_suggestions_returns_three_despite_errors(
        self, error_msg: str
    ) -> None:
        """Backend errors no impiden la generación de 3 sugerencias."""
        error = BackendConnectionError(error_msg)
        backend = AsyncMock(spec=IABackend)
        backend.analyze_context = AsyncMock(side_effect=error)
        type(backend).backend_type = PropertyMock(return_value="mock")
        type(backend).is_connected = PropertyMock(return_value=True)

        script_doc = _make_script_doc()
        enricher = IAEnricher(backend=backend, script_doc=script_doc)

        # Usar un archivo de log vacío (no existente) para forzar defaults
        session_log = Path("/tmp/nonexistent_session_log.jsonl")

        result = asyncio.run(
            enricher.generate_ad_suggestions(
                session_log=session_log, script=script_doc
            )
        )

        assert isinstance(result, list)
        assert len(result) == 3
        for suggestion in result:
            assert isinstance(suggestion, AdSuggestion)
            assert isinstance(suggestion.tc_in, SMPTETimecode)
            assert isinstance(suggestion.tc_out, SMPTETimecode)
            assert isinstance(suggestion.text, str)
            assert len(suggestion.text) > 0


class TestProperty20SessionContinuesAfterErrors:
    """Property 20.6: La sesión continúa procesando segmentos tras errores de backend.

    **Validates: Requirements 6.8**

    FOR ALL secuencias de llamadas a compare_live_audio donde algunas fallan,
    THEN todas las llamadas retornan resultados sin detenerse.
    Verifica que múltiples llamadas consecutivas donde el backend falla
    siguen retornando resultados válidos.
    """

    @given(
        num_calls=integers(min_value=3, max_value=10),
        transcript=transcript_text,
    )
    def test_multiple_calls_all_return_results(
        self, num_calls: int, transcript: str
    ) -> None:
        """Múltiples llamadas con errores de backend todas retornan resultados."""
        # Backend que alterna entre éxito y error
        call_count = 0
        results_collected: list[EnrichmentResult] = []

        backend = AsyncMock(spec=IABackend)
        type(backend).backend_type = PropertyMock(return_value="mock")
        type(backend).is_connected = PropertyMock(return_value=True)

        # side_effect alterna: error, éxito, error, éxito...
        def alternating_side_effect(text_a: str, text_b: str):
            nonlocal call_count
            call_count += 1
            if call_count % 2 == 1:
                raise BackendConnectionError(f"error call {call_count}")
            return 0.85

        backend.compute_similarity = AsyncMock(
            side_effect=alternating_side_effect
        )

        script_doc = _make_script_doc()
        enricher = IAEnricher(backend=backend, script_doc=script_doc)

        async def run_multiple():
            for i in range(num_calls):
                context = _make_context_block(index=i)
                result = await enricher.compare_live_audio(
                    transcript=transcript, context=context
                )
                results_collected.append(result)

        asyncio.run(run_multiple())

        # Todas las llamadas produjeron resultado (sin excepción propagada)
        assert len(results_collected) == num_calls
        for result in results_collected:
            assert isinstance(result, EnrichmentResult)
            assert 0.0 <= result.similarity_score <= 1.0
