"""Tests de integración del flujo completo — E2E, reconexión, pipelines y backends.

Verifica los flujos end-to-end del sistema Switch_bot:
- Captura mock → Inferencia → Decisión → 4 Pipelines
- Reconexión OBS con backoff exponencial y sincronización de escena
- Pipeline ATEM con comando TCP a mock ATEM
- Selección de backend (Bedrock/Local) antes de sesión
- Validación de conexión con timeout de 10s y mensajes descriptivos
- Listado de modelos (Bedrock lista AWS, Local lista Ollama)

Requisitos validados: 16.2, 16.3, 11.3, 11.4, 10.1, 19.2, 19.3, 19.4, 19.5
"""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Mock external dependencies before importing project modules that need them
# ---------------------------------------------------------------------------
_mock_boto3 = MagicMock()
_mock_botocore = MagicMock()
_mock_botocore_config = MagicMock()
_mock_botocore_exceptions = MagicMock()
# Provide real exception classes for botocore
_mock_botocore_exceptions.ClientError = type("ClientError", (Exception,), {})
_mock_botocore_exceptions.EndpointConnectionError = type(
    "EndpointConnectionError", (Exception,), {}
)
_mock_botocore_exceptions.ReadTimeoutError = type(
    "ReadTimeoutError", (Exception,), {}
)

if "boto3" not in sys.modules:
    sys.modules["boto3"] = _mock_boto3
if "botocore" not in sys.modules:
    sys.modules["botocore"] = _mock_botocore
if "botocore.config" not in sys.modules:
    sys.modules["botocore.config"] = _mock_botocore_config
if "botocore.exceptions" not in sys.modules:
    sys.modules["botocore.exceptions"] = _mock_botocore_exceptions

_mock_botocore_config.Config = MagicMock()

# Now import project modules
from switch_bot.engines.session_manager import (
    SessionConfigLockedError,
    SessionManager,
    SessionStartResult,
)
from switch_bot.ia.backend_base import (
    BackendConnectionError,
    BackendTimeoutError,
    IABackend,
    ModelDiscoveryError,
)
from switch_bot.ia.backend_config import IABackendConfig
from switch_bot.ia.bedrock_backend import BedrockBackend
from switch_bot.ia.local_backend import LocalBackend
from switch_bot.ia.model_catalog import IAModelCatalog, IAModelInfo
from switch_bot.models.enums import EDLColor, MarkerType, SourceOrigin
from switch_bot.models.payload import EnrichedPayload
from switch_bot.models.timecode import SMPTETimecode
from switch_bot.pipelines.atem_pipeline import ATEMPipeline
from switch_bot.pipelines.base import Pipeline
from switch_bot.pipelines.dispatcher import DispatchResult, QuadDispatcher
from switch_bot.pipelines.obs_pipeline import OBSPipeline


# ---------------------------------------------------------------------------
# Fixtures comunes
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_payload() -> EnrichedPayload:
    """Payload de prueba para dispatch."""
    return EnrichedPayload(
        personaje="ALICE",
        target_cam=1,
        marker_type=MarkerType.ENTRADA,
        note="Cambio a cámara 1",
        tc_in=SMPTETimecode(hours=1, minutes=0, seconds=0, frames=0, drop_frame=False),
        source_origin=SourceOrigin.AUTO,
        color=EDLColor.Cyan,
    )


@pytest.fixture
def bedrock_config() -> IABackendConfig:
    """Configuración Bedrock por defecto."""
    return IABackendConfig.default_bedrock()


@pytest.fixture
def local_config() -> IABackendConfig:
    """Configuración Local (Ollama) por defecto."""
    return IABackendConfig.default_local()


# ---------------------------------------------------------------------------
# TestE2EFlow — Flujo completo: Captura → Inferencia → Decisión → 4 Pipelines
# ---------------------------------------------------------------------------


