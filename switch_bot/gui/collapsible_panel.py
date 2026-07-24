"""Widget CollapsiblePanel — Panel colapsable con animación.

Panel genérico que envuelve cualquier contenido en un panel
expandible/contraíble con animación de 150ms ease-in-out.
Permite múltiples paneles expandidos simultáneamente.

Requisitos: 5.4, 5.5, 5.8
"""

from __future__ import annotations

from PyQt6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QFont, QMouseEvent
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from switch_bot.gui.theme import COLORS


class _HeaderBar(QWidget):
    """Barra de título clickable para CollapsiblePanel."""

    clicked = pyqtSignal()

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMaximumHeight(36)
        self.setMinimumHeight(36)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(8)

        # Chevron icon (rotatable via text: ▶ collapsed, ▼ expanded)
        self._chevron = QLabel("▶")
        self._chevron.setFixedWidth(16)
        self._chevron.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._chevron.setStyleSheet(
            f"color: {COLORS['subtext0']}; background: transparent;"
        )
        font = QFont("Inter", 8)
        self._chevron.setFont(font)
        layout.addWidget(self._chevron)

        # Title label
        self._title_label = QLabel(title)
        self._title_label.setStyleSheet(
            f"color: {COLORS['subtext0']}; background: transparent;"
            " font-weight: bold; font-size: 10pt;"
        )
        layout.addWidget(self._title_label)
        layout.addStretch()

        # Styling
        self.setStyleSheet(
            f"background-color: {COLORS['mantle']};"
            f" border: 1px solid {COLORS['surface1']};"
            " border-radius: 4px;"
        )

    @property
    def title_text(self) -> str:
        """Return the title text."""
        return self._title_label.text()

    def set_chevron_expanded(self, expanded: bool) -> None:
        """Update chevron direction based on expanded state."""
        self._chevron.setText("▼" if expanded else "▶")

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        """Emit clicked signal on mouse press."""
        if event and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class CollapsiblePanel(QWidget):
    """Panel colapsable con animación de expansión/contracción.

    Signals:
        toggled(bool): Emitido cuando cambia el estado (True=expandido).
    """

    toggled = pyqtSignal(bool)

    def __init__(
        self,
        title: str,
        expanded: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._expanded = expanded
        self._content_widget: QWidget | None = None

        # Main layout
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(0)

        # Header bar
        self._header = _HeaderBar(title)
        self._header.clicked.connect(self._on_header_clicked)
        self._main_layout.addWidget(self._header)

        # Content container — we animate its maximumHeight
        self._content_container = QWidget()
        self._content_container.setStyleSheet(
            f"background-color: {COLORS['surface0']};"
            f" border: 1px solid {COLORS['surface1']};"
            " border-top: none;"
            " border-bottom-left-radius: 4px;"
            " border-bottom-right-radius: 4px;"
        )
        self._content_layout = QVBoxLayout(self._content_container)
        self._content_layout.setContentsMargins(8, 8, 8, 8)
        self._content_layout.setSpacing(8)
        self._main_layout.addWidget(self._content_container)

        # Animation
        self._animation = QPropertyAnimation(
            self._content_container, b"maximumHeight"
        )
        self._animation.setDuration(150)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutQuad)

        # Set initial state without animation
        self._header.set_chevron_expanded(expanded)
        if not expanded:
            self._content_container.setMaximumHeight(0)
        else:
            # Large default so content is visible
            self._content_container.setMaximumHeight(16777215)

        self.setToolTip(f"Panel: {title} (clic para expandir/contraer)")

    def is_expanded(self) -> bool:
        """Return True if the panel is currently expanded."""
        return self._expanded

    def set_expanded(self, expanded: bool, animate: bool = True) -> None:
        """Set the expanded/collapsed state of the panel.

        Args:
            expanded: True to expand, False to collapse.
            animate: Whether to animate the transition (default True).
        """
        if expanded == self._expanded:
            return

        self._expanded = expanded
        self._header.set_chevron_expanded(expanded)

        if animate:
            self._animate_toggle(expanded)
        else:
            if expanded:
                self._content_container.setMaximumHeight(16777215)
            else:
                self._content_container.setMaximumHeight(0)

        self.toggled.emit(expanded)

    def set_content(self, widget: QWidget) -> None:
        """Set the content widget displayed inside the panel.

        Args:
            widget: The widget to display as panel content.
        """
        # Remove old content if any
        if self._content_widget is not None:
            self._content_layout.removeWidget(self._content_widget)
            self._content_widget.setParent(None)

        self._content_widget = widget
        self._content_layout.addWidget(widget)

    def title(self) -> str:
        """Return the panel title text."""
        return self._header.title_text

    def _on_header_clicked(self) -> None:
        """Toggle the panel state when header is clicked."""
        self.set_expanded(not self._expanded)

    def _animate_toggle(self, expanding: bool) -> None:
        """Animate the expand/collapse transition.

        Args:
            expanding: True if expanding, False if collapsing.
        """
        # Stop any running animation
        self._animation.stop()

        if expanding:
            # Temporarily remove max height constraint to measure content
            self._content_container.setMaximumHeight(16777215)
            target_height = self._content_container.sizeHint().height()
            # Reset to current (collapsed) state for animation start
            self._content_container.setMaximumHeight(0)

            self._animation.setStartValue(0)
            self._animation.setEndValue(target_height)
            # After animation completes, remove constraint so content can resize
            self._animation.finished.connect(self._on_expand_finished)
        else:
            current_height = self._content_container.height()
            self._animation.setStartValue(current_height)
            self._animation.setEndValue(0)
            # Disconnect expand handler if connected
            try:
                self._animation.finished.disconnect(self._on_expand_finished)
            except TypeError:
                pass

        self._animation.start()

    def _on_expand_finished(self) -> None:
        """Remove height constraint after expand animation completes."""
        if self._expanded:
            self._content_container.setMaximumHeight(16777215)
        # Disconnect to avoid multiple calls
        try:
            self._animation.finished.disconnect(self._on_expand_finished)
        except TypeError:
            pass
