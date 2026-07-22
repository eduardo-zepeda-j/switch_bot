"""Property-based tests para sugerencias publicitarias — restricciones de formato.

**Validates: Requirements 17.2, 17.3**

Verifica que:
- generate_ad_suggestions() SIEMPRE retorna exactamente 3 objetos AdSuggestion (Req 17.2)
- Cada sugerencia tiene tc_in < tc_out (tc_out posterior a tc_in) (Req 17.3)
- Cada sugerencia tiene una duración entre 15-30 segundos (Req 17.2):
  a 30fps eso equivale a 450-900 frames
- Cada sugerencia tiene SMPTETimecode válidos para tc_in y tc_out (Req 17.3)
- Cada sugerencia tiene texto no vacío (Req 17.2)
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, PropertyMock

import pytest
from hypothesis import given, settings, assume
from hypothesis.strategies import (
    booleans,
    integers,
    text,
    lists,
    sampled_from,
    composite,
    just,
)

from switch_bot.engines.script_parser import ScriptBlock, ScriptDocument
from switch_bot.ia.backend_base import (
    BackendConnectionError,
    BackendTimeoutError,
    IABackend,
)
from switch_bot.ia.ia_enricher import IAEnricher, AdSuggestion
from switch_bot.models.timecode import SMPTETimecode


# --- Strategies ---

# Texto generado por el backend (simula respuesta de IA)
ad_text_responses = text(min_size=5, max_size=200)

# Títulos de guión variados
script_titles = text(min_size=1, max_size=50)

# Nombres de personajes
character_names = sampled_from(["ACTOR", "PRESENTADOR", "INVITADO", "REPORTERO"])


@composite
def script_match_entries(draw, min_entries: int = 1, max_entries: int = 10):
    """Genera listas de entradas de log con marker_type SCRIPT_MATCH.

    Produce timecodes válidos espaciados para simular un log de sesión real.
    """
    num = draw(integers(min_value=min_entries, max_value=max_entries))
    entries = []
    for i in range(num):
        # Timecodes espaciados a lo largo de una sesión de ~1 hora
        minutes = min(59, 5 + (i * 5))
        seconds = draw(integers(min_value=0, max_value=59))
        frames = draw(integers(min_value=0, max_value=29))
        tc = f"00:{minutes:02d}:{seconds:02d}:{frames:02d}"
        character = draw(character_names)
        entries.append({
            "marker_type": "SCRIPT_MATCH",
            "tc": tc,
            "detected_text": f"Texto detectado {i}",
            "character": character,
            "note": f"Match en bloque {i}",
        })
    return entries


@composite
def session_logs_with_matches(draw):
    """Genera un log de sesión completo con entradas SCRIPT_MATCH."""
    entries = draw(script_match_entries(min_entries=3, max_entries=15))
    return entries


# --- Helpers ---


def _make_mock_backend(ad_text: str = "Espacio publicitario sugerido") -> IABackend:
    """Crea un mock de IABackend que retorna texto fijo para analyze_context."""
    backend = AsyncMock(spec=IABackend)
    backend.analyze_context = AsyncMock(return_value=ad_text)
    type(backend).backend_type = PropertyMock(return_value="mock")
    type(backend).is_connected = PropertyMock(return_value=True)
    return backend


def _make_failing_backend() -> IABackend:
    """Crea un mock de IABackend cuyo analyze_context siempre falla."""
    backend = AsyncMock(spec=IABackend)
    backend.analyze_context = AsyncMock(
        side_effect=BackendConnectionError("connection lost")
    )
    type(backend).backend_type = PropertyMock(return_value="mock")
    type(backend).is_connected = PropertyMock(return_value=True)
    return backend


def _make_script_doc(title: str = "Test Script") -> ScriptDocument:
    """Crea un ScriptDocument mínimo para testing."""
    return ScriptDocument(
        title=title,
        blocks=[
            ScriptBlock(index=0, character="ACTOR", text="Texto de prueba"),
            ScriptBlock(index=1, character="PRESENTADOR", text="Segunda línea"),
        ],
        character_camera_map={"ACTOR": 1, "PRESENTADOR": 2},
    )


def _write_session_log(entries: list[dict]) -> Path:
    """Escribe entradas de log a un archivo temporal .jsonl y retorna la ruta."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
    )
    for entry in entries:
        tmp.write(json.dumps(entry) + "\n")
    tmp.flush()
    tmp.close()
    return Path(tmp.name)


