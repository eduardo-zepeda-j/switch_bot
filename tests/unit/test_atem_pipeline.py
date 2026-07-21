"""Tests unitarios para ATEMPipeline.

Valida el comportamiento del pipeline ATEM con conexiones mockeadas,
cubriendo: inicialización, execute(), update_tally(), is_healthy(),
y manejo de errores.

Requisitos: 10.1, 10.2, 10.3, 10.4
"""

from __future__ import annotations

import asyncio
import inspect
import threading
from unittest.mock import MagicMock, patch

import pytest

from switch_bot.models.config import SystemConfig
from switch_bot.models.enums import EDLColor, MarkerType, SourceOrigin
from switch_bot.models.payload import EnrichedPayload
from switch_bot.models.timecode import SMPTETimecode
from switch_bot.pipelines.atem_pipeline import ATEMPipeline


@pytest.fixture
def config() -> SystemConfig:
    """Configuración base para tests."""
    return SystemConfig(
        atem_ip="192.168.1.100",
        fps=29.97,
    )


@pytest.fixture
def sample_payload() -> EnrichedPayload:
    """Payload de ejemplo para tests."""
    return EnrichedPayload(
        personaje="Actor1",
        target_cam=2,
        marker_type=MarkerType.MANUAL_NOTE,
        note="Test switch",
        tc_in=SMPTETimecode(hours=1, minutes=0, seconds=0, frames=0, drop_frame=False),
        source_origin=SourceOrigin.AI,
        color=EDLColor.Blue,
    )


class TestATEMPipelineInit:
    """Tests de inicialización del ATEMPipeline."""

    def test_initial_state_not_connected(self, config: SystemConfig) -> None:
        """El pipeline inicia desconectado y no saludable."""
        pipeline = ATEMPipeline(
            atem_ip="192.168.1.100",
            config=config,
        )
        assert not pipeline.connected
        assert not pipeline.is_healthy()
        assert pipeline.active_source == 0

    def test_accepts_tally_callback(self, config: SystemConfig) -> None:
        """El pipeline acepta un callback de tally opcional."""
        callback = MagicMock()
        pipeline = ATEMPipeline(
            atem_ip="192.168.1.100",
            config=config,
            tally_callback=callback,
        )
        assert pipeline._tally_callback is callback


class TestATEMPipelineExecute:
    """Tests de execute() para conmutación de fuentes."""

    @pytest.mark.asyncio
    async def test_execute_raises_when_not_connected(
        self, config: SystemConfig, sample_payload: EnrichedPayload
    ) -> None:
        """execute() lanza RuntimeError si no está conectado."""
        pipeline = ATEMPipeline(
            atem_ip="192.168.1.100",
            config=config,
        )
        with pytest.raises(RuntimeError, match="not connected"):
            await pipeline.execute(sample_payload)

    @pytest.mark.asyncio
    async def test_execute_switches_source(
        self, config: SystemConfig, sample_payload: EnrichedPayload
    ) -> None:
        """execute() llama setProgramInputVideoSource con ME 0 y source index."""
        pipeline = ATEMPipeline(
            atem_ip="192.168.1.100",
            config=config,
        )
        # Simulate connected state
        mock_atem = MagicMock()
        pipeline._atem = mock_atem
        pipeline._connected = True
        pipeline._healthy = True

        await pipeline.execute(sample_payload)

        mock_atem.setProgramInputVideoSource.assert_called_once_with(
            0, sample_payload.target_cam
        )

    @pytest.mark.asyncio
    async def test_execute_updates_active_source(
        self, config: SystemConfig, sample_payload: EnrichedPayload
    ) -> None:
        """execute() actualiza active_source tras conmutación exitosa."""
        pipeline = ATEMPipeline(
            atem_ip="192.168.1.100",
            config=config,
        )
        mock_atem = MagicMock()
        pipeline._atem = mock_atem
        pipeline._connected = True
        pipeline._healthy = True

        await pipeline.execute(sample_payload)

        assert pipeline.active_source == sample_payload.target_cam

    @pytest.mark.asyncio
    async def test_execute_marks_unhealthy_on_failure(
        self, config: SystemConfig, sample_payload: EnrichedPayload
    ) -> None:
        """execute() marca el pipeline como no saludable si falla el comando."""
        pipeline = ATEMPipeline(
            atem_ip="192.168.1.100",
            config=config,
        )
        mock_atem = MagicMock()
        mock_atem.setProgramInputVideoSource.side_effect = OSError("Socket error")
        pipeline._atem = mock_atem
        pipeline._connected = True
        pipeline._healthy = True

        # Should not raise (logged internally), but marks unhealthy
        await pipeline.execute(sample_payload)

        assert not pipeline.is_healthy()


