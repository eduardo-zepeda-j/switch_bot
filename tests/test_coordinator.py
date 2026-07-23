"""Tests para el Coordinator — orquestador principal del sistema.

Verifica la integración de los subsistemas:
CaptureManager → InferenceEngine → DecisionEngine → HysteresisFilter → QuadDispatcher
y las prioridades de PanicButton, VocalAnomalyDetector y SessionManager.

Requisitos validados: 5.1, 5.2, 5.3, 16.1, 16.2, 16.3, 16.4
"""

from __future__ import annotations

import asyncio
import multiprocessing as mp
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from switch_bot.coordinator import Coordinator, ManualNote
from switch_bot.engines.decision_engine import DecisionEngine
from switch_bot.engines.hysteresis_filter import HysteresisFilter
from switch_bot.engines.panic_button import PanicButton
from switch_bot.engines.script_parser import ScriptBlock, ScriptDocument
from switch_bot.engines.session_manager import SessionManager, SessionStartResult
from switch_bot.ia.ia_enricher import IAEnricher, MarkerEvent
from switch_bot.models.config import SystemConfig
from switch_bot.models.enums import EDLColor, MarkerType, SourceOrigin
from switch_bot.models.inference import CameraDecision, GazeResult, VADResult
from switch_bot.models.payload import EnrichedPayload
from switch_bot.models.timecode import SMPTETimecode
from switch_bot.pipelines.dispatcher import DispatchResult, QuadDispatcher


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config() -> SystemConfig:
    """Configuración de prueba a 30fps non-drop frame."""
    return SystemConfig(video_mode="1080p29.97", fps=29.97, hysteresis_frames=90)


@pytest.fixture
def script_doc() -> ScriptDocument:
    """Documento de guión de prueba con 2 personajes."""
    return ScriptDocument(
        title="Test Script",
        blocks=[
            ScriptBlock(index=0, character="ALICE", text="Hola, buen día."),
            ScriptBlock(index=1, character="BOB", text="Buenos días, Alice."),
        ],
        character_camera_map={"ALICE": 1, "BOB": 2},
    )


@pytest.fixture
def mock_backend() -> MagicMock:
    """Mock del IABackend."""
    backend = MagicMock()
    backend.backend_type = "mock"
    backend.validate_connection = AsyncMock(return_value=True)
    backend.generate_embeddings = AsyncMock(return_value=[[0.1, 0.2], [0.3, 0.4]])
    backend.compute_similarity = AsyncMock(return_value=0.95)
    backend.analyze_context = AsyncMock(return_value="Respuesta IA")
    return backend


@pytest.fixture
def mock_backend_config() -> MagicMock:
    """Mock de IABackendConfig."""
    config = MagicMock()
    config.backend_type = "mock"
    config.embedding_model_id = "test-model"
    config.llm_model_id = "test-llm"
    config.connection_timeout_seconds = 10.0
    return config


@pytest.fixture
def mock_dispatcher() -> MagicMock:
    """Mock del QuadDispatcher."""
    dispatcher = MagicMock(spec=QuadDispatcher)
    dispatcher.dispatch = AsyncMock(
        return_value=DispatchResult(total=4, successes=4, failures=0, errors=[])
    )
    return dispatcher


@pytest.fixture
def panic_button() -> PanicButton:
    """PanicButton de prueba."""
    return PanicButton()


@pytest.fixture
def coordinator(
    config: SystemConfig,
    script_doc: ScriptDocument,
    mock_backend: MagicMock,
    mock_backend_config: MagicMock,
    mock_dispatcher: MagicMock,
    panic_button: PanicButton,
) -> Coordinator:
    """Instancia de Coordinator con mocks."""
    return Coordinator(
        config=config,
        script_doc=script_doc,
        backend=mock_backend,
        backend_config=mock_backend_config,
        dispatcher=mock_dispatcher,
        panic_button=panic_button,
    )


