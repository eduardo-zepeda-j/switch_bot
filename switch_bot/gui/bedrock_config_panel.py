"""BedrockConfigPanel — Panel de configuración de credenciales AWS Bedrock.

Proporciona campos para autenticación con AWS Bedrock: credenciales
manuales (Access Key + Secret Key) o perfil AWS CLI, con exclusión
mutua entre ambos métodos. Incluye selector de región, validación
de conexión con feedback visual, y persistencia via QSettings.

Requisitos: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8
"""

from __future__ import annotations

from PyQt6.QtCore import QSettings, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from switch_bot.gui.credentials import deobfuscate_secret, obfuscate_secret
from switch_bot.gui.status_badge import BadgeState, StatusBadge
from switch_bot.gui.theme import COLORS

# Prefijo de claves para QSettings
_SETTINGS_PREFIX = "gui-redesign/v1"

# Regiones estándar de AWS con soporte para Bedrock
_AWS_REGIONS: list[str] = [
    "us-east-1",
    "us-east-2",
    "us-west-1",
    "us-west-2",
    "eu-west-1",
    "eu-west-2",
    "eu-central-1",
    "ap-southeast-1",
    "ap-southeast-2",
    "ap-northeast-1",
    "ap-northeast-2",
    "sa-east-1",
]


