"""LocalModelsPanel — Panel de descubrimiento de modelos locales.

Proporciona controles para descubrir y seleccionar modelos de IA locales
desde runtimes Ollama o llama.cpp. Incluye selector de runtime, botones
de descubrimiento y refresco, combos de modelos (embedding y LLM), y un
StatusBadge que indica la cantidad de modelos detectados.

Requisitos: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8
"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from switch_bot.gui.credentials import ModelInfo
from switch_bot.gui.status_badge import BadgeState, StatusBadge
from switch_bot.gui.theme import COLORS


class LocalModelsPanel(QWidget):
    """Panel de descubrimiento de modelos locales (Ollama/llama.cpp).

    Signals:
        discover_requested(): Emitido al presionar Descubrir o Refrescar.
        runtime_changed(str): Emitido al cambiar el tipo de runtime.
        model_selected(str, str): Emitido (model_id, model_type).
    """

    discover_requested = pyqtSignal()
    runtime_changed = pyqtSignal(str)
    model_selected = pyqtSignal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()
        self._connect_signals()

    # ------------------------------------------------------------------
    # UI Setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """Configura todos los widgets del panel."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        # --- Sección: Runtime selector ---
        runtime_header = QLabel("Runtime Local")
        runtime_header.setObjectName("sectionHeader")
        runtime_header.setStyleSheet(
            f"color: {COLORS['subtext0']}; font-weight: bold; font-size: 10pt;"
            " background: transparent;"
        )
        layout.addWidget(runtime_header)

        runtime_label = QLabel("Tipo de runtime:")
        runtime_label.setStyleSheet(
            f"color: {COLORS['text']}; background: transparent;"
        )
        layout.addWidget(runtime_label)

        self._runtime_combo = QComboBox()
        self._runtime_combo.addItems(["Ollama", "llama.cpp"])
        self._runtime_combo.setToolTip(
            "Seleccionar el sistema de modelos locales a utilizar"
        )
        layout.addWidget(self._runtime_combo)

        # --- Sección: Descubrimiento ---
        discover_header = QLabel("Descubrimiento de Modelos")
        discover_header.setObjectName("sectionHeader")
        discover_header.setStyleSheet(
            f"color: {COLORS['subtext0']}; font-weight: bold; font-size: 10pt;"
            " background: transparent;"
        )
        layout.addWidget(discover_header)

        # Botones: Descubrir + Refrescar
        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(8)

        self._discover_button = QPushButton("Descubrir Modelos")
        self._discover_button.setToolTip(
            "Consultar el runtime local para detectar modelos disponibles"
        )
        self._discover_button.setStyleSheet(
            f"QPushButton {{ background-color: {COLORS['blue']};"
            f" color: {COLORS['base']}; font-weight: bold;"
            " border-radius: 6px; padding: 8px 16px;"
            f" border: 1px solid {COLORS['blue']}; }}"
            f" QPushButton:hover {{ background-color: {COLORS['text']};"
            f" color: {COLORS['base']}; }}"
            f" QPushButton:disabled {{ background-color: {COLORS['surface1']};"
            f" color: {COLORS['surface2']};"
            f" border-color: {COLORS['surface2']}; }}"
        )
        buttons_row.addWidget(self._discover_button)

        self._refresh_button = QPushButton("⟳")
        self._refresh_button.setFixedWidth(36)
        self._refresh_button.setToolTip(
            "Ejecutar un nuevo descubrimiento de modelos"
        )
        self._refresh_button.setStyleSheet(
            f"QPushButton {{ background-color: {COLORS['surface1']};"
            f" border: 1px solid {COLORS['surface2']};"
            " border-radius: 6px; padding: 4px; }}"
            f" QPushButton:hover {{ background-color: {COLORS['surface2']};"
            f" border-color: {COLORS['blue']}; }}"
            f" QPushButton:disabled {{ background-color: {COLORS['surface0']};"
            f" color: {COLORS['surface2']};"
            f" border-color: {COLORS['surface1']}; }}"
        )
        buttons_row.addWidget(self._refresh_button)

        buttons_row.addStretch()

        # StatusBadge para conteo de modelos
        self._status_badge = StatusBadge("Modelos", BadgeState.DISABLED)
        buttons_row.addWidget(self._status_badge)

        layout.addLayout(buttons_row)

        # --- Sección: Modelos de Embedding ---
        embedding_label = QLabel("Modelo de Embedding:")
        embedding_label.setStyleSheet(
            f"color: {COLORS['text']}; background: transparent;"
        )
        layout.addWidget(embedding_label)

        self._embedding_combo = QComboBox()
        self._embedding_combo.setToolTip(
            "Seleccionar modelo de embeddings para indexación de documentos"
        )
        self._embedding_combo.setPlaceholderText("Sin modelos descubiertos")
        layout.addWidget(self._embedding_combo)

        # --- Sección: Modelos LLM ---
        llm_label = QLabel("Modelo LLM:")
        llm_label.setStyleSheet(
            f"color: {COLORS['text']}; background: transparent;"
        )
        layout.addWidget(llm_label)

        self._llm_combo = QComboBox()
        self._llm_combo.setToolTip(
            "Seleccionar modelo LLM para generación de texto"
        )
        self._llm_combo.setPlaceholderText("Sin modelos descubiertos")
        layout.addWidget(self._llm_combo)

        # --- Mensaje de error (oculto por defecto) ---
        self._error_label = QLabel("")
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet(
            f"color: {COLORS['red']}; background: transparent; font-size: 9pt;"
        )
        self._error_label.setVisible(False)
        layout.addWidget(self._error_label)

        layout.addStretch()

        # Estilo general del panel
        self.setObjectName("localModelsPanel")
        self.setStyleSheet(
            f"QWidget#localModelsPanel {{"
            f" background-color: {COLORS['surface0']};"
            f" border: 1px solid {COLORS['surface1']};"
            f" border-radius: 8px;"
            f" }}"
        )

    # ------------------------------------------------------------------
    # Signal Connections
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        """Conecta señales internas."""
        self._runtime_combo.currentTextChanged.connect(
            self._on_runtime_changed
        )
        self._discover_button.clicked.connect(self.discover_requested.emit)
        self._refresh_button.clicked.connect(self.discover_requested.emit)
        self._embedding_combo.currentIndexChanged.connect(
            self._on_embedding_selected
        )
        self._llm_combo.currentIndexChanged.connect(self._on_llm_selected)

    def _on_runtime_changed(self, runtime: str) -> None:
        """Emite runtime_changed al cambiar el selector."""
        self.runtime_changed.emit(runtime)

    def _on_embedding_selected(self, index: int) -> None:
        """Emite model_selected para el modelo de embedding elegido."""
        if index >= 0:
            model_id = self._embedding_combo.itemData(index)
            if model_id:
                self.model_selected.emit(model_id, "embedding")

    def _on_llm_selected(self, index: int) -> None:
        """Emite model_selected para el modelo LLM elegido."""
        if index >= 0:
            model_id = self._llm_combo.itemData(index)
            if model_id:
                self.model_selected.emit(model_id, "llm")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_runtime(self, runtime: str) -> None:
        """Establece programáticamente el runtime seleccionado.

        Args:
            runtime: "Ollama" o "llama.cpp".
        """
        idx = self._runtime_combo.findText(runtime)
        if idx >= 0:
            self._runtime_combo.setCurrentIndex(idx)

    def populate_models(
        self, embeddings: list[ModelInfo], llms: list[ModelInfo]
    ) -> None:
        """Pobla los combos con los modelos descubiertos.

        Usa ModelInfo.display_text() para el texto visible y almacena
        el model id como item data.

        Args:
            embeddings: Lista de ModelInfo de tipo embedding.
            llms: Lista de ModelInfo de tipo llm.
        """
        # Limpiar sin emitir señales innecesarias
        self._embedding_combo.blockSignals(True)
        self._llm_combo.blockSignals(True)

        self._embedding_combo.clear()
        for model in embeddings:
            self._embedding_combo.addItem(model.display_text(), model.id)

        self._llm_combo.clear()
        for model in llms:
            self._llm_combo.addItem(model.display_text(), model.id)

        self._embedding_combo.blockSignals(False)
        self._llm_combo.blockSignals(False)

        # Ocultar error previo al poblar exitosamente
        self._error_label.setVisible(False)

    def set_discovering(self, discovering: bool) -> None:
        """Activa/desactiva el estado de descubrimiento en progreso.

        Args:
            discovering: True para indicar descubrimiento en curso.
        """
        self._discover_button.setEnabled(not discovering)
        self._refresh_button.setEnabled(not discovering)
        if discovering:
            self._discover_button.setText("Descubriendo...")
            self._error_label.setVisible(False)
        else:
            self._discover_button.setText("Descubrir Modelos")

    def set_error(self, message: str) -> None:
        """Muestra un mensaje de error en el panel.

        Args:
            message: Texto del error a mostrar.
        """
        self._error_label.setText(message)
        self._error_label.setVisible(True)
        self._status_badge.set_state(BadgeState.DISCONNECTED)

    def set_status(self, count: int) -> None:
        """Actualiza el StatusBadge con el conteo de modelos.

        count > 0: badge verde (CONNECTED) con texto de cantidad.
        count == 0: badge desconectado con mensaje informativo.

        Args:
            count: Cantidad total de modelos encontrados.
        """
        if count > 0:
            self._status_badge.set_state(BadgeState.CONNECTED)
            self._error_label.setVisible(False)
        else:
            self._status_badge.set_state(BadgeState.DISCONNECTED)
            self._error_label.setText(
                "No se encontraron modelos instalados en el runtime. "
                "Instale modelos antes de continuar."
            )
            self._error_label.setVisible(True)