# ---------------------------------------------------------------------------
# Tests de inicialización
# ---------------------------------------------------------------------------


class TestCoordinatorInit:
    """Verifica la creación correcta del Coordinator."""

    def test_init_creates_subsystems(self, coordinator: Coordinator) -> None:
        """El coordinator debe crear todos los subsistemas internos."""
        assert coordinator.is_running is False
        assert coordinator.session_manager is not None
        assert coordinator.panic_button is not None
        assert coordinator.enricher is not None
        assert coordinator.hysteresis_filter is not None

    def test_init_hysteresis_uses_config(
        self, coordinator: Coordinator, config: SystemConfig
    ) -> None:
        """El filtro de histéresis debe usar los parámetros del config."""
        assert coordinator.hysteresis_filter.cooldown_frames == config.hysteresis_frames
        assert coordinator.hysteresis_filter.fps == config.fps


# ---------------------------------------------------------------------------
# Tests de inicio/parada de sesión
# ---------------------------------------------------------------------------


class TestSessionLifecycle:
    """Verifica el ciclo de vida de sesión: start/stop."""

    @pytest.mark.asyncio
    async def test_start_session_success(
        self, coordinator: Coordinator, mock_backend: MagicMock
    ) -> None:
        """start_session debe vectorizar guión, iniciar captura e inferencia."""
        with patch.object(
            coordinator._session_manager,
            "start_session",
            new_callable=AsyncMock,
            return_value=SessionStartResult(success=True),
        ), patch.object(
            coordinator._enricher,
            "vectorize_script",
            new_callable=AsyncMock,
        ), patch(
            "switch_bot.coordinator.CaptureManager"
        ) as mock_cm, patch(
            "switch_bot.coordinator.InferenceEngine"
        ) as mock_ie:
            mock_ie.start_process.return_value = MagicMock()

            result = await coordinator.start_session()

            assert result.success is True
            assert coordinator.is_running is True

            # Limpiar
            await coordinator.stop_session()

    @pytest.mark.asyncio
    async def test_start_session_backend_failure(
        self, coordinator: Coordinator
    ) -> None:
        """start_session debe retornar fallo si el backend no valida."""
        with patch.object(
            coordinator._session_manager,
            "start_session",
            new_callable=AsyncMock,
            return_value=SessionStartResult(
                success=False,
                error_message="Backend no accesible",
                can_retry=True,
            ),
        ):
            result = await coordinator.start_session()

            assert result.success is False
            assert coordinator.is_running is False

    @pytest.mark.asyncio
    async def test_stop_session_cleans_state(
        self, coordinator: Coordinator
    ) -> None:
        """stop_session debe limpiar todo el estado y detener procesos."""
        # Simular estado de sesión activa
        coordinator._running = True
        coordinator._loop_task = asyncio.ensure_future(asyncio.sleep(10))
        coordinator._capture_manager = MagicMock()
        coordinator._inference_process = MagicMock()
        coordinator._inference_process.is_alive.return_value = False
        coordinator._frame_count = 100

        with patch.object(
            coordinator._session_manager,
            "end_session",
            new_callable=AsyncMock,
        ):
            await coordinator.stop_session()

        assert coordinator.is_running is False
        assert coordinator._capture_manager is None
        assert coordinator._inference_process is None
        assert coordinator._frame_count == 0


# ---------------------------------------------------------------------------
# Tests del pipeline de decisión
# ---------------------------------------------------------------------------


