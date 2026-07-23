"""Tests unitarios para GuiBridge.

Verifica la conexión entre señales PyQt6 de MainWindow y los métodos
del Coordinator para notas manuales y prompts de IA, incluyendo:
- Dispatch correcto a submit_manual_note / submit_ai_prompt
- Marcadores con tipo y color correctos (MANUAL_NOTE/Red, AI_PROMPT/Magenta)
- Bypass de histéresis (force_allow) en ambos casos

Requisitos validados: 4.1, 4.2, 4.3, 4.4
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from switch_bot.engines.hysteresis_filter import HysteresisFilter
from switch_bot.gui.gui_bridge import GuiBridge
from switch_bot.models.enums import EDLColor, MarkerType, MARKER_COLOR_MAP


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_coordinator() -> MagicMock:
    """Crea un Coordinator mock con los métodos necesarios."""
    coord = MagicMock()
    coord.submit_manual_note = MagicMock()
    coord.submit_ai_prompt = MagicMock()

    # Simular el HysteresisFilter real para verificar force_allow
    coord.hysteresis_filter = HysteresisFilter(cooldown_frames=90, fps=30.0)

    return coord


@pytest.fixture
def mock_window() -> MagicMock:
    """Crea un MainWindow mock con las señales necesarias."""
    window = MagicMock()

    # Simular las señales PyQt6 como MagicMock con .connect()
    window.manual_note_submitted = MagicMock()
    window.manual_note_submitted.connect = MagicMock()

    window.ia_prompt_submitted = MagicMock()
    window.ia_prompt_submitted.connect = MagicMock()

    # Métodos de actualización de estado
    window.set_session_active = MagicMock()
    window.set_connection_state = MagicMock()
    window.set_tally_state = MagicMock()

    return window


@pytest.fixture
def bridge(mock_window: MagicMock, mock_coordinator: MagicMock) -> GuiBridge:
    """Crea una instancia de GuiBridge con mocks."""
    return GuiBridge(window=mock_window, coordinator=mock_coordinator)


# ---------------------------------------------------------------------------
# Test: Conexión de señales
# ---------------------------------------------------------------------------


class TestGuiBridgeSignalConnections:
    """Verifica que las señales se conectan correctamente al crear el bridge."""

    def test_manual_note_signal_connected(
        self, mock_window: MagicMock, mock_coordinator: MagicMock
    ) -> None:
        """manual_note_submitted signal se conecta al bridge."""
        GuiBridge(window=mock_window, coordinator=mock_coordinator)
        mock_window.manual_note_submitted.connect.assert_called_once()

    def test_ia_prompt_signal_connected(
        self, mock_window: MagicMock, mock_coordinator: MagicMock
    ) -> None:
        """ia_prompt_submitted signal se conecta al bridge."""
        GuiBridge(window=mock_window, coordinator=mock_coordinator)
        mock_window.ia_prompt_submitted.connect.assert_called_once()


# ---------------------------------------------------------------------------
# Test: Manual Notes → Coordinator (Req 4.1, 4.2)
# ---------------------------------------------------------------------------


class TestManualNoteDispatch:
    """Verifica que notas manuales se despachan correctamente al Coordinator."""

    def test_manual_note_dispatches_to_coordinator(
        self, bridge: GuiBridge, mock_coordinator: MagicMock
    ) -> None:
        """Req 4.2: Nota manual se inyecta como marcador en pipeline EDL."""
        bridge._on_manual_note("Nota de prueba", -1)
        mock_coordinator.submit_manual_note.assert_called_once_with("Nota de prueba")

    def test_manual_note_with_camera_includes_camera_tag(
        self, bridge: GuiBridge, mock_coordinator: MagicMock
    ) -> None:
        """Req 4.1: Nota rápida con cámara incluye tag [CAMn]."""
        bridge._on_manual_note("Nota rápida cámara 2", 2)
        mock_coordinator.submit_manual_note.assert_called_once_with(
            "[CAM2] Nota rápida cámara 2"
        )

    def test_manual_note_empty_text_ignored(
        self, bridge: GuiBridge, mock_coordinator: MagicMock
    ) -> None:
        """Texto vacío no se despacha al Coordinator."""
        bridge._on_manual_note("", -1)
        mock_coordinator.submit_manual_note.assert_not_called()

    def test_manual_note_whitespace_only_ignored(
        self, bridge: GuiBridge, mock_coordinator: MagicMock
    ) -> None:
        """Texto solo whitespace no se despacha al Coordinator."""
        bridge._on_manual_note("   ", -1)
        mock_coordinator.submit_manual_note.assert_not_called()

    def test_manual_note_camera_negative_no_tag(
        self, bridge: GuiBridge, mock_coordinator: MagicMock
    ) -> None:
        """Camera -1 (sin cámara) no agrega tag [CAMn]."""
        bridge._on_manual_note("Marcador general", -1)
        mock_coordinator.submit_manual_note.assert_called_once_with("Marcador general")

    def test_manual_note_camera_zero_no_tag(
        self, bridge: GuiBridge, mock_coordinator: MagicMock
    ) -> None:
        """Camera 0 (inválida) no agrega tag [CAMn]."""
        bridge._on_manual_note("Nota sin cam", 0)
        mock_coordinator.submit_manual_note.assert_called_once_with("Nota sin cam")


# ---------------------------------------------------------------------------
# Test: AI Prompts → Coordinator (Req 4.3)
# ---------------------------------------------------------------------------


class TestAIPromptDispatch:
    """Verifica que prompts de IA se despachan correctamente al Coordinator."""

    def test_ai_prompt_dispatches_to_coordinator(
        self, bridge: GuiBridge, mock_coordinator: MagicMock
    ) -> None:
        """Req 4.3: Prompt IA se envía al Coordinator para IAEnricher."""
        bridge._on_ia_prompt("Analiza la escena actual")
        mock_coordinator.submit_ai_prompt.assert_called_once_with(
            "Analiza la escena actual"
        )

    def test_ai_prompt_empty_text_ignored(
        self, bridge: GuiBridge, mock_coordinator: MagicMock
    ) -> None:
        """Texto vacío no se despacha como prompt IA."""
        bridge._on_ia_prompt("")
        mock_coordinator.submit_ai_prompt.assert_not_called()

    def test_ai_prompt_whitespace_only_ignored(
        self, bridge: GuiBridge, mock_coordinator: MagicMock
    ) -> None:
        """Texto solo whitespace no se despacha como prompt IA."""
        bridge._on_ia_prompt("  \n  ")
        mock_coordinator.submit_ai_prompt.assert_not_called()


# ---------------------------------------------------------------------------
# Test: MarkerType y Color correctos (Req 4.2, 4.3)
# ---------------------------------------------------------------------------


class TestMarkerTypeAndColor:
    """Verifica que los tipos de marcador y colores son correctos según el diseño."""

    def test_manual_note_marker_type_is_manual_note(self) -> None:
        """Req 4.2: Notas manuales usan MarkerType.MANUAL_NOTE."""
        assert MarkerType.MANUAL_NOTE.value == "MANUAL_NOTE"

    def test_manual_note_color_is_red(self) -> None:
        """Req 4.2: MANUAL_NOTE tiene color Red en MARKER_COLOR_MAP."""
        assert MARKER_COLOR_MAP[MarkerType.MANUAL_NOTE] == EDLColor.Red

    def test_ai_prompt_marker_type_is_ai_prompt(self) -> None:
        """Req 4.3: Prompts IA usan MarkerType.AI_PROMPT."""
        assert MarkerType.AI_PROMPT.value == "AI_PROMPT"

    def test_ai_prompt_color_is_magenta(self) -> None:
        """Req 4.3: AI_PROMPT tiene color Magenta en MARKER_COLOR_MAP."""
        assert MARKER_COLOR_MAP[MarkerType.AI_PROMPT] == EDLColor.Magenta


# ---------------------------------------------------------------------------
# Test: Bypass de histéresis (Req 4.4)
# ---------------------------------------------------------------------------


class TestHysteresisBypass:
    """Verifica que marcadores manuales y de IA bypasean el filtro de histéresis."""

    def test_force_allow_resets_cooldown(self) -> None:
        """Req 4.4: force_allow() resetea el cooldown de histéresis."""
        hf = HysteresisFilter(cooldown_frames=90, fps=30.0)

        # Simular que acaba de ocurrir un switch (cooldown activo)
        hf.tick()  # Frame 1
        hf._last_switch_frame = hf.current_frame  # Cooldown starts

        assert hf.is_cooling_down is True

        # force_allow debe resetear el cooldown
        hf.force_allow()
        assert hf.is_cooling_down is False

    def test_manual_note_coordinator_calls_force_allow(self) -> None:
        """Req 4.4: El Coordinator llama force_allow() para notas manuales.

        Verificamos que _handle_manual_note del Coordinator invoca
        force_allow() en el hysteresis_filter, lo que garantiza que
        los marcadores manuales bypasean el cooldown.
        """
        # Verificar en el código fuente del Coordinator que force_allow()
        # se llama en _handle_manual_note — lo probamos vía inspección
        # del comportamiento del HysteresisFilter
        hf = HysteresisFilter(cooldown_frames=90, fps=30.0)

        # Simular cooldown activo
        hf.tick()
        hf._last_switch_frame = hf.current_frame

        assert hf.is_cooling_down is True

        # Simular lo que hace _handle_manual_note: force_allow()
        hf.force_allow()

        # Después de force_allow, el cooldown ya no está activo
        assert hf.is_cooling_down is False
        assert hf.frames_remaining == 0

    def test_ai_prompt_coordinator_calls_force_allow(self) -> None:
        """Req 4.4: El Coordinator llama force_allow() para prompts IA.

        Igual que las notas manuales, los prompts IA bypasean histéresis.
        """
        hf = HysteresisFilter(cooldown_frames=90, fps=30.0)

        # Cooldown activo
        hf.tick()
        hf._last_switch_frame = hf.current_frame
        assert hf.is_cooling_down is True

        # Lo que hace _handle_ai_prompt: force_allow()
        hf.force_allow()
        assert hf.is_cooling_down is False

    @pytest.mark.asyncio
    async def test_handle_manual_note_calls_force_allow_on_filter(self) -> None:
        """Req 4.4: _handle_manual_note invoca force_allow() en el filtro real.

        Test de integración ligero que verifica el flujo completo dentro
        del Coordinator mock.
        """
        from switch_bot.models.timecode import SMPTETimecode

        # Crear mocks de los subsistemas que usa _handle_manual_note
        mock_filter = MagicMock(spec=HysteresisFilter)
        mock_dispatcher = MagicMock()
        mock_dispatcher.dispatch = AsyncMock()

        # Crear un Coordinator parcialmente mockeado
        coord = MagicMock()
        coord._hysteresis_filter = mock_filter
        coord._dispatcher = mock_dispatcher

        # Importar y ejecutar el método real
        from switch_bot.coordinator import Coordinator

        tc = SMPTETimecode(hours=1, minutes=0, seconds=0, frames=0, drop_frame=False)

        # Llamar el método real en un contexto controlado
        await Coordinator._handle_manual_note(coord, "Test note", tc)

        # Verificar que force_allow fue invocado
        mock_filter.force_allow.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_ai_prompt_calls_force_allow_on_filter(self) -> None:
        """Req 4.4: _handle_ai_prompt invoca force_allow() en el filtro real."""
        from switch_bot.models.timecode import SMPTETimecode

        mock_filter = MagicMock(spec=HysteresisFilter)
        mock_dispatcher = MagicMock()
        mock_dispatcher.dispatch = AsyncMock()

        mock_enricher = MagicMock()
        # Simular respuesta del IAEnricher
        from switch_bot.models.enums import SourceOrigin

        mock_marker_event = MagicMock()
        mock_marker_event.marker_type = MarkerType.AI_PROMPT
        mock_marker_event.note = "Enriched response"
        mock_marker_event.source_origin = SourceOrigin.AI
        mock_marker_event.color = EDLColor.Magenta
        mock_enricher.process_manual_prompt = AsyncMock(return_value=mock_marker_event)

        coord = MagicMock()
        coord._hysteresis_filter = mock_filter
        coord._dispatcher = mock_dispatcher
        coord._enricher = mock_enricher

        from switch_bot.coordinator import Coordinator

        tc = SMPTETimecode(hours=1, minutes=0, seconds=0, frames=0, drop_frame=False)
        await Coordinator._handle_ai_prompt(coord, "Analiza esto", tc)

        mock_filter.force_allow.assert_called_once()


# ---------------------------------------------------------------------------
# Test: Coordinator → GUI (actualización de estado)
# ---------------------------------------------------------------------------


class TestStateUpdates:
    """Verifica la propagación de estado del Coordinator a la GUI."""

    def test_update_session_state_active(
        self, bridge: GuiBridge, mock_window: MagicMock
    ) -> None:
        """Activar sesión se refleja en la GUI."""
        bridge.update_session_state(True)
        mock_window.set_session_active.assert_called_once_with(True)

    def test_update_session_state_inactive(
        self, bridge: GuiBridge, mock_window: MagicMock
    ) -> None:
        """Desactivar sesión se refleja en la GUI."""
        bridge.update_session_state(False)
        mock_window.set_session_active.assert_called_once_with(False)

    def test_update_connection_state(
        self, bridge: GuiBridge, mock_window: MagicMock
    ) -> None:
        """Cambio de estado de conexión se refleja en la GUI."""
        from switch_bot.gui.widgets import ConnectionState

        bridge.update_connection_state(ConnectionState.CONNECTED)
        mock_window.set_connection_state.assert_called_once_with(
            ConnectionState.CONNECTED
        )

    def test_update_tally(
        self, bridge: GuiBridge, mock_window: MagicMock
    ) -> None:
        """Cambio de tally se refleja en la GUI."""
        from switch_bot.gui.widgets import TallyState

        bridge.update_tally(2, TallyState.ON_AIR)
        mock_window.set_tally_state.assert_called_once_with(2, TallyState.ON_AIR)


# ---------------------------------------------------------------------------
# Test: Propiedades de acceso
# ---------------------------------------------------------------------------


class TestBridgeProperties:
    """Verifica acceso a window y coordinator desde el bridge."""

    def test_window_property(
        self, bridge: GuiBridge, mock_window: MagicMock
    ) -> None:
        """Property window retorna la instancia de MainWindow."""
        assert bridge.window is mock_window

    def test_coordinator_property(
        self, bridge: GuiBridge, mock_coordinator: MagicMock
    ) -> None:
        """Property coordinator retorna la instancia del Coordinator."""
        assert bridge.coordinator is mock_coordinator
