"""Unit tests para BedrockConfigPanel — Validación de comportamiento específico.

Cubre:
- Req 1.3: Secret key enmascarado por defecto, toggle para revelar
- Req 1.6: Botón Validar muestra estado de carga y resultado
- Req 1.7: Credenciales vacías + sin profile → mensaje de error
- Req 1.8: Timeout/error muestra StatusDot rojo con mensaje, botón habilitado para retry
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication, QLineEdit

from switch_bot.gui.bedrock_config_panel import BedrockConfigPanel
from switch_bot.gui.status_badge import BadgeState


@pytest.fixture(scope="session")
def qapp():
    """Ensure a QApplication instance exists for the test session."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture(autouse=True)
def ensure_qapp(qapp):
    """Auto-use fixture to make QApplication available in all tests."""
    return qapp


def _is_visible(widget) -> bool:
    """Check widget's own visibility flag (not affected by parent visibility).

    QWidget.isVisible() returns False when the widget's parent isn't shown.
    isHidden() checks only the widget's own attribute set via setVisible().
    """
    return not widget.isHidden()


class TestVisibilityToggle:
    """Req 1.3: Secret key field masked by default, toggle reveals it."""

    def test_secret_key_masked_by_default(self) -> None:
        """Secret key field uses EchoMode.Password on construction."""
        panel = BedrockConfigPanel()
        assert panel._secret_key.echoMode() == QLineEdit.EchoMode.Password

    def test_toggle_unchecked_by_default(self) -> None:
        """Visibility toggle starts unchecked (secret hidden)."""
        panel = BedrockConfigPanel()
        assert panel._visibility_toggle.isChecked() is False

    def test_toggle_checked_reveals_secret(self) -> None:
        """Checking the visibility toggle sets EchoMode.Normal."""
        panel = BedrockConfigPanel()
        panel._visibility_toggle.setChecked(True)
        assert panel._secret_key.echoMode() == QLineEdit.EchoMode.Normal

    def test_toggle_unchecked_hides_secret(self) -> None:
        """Unchecking the toggle restores EchoMode.Password."""
        panel = BedrockConfigPanel()
        # First reveal, then hide
        panel._visibility_toggle.setChecked(True)
        panel._visibility_toggle.setChecked(False)
        assert panel._secret_key.echoMode() == QLineEdit.EchoMode.Password

    def test_toggle_with_text_in_field(self) -> None:
        """Toggle works correctly even when secret key has text."""
        panel = BedrockConfigPanel()
        panel._secret_key.setText("my-secret-value")

        panel._visibility_toggle.setChecked(True)
        assert panel._secret_key.echoMode() == QLineEdit.EchoMode.Normal
        assert panel._secret_key.text() == "my-secret-value"

        panel._visibility_toggle.setChecked(False)
        assert panel._secret_key.echoMode() == QLineEdit.EchoMode.Password
        assert panel._secret_key.text() == "my-secret-value"


class TestValidationStateTransitions:
    """Req 1.6: Validate button shows loading state, then result; button disabled during validation."""

    def test_set_validating_true_disables_button(self) -> None:
        """set_validating(True) disables the validate button."""
        panel = BedrockConfigPanel()
        panel.set_validating(True)
        assert panel._validate_button.isEnabled() is False

    def test_set_validating_true_changes_button_text(self) -> None:
        """set_validating(True) changes button text to 'Validando...'."""
        panel = BedrockConfigPanel()
        panel.set_validating(True)
        assert panel._validate_button.text() == "Validando..."

    def test_set_validating_true_sets_reconnecting_badge(self) -> None:
        """set_validating(True) sets badge state to RECONNECTING."""
        panel = BedrockConfigPanel()
        panel.set_validating(True)
        assert panel._status_badge.state() == BadgeState.RECONNECTING

    def test_set_validating_true_hides_message(self) -> None:
        """set_validating(True) hides any previous validation message."""
        panel = BedrockConfigPanel()
        # First show a message
        panel.set_validation_state(BadgeState.DISCONNECTED, "Error previo")
        assert _is_visible(panel._validation_message) is True

        # Start validating — message hidden
        panel.set_validating(True)
        assert _is_visible(panel._validation_message) is False

    def test_set_validating_false_enables_button(self) -> None:
        """set_validating(False) re-enables the validate button."""
        panel = BedrockConfigPanel()
        panel.set_validating(True)
        panel.set_validating(False)
        assert panel._validate_button.isEnabled() is True

    def test_set_validating_false_restores_button_text(self) -> None:
        """set_validating(False) restores button text to 'Validar'."""
        panel = BedrockConfigPanel()
        panel.set_validating(True)
        panel.set_validating(False)
        assert panel._validate_button.text() == "Validar"

    def test_validation_success_sets_connected_badge(self) -> None:
        """set_validation_state(CONNECTED, msg) sets badge to CONNECTED."""
        panel = BedrockConfigPanel()
        panel.set_validating(True)
        panel.set_validation_state(BadgeState.CONNECTED, "Conexión exitosa")
        assert panel._status_badge.state() == BadgeState.CONNECTED

    def test_validation_success_shows_green_message(self) -> None:
        """set_validation_state(CONNECTED, msg) shows message with green color."""
        panel = BedrockConfigPanel()
        panel.set_validation_state(BadgeState.CONNECTED, "Conexión exitosa")
        assert _is_visible(panel._validation_message) is True
        assert panel._validation_message.text() == "Conexión exitosa"
        assert "#a6e3a1" in panel._validation_message.styleSheet()

    def test_validation_success_enables_button(self) -> None:
        """set_validation_state(CONNECTED, ...) re-enables validate button."""
        panel = BedrockConfigPanel()
        panel.set_validating(True)
        panel.set_validation_state(BadgeState.CONNECTED, "OK")
        assert panel._validate_button.isEnabled() is True
        assert panel._validate_button.text() == "Validar"

    def test_validation_error_sets_disconnected_badge(self) -> None:
        """set_validation_state(DISCONNECTED, msg) sets badge to DISCONNECTED."""
        panel = BedrockConfigPanel()
        panel.set_validating(True)
        panel.set_validation_state(BadgeState.DISCONNECTED, "Credenciales inválidas")
        assert panel._status_badge.state() == BadgeState.DISCONNECTED

    def test_validation_error_shows_red_message(self) -> None:
        """set_validation_state(DISCONNECTED, msg) shows message with red color."""
        panel = BedrockConfigPanel()
        panel.set_validation_state(BadgeState.DISCONNECTED, "Credenciales inválidas")
        assert _is_visible(panel._validation_message) is True
        assert panel._validation_message.text() == "Credenciales inválidas"
        assert "#f38ba8" in panel._validation_message.styleSheet()

    def test_validation_error_enables_button(self) -> None:
        """set_validation_state(DISCONNECTED, ...) re-enables validate button."""
        panel = BedrockConfigPanel()
        panel.set_validating(True)
        panel.set_validation_state(BadgeState.DISCONNECTED, "Fallo")
        assert panel._validate_button.isEnabled() is True


