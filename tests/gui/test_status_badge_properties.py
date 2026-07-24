# Feature: gui-redesign, Property 7: StatusBadge state mapping correctness
"""Property-based tests para StatusBadge — Mapeo de estados correcto.

**Validates: Requirements 6.3, 6.6**

Property 7: StatusBadge state mapping correctness — For any BadgeState enum value,
the StatusBadge SHALL map it to (a) the correct color from the design system COLORS
dict (green for CONNECTED, yellow for RECONNECTING, red for DISCONNECTED, surface2
for DISABLED) and (b) a non-empty descriptive text string.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from PyQt6.QtWidgets import QApplication

from switch_bot.gui.status_badge import BadgeState, StatusBadge, _STATE_COLORS, _STATE_TEXTS
from switch_bot.gui.theme import COLORS


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


# Expected color mapping per design system
_EXPECTED_COLORS: dict[BadgeState, str] = {
    BadgeState.CONNECTED: COLORS["green"],       # #a6e3a1
    BadgeState.RECONNECTING: COLORS["yellow"],   # #f9e2af
    BadgeState.DISCONNECTED: COLORS["red"],      # #f38ba8
    BadgeState.DISABLED: COLORS["surface2"],     # #585b70
}


class TestProperty7StatusBadgeStateMappingCorrectness:
    """Property 7: StatusBadge state mapping correctness.

    **Validates: Requirements 6.3, 6.6**

    For any BadgeState enum value, the StatusBadge SHALL map it to the correct
    color from the design system and a non-empty descriptive text string.
    """

    @given(state=st.sampled_from(BadgeState))
    @settings(max_examples=100)
    def test_state_maps_to_correct_color(self, state: BadgeState) -> None:
        """FOR ALL BadgeState values, the mapped color matches the design system.

        Validates: Requirement 6.3 — each state has a distinct color from the
        Catppuccin Mocha palette.
        """
        badge = StatusBadge(label="Test", state=state)

        # Verify the internal color mapping matches expected design system colors
        actual_color = _STATE_COLORS[badge.state()]
        expected_color = _EXPECTED_COLORS[state]
        assert actual_color == expected_color, (
            f"State {state.name}: expected color {expected_color}, got {actual_color}"
        )

    @given(state=st.sampled_from(BadgeState))
    @settings(max_examples=100)
    def test_state_maps_to_non_empty_text(self, state: BadgeState) -> None:
        """FOR ALL BadgeState values, the descriptive text is non-empty.

        Validates: Requirement 6.6 — every badge state displays a descriptive
        text string to the user.
        """
        badge = StatusBadge(label="", state=state)

        # The state text mapping must produce a non-empty string
        state_text = _STATE_TEXTS[badge.state()]
        assert len(state_text) > 0, (
            f"State {state.name}: text mapping is empty"
        )

    @given(state=st.sampled_from(BadgeState))
    @settings(max_examples=100)
    def test_badge_widget_displays_state_text(self, state: BadgeState) -> None:
        """FOR ALL BadgeState values, the widget label contains the state text.

        Validates: Requirements 6.3, 6.6 — the badge visually renders the
        correct text for the current state.
        """
        badge = StatusBadge(label="", state=state)

        # The widget's internal label should contain the state text
        expected_text = _STATE_TEXTS[state]
        actual_label_text = badge._status_label.text()
        assert expected_text in actual_label_text, (
            f"State {state.name}: expected '{expected_text}' in label, "
            f"got '{actual_label_text}'"
        )

    @given(state=st.sampled_from(BadgeState))
    @settings(max_examples=100)
    def test_set_state_updates_badge_correctly(self, state: BadgeState) -> None:
        """FOR ALL BadgeState values, set_state() updates color and text.

        Validates: Requirements 6.3, 6.6 — calling set_state transitions
        the badge to the correct visual state.
        """
        # Start with a different state to ensure transition works
        initial_state = BadgeState.DISABLED if state != BadgeState.DISABLED else BadgeState.CONNECTED
        badge = StatusBadge(label="Svc", state=initial_state)

        # Transition to target state
        badge.set_state(state)

        # Verify state is correctly stored
        assert badge.state() == state

        # Verify color mapping is correct after transition
        assert _STATE_COLORS[badge.state()] == _EXPECTED_COLORS[state]

        # Verify text is non-empty after transition
        assert len(_STATE_TEXTS[badge.state()]) > 0