def _tc_to_frame_count(tc: SMPTETimecode) -> int:
    """Convierte un SMPTETimecode a conteo absoluto de frames (30fps NDF)."""
    return tc._to_frame_count(30)


# --- Test Classes ---


class TestProperty11ExactlyThreeSuggestions:
    """Property 11.1: generate_ad_suggestions() retorna exactamente 3 AdSuggestion.

    **Validates: Requirements 17.2**

    FOR ALL logs de sesión (vacíos o con entradas SCRIPT_MATCH),
    FOR ALL backends (exitosos o con errores),
    THEN generate_ad_suggestions() retorna exactamente 3 sugerencias.
    """

    @given(ad_text=ad_text_responses)
    def test_empty_log_returns_three_suggestions(self, ad_text: str) -> None:
        """Con log vacío (no existente), retorna exactamente 3 sugerencias."""
        backend = _make_mock_backend(ad_text)
        script_doc = _make_script_doc()
        enricher = IAEnricher(backend=backend, script_doc=script_doc)

        session_log = Path("/tmp/nonexistent_test_log_property11.jsonl")

        result = asyncio.run(
            enricher.generate_ad_suggestions(
                session_log=session_log, script=script_doc
            )
        )

        assert len(result) == 3

    @given(log_entries=session_logs_with_matches())
    def test_log_with_matches_returns_three_suggestions(
        self, log_entries: list[dict]
    ) -> None:
        """Con log que contiene entradas SCRIPT_MATCH, retorna exactamente 3."""
        backend = _make_mock_backend("Texto publicitario generado")
        script_doc = _make_script_doc()
        enricher = IAEnricher(backend=backend, script_doc=script_doc)

        session_log = _write_session_log(log_entries)
        try:
            result = asyncio.run(
                enricher.generate_ad_suggestions(
                    session_log=session_log, script=script_doc
                )
            )
            assert len(result) == 3
        finally:
            session_log.unlink(missing_ok=True)

    @given(log_entries=session_logs_with_matches())
    def test_failing_backend_returns_three_suggestions(
        self, log_entries: list[dict]
    ) -> None:
        """Con backend que falla, aún retorna exactamente 3 sugerencias."""
        backend = _make_failing_backend()
        script_doc = _make_script_doc()
        enricher = IAEnricher(backend=backend, script_doc=script_doc)

        session_log = _write_session_log(log_entries)
        try:
            result = asyncio.run(
                enricher.generate_ad_suggestions(
                    session_log=session_log, script=script_doc
                )
            )
            assert len(result) == 3
        finally:
            session_log.unlink(missing_ok=True)


class TestProperty11TcInBeforeTcOut:
    """Property 11.2: Cada sugerencia tiene tc_in < tc_out.

    **Validates: Requirements 17.3**

    FOR ALL sugerencias generadas,
    THEN tc_in debe preceder estrictamente a tc_out en frames absolutos.
    """

    @given(ad_text=ad_text_responses)
    def test_empty_log_tc_in_before_tc_out(self, ad_text: str) -> None:
        """Con log vacío, tc_in < tc_out para todas las sugerencias."""
        backend = _make_mock_backend(ad_text)
        script_doc = _make_script_doc()
        enricher = IAEnricher(backend=backend, script_doc=script_doc)

        session_log = Path("/tmp/nonexistent_test_log_property11_tc.jsonl")

        result = asyncio.run(
            enricher.generate_ad_suggestions(
                session_log=session_log, script=script_doc
            )
        )

        for suggestion in result:
            frames_in = _tc_to_frame_count(suggestion.tc_in)
            frames_out = _tc_to_frame_count(suggestion.tc_out)
            assert frames_in < frames_out, (
                f"tc_in ({suggestion.tc_in.to_string()}) debe preceder a "
                f"tc_out ({suggestion.tc_out.to_string()})"
            )

    @given(log_entries=session_logs_with_matches())
    def test_log_with_matches_tc_in_before_tc_out(
        self, log_entries: list[dict]
    ) -> None:
        """Con log de sesión real, tc_in < tc_out para todas las sugerencias."""
        backend = _make_mock_backend("Ad text")
        script_doc = _make_script_doc()
        enricher = IAEnricher(backend=backend, script_doc=script_doc)

        session_log = _write_session_log(log_entries)
        try:
            result = asyncio.run(
                enricher.generate_ad_suggestions(
                    session_log=session_log, script=script_doc
                )
            )
            for suggestion in result:
                frames_in = _tc_to_frame_count(suggestion.tc_in)
                frames_out = _tc_to_frame_count(suggestion.tc_out)
                assert frames_in < frames_out
        finally:
            session_log.unlink(missing_ok=True)


