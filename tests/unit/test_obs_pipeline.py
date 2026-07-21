"""Tests unitarios para OBSPipeline.

Valida el comportamiento del pipeline OBS con conexiones mockeadas,
cubriendo: inicialización, execute(), reconnect(), is_healthy(),
sincronización de estado y backoff exponencial.

Requisitos: 11.1, 11.2, 11.3, 11.4
"""

from __future__ import annotations

import asyncio
import inspect
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from switch_bot.models.enums import EDLColor, MarkerType, SourceOrigin
from switch_bot.models.payload import EnrichedPayload
from switch_bot.models.timecode import SMPTETimecode
from switch_bot.pipelines.obs_pipeline import (
    OBSPipeline,
    _BACKOFF_MULTIPLIER,
    _INITIAL_BACKOFF_S,
    _MAX_BACKOFF_S,
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


@pytest.fixture
def obs_pipeline() -> OBSPipeline:
    """Pipeline OBS para tests."""
    return OBSPipeline(ws_url="ws://localhost:4455")


class TestOBSPipelineInit:
    """Tests de inicialización del OBSPipeline."""

    def test_initial_state_not_connected(self) -> None:
        """El pipeline inicia desconectado y no saludable."""
        pipeline = OBSPipeline(ws_url="ws://localhost:4455")
        assert not pipeline.connected
        assert not pipeline.is_healthy()
        assert pipeline.last_scene is None

    def test_accepts_password(self) -> None:
        """El pipeline acepta contraseña opcional."""
        pipeline = OBSPipeline(ws_url="ws://localhost:4455", password="secret")
        assert pipeline._password == "secret"

    def test_stores_ws_url(self) -> None:
        """El pipeline almacena la URL WebSocket."""
        pipeline = OBSPipeline(ws_url="ws://192.168.1.50:4455")
        assert pipeline._ws_url == "ws://192.168.1.50:4455"


class TestOBSPipelineExecute:
    """Tests de execute() para conmutación de escenas."""

    @pytest.mark.asyncio
    async def test_execute_raises_when_not_connected(
        self, obs_pipeline: OBSPipeline, sample_payload: EnrichedPayload
    ) -> None:
        """execute() lanza RuntimeError si no está conectado."""
        with pytest.raises(RuntimeError, match="not connected"):
            await obs_pipeline.execute(sample_payload)

    @pytest.mark.asyncio
    async def test_execute_sends_set_scene_request(
        self, obs_pipeline: OBSPipeline, sample_payload: EnrichedPayload
    ) -> None:
        """execute() envía SetCurrentProgramScene con el nombre correcto."""
        mock_ws = AsyncMock()
        # Simulate successful response from OBS
        mock_ws.recv = AsyncMock(
            return_value=json.dumps(
                {
                    "op": 7,
                    "d": {
                        "requestType": "SetCurrentProgramScene",
                        "requestId": "1",
                        "requestStatus": {"result": True, "code": 100},
                    },
                }
            )
        )
        obs_pipeline._ws = mock_ws
        obs_pipeline._connected = True
        obs_pipeline._healthy = True

        await obs_pipeline.execute(sample_payload)

        # Verify the sent message
        sent_data = json.loads(mock_ws.send.call_args[0][0])
        assert sent_data["op"] == 6
        assert sent_data["d"]["requestType"] == "SetCurrentProgramScene"
        assert sent_data["d"]["requestData"]["sceneName"] == "Actor1_cam2"

    @pytest.mark.asyncio
    async def test_execute_builds_scene_name_correctly(
        self, obs_pipeline: OBSPipeline
    ) -> None:
        """execute() construye nombre de escena como personaje_camN."""
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(
            return_value=json.dumps(
                {
                    "op": 7,
                    "d": {
                        "requestType": "SetCurrentProgramScene",
                        "requestId": "1",
                        "requestStatus": {"result": True, "code": 100},
                    },
                }
            )
        )
        obs_pipeline._ws = mock_ws
        obs_pipeline._connected = True
        obs_pipeline._healthy = True

        payload = EnrichedPayload(
            personaje="Cantante",
            target_cam=3,
            marker_type=MarkerType.MANUAL_NOTE,
            note="Switch",
            tc_in=SMPTETimecode(hours=0, minutes=5, seconds=10, frames=15, drop_frame=False),
            source_origin=SourceOrigin.MANUAL,
            color=EDLColor.Green,
        )

        await obs_pipeline.execute(payload)

        sent_data = json.loads(mock_ws.send.call_args[0][0])
        assert sent_data["d"]["requestData"]["sceneName"] == "Cantante_cam3"

    @pytest.mark.asyncio
    async def test_execute_updates_last_scene(
        self, obs_pipeline: OBSPipeline, sample_payload: EnrichedPayload
    ) -> None:
        """execute() actualiza last_scene tras cambio exitoso."""
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(
            return_value=json.dumps(
                {
                    "op": 7,
                    "d": {
                        "requestType": "SetCurrentProgramScene",
                        "requestId": "1",
                        "requestStatus": {"result": True, "code": 100},
                    },
                }
            )
        )
        obs_pipeline._ws = mock_ws
        obs_pipeline._connected = True
        obs_pipeline._healthy = True

        await obs_pipeline.execute(sample_payload)

        assert obs_pipeline.last_scene == "Actor1_cam2"

    @pytest.mark.asyncio
    async def test_execute_marks_unhealthy_on_failure(
        self, obs_pipeline: OBSPipeline, sample_payload: EnrichedPayload
    ) -> None:
        """execute() marca no saludable si OBS retorna error."""
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(
            return_value=json.dumps(
                {
                    "op": 7,
                    "d": {
                        "requestType": "SetCurrentProgramScene",
                        "requestId": "1",
                        "requestStatus": {
                            "result": False,
                            "code": 600,
                            "comment": "No scene found",
                        },
                    },
                }
            )
        )
        obs_pipeline._ws = mock_ws
        obs_pipeline._connected = True
        obs_pipeline._healthy = True

        with pytest.raises(RuntimeError, match="SetCurrentProgramScene failed"):
            await obs_pipeline.execute(sample_payload)

        assert not obs_pipeline.is_healthy()


class TestOBSPipelineReconnect:
    """Tests de reconexión con backoff exponencial."""

    @pytest.mark.asyncio
    async def test_reconnect_with_exponential_backoff(
        self, obs_pipeline: OBSPipeline
    ) -> None:
        """reconnect() aplica backoff exponencial entre intentos."""
        sleep_times: list[float] = []

        async def mock_sleep(seconds: float) -> None:
            sleep_times.append(seconds)

        # Fail twice, then succeed on third attempt
        connect_calls = [0]

        async def mock_connect() -> None:
            connect_calls[0] += 1
            if connect_calls[0] >= 3:
                obs_pipeline._connected = True
                obs_pipeline._healthy = True

        with patch("asyncio.sleep", side_effect=mock_sleep):
            obs_pipeline._connect = mock_connect  # type: ignore[assignment]
            obs_pipeline._sync_state = AsyncMock()  # type: ignore[assignment]
            await obs_pipeline.reconnect()

        # Verify exponential backoff: 1s, 2s, 4s...
        assert sleep_times[0] == _INITIAL_BACKOFF_S
        assert sleep_times[1] == _INITIAL_BACKOFF_S * _BACKOFF_MULTIPLIER

    @pytest.mark.asyncio
    async def test_reconnect_caps_at_max_backoff(
        self, obs_pipeline: OBSPipeline
    ) -> None:
        """reconnect() no supera el backoff máximo de 30s."""
        sleep_times: list[float] = []

        async def mock_sleep(seconds: float) -> None:
            sleep_times.append(seconds)

        # Fail many times, then succeed
        connect_calls = [0]

        async def mock_connect() -> None:
            connect_calls[0] += 1
            if connect_calls[0] >= 10:
                obs_pipeline._connected = True
                obs_pipeline._healthy = True

        with patch("asyncio.sleep", side_effect=mock_sleep):
            obs_pipeline._connect = mock_connect  # type: ignore[assignment]
            obs_pipeline._sync_state = AsyncMock()  # type: ignore[assignment]
            await obs_pipeline.reconnect()

        # No sleep should exceed MAX_BACKOFF_S
        for t in sleep_times:
            assert t <= _MAX_BACKOFF_S

    @pytest.mark.asyncio
    async def test_reconnect_syncs_state_on_success(
        self, obs_pipeline: OBSPipeline
    ) -> None:
        """reconnect() sincroniza el estado de escena tras reconexión exitosa."""
        obs_pipeline._last_scene = "Actor1_cam2"

        async def mock_connect() -> None:
            obs_pipeline._connected = True
            obs_pipeline._healthy = True

        mock_sync = AsyncMock()

        async def mock_sleep(seconds: float) -> None:
            pass

        with patch("asyncio.sleep", side_effect=mock_sleep):
            obs_pipeline._connect = mock_connect  # type: ignore[assignment]
            obs_pipeline._sync_state = mock_sync  # type: ignore[assignment]
            await obs_pipeline.reconnect()

        mock_sync.assert_called_once()

    @pytest.mark.asyncio
    async def test_reconnect_stops_on_shutdown(
        self, obs_pipeline: OBSPipeline
    ) -> None:
        """reconnect() se detiene si se señaliza shutdown."""
        obs_pipeline._shutdown = True

        async def mock_sleep(seconds: float) -> None:
            pass

        with patch("asyncio.sleep", side_effect=mock_sleep):
            obs_pipeline._connect = AsyncMock()  # type: ignore[assignment]
            await obs_pipeline.reconnect()

        # _connect should never be called when shutdown is set
        obs_pipeline._connect.assert_not_called()  # type: ignore[union-attr]


class TestOBSPipelineSyncState:
    """Tests de sincronización de estado tras reconexión."""

    @pytest.mark.asyncio
    async def test_sync_state_restores_last_scene(
        self, obs_pipeline: OBSPipeline
    ) -> None:
        """_sync_state() reenvía el último cambio de escena solicitado."""
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(
            return_value=json.dumps(
                {
                    "op": 7,
                    "d": {
                        "requestType": "SetCurrentProgramScene",
                        "requestId": "1",
                        "requestStatus": {"result": True, "code": 100},
                    },
                }
            )
        )
        obs_pipeline._ws = mock_ws
        obs_pipeline._connected = True
        obs_pipeline._healthy = True
        obs_pipeline._last_scene = "Cantante_cam1"

        await obs_pipeline._sync_state()

        sent_data = json.loads(mock_ws.send.call_args[0][0])
        assert sent_data["d"]["requestData"]["sceneName"] == "Cantante_cam1"

    @pytest.mark.asyncio
    async def test_sync_state_noop_when_no_last_scene(
        self, obs_pipeline: OBSPipeline
    ) -> None:
        """_sync_state() no hace nada si no hay escena previa."""
        mock_ws = AsyncMock()
        obs_pipeline._ws = mock_ws
        obs_pipeline._connected = True
        obs_pipeline._last_scene = None

        await obs_pipeline._sync_state()

        mock_ws.send.assert_not_called()


class TestOBSPipelineHealthy:
    """Tests de is_healthy() para verificar estado del pipeline."""

    def test_initially_not_healthy(self, obs_pipeline: OBSPipeline) -> None:
        """El pipeline inicia como no saludable."""
        assert not obs_pipeline.is_healthy()

    def test_healthy_when_connected(self, obs_pipeline: OBSPipeline) -> None:
        """is_healthy() retorna True cuando está conectado."""
        obs_pipeline._connected = True
        obs_pipeline._healthy = True
        assert obs_pipeline.is_healthy()


class TestOBSPipelineInheritance:
    """Tests de herencia de Pipeline ABC."""

    def test_is_pipeline_subclass(self) -> None:
        """OBSPipeline hereda de Pipeline."""
        from switch_bot.pipelines.base import Pipeline

        assert issubclass(OBSPipeline, Pipeline)

    def test_implements_execute(self) -> None:
        """OBSPipeline implementa execute()."""
        assert hasattr(OBSPipeline, "execute")
        assert inspect.iscoroutinefunction(OBSPipeline.execute)

    def test_implements_is_healthy(self) -> None:
        """OBSPipeline implementa is_healthy()."""
        assert hasattr(OBSPipeline, "is_healthy")
        assert callable(OBSPipeline.is_healthy)


class TestOBSPipelineLifecycle:
    """Tests del ciclo de vida start/stop."""

    @pytest.mark.asyncio
    async def test_stop_sets_shutdown(self, obs_pipeline: OBSPipeline) -> None:
        """stop() marca shutdown y desconecta."""
        obs_pipeline._connected = False
        await obs_pipeline.stop()
        assert obs_pipeline._shutdown is True
        assert not obs_pipeline.connected

    @pytest.mark.asyncio
    async def test_stop_cancels_reconnect_task(
        self, obs_pipeline: OBSPipeline
    ) -> None:
        """stop() cancela tarea de reconexión activa."""
        # Create a fake reconnect task
        async def fake_reconnect() -> None:
            await asyncio.sleep(100)

        obs_pipeline._reconnect_task = asyncio.create_task(fake_reconnect())
        await obs_pipeline.stop()

        assert obs_pipeline._reconnect_task is None