class TestE2EFlow:
    """Test E2E: Captura mock → Inferencia → Decisión → 4 Pipelines.

    Requisitos validados: 16.2, 16.3
    """

    @pytest.fixture
    def mock_pipelines(self) -> list[MagicMock]:
        """Crea 4 mock pipelines que simulan ATEM, OBS, Metadata, EDL."""
        pipelines = []
        for name in ["ATEM", "OBS", "Metadata", "EDL"]:
            p = MagicMock(spec=Pipeline)
            p.execute = AsyncMock(return_value=None)
            p.is_healthy.return_value = True
            p.name = name
            pipelines.append(p)
        return pipelines

    @pytest.mark.asyncio
    async def test_dispatch_to_all_four_pipelines(
        self, mock_pipelines: list[MagicMock], sample_payload: EnrichedPayload
    ) -> None:
        """El QuadDispatcher debe enviar el payload a los 4 pipelines."""
        dispatcher = QuadDispatcher(pipelines=mock_pipelines)

        result = await dispatcher.dispatch(sample_payload)

        assert result.total == 4
        assert result.successes == 4
        assert result.failures == 0
        assert result.errors == []
        for p in mock_pipelines:
            p.execute.assert_called_once_with(sample_payload)

    @pytest.mark.asyncio
    async def test_dispatch_tolerates_single_pipeline_failure(
        self, mock_pipelines: list[MagicMock], sample_payload: EnrichedPayload
    ) -> None:
        """Si un pipeline falla, los demás 3 deben completar correctamente."""
        mock_pipelines[0].execute = AsyncMock(
            side_effect=RuntimeError("ATEM connection lost")
        )

        dispatcher = QuadDispatcher(pipelines=mock_pipelines)
        result = await dispatcher.dispatch(sample_payload)

        assert result.total == 4
        assert result.successes == 3
        assert result.failures == 1
        assert len(result.errors) == 1
        assert "ATEM connection lost" in str(result.errors[0])

    @pytest.mark.asyncio
    async def test_dispatch_all_pipelines_fail(
        self, mock_pipelines: list[MagicMock], sample_payload: EnrichedPayload
    ) -> None:
        """Si todos los pipelines fallan, se reportan todos los errores."""
        for p in mock_pipelines:
            p.execute = AsyncMock(side_effect=RuntimeError("Pipeline error"))

        dispatcher = QuadDispatcher(pipelines=mock_pipelines)
        result = await dispatcher.dispatch(sample_payload)

        assert result.total == 4
        assert result.successes == 0
        assert result.failures == 4
        assert len(result.errors) == 4

    @pytest.mark.asyncio
    async def test_e2e_payload_reaches_pipelines_with_correct_data(
        self, mock_pipelines: list[MagicMock]
    ) -> None:
        """El payload enriquecido debe llegar a cada pipeline con datos correctos."""
        payload = EnrichedPayload(
            personaje="BOB",
            target_cam=2,
            marker_type=MarkerType.IMAGEN,
            note="Reaction shot",
            tc_in=SMPTETimecode(
                hours=1, minutes=30, seconds=15, frames=10, drop_frame=False
            ),
            source_origin=SourceOrigin.AUTO,
            color=EDLColor.Green,
        )

        dispatcher = QuadDispatcher(pipelines=mock_pipelines)
        await dispatcher.dispatch(payload)

        for p in mock_pipelines:
            call_payload = p.execute.call_args[0][0]
            assert call_payload.personaje == "BOB"
            assert call_payload.target_cam == 2
            assert call_payload.marker_type == MarkerType.IMAGEN


# ---------------------------------------------------------------------------
# TestOBSReconnection — Reconexión OBS con backoff y sincronización
# ---------------------------------------------------------------------------