class TestProperty11DurationBetween15And30Seconds:
    """Property 11.3: Cada sugerencia dura entre 15-30 segundos (450-900 frames @30fps).

    **Validates: Requirements 17.2**

    FOR ALL sugerencias generadas,
    THEN la duración (tc_out - tc_in) en frames está entre 450 y 900 (inclusive).
    """

    @given(ad_text=ad_text_responses)
    def test_empty_log_duration_in_range(self, ad_text: str) -> None:
        """Con log vacío, duración de cada sugerencia entre 15-30 segundos."""
        backend = _make_mock_backend(ad_text)
        script_doc = _make_script_doc()
        enricher = IAEnricher(backend=backend, script_doc=script_doc)

        session_log = Path("/tmp/nonexistent_test_log_property11_dur.jsonl")

        result = asyncio.run(
            enricher.generate_ad_suggestions(
                session_log=session_log, script=script_doc
            )
        )

        for suggestion in result:
            frames_in = _tc_to_frame_count(suggestion.tc_in)
            frames_out = _tc_to_frame_count(suggestion.tc_out)
            duration_frames = frames_out - frames_in
            assert 450 <= duration_frames <= 900, (
                f"Duración {duration_frames} frames fuera del rango 450-900. "
                f"tc_in={suggestion.tc_in.to_string()}, "
                f"tc_out={suggestion.tc_out.to_string()}"
            )

    @given(log_entries=session_logs_with_matches())
    def test_log_with_matches_duration_in_range(
        self, log_entries: list[dict]
    ) -> None:
        """Con log de sesión real, duración de cada sugerencia entre 15-30s."""
        backend = _make_mock_backend("Ad text")
        script_doc = _make_script_doc()
        enricher = IAEnricher(backend=backend, script_doc=script_doc)

        session_log = _write_session_log(log_entries)
        try:
            result = asyncio.run(
                enricher.generate_ad_suggestions(
                    session_log=session_log, script=script_doc
                )
            )
            for suggestion in result:
                frames_in = _tc_to_frame_count(suggestion.tc_in)
                frames_out = _tc_to_frame_count(suggestion.tc_out)
                duration_frames = frames_out - frames_in
                assert 450 <= duration_frames <= 900, (
                    f"Duración {duration_frames} frames fuera del rango 450-900"
                )
        finally:
            session_log.unlink(missing_ok=True)