class BedrockConfigPanel(QWidget):
    """Panel de configuración de credenciales AWS Bedrock.

    Signals:
        credentials_changed(): Emitido cuando cambian las credenciales.
        validate_requested(): Emitido al presionar Validar.
    """

    credentials_changed = pyqtSignal()
    validate_requested = pyqtSignal()

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

        # --- Sección: Credenciales manuales ---
        manual_header = QLabel("Credenciales manuales")
        manual_header.setObjectName("sectionHeader")
        manual_header.setStyleSheet(
            f"color: {COLORS['subtext0']}; font-weight: bold; font-size: 10pt;"
            " background: transparent;"
        )
        layout.addWidget(manual_header)

        # Access Key ID
        self._access_key_label = QLabel("AWS Access Key ID:")
        self._access_key_label.setStyleSheet(
            f"color: {COLORS['text']}; background: transparent;"
        )
        layout.addWidget(self._access_key_label)

        self._access_key = QLineEdit()
        self._access_key.setMaxLength(128)
        self._access_key.setPlaceholderText("AKIAIOSFODNN7EXAMPLE")
        self._access_key.setToolTip(
            "AWS Access Key ID para autenticación con Bedrock"
        )
        layout.addWidget(self._access_key)

        # Secret Access Key (con toggle de visibilidad)
        self._secret_key_label = QLabel("AWS Secret Access Key:")
        self._secret_key_label.setStyleSheet(
            f"color: {COLORS['text']}; background: transparent;"
        )
        layout.addWidget(self._secret_key_label)

        secret_row = QHBoxLayout()
        secret_row.setSpacing(4)

        self._secret_key = QLineEdit()
        self._secret_key.setMaxLength(128)
        self._secret_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._secret_key.setPlaceholderText("wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")
        self._secret_key.setToolTip(
            "AWS Secret Access Key (se almacena ofuscado)"
        )
        secret_row.addWidget(self._secret_key)

        self._visibility_toggle = QPushButton("👁")
        self._visibility_toggle.setFixedWidth(36)
        self._visibility_toggle.setCheckable(True)
        self._visibility_toggle.setToolTip("Mostrar/ocultar Secret Access Key")
        self._visibility_toggle.setStyleSheet(
            f"QPushButton {{ background-color: {COLORS['surface1']};"
            f" border: 1px solid {COLORS['surface2']};"
            " border-radius: 6px; padding: 4px; }"
            f" QPushButton:checked {{ background-color: {COLORS['blue']};"
            f" color: {COLORS['base']}; }}"
        )
        secret_row.addWidget(self._visibility_toggle)

        layout.addLayout(secret_row)

        # --- Separador visual ---
        separator_label = QLabel("— o —")
        separator_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        separator_label.setStyleSheet(
            f"color: {COLORS['subtext0']}; background: transparent;"
            " font-size: 9pt; padding: 4px 0px;"
        )
        layout.addWidget(separator_label)

        # --- Sección: Perfil AWS CLI ---
        profile_header = QLabel("Perfil AWS CLI")
        profile_header.setObjectName("sectionHeader")
        profile_header.setStyleSheet(
            f"color: {COLORS['subtext0']}; font-weight: bold; font-size: 10pt;"
            " background: transparent;"
        )
        layout.addWidget(profile_header)

        self._profile_label = QLabel("Nombre del perfil:")
        self._profile_label.setStyleSheet(
            f"color: {COLORS['text']}; background: transparent;"
        )
        layout.addWidget(self._profile_label)

        self._profile_name = QLineEdit()
        self._profile_name.setMaxLength(64)
        self._profile_name.setPlaceholderText("default")
        self._profile_name.setToolTip(
            "Nombre del perfil AWS CLI (alternativa a credenciales manuales)"
        )
        layout.addWidget(self._profile_name)

        # --- Región ---
        region_label = QLabel("Región:")
        region_label.setStyleSheet(
            f"color: {COLORS['text']}; background: transparent;"
        )
        layout.addWidget(region_label)

        self._region = QComboBox()
        self._region.addItems(_AWS_REGIONS)
        self._region.setToolTip("Región de AWS donde está habilitado Bedrock")
        layout.addWidget(self._region)

        # --- Validación ---
        validation_row = QHBoxLayout()
        validation_row.setSpacing(8)

        self._validate_button = QPushButton("Validar")
        self._validate_button.setToolTip("Validar conexión con AWS Bedrock")
        self._validate_button.setStyleSheet(
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
        validation_row.addWidget(self._validate_button)

        self._status_badge = StatusBadge("Bedrock", BadgeState.DISABLED)
        validation_row.addWidget(self._status_badge)

        validation_row.addStretch()
        layout.addLayout(validation_row)

        # Mensaje de validación (errores, etc.)
        self._validation_message = QLabel("")
        self._validation_message.setWordWrap(True)
        self._validation_message.setStyleSheet(
            f"color: {COLORS['subtext0']}; background: transparent;"
            " font-size: 9pt;"
        )
        self._validation_message.setVisible(False)
        layout.addWidget(self._validation_message)

        layout.addStretch()

        # Estilo general del panel
        self.setObjectName("bedrockConfigPanel")
        self.setStyleSheet(
            f"QWidget#bedrockConfigPanel {{"
            f" background-color: {COLORS['surface0']};"
            f" border: 1px solid {COLORS['surface1']};"
            f" border-radius: 8px;"
            f" }}"
        )

    # ------------------------------------------------------------------
    # Signal Connections
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        """Conecta señales internas para exclusión mutua y notificaciones."""
        # Exclusión mutua
        self._access_key.textChanged.connect(self._on_manual_changed)
        self._secret_key.textChanged.connect(self._on_manual_changed)
        self._profile_name.textChanged.connect(self._on_profile_changed)

        # Notificar cambios de credenciales
        self._access_key.textChanged.connect(self._emit_credentials_changed)
        self._secret_key.textChanged.connect(self._emit_credentials_changed)
        self._profile_name.textChanged.connect(self._emit_credentials_changed)
        self._region.currentIndexChanged.connect(self._emit_credentials_changed)

        # Toggle visibilidad
        self._visibility_toggle.toggled.connect(self._on_visibility_toggled)

        # Botón validar
        self._validate_button.clicked.connect(self.validate_requested.emit)

    # ------------------------------------------------------------------
    # Mutual Exclusion Logic
    # ------------------------------------------------------------------

    def _on_manual_changed(self) -> None:
        """Cuando se escriben credenciales manuales, deshabilitar perfil."""
        has_manual = bool(
            self._access_key.text().strip() or self._secret_key.text().strip()
        )
        self._profile_name.setEnabled(not has_manual)

    def _on_profile_changed(self) -> None:
        """Cuando se escribe un perfil, deshabilitar credenciales manuales."""
        has_profile = bool(self._profile_name.text().strip())
        self._access_key.setEnabled(not has_profile)
        self._secret_key.setEnabled(not has_profile)
        self._visibility_toggle.setEnabled(not has_profile)

    # ------------------------------------------------------------------
    # Visibility Toggle
    # ------------------------------------------------------------------

    def _on_visibility_toggled(self, checked: bool) -> None:
        """Cambia el modo de visualización del secret key."""
        if checked:
            self._secret_key.setEchoMode(QLineEdit.EchoMode.Normal)
        else:
            self._secret_key.setEchoMode(QLineEdit.EchoMode.Password)

    # ------------------------------------------------------------------
    # Credential Change Notification
    # ------------------------------------------------------------------

    def _emit_credentials_changed(self) -> None:
        """Emite la señal credentials_changed."""
        self.credentials_changed.emit()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_credentials(self) -> dict:
        """Retorna las credenciales configuradas actualmente.

        Returns:
            Dict con las claves: access_key, secret_key, region, profile_name.
            Los campos vacíos se retornan como cadena vacía.
        """
        return {
            "access_key": self._access_key.text().strip(),
            "secret_key": self._secret_key.text().strip(),
            "region": self._region.currentText(),
            "profile_name": self._profile_name.text().strip(),
        }

    def set_validation_state(self, state: BadgeState, message: str = "") -> None:
        """Actualiza el estado visual de la validación.

        Args:
            state: Estado del badge (CONNECTED=ok, DISCONNECTED=error, etc.).
            message: Mensaje descriptivo opcional (se muestra si no está vacío).
        """
        self._status_badge.set_state(state)

        # Re-habilitar botón validar al recibir resultado
        self._validate_button.setEnabled(True)
        self._validate_button.setText("Validar")

        # Mostrar mensaje si hay
        if message:
            self._validation_message.setText(message)
            self._validation_message.setVisible(True)

            # Color del mensaje según estado
            if state == BadgeState.DISCONNECTED:
                color = COLORS["red"]
            elif state == BadgeState.CONNECTED:
                color = COLORS["green"]
            else:
                color = COLORS["subtext0"]

            self._validation_message.setStyleSheet(
                f"color: {color}; background: transparent; font-size: 9pt;"
            )
        else:
            self._validation_message.setVisible(False)

    def set_validating(self, validating: bool) -> None:
        """Activa/desactiva el estado de validación en progreso.

        Args:
            validating: True para indicar validación en curso, False para restablecer.
        """
        self._validate_button.setEnabled(not validating)
        if validating:
            self._validate_button.setText("Validando...")
            self._status_badge.set_state(BadgeState.RECONNECTING)
            self._validation_message.setVisible(False)
        else:
            self._validate_button.setText("Validar")

    # ------------------------------------------------------------------
    # Persistence (QSettings)
    # ------------------------------------------------------------------

    def load_settings(self, settings: QSettings) -> None:
        """Carga credenciales desde QSettings.

        El secret_key se almacena ofuscado — se desofusca al cargar.

        Args:
            settings: Instancia de QSettings de la aplicación.
        """
        settings.beginGroup(_SETTINGS_PREFIX)

        region = settings.value("backend/bedrock_region", "us-east-1", type=str)
        idx = self._region.findText(region)
        if idx >= 0:
            self._region.setCurrentIndex(idx)

        profile = settings.value("backend/bedrock_profile", "", type=str)
        self._profile_name.setText(profile)

        access_key = settings.value("backend/bedrock_access_key", "", type=str)
        self._access_key.setText(access_key)

        stored_secret = settings.value("backend/bedrock_secret_key", "", type=str)
        if stored_secret:
            try:
                secret = deobfuscate_secret(stored_secret)
            except Exception:
                secret = ""
            self._secret_key.setText(secret)

        settings.endGroup()

    def save_settings(self, settings: QSettings) -> None:
        """Guarda credenciales en QSettings.

        El secret_key se almacena ofuscado para evitar texto plano.

        Args:
            settings: Instancia de QSettings de la aplicación.
        """
        settings.beginGroup(_SETTINGS_PREFIX)

        settings.setValue("backend/bedrock_region", self._region.currentText())
        settings.setValue("backend/bedrock_profile", self._profile_name.text().strip())
        settings.setValue("backend/bedrock_access_key", self._access_key.text().strip())

        secret = self._secret_key.text().strip()
        if secret:
            settings.setValue(
                "backend/bedrock_secret_key", obfuscate_secret(secret)
            )
        else:
            settings.setValue("backend/bedrock_secret_key", "")

        settings.endGroup()
