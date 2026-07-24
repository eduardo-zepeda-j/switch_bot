# Feature: gui-redesign, Property 6: CollapsiblePanel toggle inverts state
"""Property-based tests para CollapsiblePanel — Toggle invierte estado.

**Validates: Requirements 5.8**

Property 6: CollapsiblePanel toggle inverts state — For any initial expanded
state (True or False) of a CollapsiblePanel, calling set_expanded(not current_state)
SHALL result in is_expanded() returning the opposite of the initial state.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from PyQt6.QtWidgets import QApplication

from switch_bot.gui.collapsible_panel import CollapsiblePanel


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


class TestProperty6CollapsiblePanelToggleInvertsState:
    """Property 6: CollapsiblePanel toggle inverts state.

    **Validates: Requirements 5.8**

    For any initial expanded state (True or False) of a CollapsiblePanel,
    calling set_expanded(not current_state) SHALL result in is_expanded()
    returning the opposite of the initial state.
    """

    @given(initial_state=st.booleans())
    @settings(max_examples=100)
    def test_toggle_inverts_expanded_state(self, initial_state: bool) -> None:
        """FOR ALL boolean states, set_expanded(not state) inverts is_expanded().

        Validates: Requirement 5.8 — clicking the panel header toggles
        expanded/collapsed state.
        """
        panel = CollapsiblePanel(title="Test Panel", expanded=initial_state)

        # Verify initial state is correctly set
        assert panel.is_expanded() == initial_state

        # Toggle the state (without animation to avoid timing issues)
        panel.set_expanded(not initial_state, animate=False)

        # Verify the state is now inverted
        assert panel.is_expanded() == (not initial_state)