class TestProperty11ValidSMPTETimecodes:
    """Property 11.4: tc_in y tc_out son SMPTETimecode válidos.

    **Validates: Requirements 17.3**

    FOR ALL sugerencias generadas,
    THEN tc_in y tc_out son instancias válidas de SMPTETimecode.
    """

    @given(ad_text=ad_text_responses)
    def test_empty_log_valid_timecodes(self, ad_text: str) -> None:
        """Con log vacío, tc_in y tc_out son SMPTETimecode válidos."""
        backend = _make_mock_backend(ad_text)
        script_doc = _make_script_doc()
        enricher = IAEnricher(backend=backend, script_doc=script_doc)

        session_log = Path("/tmp/nonexistent_test_log_property11_valid.jsonl")

        result = asyncio.run(
            enricher.generate_ad_suggestions(
                session_log=session_log, script=script_doc
            )
        )

        for suggestion in result:
            assert isinstance(suggestion.tc_in, SMPTETimecode)
            assert isinstance(suggestion.tc_out, SMPTETimecode)
            # Verificar que los campos están en rango válido
            assert 0 <= suggestion.tc_in.hours <= 23
            assert 0 <= suggestion.tc_in.minutes <= 59
            assert 0 <= suggestion.tc_in.seconds <= 59
            assert 0 <= suggestion.tc_in.frames <= 29
            assert 0 <= suggestion.tc_out.hours <= 23
            assert 0 <= suggestion.tc_out.minutes <= 59
            assert 0 <= suggestion.tc_out.seconds <= 59
            assert 0 <= suggestion.tc_out.frames <= 29

    @given(log_entries=session_logs_with_matches())
    def test_log_with_matches_valid_timecodes(
        self, log_entries: list[dict]
    ) -> None:
        """Con log de sesión real, tc_in y tc_out son SMPTETimecode válidos."""
        backend = _make_mock_backend("Ad text")
        script_doc = _make_script_doc()
        enricher = IAEnricher(backend=backend, script_doc=script_doc)

        session_log = _write_session_log(log_entries)
        try:
            result = asyncio.run(
                enricher.generate_ad_suggestions(
                    session_log=session_log, script=script_doc
                )
            )
            for suggestion in result:
                assert isinstance(suggestion.tc_in, SMPTETimecode)
                assert isinstance(suggestion.tc_out, SMPTETimecode)
                # Verificar serialización a string válido
                tc_in_str = suggestion.tc_in.to_string()
                tc_out_str = suggestion.tc_out.to_string()
                # Verificar que se puede parsear de vuelta
                parsed_in = SMPTETimecode.from_string(tc_in_str)
                parsed_out = SMPTETimecode.from_string(tc_out_str)
                assert parsed_in == suggestion.tc_in
                assert parsed_out == suggestion.tc_out
        finally:
            session_log.unlink(missing_ok=True)


class TestProperty11NonEmptyText:
    """Property 11.5: Cada sugerencia tiene texto no vacío.

    **Validates: Requirements 17.2**

    FOR ALL sugerencias generadas,
    THEN el campo text es un string no vacío.
    """

    @given(ad_text=ad_text_responses)
    def test_empty_log_non_empty_text(self, ad_text: str) -> None:
        """Con log vacío y backend exitoso, cada sugerencia tiene texto."""
        backend = _make_mock_backend(ad_text)
        script_doc = _make_script_doc()
        enricher = IAEnricher(backend=backend, script_doc=script_doc)

        session_log = Path("/tmp/nonexistent_test_log_property11_text.jsonl")

        result = asyncio.run(
            enricher.generate_ad_suggestions(
                session_log=session_log, script=script_doc
            )
        )

        for suggestion in result:
            assert isinstance(suggestion.text, str)
            assert len(suggestion.text) > 0

    @given(log_entries=session_logs_with_matches())
    def test_failing_backend_non_empty_text(
        self, log_entries: list[dict]
    ) -> None:
        """Con backend que falla, el fallback produce texto no vacío."""
        backend = _make_failing_backend()
        script_doc = _make_script_doc()
        enricher = IAEnricher(backend=backend, script_doc=script_doc)

        session_log = _write_session_log(log_entries)
        try:
            result = asyncio.run(
                enricher.generate_ad_suggestions(
                    session_log=session_log, script=script_doc
                )
            )
            for suggestion in result:
                assert isinstance(suggestion.text, str)
                assert len(suggestion.text) > 0
        finally:
            session_log.unlink(missing_ok=True)

    @given(ad_text=ad_text_responses)
    def test_successful_backend_non_empty_text(self, ad_text: str) -> None:
        """Con backend exitoso, el texto generado no está vacío."""
        assume(len(ad_text.strip()) > 0)
        backend = _make_mock_backend(ad_text)
        script_doc = _make_script_doc()
        enricher = IAEnricher(backend=backend, script_doc=script_doc)

        session_log = Path("/tmp/nonexistent_test_log_property11_stext.jsonl")

        result = asyncio.run(
            enricher.generate_ad_suggestions(
                session_log=session_log, script=script_doc
            )
        )

        for suggestion in result:
            assert isinstance(suggestion.text, str)
            assert len(suggestion.text) > 0