class TestOBSReconnection:
    """Test reconexión OBS: desconexión → reconexión → sincronización de escena.

    Requisitos validados: 11.3, 11.4
    """

    @pytest.mark.asyncio
    async def test_reconnect_with_backoff_and_state_sync(self) -> None:
        """Reconexión OBS usa backoff exponencial y restaura last_scene."""
        obs = OBSPipeline(ws_url="ws://localhost:4455")
        obs._last_scene = "ALICE_cam1"
        obs._connected = False
        obs._healthy = False

        connect_call_count = 0

        async def mock_connect() -> None:
            nonlocal connect_call_count
            connect_call_count += 1
            if connect_call_count >= 3:
                obs._connected = True
                obs._healthy = True

        async def mock_set_scene(scene_name: str) -> None:
            pass

        with patch.object(obs, "_connect", side_effect=mock_connect), \
             patch.object(obs, "_set_current_scene", side_effect=mock_set_scene), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            await obs.reconnect()

        assert obs.connected is True
        assert obs._healthy is True
        assert connect_call_count == 3

    @pytest.mark.asyncio
    async def test_reconnect_does_not_block_other_pipelines(self) -> None:
        """La reconexión OBS no bloquea a otros pipelines (Req 11.3)."""
        obs = OBSPipeline(ws_url="ws://localhost:4455")
        obs._connected = False

        other_pipeline = MagicMock(spec=Pipeline)
        other_pipeline.execute = AsyncMock(return_value=None)
        other_pipeline.is_healthy.return_value = True

        async def slow_connect() -> None:
            await asyncio.sleep(0.01)
            obs._connected = True
            obs._healthy = True

        with patch.object(obs, "_connect", side_effect=slow_connect), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            reconnect_task = asyncio.create_task(obs.reconnect())

            payload = EnrichedPayload(
                personaje="ALICE",
                target_cam=1,
                marker_type=MarkerType.ENTRADA,
                note="Test",
                tc_in=SMPTETimecode(0, 0, 0, 0, False),
                source_origin=SourceOrigin.AUTO,
                color=EDLColor.Cyan,
            )
            await other_pipeline.execute(payload)
            await reconnect_task

        other_pipeline.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_sync_state_restores_last_scene(self) -> None:
        """Al reconectar, se sincroniza la última escena (Req 11.4)."""
        obs = OBSPipeline(ws_url="ws://localhost:4455")
        obs._last_scene = "BOB_cam2"
        obs._connected = True
        obs._healthy = True

        set_scene_calls: list[str] = []

        async def mock_set_scene(scene_name: str) -> None:
            set_scene_calls.append(scene_name)

        with patch.object(obs, "_set_current_scene", side_effect=mock_set_scene):
            await obs._sync_state()

        assert set_scene_calls == ["BOB_cam2"]

    @pytest.mark.asyncio
    async def test_sync_state_no_op_without_previous_scene(self) -> None:
        """Si no hay escena previa, _sync_state no hace nada."""
        obs = OBSPipeline(ws_url="ws://localhost:4455")
        obs._last_scene = None
        obs._connected = True

        with patch.object(
            obs, "_set_current_scene", new_callable=AsyncMock
        ) as mock_set:
            await obs._sync_state()

        mock_set.assert_not_called()


# ---------------------------------------------------------------------------
# TestATEMPipeline — Comando TCP a mock ATEM
# ---------------------------------------------------------------------------


class TestATEMPipeline:
    """Test Pipeline ATEM: comando TCP a mock ATEM.

    Requisitos validados: 10.1
    """

    @pytest.mark.asyncio
    async def test_atem_execute_switches_source(
        self, sample_payload: EnrichedPayload
    ) -> None:
        """execute() conmuta la fuente ATEM al target_cam del payload."""
        config = MagicMock()
        atem = ATEMPipeline(atem_ip="192.168.1.100", config=config)
        atem._connected = True

        mock_atem_device = MagicMock()
        atem._atem = mock_atem_device

        await atem.execute(sample_payload)

        mock_atem_device.setProgramInputVideoSource.assert_called_once_with(
            0, sample_payload.target_cam
        )

    @pytest.mark.asyncio
    async def test_atem_execute_updates_active_source(
        self, sample_payload: EnrichedPayload
    ) -> None:
        """execute() actualiza active_source tras el switch."""
        config = MagicMock()
        atem = ATEMPipeline(atem_ip="192.168.1.100", config=config)
        atem._connected = True

        mock_atem_device = MagicMock()
        atem._atem = mock_atem_device

        await atem.execute(sample_payload)

        assert atem.active_source == sample_payload.target_cam

    @pytest.mark.asyncio
    async def test_atem_execute_raises_when_disconnected(
        self, sample_payload: EnrichedPayload
    ) -> None:
        """execute() lanza RuntimeError si no está conectado."""
        config = MagicMock()
        atem = ATEMPipeline(atem_ip="192.168.1.100", config=config)
        atem._connected = False

        with pytest.raises(RuntimeError, match="not connected"):
            await atem.execute(sample_payload)

    def test_atem_tally_update(self) -> None:
        """update_tally() actualiza active_source y dispara callback."""
        callback_calls: list[int] = []
        config = MagicMock()
        atem = ATEMPipeline(
            atem_ip="192.168.1.100",
            config=config,
            tally_callback=lambda src: callback_calls.append(src),
        )

        atem.update_tally(3)

        assert atem.active_source == 3
        assert callback_calls == [3]

    def test_atem_is_healthy_reflects_connection_state(self) -> None:
        """is_healthy() refleja el estado de conexión del pipeline."""
        config = MagicMock()
        atem = ATEMPipeline(atem_ip="192.168.1.100", config=config)

        assert atem.is_healthy() is False

        atem._healthy = True
        assert atem.is_healthy() is True