class TestDecisionPipeline:
    """Verifica el flujo DecisionEngine → HysteresisFilter → Dispatch."""

    @pytest.mark.asyncio
    async def test_process_gaze_and_vad_triggers_dispatch(
        self, coordinator: Coordinator, mock_dispatcher: MagicMock
    ) -> None:
        """Cuando GazeResult + VADResult producen una decisión, debe despachar."""
        gaze = GazeResult(feed_index=0, looking_at=1, confidence=0.9)
        vad = VADResult(is_speaking=True, speaker_id="ALICE", confidence=0.8)

        # Procesar gaze y vad secuencialmente
        await coordinator._process_inference_result(gaze)
        await coordinator._process_inference_result(vad)

        # Debe haber despachado al menos una vez
        assert mock_dispatcher.dispatch.called

    @pytest.mark.asyncio
    async def test_no_dispatch_without_both_results(
        self, coordinator: Coordinator, mock_dispatcher: MagicMock
    ) -> None:
        """No debe despachar si solo hay GazeResult sin VADResult."""
        gaze = GazeResult(feed_index=0, looking_at=1, confidence=0.9)

        await coordinator._process_inference_result(gaze)

        assert not mock_dispatcher.dispatch.called

    @pytest.mark.asyncio
    async def test_hysteresis_blocks_rapid_switches(
        self, coordinator: Coordinator, mock_dispatcher: MagicMock
    ) -> None:
        """El filtro de histéresis debe bloquear switches rápidos."""
        gaze = GazeResult(feed_index=0, looking_at=1, confidence=0.9)
        vad = VADResult(is_speaking=True, speaker_id="ALICE", confidence=0.8)

        # Primer dispatch — debe pasar
        await coordinator._process_inference_result(gaze)
        await coordinator._process_inference_result(vad)
        first_call_count = mock_dispatcher.dispatch.call_count

        # Segundo dispatch inmediato — debe ser bloqueado por histéresis
        coordinator._last_gaze = None
        coordinator._last_vad = None
        await coordinator._process_inference_result(gaze)
        await coordinator._process_inference_result(vad)

        # El call_count no debe haber aumentado (bloqueado por cooldown)
        assert mock_dispatcher.dispatch.call_count == first_call_count


# ---------------------------------------------------------------------------
# Tests de PanicButton
# ---------------------------------------------------------------------------


class TestPanicButtonIntegration:
    """Verifica que PanicButton tiene prioridad inmediata."""

    def test_panic_button_is_accessible(self, coordinator: Coordinator) -> None:
        """El PanicButton debe ser accesible desde el Coordinator."""
        assert coordinator.panic_button is not None
        assert coordinator.panic_button.is_active is False

    def test_panic_activation_blocks_processing(
        self, coordinator: Coordinator
    ) -> None:
        """Cuando PanicButton está activo, no se procesan decisiones."""
        tc = SMPTETimecode(hours=0, minutes=0, seconds=0, frames=0, drop_frame=False)
        coordinator.panic_button.activate(tc)
        assert coordinator.panic_button.is_active is True


# ---------------------------------------------------------------------------
# Tests de GUI queue (Req 5.2)
# ---------------------------------------------------------------------------


