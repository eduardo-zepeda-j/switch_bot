# Feature: gui-redesign, Property 1: Credential mutual exclusion
"""Property-based tests para BedrockConfigPanel — Exclusión mutua de credenciales.

**Validates: Requirements 1.4**

Property 1: Credential mutual exclusion — For any non-empty string entered in
the profile name field, the manual credential fields (access key, secret key)
SHALL be disabled; and for any non-empty string entered in either manual
credential field, the profile name field SHALL be disabled. At no point can
both input modes be simultaneously active.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from PyQt6.QtWidgets import QApplication

from switch_bot.gui.bedrock_config_panel import BedrockConfigPanel


# Strategy for non-empty, non-whitespace-only strings (handlers use .strip())
_non_blank_text = st.text(
    min_size=1,
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S")),
)


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


class TestProperty1CredentialMutualExclusion:
    """Property 1: Credential mutual exclusion.

    **Validates: Requirements 1.4**

    For any non-empty string entered in the profile name field, the manual
    credential fields (access key, secret key) SHALL be disabled; and for any
    non-empty string entered in either manual credential field, the profile
    name field SHALL be disabled.
    """

    @given(profile_text=_non_blank_text)
    @settings(max_examples=100)
    def test_profile_disables_manual_fields(self, profile_text: str) -> None:
        """FOR ALL non-blank profile names, manual credential fields are disabled.

        Validates: Requirement 1.4 — setting profile name disables access_key
        and secret_key fields.
        """
        panel = BedrockConfigPanel()

        # Set profile name text (triggers textChanged → _on_profile_changed)
        panel._profile_name.setText(profile_text)

        # Manual credential fields must be disabled
        assert panel._access_key.isEnabled() is False
        assert panel._secret_key.isEnabled() is False

    @given(access_key_text=_non_blank_text)
    @settings(max_examples=100)
    def test_access_key_disables_profile_field(self, access_key_text: str) -> None:
        """FOR ALL non-blank access keys, profile name field is disabled.

        Validates: Requirement 1.4 — setting access_key disables profile_name.
        """
        panel = BedrockConfigPanel()

        # Set access key text (triggers textChanged → _on_manual_changed)
        panel._access_key.setText(access_key_text)

        # Profile name field must be disabled
        assert panel._profile_name.isEnabled() is False

    @given(secret_key_text=_non_blank_text)
    @settings(max_examples=100)
    def test_secret_key_disables_profile_field(self, secret_key_text: str) -> None:
        """FOR ALL non-blank secret keys, profile name field is disabled.

        Validates: Requirement 1.4 — setting secret_key disables profile_name.
        """
        panel = BedrockConfigPanel()

        # Set secret key text (triggers textChanged → _on_manual_changed)
        panel._secret_key.setText(secret_key_text)

        # Profile name field must be disabled
        assert panel._profile_name.isEnabled() is False

    @given(profile_text=_non_blank_text)
    @settings(max_examples=100)
    def test_clearing_profile_re_enables_manual_fields(self, profile_text: str) -> None:
        """FOR ALL non-blank profile names, clearing profile re-enables manual fields.

        Validates: Requirement 1.4 — both modes cannot be simultaneously active;
        clearing one mode re-enables the other.
        """
        panel = BedrockConfigPanel()

        # Set profile → manual fields disabled
        panel._profile_name.setText(profile_text)
        assert panel._access_key.isEnabled() is False
        assert panel._secret_key.isEnabled() is False

        # Clear profile → manual fields re-enabled
        panel._profile_name.setText("")
        assert panel._access_key.isEnabled() is True
        assert panel._secret_key.isEnabled() is True

    @given(manual_text=_non_blank_text)
    @settings(max_examples=100)
    def test_clearing_manual_re_enables_profile_field(self, manual_text: str) -> None:
        """FOR ALL non-blank manual credentials, clearing them re-enables profile.

        Validates: Requirement 1.4 — both modes cannot be simultaneously active;
        clearing one mode re-enables the other.
        """
        panel = BedrockConfigPanel()

        # Set access key → profile disabled
        panel._access_key.setText(manual_text)
        assert panel._profile_name.isEnabled() is False

        # Clear access key → profile re-enabled
        panel._access_key.setText("")
        assert panel._profile_name.isEnabled() is True
