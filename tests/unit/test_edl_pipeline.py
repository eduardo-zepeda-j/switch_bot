"""Tests unitarios para EDLPipeline.

Valida generación de archivos EDL CMX 3600 en tiempo real con:
- Cabecera TITLE + FCM correcta
- Numeración secuencial de eventos (3 dígitos)
- Clasificación de source_origin (Manual vs IA/Contexto)
- Duración de 1 frame por evento
- Escritura atómica con flush/fsync

Requisitos: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from switch_bot.models.config import SystemConfig
from switch_bot.models.enums import EDLColor, MarkerType, SourceOrigin
from switch_bot.models.payload import EnrichedPayload
from switch_bot.models.timecode import SMPTETimecode
from switch_bot.pipelines.edl_pipeline import (
    EDLPipeline,
    SOURCE_ORIGIN_CLASSIFICATION,
)
from switch_bot.serializers.edl_serializer import EDLDocument


# --- Helpers ---


def _make_payload(
    personaje: str = "Ana",
    target_cam: int = 1,
    marker_type: MarkerType = MarkerType.ENTRADA,
    note: str = "Test event",
    tc_hours: int = 10,
    tc_minutes: int = 30,
    tc_seconds: int = 0,
    tc_frames: int = 0,
    drop_frame: bool = True,
    source_origin: SourceOrigin = SourceOrigin.AUTO,
    color: EDLColor = EDLColor.Cyan,
) -> EnrichedPayload:
    """Crea un payload de prueba válido."""
    return EnrichedPayload(
        personaje=personaje,
        target_cam=target_cam,
        marker_type=marker_type,
        note=note,
        tc_in=SMPTETimecode(tc_hours, tc_minutes, tc_seconds, tc_frames, drop_frame=drop_frame),
        source_origin=source_origin,
        color=color,
    )


def _make_config(drop_frame: bool = True) -> SystemConfig:
    """Crea una configuración de prueba."""
    fps = 29.97 if drop_frame else 30.0
    return SystemConfig(
        video_mode="1080p29.97" if drop_frame else "1080p30",
        fps=fps,
        drop_frame=drop_frame,
    )


# --- Tests ---


class TestEDLPipelineStart:
    """Tests para inicio y configuración del pipeline EDL."""

    def test_start_creates_output_directory(self, tmp_path: Path) -> None:
        """start() crea el directorio de salida si no existe."""
        output_dir = tmp_path / "nested" / "edl_output"
        pipeline = EDLPipeline(output_dir=output_dir, config=_make_config())

        pipeline.start(session_name="test_session")

        assert output_dir.exists()
        pipeline.stop()

    def test_start_creates_edl_file_with_header(self, tmp_path: Path) -> None:
        """start() crea el archivo .edl con cabecera TITLE y FCM: NON-DROP FRAME."""
        pipeline = EDLPipeline(output_dir=tmp_path, config=_make_config())
        pipeline.start(session_name="my_session")

        assert pipeline.edl_path is not None
        assert pipeline.edl_path.exists()
        assert pipeline.edl_path.name == "my_session.edl"

        # Verify header content (Req 13.1)
        content = pipeline.edl_path.read_text(encoding="utf-8")
        assert content.startswith("TITLE: my_session\n")
        assert "FCM: NON-DROP FRAME\n" in content

        pipeline.stop()

    def test_start_marks_pipeline_healthy(self, tmp_path: Path) -> None:
        """start() marca el pipeline como healthy."""
        pipeline = EDLPipeline(output_dir=tmp_path, config=_make_config())
        assert not pipeline.is_healthy()

        pipeline.start(session_name="test")
        assert pipeline.is_healthy()

        pipeline.stop()
        assert not pipeline.is_healthy()

    def test_start_auto_generates_session_name(self, tmp_path: Path) -> None:
        """start() genera nombre de sesión automático si no se proporciona."""
        pipeline = EDLPipeline(output_dir=tmp_path, config=_make_config())
        pipeline.start()

        assert pipeline.edl_path is not None
        assert pipeline.edl_path.name.startswith("session_")
        assert pipeline.edl_path.suffix == ".edl"
        pipeline.stop()


class TestEDLPipelineExecute:
    """Tests para ejecución de eventos EDL."""

    @pytest.mark.asyncio
    async def test_execute_writes_valid_edl_event(self, tmp_path: Path) -> None:
        """execute() escribe un evento EDL válido al archivo."""
        pipeline = EDLPipeline(output_dir=tmp_path, config=_make_config())
        pipeline.start(session_name="test")

        payload = _make_payload()
        await pipeline.execute(payload)

        # Read and verify EDL content
        assert pipeline.edl_path is not None
        content = pipeline.edl_path.read_text(encoding="utf-8")

        # Should contain header + event
        assert "TITLE: test" in content
        assert "FCM: NON-DROP FRAME" in content
        # Event number 001
        assert "001  001" in content
        # Color and marker type in comment line
        assert "|C:ResolveColorCyan" in content
        assert "|M:ENTRADA" in content
        assert "|D:1" in content

        pipeline.stop()

    @pytest.mark.asyncio
    async def test_events_numbered_sequentially(self, tmp_path: Path) -> None:
        """Eventos se numeran secuencialmente desde 001 (Req 13.6)."""
        pipeline = EDLPipeline(output_dir=tmp_path, config=_make_config())
        pipeline.start(session_name="test")

        for i in range(5):
            payload = _make_payload(tc_frames=i * 5)
            await pipeline.execute(payload)

        # Verify sequential numbering
        assert pipeline.edl_path is not None
        content = pipeline.edl_path.read_text(encoding="utf-8")

        # Parse back with EDLDocument to validate
        doc = EDLDocument.parse(content)
        assert len(doc.events) == 5

        for i, event in enumerate(doc.events, start=1):
            assert event.event_number == i

        pipeline.stop()

    @pytest.mark.asyncio
    async def test_event_is_one_frame_duration(self, tmp_path: Path) -> None:
        """Cada evento tiene duración de 1 frame (Req 13.4)."""
        pipeline = EDLPipeline(output_dir=tmp_path, config=_make_config())
        pipeline.start(session_name="test")

        payload = _make_payload(tc_hours=1, tc_minutes=0, tc_seconds=10, tc_frames=15)
        await pipeline.execute(payload)

        # Parse and verify 1 frame duration
        assert pipeline.edl_path is not None
        content = pipeline.edl_path.read_text(encoding="utf-8")
        doc = EDLDocument.parse(content)

        assert len(doc.events) == 1
        event = doc.events[0]

        # tc_out should be tc_in + 1 frame
        assert event.tc_in.frames == 15
        assert event.tc_out.frames == 16
        assert event.duration == 1

        pipeline.stop()

    @pytest.mark.asyncio
    async def test_classification_manual(self, tmp_path: Path) -> None:
        """SourceOrigin.MANUAL se clasifica como 'Manual' (Req 13.2)."""
        pipeline = EDLPipeline(output_dir=tmp_path, config=_make_config())
        pipeline.start(session_name="test")

        payload = _make_payload(
            source_origin=SourceOrigin.MANUAL,
            marker_type=MarkerType.MANUAL_NOTE,
            color=EDLColor.Red,
        )
        await pipeline.execute(payload)

        # Verify classification via internal function
        classification = pipeline._classify_source(SourceOrigin.MANUAL)
        assert classification == "Manual"

        pipeline.stop()

    @pytest.mark.asyncio
    async def test_classification_ia_contexto(self, tmp_path: Path) -> None:
        """SourceOrigin.AI se clasifica como 'IA/Contexto' (Req 13.2)."""
        pipeline = EDLPipeline(output_dir=tmp_path, config=_make_config())
        pipeline.start(session_name="test")

        payload = _make_payload(
            source_origin=SourceOrigin.AI,
            marker_type=MarkerType.AI_PROMPT,
            color=EDLColor.Magenta,
        )
        await pipeline.execute(payload)

        classification = pipeline._classify_source(SourceOrigin.AI)
        assert classification == "IA/Contexto"

        pipeline.stop()

    @pytest.mark.asyncio
    async def test_classification_auto(self, tmp_path: Path) -> None:
        """SourceOrigin.AUTO se clasifica como 'AUTO' (Req 13.2)."""
        pipeline = EDLPipeline(output_dir=tmp_path, config=_make_config())

        classification = pipeline._classify_source(SourceOrigin.AUTO)
        assert classification == "AUTO"

    @pytest.mark.asyncio
    async def test_classification_anomaly(self, tmp_path: Path) -> None:
        """SourceOrigin.ANOMALY se clasifica como 'Anomalía' (Req 13.2)."""
        pipeline = EDLPipeline(output_dir=tmp_path, config=_make_config())

        classification = pipeline._classify_source(SourceOrigin.ANOMALY)
        assert classification == "Anomalía"

    @pytest.mark.asyncio
    async def test_color_assignment_red_manual_note(self, tmp_path: Path) -> None:
        """MANUAL_NOTE usa color Red (Req 13.3)."""
        pipeline = EDLPipeline(output_dir=tmp_path, config=_make_config())
        pipeline.start(session_name="test")

        payload = _make_payload(
            source_origin=SourceOrigin.MANUAL,
            marker_type=MarkerType.MANUAL_NOTE,
            color=EDLColor.Red,
        )
        await pipeline.execute(payload)

        assert pipeline.edl_path is not None
        content = pipeline.edl_path.read_text(encoding="utf-8")
        assert "|C:ResolveColorRed" in content
        assert "|M:MANUAL_NOTE" in content

        pipeline.stop()

    @pytest.mark.asyncio
    async def test_color_assignment_green_script_match(self, tmp_path: Path) -> None:
        """SCRIPT_MATCH usa color Green (Req 13.3)."""
        pipeline = EDLPipeline(output_dir=tmp_path, config=_make_config())
        pipeline.start(session_name="test")

        payload = _make_payload(
            source_origin=SourceOrigin.AI,
            marker_type=MarkerType.SCRIPT_MATCH,
            color=EDLColor.Green,
        )
        await pipeline.execute(payload)

        assert pipeline.edl_path is not None
        content = pipeline.edl_path.read_text(encoding="utf-8")
        assert "|C:ResolveColorGreen" in content
        assert "|M:SCRIPT_MATCH" in content

        pipeline.stop()

    @pytest.mark.asyncio
    async def test_color_assignment_magenta_ai_prompt(self, tmp_path: Path) -> None:
        """AI_PROMPT usa color Magenta (Req 13.3)."""
        pipeline = EDLPipeline(output_dir=tmp_path, config=_make_config())
        pipeline.start(session_name="test")

        payload = _make_payload(
            source_origin=SourceOrigin.AI,
            marker_type=MarkerType.AI_PROMPT,
            color=EDLColor.Magenta,
        )
        await pipeline.execute(payload)

        assert pipeline.edl_path is not None
        content = pipeline.edl_path.read_text(encoding="utf-8")
        assert "|C:ResolveColorMagenta" in content
        assert "|M:AI_PROMPT" in content

        pipeline.stop()

    @pytest.mark.asyncio
    async def test_execute_without_start_raises(self, tmp_path: Path) -> None:
        """execute() sin start() previo lanza RuntimeError."""
        pipeline = EDLPipeline(output_dir=tmp_path, config=_make_config())

        with pytest.raises(RuntimeError, match="not started"):
            await pipeline.execute(_make_payload())

    @pytest.mark.asyncio
    async def test_execute_increments_event_count(self, tmp_path: Path) -> None:
        """execute() incrementa el contador de eventos."""
        pipeline = EDLPipeline(output_dir=tmp_path, config=_make_config())
        pipeline.start(session_name="test")

        assert pipeline.event_count == 0

        await pipeline.execute(_make_payload())
        assert pipeline.event_count == 1

        await pipeline.execute(_make_payload(tc_frames=5))
        assert pipeline.event_count == 2

        pipeline.stop()

    @pytest.mark.asyncio
    async def test_edl_document_in_memory_consistent(self, tmp_path: Path) -> None:
        """El EDLDocument en memoria es consistente con el archivo en disco."""
        pipeline = EDLPipeline(output_dir=tmp_path, config=_make_config())
        pipeline.start(session_name="test")

        for i in range(3):
            await pipeline.execute(_make_payload(tc_frames=i * 5))

        # In-memory document
        assert pipeline.edl_document is not None
        assert len(pipeline.edl_document.events) == 3

        # Parse from disk
        assert pipeline.edl_path is not None
        content = pipeline.edl_path.read_text(encoding="utf-8")
        parsed = EDLDocument.parse(content)

        assert len(parsed.events) == 3
        assert parsed.title == "test"
        assert parsed.fcm == "NON-DROP FRAME"

        pipeline.stop()


class TestEDLPipelineAtomicWrites:
    """Tests para escritura atómica con flush/fsync (Req 13.5)."""

    @pytest.mark.asyncio
    async def test_fsync_called_on_execute(self, tmp_path: Path) -> None:
        """flush/fsync se llama durante execute() para persistencia."""
        pipeline = EDLPipeline(output_dir=tmp_path, config=_make_config())
        pipeline.start(session_name="test")

        with patch("switch_bot.pipelines.edl_pipeline.os.fsync") as mock_fsync:
            await pipeline.execute(_make_payload())

            # fsync should be called at least once during execute
            assert mock_fsync.called

        pipeline.stop()

    @pytest.mark.asyncio
    async def test_fsync_called_on_start(self, tmp_path: Path) -> None:
        """flush/fsync se llama durante start() al escribir la cabecera."""
        with patch("switch_bot.pipelines.edl_pipeline.os.fsync") as mock_fsync:
            pipeline = EDLPipeline(output_dir=tmp_path, config=_make_config())
            pipeline.start(session_name="test")

            # fsync should be called for the header write
            assert mock_fsync.called

            pipeline.stop()

    @pytest.mark.asyncio
    async def test_fsync_called_on_stop(self, tmp_path: Path) -> None:
        """flush/fsync se llama durante stop() para garantizar persistencia."""
        pipeline = EDLPipeline(output_dir=tmp_path, config=_make_config())
        pipeline.start(session_name="test")

        with patch("switch_bot.pipelines.edl_pipeline.os.fsync") as mock_fsync:
            pipeline.stop()
            assert mock_fsync.called


class TestEDLPipelineStop:
    """Tests para detención del pipeline."""

    def test_stop_closes_file_and_marks_unhealthy(self, tmp_path: Path) -> None:
        """stop() cierra el archivo y marca el pipeline como no-healthy."""
        pipeline = EDLPipeline(output_dir=tmp_path, config=_make_config())
        pipeline.start(session_name="test")
        assert pipeline.is_healthy()

        pipeline.stop()
        assert not pipeline.is_healthy()

    @pytest.mark.asyncio
    async def test_generated_edl_parseable_after_stop(self, tmp_path: Path) -> None:
        """El archivo .edl generado es parseable como EDLDocument válido tras stop()."""
        pipeline = EDLPipeline(output_dir=tmp_path, config=_make_config())
        pipeline.start(session_name="test")

        await pipeline.execute(_make_payload(
            marker_type=MarkerType.ENTRADA, color=EDLColor.Cyan
        ))
        await pipeline.execute(_make_payload(
            marker_type=MarkerType.MANUAL_NOTE, color=EDLColor.Red, tc_frames=10
        ))
        await pipeline.execute(_make_payload(
            marker_type=MarkerType.AI_PROMPT, color=EDLColor.Magenta, tc_frames=20
        ))

        pipeline.stop()

        # Parse the generated EDL file
        edl_content = (tmp_path / "test.edl").read_text(encoding="utf-8")
        doc = EDLDocument.parse(edl_content)

        assert doc.title == "test"
        assert doc.fcm == "NON-DROP FRAME"
        assert len(doc.events) == 3

        # Verify event properties
        assert doc.events[0].color == EDLColor.Cyan
        assert doc.events[0].marker_type == MarkerType.ENTRADA
        assert doc.events[1].color == EDLColor.Red
        assert doc.events[1].marker_type == MarkerType.MANUAL_NOTE
        assert doc.events[2].color == EDLColor.Magenta
        assert doc.events[2].marker_type == MarkerType.AI_PROMPT


class TestSourceOriginClassification:
    """Tests para la constante SOURCE_ORIGIN_CLASSIFICATION."""

    def test_all_source_origins_have_classification(self) -> None:
        """Todos los SourceOrigin tienen una clasificación definida."""
        for origin in SourceOrigin:
            assert origin in SOURCE_ORIGIN_CLASSIFICATION

    def test_classification_values(self) -> None:
        """Los valores de clasificación son correctos."""
        assert SOURCE_ORIGIN_CLASSIFICATION[SourceOrigin.MANUAL] == "Manual"
        assert SOURCE_ORIGIN_CLASSIFICATION[SourceOrigin.AI] == "IA/Contexto"
        assert SOURCE_ORIGIN_CLASSIFICATION[SourceOrigin.AUTO] == "AUTO"
        assert SOURCE_ORIGIN_CLASSIFICATION[SourceOrigin.ANOMALY] == "Anomalía"
