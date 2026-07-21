"""Tests unitarios para MetadataPipeline.

Valida escritura append-only .jsonl, compilación .drp en tiempo real,
y consistencia de datos ante múltiples eventos.

Requisitos: 12.1, 12.2, 12.3, 12.4
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from switch_bot.models.config import SystemConfig
from switch_bot.models.enums import EDLColor, MarkerType, SourceOrigin
from switch_bot.models.payload import EnrichedPayload
from switch_bot.models.timecode import SMPTETimecode
from switch_bot.pipelines.metadata_pipeline import MetadataPipeline
from switch_bot.serializers.drp_serializer import DRPDocument


# --- Helpers ---


def _make_payload(
    personaje: str = "Ana",
    target_cam: int = 1,
    tc_hours: int = 10,
    tc_minutes: int = 30,
    tc_seconds: int = 0,
    tc_frames: int = 0,
    drop_frame: bool = True,
) -> EnrichedPayload:
    """Crea un payload de prueba válido."""
    return EnrichedPayload(
        personaje=personaje,
        target_cam=target_cam,
        marker_type=MarkerType.ENTRADA,
        note="Test event",
        tc_in=SMPTETimecode(tc_hours, tc_minutes, tc_seconds, tc_frames, drop_frame=drop_frame),
        source_origin=SourceOrigin.AUTO,
        color=EDLColor.Cyan,
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


class TestMetadataPipelineStart:
    """Tests para inicio y configuración del pipeline."""

    def test_start_creates_output_directory(self, tmp_path: Path) -> None:
        """start() crea el directorio de salida si no existe."""
        output_dir = tmp_path / "nested" / "output"
        pipeline = MetadataPipeline(output_dir=output_dir, config=_make_config())

        pipeline.start(session_name="test_session")

        assert output_dir.exists()
        pipeline.stop()

    def test_start_creates_jsonl_file(self, tmp_path: Path) -> None:
        """start() crea el archivo .jsonl."""
        pipeline = MetadataPipeline(output_dir=tmp_path, config=_make_config())
        pipeline.start(session_name="my_session")

        assert pipeline.jsonl_path is not None
        assert pipeline.jsonl_path.exists()
        assert pipeline.jsonl_path.name == "my_session.jsonl"
        pipeline.stop()

    def test_start_creates_drp_file_with_header(self, tmp_path: Path) -> None:
        """start() crea el archivo .drp con la cabecera de configuración."""
        pipeline = MetadataPipeline(output_dir=tmp_path, config=_make_config())
        pipeline.start(session_name="my_session")

        assert pipeline.drp_path is not None
        assert pipeline.drp_path.exists()
        assert pipeline.drp_path.name == "my_session.drp"

        # DRP file should have exactly 1 line (the header)
        lines = pipeline.drp_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1

        # Header should be valid JSON with project config
        config = json.loads(lines[0])
        assert config["version"] == 1
        assert config["videoMode"] == "1080p29.97"
        assert len(config["sources"]) == 9
        assert config["sources"][0]["name"] == "Black"
        assert config["sources"][1]["name"] == "Camera 1"

        pipeline.stop()

    def test_start_marks_pipeline_healthy(self, tmp_path: Path) -> None:
        """start() marca el pipeline como healthy."""
        pipeline = MetadataPipeline(output_dir=tmp_path, config=_make_config())
        assert not pipeline.is_healthy()

        pipeline.start(session_name="test")
        assert pipeline.is_healthy()

        pipeline.stop()
        assert not pipeline.is_healthy()

    def test_start_auto_generates_session_name(self, tmp_path: Path) -> None:
        """start() genera nombre de sesión automático si no se proporciona."""
        pipeline = MetadataPipeline(output_dir=tmp_path, config=_make_config())
        pipeline.start()

        assert pipeline.jsonl_path is not None
        assert pipeline.jsonl_path.name.startswith("session_")
        assert pipeline.jsonl_path.suffix == ".jsonl"
        pipeline.stop()


class TestMetadataPipelineExecute:
    """Tests para ejecución de eventos."""

    @pytest.mark.asyncio
    async def test_execute_writes_jsonl_event(self, tmp_path: Path) -> None:
        """execute() escribe un evento JSON en el archivo .jsonl."""
        pipeline = MetadataPipeline(output_dir=tmp_path, config=_make_config())
        pipeline.start(session_name="test")

        payload = _make_payload()
        await pipeline.execute(payload)

        # Read and verify JSONL content
        assert pipeline.jsonl_path is not None
        content = pipeline.jsonl_path.read_text(encoding="utf-8").strip()
        event = json.loads(content)

        assert event["personaje"] == "Ana"
        assert event["target_cam"] == 1
        assert event["timecode"] == "10:30:00;00"
        assert event["marker_type"] == "ENTRADA"
        assert event["source_origin"] == "AUTO"
        assert event["color"] == "ResolveColorCyan"
        assert event["note"] == "Test event"
        assert event["event_number"] == 1

        pipeline.stop()

    @pytest.mark.asyncio
    async def test_execute_writes_drp_event(self, tmp_path: Path) -> None:
        """execute() agrega un evento de conmutación al archivo .drp."""
        pipeline = MetadataPipeline(output_dir=tmp_path, config=_make_config())
        pipeline.start(session_name="test")

        payload = _make_payload(target_cam=2, tc_minutes=45, tc_frames=15)
        await pipeline.execute(payload)

        # Read DRP file: should have header + 1 event = 2 lines
        assert pipeline.drp_path is not None
        lines = pipeline.drp_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2

        # Verify the switch event
        event = json.loads(lines[1])
        assert event["masterTimecode"] == "10:45:00;15"
        assert event["mixEffectBlocks"][0]["source"] == 2

        pipeline.stop()

    @pytest.mark.asyncio
    async def test_execute_multiple_events_append(self, tmp_path: Path) -> None:
        """Múltiples execute() agregan líneas al .jsonl y .drp."""
        pipeline = MetadataPipeline(output_dir=tmp_path, config=_make_config())
        pipeline.start(session_name="test")

        for i in range(5):
            payload = _make_payload(
                personaje=f"Actor{i}",
                target_cam=(i % 4) + 1,
                tc_frames=i * 5,
            )
            await pipeline.execute(payload)

        # JSONL should have 5 lines
        assert pipeline.jsonl_path is not None
        jsonl_lines = pipeline.jsonl_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(jsonl_lines) == 5

        # DRP should have 1 header + 5 events = 6 lines
        assert pipeline.drp_path is not None
        drp_lines = pipeline.drp_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(drp_lines) == 6

        # Verify event numbering
        for i, line in enumerate(jsonl_lines):
            event = json.loads(line)
            assert event["event_number"] == i + 1

        pipeline.stop()

    @pytest.mark.asyncio
    async def test_execute_increments_event_count(self, tmp_path: Path) -> None:
        """execute() incrementa el contador de eventos."""
        pipeline = MetadataPipeline(output_dir=tmp_path, config=_make_config())
        pipeline.start(session_name="test")

        assert pipeline.event_count == 0

        await pipeline.execute(_make_payload())
        assert pipeline.event_count == 1

        await pipeline.execute(_make_payload())
        assert pipeline.event_count == 2

        pipeline.stop()

    @pytest.mark.asyncio
    async def test_execute_without_start_raises(self, tmp_path: Path) -> None:
        """execute() sin start() previo lanza RuntimeError."""
        pipeline = MetadataPipeline(output_dir=tmp_path, config=_make_config())

        with pytest.raises(RuntimeError, match="not started"):
            await pipeline.execute(_make_payload())

    @pytest.mark.asyncio
    async def test_drp_file_is_valid_drp_document(self, tmp_path: Path) -> None:
        """El archivo .drp generado es parseable como DRPDocument válido."""
        pipeline = MetadataPipeline(output_dir=tmp_path, config=_make_config())
        pipeline.start(session_name="test")

        # Write several events
        for i in range(3):
            await pipeline.execute(
                _make_payload(target_cam=(i % 4) + 1, tc_frames=i * 10)
            )

        pipeline.stop()

        # Parse the generated DRP file
        drp_content = (tmp_path / "test.drp").read_text(encoding="utf-8")
        drp_doc = DRPDocument.parse(drp_content)

        assert drp_doc.config.video_mode == "1080p29.97"
        assert drp_doc.config.version == 1
        assert len(drp_doc.events) == 3

    @pytest.mark.asyncio
    async def test_non_drop_frame_timecode_format(self, tmp_path: Path) -> None:
        """Timecodes non-drop frame usan separador ':' en el DRP."""
        config = _make_config(drop_frame=False)
        pipeline = MetadataPipeline(output_dir=tmp_path, config=config)
        pipeline.start(session_name="test")

        payload = _make_payload(drop_frame=False)
        await pipeline.execute(payload)

        # DRP header should use ':' separator
        assert pipeline.drp_path is not None
        lines = pipeline.drp_path.read_text(encoding="utf-8").strip().split("\n")
        header = json.loads(lines[0])
        assert ";" not in header["masterTimecode"]
        assert ":" in header["masterTimecode"]

        pipeline.stop()


class TestMetadataPipelineStop:
    """Tests para detención del pipeline."""

    def test_stop_closes_files(self, tmp_path: Path) -> None:
        """stop() cierra los archivos y marca el pipeline como no-healthy."""
        pipeline = MetadataPipeline(output_dir=tmp_path, config=_make_config())
        pipeline.start(session_name="test")
        assert pipeline.is_healthy()

        pipeline.stop()
        assert not pipeline.is_healthy()

    @pytest.mark.asyncio
    async def test_stop_persists_all_data(self, tmp_path: Path) -> None:
        """stop() garantiza que todos los datos se persisten en disco."""
        pipeline = MetadataPipeline(output_dir=tmp_path, config=_make_config())
        pipeline.start(session_name="test")

        await pipeline.execute(_make_payload())
        await pipeline.execute(_make_payload(personaje="Bob", target_cam=3))

        pipeline.stop()

        # Verify files are readable after stop
        assert pipeline.jsonl_path is not None
        jsonl_content = pipeline.jsonl_path.read_text(encoding="utf-8").strip()
        lines = jsonl_content.split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["personaje"] == "Ana"
        assert json.loads(lines[1])["personaje"] == "Bob"
