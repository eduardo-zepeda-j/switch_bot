"""Puente entre señales PyQt6 de la GUI y el Coordinator asyncio.

Conecta las señales de MainWindow a los métodos síncronos del Coordinator,
manejando la comunicación thread-safe entre el hilo de Qt y el event loop
asyncio del Coordinator (ambos corren en el proceso principal).

Requisitos: 4.1, 4.2, 4.3, 4.4, 5.2, 17.5
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, pyqtSlot

from switch_bot.gui.ad_suggestions_dialog import AdSuggestionsDialog

if TYPE_CHECKING:
    from switch_bot.coordinator import Coordinator
    from switch_bot.gui.main_window import MainWindow
    from switch_bot.gui.widgets import ConnectionState, TallyState

logger = logging.getLogger(__name__)


class GuiBridge(QObject):
    """Puente bidireccional entre MainWindow (PyQt6) y Coordinator (asyncio).

    Responsabilidades:
    - Conectar señales de la GUI a métodos del Coordinator (GUI → Coordinator)
    - Propagar cambios de estado del Coordinator a la GUI (Coordinator → GUI)
    - Garantizar thread-safety usando el mecanismo signal/slot de Qt

    Dado que la GUI y el Coordinator corren en el mismo proceso principal
    (arquitectura: "Proceso Principal (GUI + Coordinador)"), la conexión
    se realiza directamente via signal/slot sin necesidad de IPC externo.
    Los métodos submit_manual_note() y submit_ai_prompt() del Coordinator
    son thread-safe (ponen items en asyncio.Queue desde cualquier hilo).

    Args:
        window: Instancia de MainWindow con las señales de la GUI.
        coordinator: Instancia del Coordinator con los métodos de inyección.
        parent: Padre Qt opcional.
    """

    def __init__(
        self,
        window: MainWindow,
        coordinator: Coordinator,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._window = window
        self._coordinator = coordinator
        self._connect_signals()

    # ------------------------------------------------------------------
    # Conexión de señales
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        """Conecta las señales de MainWindow a los slots del bridge."""
        # Notas manuales → Coordinator.submit_manual_note (Req 4.1, 4.2)
        self._window.manual_note_submitted.connect(self._on_manual_note)

        # Prompts de IA → Coordinator.submit_ai_prompt (Req 4.3)
        self._window.ia_prompt_submitted.connect(self._on_ia_prompt)

        logger.debug("GuiBridge: Señales de GUI conectadas al Coordinator.")

    # ------------------------------------------------------------------
    # Slots — GUI → Coordinator
    # ------------------------------------------------------------------

    @pyqtSlot(str, int)
    def _on_manual_note(self, text: str, camera: int) -> None:
        """Recibe nota manual de la GUI y la envía al Coordinator.

        El Coordinator la procesará como marcador MANUAL_NOTE con color Red
        y bypass de histéresis (Req 4.1, 4.2, 4.4).

        Args:
            text: Texto de la nota manual.
            camera: Número de cámara asociada (-1 si no aplica).
        """
        if not text.strip():
            return

        # Incluir referencia a cámara si se proporcionó
        note_text = text if camera < 1 else f"[CAM{camera}] {text}"

        self._coordinator.submit_manual_note(note_text)
        logger.info("GuiBridge: Nota manual enviada → '%s'", note_text[:50])

    @pyqtSlot(str)
    def _on_ia_prompt(self, prompt: str) -> None:
        """Recibe prompt de IA de la GUI y lo envía al Coordinator.

        El Coordinator lo procesará via IAEnricher → marcador AI_PROMPT
        con color Magenta y bypass de histéresis (Req 4.3, 4.4).

        Args:
            prompt: Texto del prompt para el enriquecedor IA.
        """
        if not prompt.strip():
            return

        self._coordinator.submit_ai_prompt(prompt)
        logger.info("GuiBridge: Prompt IA enviado → '%s'", prompt[:50])

    # ------------------------------------------------------------------
    # Coordinator → GUI (métodos de actualización de estado)
    # ------------------------------------------------------------------

    def update_session_state(self, active: bool) -> None:
        """Actualiza la GUI con el estado de sesión del Coordinator.

        Args:
            active: True si la sesión está activa.
        """
        self._window.set_session_active(active)

    def update_connection_state(self, state: ConnectionState) -> None:
        """Actualiza el indicador de conexión en la GUI.

        Args:
            state: Nuevo estado de conexión del backend IA.
        """
        self._window.set_connection_state(state)

    def update_tally(self, camera: int, state: TallyState) -> None:
        """Actualiza el indicador de tally de una cámara en la GUI.

        Args:
            camera: Número de cámara (1-4).
            state: Nuevo estado del tally.
        """
        self._window.set_tally_state(camera, state)

    # ------------------------------------------------------------------
    # Propiedades de acceso
    # ------------------------------------------------------------------

    @property
    def window(self) -> MainWindow:
        """Referencia a la MainWindow conectada."""
        return self._window

    @property
    def coordinator(self) -> Coordinator:
        """Referencia al Coordinator conectado."""
        return self._coordinator

    # ------------------------------------------------------------------
    # Sugerencias publicitarias post-sesión (Req 17.5)
    # ------------------------------------------------------------------

    def show_ad_suggestions(self, suggestions: list) -> None:
        """Muestra el diálogo de sugerencias publicitarias al finalizar sesión.

        Presenta las 3 sugerencias generadas por IAEnricher en un diálogo
        modal con timecodes, texto propuesto y score de relevancia.

        Args:
            suggestions: Lista de AdSuggestion generadas por el Coordinator.
        """
        if not suggestions:
            logger.info(
                "GuiBridge: No hay sugerencias publicitarias para mostrar."
            )
            return

        dialog = AdSuggestionsDialog(suggestions, parent=self._window)
        dialog.exec()
        logger.info(
            "GuiBridge: Diálogo de sugerencias publicitarias presentado "
            "(%d sugerencias).",
            len(suggestions),
        )

    async def handle_session_stop(self) -> None:
        """Gestiona el flujo completo de detención de sesión.

        Invoca Coordinator.stop_session(), captura las sugerencias
        generadas y las presenta en el diálogo (Req 17.5).
        """
        suggestions = await self._coordinator.stop_session()
        self.update_session_state(active=False)
        self.show_ad_suggestions(suggestions)