class TestEmptyCredentialsError:
    """Req 1.7: Empty credentials + no profile → error message displayed."""

    def test_empty_credentials_error_message_displayed(self) -> None:
        """Calling set_validation_state with DISCONNECTED and empty-creds message shows error."""
        panel = BedrockConfigPanel()
        error_msg = "Se requiere un profile name o credenciales manuales"
        panel.set_validation_state(BadgeState.DISCONNECTED, error_msg)

        assert _is_visible(panel._validation_message) is True
        assert panel._validation_message.text() == error_msg
        assert "#f38ba8" in panel._validation_message.styleSheet()

    def test_get_credentials_empty_when_no_input(self) -> None:
        """get_credentials returns empty strings when nothing is entered."""
        panel = BedrockConfigPanel()
        creds = panel.get_credentials()
        assert creds["access_key"] == ""
        assert creds["secret_key"] == ""
        assert creds["profile_name"] == ""

    def test_no_credentials_and_no_profile_detectable(self) -> None:
        """With empty fields, both access_key and profile_name are empty (caller can detect)."""
        panel = BedrockConfigPanel()
        creds = panel.get_credentials()
        has_manual = bool(creds["access_key"] or creds["secret_key"])
        has_profile = bool(creds["profile_name"])
        assert has_manual is False
        assert has_profile is False


class TestTimeoutErrorState:
    """Req 1.8: Timeout/error shows red StatusDot with message, button re-enabled for retry."""

    def test_timeout_error_shows_disconnected_badge(self) -> None:
        """Timeout error sets badge to DISCONNECTED (red)."""
        panel = BedrockConfigPanel()
        panel.set_validating(True)
        panel.set_validation_state(
            BadgeState.DISCONNECTED,
            "No se pudo conectar al servicio dentro del tiempo límite",
        )
        assert panel._status_badge.state() == BadgeState.DISCONNECTED

    def test_timeout_error_shows_message(self) -> None:
        """Timeout error displays the error message."""
        panel = BedrockConfigPanel()
        timeout_msg = "No se pudo conectar al servicio dentro del tiempo límite"
        panel.set_validation_state(BadgeState.DISCONNECTED, timeout_msg)
        assert _is_visible(panel._validation_message) is True
        assert panel._validation_message.text() == timeout_msg

    def test_timeout_error_enables_retry(self) -> None:
        """After timeout error, validate button is enabled for retry."""
        panel = BedrockConfigPanel()
        panel.set_validating(True)
        panel.set_validation_state(
            BadgeState.DISCONNECTED,
            "No se pudo conectar al servicio dentro del tiempo límite",
        )
        assert panel._validate_button.isEnabled() is True
        assert panel._validate_button.text() == "Validar"

    def test_retry_after_error_works(self) -> None:
        """After error, user can trigger validation again (full cycle)."""
        panel = BedrockConfigPanel()

        # First validation attempt — timeout
        panel.set_validating(True)
        assert panel._validate_button.isEnabled() is False
        panel.set_validation_state(
            BadgeState.DISCONNECTED, "Timeout"
        )
        assert panel._validate_button.isEnabled() is True

        # Second attempt (retry)
        panel.set_validating(True)
        assert panel._validate_button.isEnabled() is False
        assert panel._validate_button.text() == "Validando..."
        assert panel._status_badge.state() == BadgeState.RECONNECTING

        # Success on retry
        panel.set_validation_state(BadgeState.CONNECTED, "Conexión exitosa")
        assert panel._validate_button.isEnabled() is True
        assert panel._status_badge.state() == BadgeState.CONNECTED

    def test_empty_message_hides_validation_label(self) -> None:
        """set_validation_state with empty message hides the message label."""
        panel = BedrockConfigPanel()
        panel.set_validation_state(BadgeState.CONNECTED, "")
        assert _is_visible(panel._validation_message) is False
