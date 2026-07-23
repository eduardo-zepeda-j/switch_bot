"""Ventana principal de la GUI de Switch_bot.

Implementa todos los controles de sesión, selectores de backend IA,
indicadores de tally, y configuración del sistema. Diseñada para
operación profesional de producción broadcast multicámara.

Requisitos: 4.1, 4.2, 4.3, 9.1, 10.3, 18.1, 18.2, 19.1, 19.2, 19.3, 19.5, 19.7, 19.9
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QFont, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from switch_bot.gui.theme import BASE_STYLESHEET, COLORS
from switch_bot.gui.widgets import (
    ConnectionState,
    StatusDot,
    TallyIndicator,
    TallyState,
    TimecodeDisplay,
)


class MainWindow(QMainWindow):
    """Ventana principal de Switch_bot.

    Proporciona controles para:
    - Selección de backend IA y modelos (Req 19.1, 19.2, 19.3)
    - Indicador de estado de conexión (Req 19.5)
    - Validación y reintento de conexión (Req 19.5)
    - Selector de modo de video/fps (Req 18.1, 18.2)
    - Inicio/parada de sesión
    - Notas manuales y prompts de IA (Req 4.3)
    - Panic Button prominente (Req 9.1)
    - Indicadores de tally para 4 cámaras (Req 10.3)
    - Configuración de IP ATEM, URL OBS, directorio de salida (Req 4.2)
    - Inmutabilidad de configuración durante sesión activa (Req 19.7)

    Signals:
        session_start_requested: Emitido cuando el operador solicita iniciar sesión.
        session_stop_requested: Emitido cuando el operador solicita detener sesión.
        panic_triggered: Emitido cuando se activa el Panic Button.
        validate_connection_requested: Emitido para validar la conexión al backend.
        retry_connection_requested: Emitido para reintentar conexión.
        ia_prompt_submitted: Emitido con el texto del prompt de IA.
        manual_note_submitted: Emitido con texto de nota manual y cámara opcional.
        backend_changed: Emitido cuando cambia la selección de backend.
    """

    # Señales para comunicación con el controlador
    session_start_requested = pyqtSignal()
    session_stop_requested = pyqtSignal()
    panic_triggered = pyqtSignal()
    validate_connection_requested = pyqtSignal()
    retry_connection_requested = pyqtSignal()
    ia_prompt_submitted = pyqtSignal(str)
    manual_note_submitted = pyqtSignal(str, int)  # texto, cámara (-1 = sin cámara)
    backend_changed = pyqtSignal(str)  # "bedrock" o "local"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session_active = False

        self.setWindowTitle("Switch_bot — Control de Producción Multicámara")
        self.setMinimumSize(1200, 700)
        self.setStyleSheet(BASE_STYLESHEET)

        self._setup_ui()
        self._setup_shortcuts()

    # ------------------------------------------------------------------
    # Setup UI
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """Construye toda la interfaz de usuario."""
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Splitter principal: área principal (70%) + panel lateral (30%)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # Área principal
        main_area = QWidget()
        main_area.setObjectName("mainArea")
        main_area_layout = QVBoxLayout(main_area)
        main_area_layout.setContentsMargins(16, 16, 16, 16)
        main_area_layout.setSpacing(8)

        self._build_top_bar(main_area_layout)
        self._build_tally_section(main_area_layout)
        self._build_notes_section(main_area_layout)

        # Panel lateral
        side_panel = QWidget()
        side_panel.setObjectName("sidePanel")
        side_panel.setStyleSheet(
            f"QWidget#sidePanel {{ background-color: {COLORS['mantle']}; }}"
        )
        side_layout = QVBoxLayout(side_panel)
        side_layout.setContentsMargins(16, 16, 16, 16)
        side_layout.setSpacing(8)

        self._build_backend_section(side_layout)
        self._build_video_mode_section(side_layout)
        self._build_config_section(side_layout)
        self._build_session_controls(side_layout)
        side_layout.addStretch()

        splitter.addWidget(main_area)
        splitter.addWidget(side_panel)
        splitter.setSizes([700, 300])

        main_layout.addWidget(splitter)

    # ------------------------------------------------------------------
    # Top Bar: Timecode + Status + Panic
    # ------------------------------------------------------------------

    def _build_top_bar(self, parent_layout: QVBoxLayout) -> None:
        """Construye la barra superior con timecode, estado y panic button."""
        top_bar = QHBoxLayout()
        top_bar.setSpacing(16)

        # Timecode display
        self.timecode_display = TimecodeDisplay(drop_frame=True)
        top_bar.addWidget(self.timecode_display)

        # Session status label
        self._session_status_label = QLabel("Sesión: Inactiva")
        self._session_status_label.setObjectName("statusLabel")
        self._session_status_label.setFont(QFont("Inter", 10))
        top_bar.addWidget(self._session_status_label)

        top_bar.addStretch()

        # Panic Button (prominente)
        self.panic_button = QPushButton("⚠ PANIC")
        self.panic_button.setObjectName("panicButton")
        self.panic_button.setToolTip(
            "Panic Button — Detiene toda automatización inmediatamente\n"
            "Atajo: F12 o Escape"
        )
        self.panic_button.clicked.connect(self.panic_triggered.emit)
        top_bar.addWidget(self.panic_button)

        parent_layout.addLayout(top_bar)

    # ------------------------------------------------------------------
    # Tally Indicators
    # ------------------------------------------------------------------

    def _build_tally_section(self, parent_layout: QVBoxLayout) -> None:
        """Construye la sección de indicadores de tally (4 cámaras)."""
        tally_group = QGroupBox("Tally — Cámaras")
        tally_layout = QHBoxLayout(tally_group)
        tally_layout.setSpacing(12)
        tally_layout.setContentsMargins(16, 24, 16, 16)

        self.tally_indicators: list[TallyIndicator] = []
        for i in range(1, 5):
            indicator = TallyIndicator(camera_number=i)
            indicator.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
            self.tally_indicators.append(indicator)
            tally_layout.addWidget(indicator)

        parent_layout.addWidget(tally_group)

    # ------------------------------------------------------------------
    # Notes / Prompts Section
    # ------------------------------------------------------------------

    def _build_notes_section(self, parent_layout: QVBoxLayout) -> None:
        """Construye la sección de notas manuales y prompts de IA."""
        notes_group = QGroupBox("Notas y Prompts de IA")
        notes_layout = QVBoxLayout(notes_group)
        notes_layout.setSpacing(8)

        # Campo de texto para notas/prompts
        self.notes_text = QTextEdit()
        self.notes_text.setPlaceholderText(
            "Escriba una nota manual o prompt para la IA...\n"
            "Ctrl+Enter para enviar como prompt de IA\n"
            "Space para marcador manual rápido"
        )
        self.notes_text.setMaximumHeight(120)
        self.notes_text.setToolTip(
            "Campo de notas manuales y prompts de IA\n"
            "Ctrl+Enter: Enviar como prompt de IA\n"
            "Space (sin foco): Marcador manual rápido"
        )
        notes_layout.addWidget(self.notes_text)

        # Botones de envío
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self._send_note_btn = QPushButton("📝 Enviar Nota")
        self._send_note_btn.setToolTip("Enviar como nota manual de operador")
        self._send_note_btn.clicked.connect(self._on_send_note)
        btn_layout.addWidget(self._send_note_btn)

        self._send_prompt_btn = QPushButton("🤖 Enviar Prompt IA")
        self._send_prompt_btn.setToolTip(
            "Enviar texto como prompt al modelo de IA\nAtajo: Ctrl+Enter"
        )
        self._send_prompt_btn.setStyleSheet(
            f"QPushButton {{ border-color: {COLORS['magenta']}; }}"
            f"QPushButton:hover {{ background-color: {COLORS['magenta']}; color: {COLORS['crust']}; }}"
        )
        self._send_prompt_btn.clicked.connect(self._on_send_prompt)
        btn_layout.addWidget(self._send_prompt_btn)

        btn_layout.addStretch()
        notes_layout.addLayout(btn_layout)

        parent_layout.addWidget(notes_group, stretch=1)

    # ------------------------------------------------------------------
    # Side Panel: Backend IA
    # ------------------------------------------------------------------

    def _build_backend_section(self, parent_layout: QVBoxLayout) -> None:
        """Construye la sección de selección de backend IA."""
        backend_group = QGroupBox("Backend IA")
        layout = QVBoxLayout(backend_group)
        layout.setSpacing(8)

        # Selector de backend
        lbl_backend = QLabel("Backend:")
        lbl_backend.setObjectName("sectionHeader")
        layout.addWidget(lbl_backend)

        self.backend_combo = QComboBox()
        self.backend_combo.addItems(["AWS Bedrock", "Backend Local"])
        self.backend_combo.setToolTip(
            "Seleccione el backend de IA para enriquecimiento semántico\n"
            "AWS Bedrock: Cloud (Claude 3.5, Titan Embeddings)\n"
            "Backend Local: Ollama o llama.cpp"
        )
        self.backend_combo.currentTextChanged.connect(self._on_backend_changed)
        layout.addWidget(self.backend_combo)

        # Selector de modelo de embeddings
        lbl_emb = QLabel("Modelo Embeddings:")
        layout.addWidget(lbl_emb)

        self.embedding_model_combo = QComboBox()
        self.embedding_model_combo.setToolTip(
            "Modelo de embeddings para similitud semántica"
        )
        layout.addWidget(self.embedding_model_combo)

        # Selector de modelo LLM
        lbl_llm = QLabel("Modelo LLM:")
        layout.addWidget(lbl_llm)

        self.llm_model_combo = QComboBox()
        self.llm_model_combo.setToolTip(
            "Modelo de lenguaje para análisis contextual y sugerencias"
        )
        layout.addWidget(self.llm_model_combo)

        # Estado de conexión
        conn_layout = QHBoxLayout()
        conn_layout.setSpacing(8)

        self.connection_dot = StatusDot(ConnectionState.DISCONNECTED)
        conn_layout.addWidget(self.connection_dot)

        self._connection_label = QLabel("Desconectado")
        self._connection_label.setObjectName("statusLabel")
        conn_layout.addWidget(self._connection_label)
        conn_layout.addStretch()
        layout.addLayout(conn_layout)

        # Botones de conexión
        conn_btn_layout = QHBoxLayout()
        conn_btn_layout.setSpacing(8)

        self.validate_btn = QPushButton("✓ Validar")
        self.validate_btn.setToolTip("Validar conexión con el backend de IA seleccionado")
        self.validate_btn.clicked.connect(self.validate_connection_requested.emit)
        conn_btn_layout.addWidget(self.validate_btn)

        self.retry_btn = QPushButton("↻ Reintentar")
        self.retry_btn.setToolTip("Reintentar la conexión al backend de IA")
        self.retry_btn.clicked.connect(self.retry_connection_requested.emit)
        conn_btn_layout.addWidget(self.retry_btn)

        layout.addLayout(conn_btn_layout)

        parent_layout.addWidget(backend_group)

    # ------------------------------------------------------------------
    # Side Panel: Video Mode
    # ------------------------------------------------------------------

    def _build_video_mode_section(self, parent_layout: QVBoxLayout) -> None:
        """Construye la sección de selección de modo de video/fps."""
        video_group = QGroupBox("Modo de Video")
        layout = QVBoxLayout(video_group)
        layout.setSpacing(8)

        lbl = QLabel("Modo / FPS:")
        layout.addWidget(lbl)

        self.video_mode_combo = QComboBox()
        self.video_mode_combo.addItems([
            "1080p29.97 (Drop Frame)",
            "1080p30",
            "1080p60",
        ])
        self.video_mode_combo.setToolTip(
            "Modo de video y FPS del proyecto\n"
            "Determina la resolución temporal del timecode"
        )
        layout.addWidget(self.video_mode_combo)

        parent_layout.addWidget(video_group)

    # ------------------------------------------------------------------
    # Side Panel: Configuration
    # ------------------------------------------------------------------

    def _build_config_section(self, parent_layout: QVBoxLayout) -> None:
        """Construye la sección de configuración (ATEM, OBS, directorio)."""
        config_group = QGroupBox("Configuración")
        layout = QVBoxLayout(config_group)
        layout.setSpacing(8)

        # ATEM IP
        lbl_atem = QLabel("IP ATEM:")
        layout.addWidget(lbl_atem)

        self.atem_ip_input = QLineEdit()
        self.atem_ip_input.setPlaceholderText("192.168.1.100")
        self.atem_ip_input.setToolTip("Dirección IP del switcher ATEM")
        layout.addWidget(self.atem_ip_input)

        # OBS WebSocket URL
        lbl_obs = QLabel("URL OBS WebSocket:")
        layout.addWidget(lbl_obs)

        self.obs_url_input = QLineEdit()
        self.obs_url_input.setPlaceholderText("ws://localhost:4455")
        self.obs_url_input.setText("ws://localhost:4455")
        self.obs_url_input.setToolTip("URL WebSocket de OBS Studio")
        layout.addWidget(self.obs_url_input)

        # Directorio de salida
        lbl_output = QLabel("Directorio de Salida:")
        layout.addWidget(lbl_output)

        output_layout = QHBoxLayout()
        output_layout.setSpacing(4)

        self.output_dir_input = QLineEdit()
        self.output_dir_input.setPlaceholderText("./output")
        self.output_dir_input.setText("./output")
        self.output_dir_input.setToolTip("Directorio donde se guardan los archivos generados")
        output_layout.addWidget(self.output_dir_input)

        self._browse_btn = QPushButton("...")
        self._browse_btn.setFixedWidth(32)
        self._browse_btn.setToolTip("Seleccionar directorio de salida")
        self._browse_btn.clicked.connect(self._on_browse_output_dir)
        output_layout.addWidget(self._browse_btn)

        layout.addLayout(output_layout)

        parent_layout.addWidget(config_group)

    # ------------------------------------------------------------------
    # Side Panel: Session Controls
    # ------------------------------------------------------------------

    def _build_session_controls(self, parent_layout: QVBoxLayout) -> None:
        """Construye los botones de inicio/parada de sesión."""
        session_group = QGroupBox("Sesión")
        layout = QVBoxLayout(session_group)
        layout.setSpacing(8)

        self.start_session_btn = QPushButton("▶ Iniciar Sesión")
        self.start_session_btn.setObjectName("startButton")
        self.start_session_btn.setToolTip(
            "Iniciar sesión de grabación\nAtajo: Ctrl+S"
        )
        self.start_session_btn.clicked.connect(self.session_start_requested.emit)
        layout.addWidget(self.start_session_btn)

        self.stop_session_btn = QPushButton("■ Detener Sesión")
        self.stop_session_btn.setObjectName("stopButton")
        self.stop_session_btn.setToolTip(
            "Detener sesión de grabación\nAtajo: Ctrl+S"
        )
        self.stop_session_btn.setEnabled(False)
        self.stop_session_btn.clicked.connect(self.session_stop_requested.emit)
        layout.addWidget(self.stop_session_btn)

        parent_layout.addWidget(session_group)

    # ------------------------------------------------------------------
    # Keyboard Shortcuts
    # ------------------------------------------------------------------

    def _setup_shortcuts(self) -> None:
        """Configura atajos de teclado globales."""
        # F12 / Escape — Panic Button
        shortcut_panic_f12 = QShortcut(QKeySequence(Qt.Key.Key_F12), self)
        shortcut_panic_f12.activated.connect(self.panic_triggered.emit)

        shortcut_panic_esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        shortcut_panic_esc.activated.connect(self.panic_triggered.emit)

        # F1-F4 — Nota rápida en cámara 1-4
        for i in range(1, 5):
            key = getattr(Qt.Key, f"Key_F{i}")
            shortcut = QShortcut(QKeySequence(key), self)
            camera_num = i
            shortcut.activated.connect(
                lambda cam=camera_num: self._on_quick_note(cam)
            )

        # Ctrl+Enter — Enviar prompt de IA
        shortcut_prompt = QShortcut(
            QKeySequence(Qt.Modifier.CTRL | Qt.Key.Key_Return), self
        )
        shortcut_prompt.activated.connect(self._on_send_prompt)

        # Space — Marcador manual rápido (solo si notes_text no tiene foco)
        shortcut_space = QShortcut(QKeySequence(Qt.Key.Key_Space), self)
        shortcut_space.activated.connect(self._on_quick_marker)

        # Ctrl+S — Start/Stop sesión
        shortcut_session = QShortcut(
            QKeySequence(Qt.Modifier.CTRL | Qt.Key.Key_S), self
        )
        shortcut_session.activated.connect(self._on_toggle_session)

    # ------------------------------------------------------------------
    # Public API — Métodos para actualizar estado desde controlador
    # ------------------------------------------------------------------

    def set_session_active(self, active: bool) -> None:
        """Marca la sesión como activa/inactiva y actualiza la UI.

        Cuando la sesión está activa, deshabilita selectores de backend
        y modelos para garantizar inmutabilidad de configuración (Req 19.7).

        Args:
            active: True si la sesión está activa.
        """
        self._session_active = active

        if active:
            self._session_status_label.setText("Sesión: ACTIVA")
            self._session_status_label.setStyleSheet(
                f"color: {COLORS['green']}; font-weight: bold;"
            )
            self.start_session_btn.setEnabled(False)
            self.stop_session_btn.setEnabled(True)
            self.timecode_display.start()
        else:
            self._session_status_label.setText("Sesión: Inactiva")
            self._session_status_label.setStyleSheet(f"color: {COLORS['subtext0']};")
            self.start_session_btn.setEnabled(True)
            self.stop_session_btn.setEnabled(False)
            self.timecode_display.stop()

        # Inmutabilidad visual (Req 19.7)
        locked_tooltip = "Sesión activa — configuración bloqueada"
        self.backend_combo.setEnabled(not active)
        self.embedding_model_combo.setEnabled(not active)
        self.llm_model_combo.setEnabled(not active)
        self.validate_btn.setEnabled(not active)
        self.retry_btn.setEnabled(not active)
        self.video_mode_combo.setEnabled(not active)
        self.atem_ip_input.setEnabled(not active)
        self.obs_url_input.setEnabled(not active)
        self.output_dir_input.setEnabled(not active)
        self._browse_btn.setEnabled(not active)

        if active:
            for widget in (
                self.backend_combo,
                self.embedding_model_combo,
                self.llm_model_combo,
                self.validate_btn,
                self.retry_btn,
            ):
                widget.setToolTip(locked_tooltip)

    def set_connection_state(self, state: ConnectionState) -> None:
        """Actualiza el indicador visual de estado de conexión.

        Args:
            state: Nuevo estado de conexión del backend.
        """
        self.connection_dot.set_state(state)
        labels = {
            ConnectionState.CONNECTED: "Conectado",
            ConnectionState.RECONNECTING: "Reconectando...",
            ConnectionState.DISCONNECTED: "Desconectado",
        }
        self._connection_label.setText(labels[state])

    def set_tally_state(self, camera: int, state: TallyState) -> None:
        """Actualiza el estado de tally de una cámara.

        Args:
            camera: Número de cámara (1-4).
            state: Nuevo estado del tally.
        """
        if 1 <= camera <= 4:
            self.tally_indicators[camera - 1].set_state(state)

    def populate_models(
        self,
        embedding_models: list[str],
        llm_models: list[str],
    ) -> None:
        """Puebla los dropdowns de modelos con los disponibles.

        Se invoca después de llamar list_available_models() en el backend.

        Args:
            embedding_models: Lista de IDs de modelos de embeddings.
            llm_models: Lista de IDs de modelos de lenguaje.
        """
        self.embedding_model_combo.clear()
        self.embedding_model_combo.addItems(embedding_models)

        self.llm_model_combo.clear()
        self.llm_model_combo.addItems(llm_models)

    def get_selected_backend(self) -> str:
        """Retorna el tipo de backend seleccionado.

        Returns:
            "bedrock" o "local".
        """
        text = self.backend_combo.currentText()
        return "bedrock" if "Bedrock" in text else "local"

    def get_selected_embedding_model(self) -> str:
        """Retorna el ID del modelo de embeddings seleccionado."""
        return self.embedding_model_combo.currentText()

    def get_selected_llm_model(self) -> str:
        """Retorna el ID del modelo LLM seleccionado."""
        return self.llm_model_combo.currentText()

    def get_video_mode(self) -> str:
        """Retorna el modo de video seleccionado."""
        return self.video_mode_combo.currentText()

    def get_atem_ip(self) -> str:
        """Retorna la IP ATEM configurada."""
        return self.atem_ip_input.text().strip()

    def get_obs_url(self) -> str:
        """Retorna la URL de OBS WebSocket configurada."""
        return self.obs_url_input.text().strip()

    def get_output_dir(self) -> str:
        """Retorna el directorio de salida configurado."""
        return self.output_dir_input.text().strip()

    # ------------------------------------------------------------------
    # Internal Slots
    # ------------------------------------------------------------------

    def _on_backend_changed(self, text: str) -> None:
        """Maneja cambio en el selector de backend."""
        backend_type = "bedrock" if "Bedrock" in text else "local"
        self.backend_changed.emit(backend_type)

    def _on_send_note(self) -> None:
        """Envía el contenido del campo de texto como nota manual."""
        text = self.notes_text.toPlainText().strip()
        if text:
            self.manual_note_submitted.emit(text, -1)
            self.notes_text.clear()

    def _on_send_prompt(self) -> None:
        """Envía el contenido del campo de texto como prompt de IA."""
        text = self.notes_text.toPlainText().strip()
        if text:
            self.ia_prompt_submitted.emit(text)
            self.notes_text.clear()

    def _on_quick_note(self, camera: int) -> None:
        """Genera una nota rápida para una cámara específica."""
        self.manual_note_submitted.emit(f"Nota rápida cámara {camera}", camera)

    def _on_quick_marker(self) -> None:
        """Genera un marcador manual rápido (Space)."""
        # Solo si el campo de notas no tiene foco
        if not self.notes_text.hasFocus():
            self.manual_note_submitted.emit("Marcador manual", -1)

    def _on_toggle_session(self) -> None:
        """Alterna entre iniciar y detener sesión (Ctrl+S)."""
        if self._session_active:
            self.session_stop_requested.emit()
        else:
            self.session_start_requested.emit()

    def _on_browse_output_dir(self) -> None:
        """Abre diálogo para seleccionar directorio de salida."""
        directory = QFileDialog.getExistingDirectory(
            self,
            "Seleccionar directorio de salida",
            self.output_dir_input.text(),
        )
        if directory:
            self.output_dir_input.setText(directory)
