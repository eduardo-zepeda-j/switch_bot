"""StatusBadge — Widget compuesto de estado de conexión para servicios.

Combina un StatusDot con un QLabel descriptivo en layout horizontal,
proporcionando feedback visual inmediato del estado de cada servicio
(Backend IA, ATEM, OBS).

Requisitos: 6.1, 6.3, 6.6
"""

from __future__ import annotations

from enum import Enum

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QPaintEvent
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget

from switch_bot.gui.theme import COLORS


class BadgeState(Enum):
    """Estados posibles de un StatusBadge."""

    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    DISCONNECTED = "disconnected"
    DISABLED = "disabled"


# Mapeo de estados a colores del design system
_STATE_COLORS: dict[BadgeState, str] = {
    BadgeState.CONNECTED: COLORS["green"],       # #a6e3a1
    BadgeState.RECONNECTING: COLORS["yellow"],   # #f9e2af
    BadgeState.DISCONNECTED: COLORS["red"],      # #f38ba8
    BadgeState.DISABLED: COLORS["surface2"],     # #585b70
}

# Mapeo de estados a texto descriptivo (español, producción broadcast)
_STATE_TEXTS: dict[BadgeState, str] = {
    BadgeState.CONNECTED: "Conectado",
    BadgeState.RECONNECTING: "Reconectando...",
    BadgeState.DISCONNECTED: "Desconectado",
    BadgeState.DISABLED: "No configurado",
}


class _BadgeDot(QWidget):
    """Indicador circular interno del StatusBadge (12x12px).

    Similar a StatusDot pero acepta BadgeState que incluye DISABLED.
    """

    def __init__(self, state: BadgeState = BadgeState.DISCONNECTED, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self.setFixedSize(12, 12)

    def set_state(self, state: BadgeState) -> None:
        """Actualiza el estado y repinta el indicador."""
        self._state = state
        self.update()

    def paintEvent(self, event: QPaintEvent | None) -> None:
        """Pinta el círculo indicador con el color correspondiente al estado."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(_STATE_COLORS[self._state])
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(0, 0, 12, 12)
        painter.end()


class StatusBadge(QWidget):
    """StatusDot + label de texto para mostrar estado de un servicio.

    Compone un indicador circular de 12x12px con un QLabel que muestra
    el texto descriptivo del estado actual. El layout es horizontal con
    spacing de 6px entre dot y texto.

    Ejemplo de uso:
        badge = StatusBadge("IA")
        badge.set_state(BadgeState.CONNECTED)  # Dot verde + "Conectado"
    """

    def __init__(
        self,
        label: str = "",
        state: BadgeState = BadgeState.DISCONNECTED,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._label_text = label
        self._state = state

        self._setup_ui()
        self._apply_state()

    def _setup_ui(self) -> None:
        """Configura el layout horizontal con dot + label."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)

        # Indicador circular de color
        self._dot = _BadgeDot(self._state, self)
        layout.addWidget(self._dot, alignment=Qt.AlignmentFlag.AlignVCenter)

        # Label del servicio (nombre + estado)
        self._status_label = QLabel()
        self._status_label.setStyleSheet(
            f"color: {COLORS['subtext0']}; background: transparent; font-size: 9pt;"
        )
        layout.addWidget(self._status_label, alignment=Qt.AlignmentFlag.AlignVCenter)

        # No expandir más de lo necesario
        self.setSizePolicy(self.sizePolicy())
        layout.addStretch()

    def _apply_state(self) -> None:
        """Aplica el estado actual al dot y al label."""
        self._dot.set_state(self._state)

        # Construir texto: "NombreServicio: Estado"
        state_text = _STATE_TEXTS[self._state]
        if self._label_text:
            display = f"{self._label_text}: {state_text}"
        else:
            display = state_text

        self._status_label.setText(display)

        # Color del texto según estado
        color = _STATE_COLORS[self._state]
        self._status_label.setStyleSheet(
            f"color: {color}; background: transparent; font-size: 9pt;"
        )

        # Tooltip accesible
        self.setToolTip(display)

    def set_state(self, state: BadgeState) -> None:
        """Cambia el estado del badge.

        Actualiza el color del dot y el texto descriptivo.

        Args:
            state: Nuevo estado del servicio.
        """
        self._state = state
        self._apply_state()

    def state(self) -> BadgeState:
        """Retorna el estado actual del badge."""
        return self._state