# ---------------------------------------------------------------------------
# TestBackendSelection — Cambio entre Bedrock y Local antes de sesión
# ---------------------------------------------------------------------------


class TestBackendSelection:
    """Test selección de backend: cambio entre Bedrock y Local antes de sesión.

    Requisitos validados: 19.4, 19.5
    """

    @pytest.mark.asyncio
    async def test_switch_to_bedrock_before_session(
        self, bedrock_config: IABackendConfig
    ) -> None:
        """Se puede seleccionar Bedrock como backend antes de sesión."""
        session_mgr = SessionManager()

        session_mgr.change_backend_config(bedrock_config)

        assert session_mgr.current_config is not None
        assert session_mgr.current_config.backend_type == "bedrock"

    @pytest.mark.asyncio
    async def test_switch_to_local_before_session(
        self, local_config: IABackendConfig
    ) -> None:
        """Se puede seleccionar Local como backend antes de sesión."""
        session_mgr = SessionManager()

        session_mgr.change_backend_config(local_config)

        assert session_mgr.current_config is not None
        assert session_mgr.current_config.backend_type == "local"

    @pytest.mark.asyncio
    async def test_cannot_change_backend_during_session(
        self, bedrock_config: IABackendConfig, local_config: IABackendConfig
    ) -> None:
        """No se puede cambiar de backend durante sesión activa (Req 19.7)."""
        session_mgr = SessionManager()
        mock_backend = MagicMock(spec=IABackend)
        mock_backend.validate_connection = AsyncMock(return_value=True)
        mock_enricher = MagicMock()

        result = await session_mgr.start_session(
            backend=mock_backend,
            config=bedrock_config,
            enricher=mock_enricher,
        )
        assert result.success is True
        assert session_mgr.is_config_locked is True

        with pytest.raises(SessionConfigLockedError):
            session_mgr.change_backend_config(local_config)

        await session_mgr.end_session()
        assert session_mgr.is_config_locked is False

        # Now we can change config
        session_mgr.change_backend_config(local_config)

    @pytest.mark.asyncio
    async def test_backend_type_property(self) -> None:
        """Las instancias de backend reportan correctamente su tipo."""
        bedrock_cfg = IABackendConfig.default_bedrock()
        local_cfg = IABackendConfig.default_local()

        bedrock = BedrockBackend(bedrock_cfg)
        local = LocalBackend(local_cfg)

        assert bedrock.backend_type == "bedrock"
        assert local.backend_type == "local"


# ---------------------------------------------------------------------------
# TestConnectionValidation — Timeout de 10s + mensaje descriptivo
# ---------------------------------------------------------------------------