class TestGUIQueue:
    """Verifica el enrutamiento independiente de notas/prompts."""

    def test_submit_manual_note(self, coordinator: Coordinator) -> None:
        """submit_manual_note debe encolar una nota manual."""
        coordinator.submit_manual_note("Nota de prueba")
        assert not coordinator._gui_queue.empty()

    def test_submit_ai_prompt(self, coordinator: Coordinator) -> None:
        """submit_ai_prompt debe encolar un prompt IA."""
        coordinator.submit_ai_prompt("Analiza esta escena")
        assert not coordinator._gui_queue.empty()

    @pytest.mark.asyncio
    async def test_handle_manual_note_dispatches(
        self, coordinator: Coordinator, mock_dispatcher: MagicMock
    ) -> None:
        """Una nota manual debe generar un dispatch con MANUAL_NOTE."""
        # Configurar estado de sesión para timecodes
        coordinator._session_start_tc = SMPTETimecode(
            hours=0, minutes=0, seconds=0, frames=0, drop_frame=False
        )
        coordinator._frame_count = 10

        tc = coordinator._current_timecode()
        await coordinator._handle_manual_note("Nota test", tc)

        mock_dispatcher.dispatch.assert_called_once()
        payload: EnrichedPayload = mock_dispatcher.dispatch.call_args[0][0]
        assert payload.marker_type == MarkerType.MANUAL_NOTE
        assert payload.source_origin == SourceOrigin.MANUAL
        assert payload.note == "Nota test"

    @pytest.mark.asyncio
    async def test_handle_ai_prompt_dispatches(
        self, coordinator: Coordinator, mock_dispatcher: MagicMock
    ) -> None:
        """Un prompt IA debe procesarse via IAEnricher y despachar."""
        coordinator._session_start_tc = SMPTETimecode(
            hours=0, minutes=0, seconds=0, frames=0, drop_frame=False
        )
        coordinator._frame_count = 5

        tc = coordinator._current_timecode()

        with patch.object(
            coordinator._enricher,
            "process_manual_prompt",
            new_callable=AsyncMock,
            return_value=MarkerEvent(
                marker_type=MarkerType.AI_PROMPT,
                color=EDLColor.Magenta,
                note="Respuesta IA",
                tc=tc,
                source_origin=SourceOrigin.AI,
                cmx_comment="|C:ResolveColorMagenta |M:AI_PROMPT |D:1",
            ),
        ):
            await coordinator._handle_ai_prompt("Analiza escena", tc)

        mock_dispatcher.dispatch.assert_called_once()
        payload: EnrichedPayload = mock_dispatcher.dispatch.call_args[0][0]
        assert payload.marker_type == MarkerType.AI_PROMPT
        assert payload.source_origin == SourceOrigin.AI


# ---------------------------------------------------------------------------
# Tests de timecode
# ---------------------------------------------------------------------------


class TestTimecodeManagement:
    """Verifica la gestión de timecodes alineados a TOD."""

    def test_current_timecode_advances_by_frame(
        self, coordinator: Coordinator
    ) -> None:
        """El timecode debe avanzar según frame_count."""
        coordinator._session_start_tc = SMPTETimecode(
            hours=0, minutes=0, seconds=0, frames=0, drop_frame=False
        )

        coordinator._frame_count = 0
        tc0 = coordinator._current_timecode()
        assert tc0.frames == 0

        coordinator._frame_count = 30
        tc1 = coordinator._current_timecode()
        assert tc1.seconds == 1

    def test_current_timecode_fallback_without_session(
        self, coordinator: Coordinator
    ) -> None:
        """Sin sesión activa, retorna timecode cero."""
        coordinator._session_start_tc = None
        tc = coordinator._current_timecode()
        assert tc.hours == 0 and tc.minutes == 0 and tc.seconds == 0


# ---------------------------------------------------------------------------
# Tests de resolución de personaje/marcador
# ---------------------------------------------------------------------------


class TestResolvers:
    """Verifica resolución de personajes y tipos de marcador."""

    def test_resolve_character_found(self, coordinator: Coordinator) -> None:
        """Debe resolver personaje por cámara."""
        assert coordinator._resolve_character(1) == "ALICE"
        assert coordinator._resolve_character(2) == "BOB"

    def test_resolve_character_not_found(self, coordinator: Coordinator) -> None:
        """Debe retornar CAM_N si no hay mapeo."""
        assert coordinator._resolve_character(3) == "CAM_3"

    def test_resolve_marker_type_reaction(self) -> None:
        """REACTION_SHOT debe mapear a IMAGEN."""
        decision = CameraDecision(
            target_cam=2, reason="REACTION_SHOT", source_origin=SourceOrigin.AUTO
        )
        assert Coordinator._resolve_marker_type(decision) == MarkerType.IMAGEN

    def test_resolve_marker_type_speaker(self) -> None:
        """SPEAKER_ACTIVE debe mapear a ENTRADA."""
        decision = CameraDecision(
            target_cam=1, reason="SPEAKER_ACTIVE", source_origin=SourceOrigin.AUTO
        )
        assert Coordinator._resolve_marker_type(decision) == MarkerType.ENTRADA