class TestATEMPipelineUpdateTally:
    """Tests de update_tally() para indicador visual."""

    def test_update_tally_sets_active_source(self, config: SystemConfig) -> None:
        """update_tally() actualiza la fuente activa."""
        pipeline = ATEMPipeline(
            atem_ip="192.168.1.100",
            config=config,
        )
        pipeline.update_tally(3)
        assert pipeline.active_source == 3

    def test_update_tally_triggers_callback(self, config: SystemConfig) -> None:
        """update_tally() invoca el callback de tally con la fuente."""
        callback = MagicMock()
        pipeline = ATEMPipeline(
            atem_ip="192.168.1.100",
            config=config,
            tally_callback=callback,
        )
        pipeline.update_tally(2)
        callback.assert_called_once_with(2)

    def test_update_tally_no_crash_without_callback(
        self, config: SystemConfig
    ) -> None:
        """update_tally() funciona sin callback configurado."""
        pipeline = ATEMPipeline(
            atem_ip="192.168.1.100",
            config=config,
        )
        # Should not raise
        pipeline.update_tally(1)
        assert pipeline.active_source == 1

    def test_update_tally_handles_callback_error(
        self, config: SystemConfig
    ) -> None:
        """update_tally() no propaga excepciones del callback."""
        callback = MagicMock(side_effect=RuntimeError("GUI error"))
        pipeline = ATEMPipeline(
            atem_ip="192.168.1.100",
            config=config,
            tally_callback=callback,
        )
        # Should not raise
        pipeline.update_tally(4)
        assert pipeline.active_source == 4


class TestATEMPipelineHealthy:
    """Tests de is_healthy() para verificar estado del pipeline."""

    def test_initially_not_healthy(self, config: SystemConfig) -> None:
        """El pipeline inicia como no saludable."""
        pipeline = ATEMPipeline(
            atem_ip="192.168.1.100",
            config=config,
        )
        assert not pipeline.is_healthy()

    def test_healthy_after_simulated_connection(self, config: SystemConfig) -> None:
        """is_healthy() retorna True cuando está conectado."""
        pipeline = ATEMPipeline(
            atem_ip="192.168.1.100",
            config=config,
        )
        pipeline._connected = True
        pipeline._healthy = True
        assert pipeline.is_healthy()


class TestATEMPipelineWorkerThread:
    """Tests del worker thread dedicado."""

    def test_start_creates_worker_thread(self, config: SystemConfig) -> None:
        """start() crea el worker thread con nombre apropiado."""
        with patch("switch_bot.pipelines.atem_pipeline.ATEMPipeline._worker_run"):
            with patch("switch_bot.pipelines.atem_pipeline.ATEMPipeline._tally_loop"):
                pipeline = ATEMPipeline(
                    atem_ip="192.168.1.100",
                    config=config,
                )
                pipeline.start()

                assert pipeline._worker_thread is not None
                assert pipeline._worker_thread.name == "ATEMPipeline-Worker"
                assert pipeline._worker_thread.daemon is True

                assert pipeline._tally_thread is not None
                assert pipeline._tally_thread.name == "ATEMPipeline-Tally"
                assert pipeline._tally_thread.daemon is True

                pipeline.stop()

    def test_stop_signals_shutdown(self, config: SystemConfig) -> None:
        """stop() señaliza el evento de shutdown."""
        pipeline = ATEMPipeline(
            atem_ip="192.168.1.100",
            config=config,
        )
        pipeline._shutdown_event.clear()
        pipeline.stop()
        assert pipeline._shutdown_event.is_set()
        assert not pipeline.connected
        assert not pipeline.is_healthy()


class TestATEMPipelineInheritance:
    """Tests de herencia de Pipeline ABC."""

    def test_is_pipeline_subclass(self) -> None:
        """ATEMPipeline hereda de Pipeline."""
        from switch_bot.pipelines.base import Pipeline

        assert issubclass(ATEMPipeline, Pipeline)

    def test_implements_execute(self) -> None:
        """ATEMPipeline implementa execute()."""
        assert hasattr(ATEMPipeline, "execute")
        assert inspect.iscoroutinefunction(ATEMPipeline.execute)

    def test_implements_is_healthy(self) -> None:
        """ATEMPipeline implementa is_healthy()."""
        assert hasattr(ATEMPipeline, "is_healthy")
        assert callable(ATEMPipeline.is_healthy)