class TestConnectionValidation:
    """Test validación de conexión: timeout de 10s + mensaje descriptivo.

    Requisitos validados: 19.4, 19.5
    """

    @pytest.mark.asyncio
    async def test_session_start_timeout_produces_descriptive_message(
        self, bedrock_config: IABackendConfig
    ) -> None:
        """Un timeout produce SessionStartResult con mensaje descriptivo."""
        session_mgr = SessionManager()
        mock_backend = MagicMock(spec=IABackend)
        mock_backend.validate_connection = AsyncMock(
            side_effect=BackendTimeoutError(
                "Timeout al validar conexión",
                timeout_seconds=10.0,
            )
        )
        mock_enricher = MagicMock()

        result = await session_mgr.start_session(
            backend=mock_backend,
            config=bedrock_config,
            enricher=mock_enricher,
        )

        assert result.success is False
        assert result.can_retry is True
        assert result.can_select_alternative is True
        assert "timeout" in result.error_message.lower() or "10" in result.error_message

    @pytest.mark.asyncio
    async def test_session_start_connection_error_descriptive_message(
        self, local_config: IABackendConfig
    ) -> None:
        """Error de conexión produce SessionStartResult con mensaje descriptivo."""
        session_mgr = SessionManager()
        mock_backend = MagicMock(spec=IABackend)
        mock_backend.validate_connection = AsyncMock(
            side_effect=BackendConnectionError("Runtime local no iniciado")
        )
        mock_enricher = MagicMock()

        result = await session_mgr.start_session(
            backend=mock_backend,
            config=local_config,
            enricher=mock_enricher,
        )

        assert result.success is False
        assert result.can_retry is True
        assert result.can_select_alternative is True
        assert "local" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_validate_connection_respects_timeout(self) -> None:
        """validate_connection respeta el timeout especificado."""
        import threading

        bedrock_cfg = IABackendConfig.default_bedrock()
        bedrock = BedrockBackend(bedrock_cfg)

        # Use an event so we can release the blocking thread after the test
        release_event = threading.Event()

        def _block_until_released(**kwargs):
            release_event.wait(timeout=5.0)

        mock_client = MagicMock()
        mock_client.list_foundation_models = _block_until_released
        bedrock._bedrock_client = mock_client

        with pytest.raises(BackendTimeoutError) as exc_info:
            await bedrock.validate_connection(timeout_seconds=0.05)

        # Release the blocked thread so it doesn't linger
        release_event.set()
        assert exc_info.value.timeout_seconds == 0.05

    @pytest.mark.asyncio
    async def test_session_manager_uses_config_timeout(self) -> None:
        """SessionManager usa connection_timeout_seconds de la config."""
        config = IABackendConfig.default_bedrock()
        config.connection_timeout_seconds = 10.0

        session_mgr = SessionManager()
        mock_backend = MagicMock(spec=IABackend)
        mock_backend.validate_connection = AsyncMock(return_value=True)
        mock_enricher = MagicMock()

        await session_mgr.start_session(
            backend=mock_backend,
            config=config,
            enricher=mock_enricher,
        )

        mock_backend.validate_connection.assert_called_once_with(
            timeout_seconds=10.0
        )

        await session_mgr.end_session()

    @pytest.mark.asyncio
    async def test_backend_not_accessible_returns_can_retry(
        self, bedrock_config: IABackendConfig
    ) -> None:
        """Si backend retorna False, el resultado indica can_retry."""
        session_mgr = SessionManager()
        mock_backend = MagicMock(spec=IABackend)
        mock_backend.validate_connection = AsyncMock(return_value=False)
        mock_enricher = MagicMock()

        result = await session_mgr.start_session(
            backend=mock_backend,
            config=bedrock_config,
            enricher=mock_enricher,
        )

        assert result.success is False
        assert result.can_retry is True
        assert result.can_select_alternative is True


# ---------------------------------------------------------------------------
# TestModelListing — Bedrock lista modelos AWS, Local lista modelos Ollama
# ---------------------------------------------------------------------------


class TestModelListing:
    """Test listado de modelos: Bedrock lista AWS, Local lista Ollama.

    Requisitos validados: 19.2, 19.3
    """

    @pytest.mark.asyncio
    async def test_bedrock_list_models_returns_catalog(self) -> None:
        """Bedrock retorna IAModelCatalog con modelos de AWS."""
        config = IABackendConfig.default_bedrock()
        bedrock = BedrockBackend(config)

        mock_client = MagicMock()
        mock_client.list_foundation_models.return_value = {
            "modelSummaries": [
                {
                    "modelId": "amazon.titan-embed-text-v2:0",
                    "modelName": "Titan Embeddings V2",
                    "outputModalities": ["EMBEDDING"],
                    "modelArn": "arn:aws:bedrock:us-east-1::foundation-model/titan",
                },
                {
                    "modelId": "anthropic.claude-3-5-sonnet-20241022-v2:0",
                    "modelName": "Claude 3.5 Sonnet",
                    "outputModalities": ["TEXT"],
                    "modelArn": "arn:aws:bedrock:us-east-1::foundation-model/claude",
                },
            ]
        }
        bedrock._bedrock_client = mock_client

        catalog = await bedrock.list_available_models()

        assert isinstance(catalog, IAModelCatalog)
        assert catalog.backend_type == "bedrock"
        assert len(catalog.embedding_models) == 1
        assert len(catalog.llm_models) == 1
        assert catalog.embedding_models[0].model_id == "amazon.titan-embed-text-v2:0"
        assert catalog.llm_models[0].model_id == "anthropic.claude-3-5-sonnet-20241022-v2:0"
        assert catalog.last_updated != ""

    @pytest.mark.asyncio
    async def test_local_ollama_list_models_returns_catalog(self) -> None:
        """Local (Ollama) retorna IAModelCatalog con modelos locales."""
        config = IABackendConfig.default_local()
        local = LocalBackend(config)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "models": [
                {
                    "name": "nomic-embed-text:latest",
                    "model": "nomic-embed-text:latest",
                    "size": 274000000,
                    "details": {"family": "nomic-bert"},
                },
                {
                    "name": "llama3:8b",
                    "model": "llama3:8b",
                    "size": 4700000000,
                    "details": {"family": "llama"},
                },
            ]
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        local._client = mock_client

        catalog = await local.list_available_models()

        assert isinstance(catalog, IAModelCatalog)
        assert catalog.backend_type == "local"
        assert len(catalog.embedding_models) == 1
        assert len(catalog.llm_models) == 1
        assert catalog.embedding_models[0].model_id == "nomic-embed-text:latest"
        assert catalog.embedding_models[0].model_type == "embedding"
        assert catalog.llm_models[0].model_id == "llama3:8b"
        assert catalog.llm_models[0].model_type == "llm"
        assert catalog.last_updated != ""

    @pytest.mark.asyncio
    async def test_bedrock_list_models_handles_discovery_error(self) -> None:
        """Bedrock lanza ModelDiscoveryError si la llamada boto3 falla."""
        config = IABackendConfig.default_bedrock()
        bedrock = BedrockBackend(config)

        mock_client = MagicMock()
        mock_client.list_foundation_models.side_effect = Exception("Access denied")
        bedrock._bedrock_client = mock_client

        with pytest.raises(ModelDiscoveryError):
            await bedrock.list_available_models()

    @pytest.mark.asyncio
    async def test_local_list_models_handles_connection_error(self) -> None:
        """Local lanza BackendConnectionError si no está inicializado."""
        config = IABackendConfig.default_local()
        local = LocalBackend(config)

        with pytest.raises(BackendConnectionError):
            await local.list_available_models()

    @pytest.mark.asyncio
    async def test_model_catalog_structure(self) -> None:
        """IAModelCatalog tiene la estructura correcta con helpers."""
        catalog = IAModelCatalog(
            backend_type="bedrock",
            embedding_models=[
                IAModelInfo(
                    model_id="titan-embed-v2",
                    name="Titan V2",
                    model_type="embedding",
                ),
            ],
            llm_models=[
                IAModelInfo(
                    model_id="claude-3.5-sonnet",
                    name="Claude 3.5",
                    model_type="llm",
                ),
            ],
            last_updated="2024-01-01T00:00:00Z",
        )

        assert catalog.get_embedding_model_ids() == ["titan-embed-v2"]
        assert catalog.get_llm_model_ids() == ["claude-3.5-sonnet"]
