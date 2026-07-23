"""Widgets personalizados reutilizables para la GUI de Switch_bot.

Incluye TallyIndicator, StatusDot y TimecodeDisplay — componentes
específicos de producción broadcast con feedback visual inmediato.

Requisitos: 4.1, 4.2, 4.3, 10.3
"""

from __future__ import annotations

from enum import Enum

from PyQt6.QtCore import (
    QPropertyAnimation,
    QSize,
    Qt,
    QTimer,
    pyqtProperty,
)
from PyQt6.QtGui import QColor, QFont, QPainter, QPaintEvent
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from switch_bot.gui.theme import COLORS


# ---------------------------------------------------------------------------
# TallyIndicator — Indicador de tally para cada cámara
# ---------------------------------------------------------------------------


class TallyState(Enum):
    """Estados posibles de un indicador de tally."""

    OFF = "off"
    PREVIEW = "preview"
    ON_AIR = "on_air"


class TallyIndicator(QFrame):
    """Indicador de tally para cada cámara.

    Muestra el número de cámara (grande), nombre de personaje (pequeño),
    y el estado actual (OFF/PREVIEW/ON_AIR) con animación de pulso
    cuando está on-air.

    Mínimo 60x60px. Border-radius 8px.
    """

    def __init__(
        self,
        camera_number: int,
        character_name: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._camera_number = camera_number
        self._character_name = character_name
        self._state = TallyState.OFF
        self._pulse_opacity: float = 1.0

        self.setMinimumSize(QSize(60, 60))
        self.setObjectName(f"tally_{camera_number}")
        self._setup_ui()
        self._setup_animation()
        self._apply_state_style()

    def _setup_ui(self) -> None:
        """Configura el layout interno del indicador."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Número de cámara (prominente)
        self._camera_label = QLabel(str(self._camera_number))
        self._camera_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont("Inter", 18, QFont.Weight.Bold)
        self._camera_label.setFont(font)
        self._camera_label.setStyleSheet(f"color: {COLORS['text']}; background: transparent;")
        layout.addWidget(self._camera_label)

        # Estado textual (accesibilidad: no solo color)
        self._state_label = QLabel("")
        self._state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        state_font = QFont("Inter", 7, QFont.Weight.Bold)
        self._state_label.setFont(state_font)
        self._state_label.setStyleSheet("background: transparent;")
        layout.addWidget(self._state_label)

        # Nombre de personaje (pequeño)
        self._name_label = QLabel(self._character_name)
        self._name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_font = QFont("Inter", 8)
        self._name_label.setFont(name_font)
        self._name_label.setStyleSheet(f"color: {COLORS['subtext0']}; background: transparent;")
        layout.addWidget(self._name_label)

        self.setToolTip(
            f"Cámara {self._camera_number}"
            + (f" — {self._character_name}" if self._character_name else "")
            + "\nEstado: OFF"
        )

    def _setup_animation(self) -> None:
        """Configura la animación de pulso para ON_AIR."""
        self._pulse_animation = QPropertyAnimation(self, b"pulse_opacity")
        self._pulse_animation.setDuration(800)
        self._pulse_animation.setStartValue(1.0)
        self._pulse_animation.setEndValue(0.5)
        self._pulse_animation.setLoopCount(-1)  # Loop infinito

    # -- Propiedad para animación de pulso --

    @pyqtProperty(float)  # type: ignore[misc]
    def pulse_opacity(self) -> float:
        """Opacidad actual del pulso (para animación)."""
        return self._pulse_opacity

    @pulse_opacity.setter  # type: ignore[no-redef]
    def pulse_opacity(self, value: float) -> None:
        self._pulse_opacity = value
        self._apply_state_style()

    # -- API pública --

    @property
    def state(self) -> TallyState:
        """Estado actual del tally."""
        return self._state

    @property
    def camera_number(self) -> int:
        """Número de cámara."""
        return self._camera_number

    def set_state(self, state: TallyState) -> None:
        """Cambia el estado del indicador de tally.

        Args:
            state: Nuevo estado (OFF, PREVIEW, ON_AIR).
        """
        old_state = self._state
        self._state = state
        self._apply_state_style()
        self._update_tooltip()

        # Controlar animación de pulso
        if state == TallyState.ON_AIR and old_state != TallyState.ON_AIR:
            self._pulse_animation.start()
        elif state != TallyState.ON_AIR:
            self._pulse_animation.stop()
            self._pulse_opacity = 1.0

    def set_character_name(self, name: str) -> None:
        """Actualiza el nombre de personaje mostrado."""
        self._character_name = name
        self._name_label.setText(name)
        self._update_tooltip()

    def _apply_state_style(self) -> None:
        """Aplica el estilo visual según el estado actual."""
        if self._state == TallyState.OFF:
            bg = COLORS["surface0"]
            border = COLORS["surface1"]
            self._state_label.setText("")
            self._state_label.setStyleSheet("background: transparent; color: transparent;")
        elif self._state == TallyState.PREVIEW:
            bg = COLORS["surface0"]
            border = COLORS["green"]
            self._state_label.setText("PREVIEW")
            self._state_label.setStyleSheet(
                f"background: transparent; color: {COLORS['green']};"
            )
        else:  # ON_AIR
            opacity_hex = hex(int(self._pulse_opacity * 255))[2:].zfill(2)
            bg = f"{COLORS['red']}{opacity_hex}"
            border = COLORS["red"]
            self._state_label.setText("ON AIR")
            self._state_label.setStyleSheet(
                f"background: transparent; color: {COLORS['text']}; font-weight: bold;"
            )

        self.setStyleSheet(
            f"QFrame#{self.objectName()} {{"
            f"  background-color: {bg};"
            f"  border: 2px solid {border};"
            f"  border-radius: 8px;"
            f"}}"
        )

    def _update_tooltip(self) -> None:
        """Actualiza el tooltip con información detallada."""
        state_text = {
            TallyState.OFF: "OFF",
            TallyState.PREVIEW: "PREVIEW (verde)",
            TallyState.ON_AIR: "ON AIR (rojo)",
        }
        self.setToolTip(
            f"Cámara {self._camera_number}"
            + (f" — {self._character_name}" if self._character_name else "")
            + f"\nEstado: {state_text[self._state]}"
        )


# ---------------------------------------------------------------------------
# StatusDot — Indicador circular de estado de conexión
# ---------------------------------------------------------------------------


class ConnectionState(Enum):
    """Estados de conexión del backend."""

    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    DISCONNECTED = "disconnected"


class StatusDot(QWidget):
    """Indicador circular de estado de conexión (12x12px).

    Colores:
        - Verde: Conectado
        - Amarillo: Reconectando
        - Rojo: Desconectado

    Se pinta con QPainter.drawEllipse y tiene tooltip detallado.
    """

    _STATE_COLORS: dict[ConnectionState, str] = {
        ConnectionState.CONNECTED: COLORS["green"],
        ConnectionState.RECONNECTING: COLORS["yellow"],
        ConnectionState.DISCONNECTED: COLORS["red"],
    }

    _STATE_TOOLTIPS: dict[ConnectionState, str] = {
        ConnectionState.CONNECTED: "Backend conectado y operativo",
        ConnectionState.RECONNECTING: "Reconectando al backend...",
        ConnectionState.DISCONNECTED: "Backend desconectado",
    }

    def __init__(
        self,
        state: ConnectionState = ConnectionState.DISCONNECTED,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._state = state
        self.setFixedSize(12, 12)
        self.setToolTip(self._STATE_TOOLTIPS[state])

    @property
    def state(self) -> ConnectionState:
        """Estado de conexión actual."""
        return self._state

    def set_state(self, state: ConnectionState) -> None:
        """Cambia el estado de conexión visualizado.

        Args:
            state: Nuevo estado de conexión.
        """
        self._state = state
        self.setToolTip(self._STATE_TOOLTIPS[state])
        self.update()

    def paintEvent(self, event: QPaintEvent | None) -> None:
        """Pinta el círculo indicador."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(self._STATE_COLORS[self._state])
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(0, 0, 12, 12)
        painter.end()


# ---------------------------------------------------------------------------
# TimecodeDisplay — Display de timecode SMPTE
# ---------------------------------------------------------------------------


class TimecodeDisplay(QLabel):
    """Display de timecode SMPTE con fuente monoespaciada.

    Se actualiza cada frame (~33ms) mediante un QTimer interno.
    Formato: HH:MM:SS:FF (non-drop) o HH:MM:SS;FF (drop frame).

    objectName = "timecodeDisplay" para aplicar estilo QSS.
    """

    def __init__(
        self,
        drop_frame: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._drop_frame = drop_frame
        self._hours = 0
        self._minutes = 0
        self._seconds = 0
        self._frames = 0
        self._running = False

        self.setObjectName("timecodeDisplay")
        font = QFont("JetBrains Mono", 14)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(font)
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setMinimumWidth(160)
        self.setToolTip("Timecode de sesión (SMPTE)")
        self._update_display()

        # Timer para actualización (no se inicia hasta start)
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._advance_frame)

    @property
    def is_running(self) -> bool:
        """True si el timecode está corriendo."""
        return self._running

    def start(self, fps: float = 29.97) -> None:
        """Inicia el conteo de timecode.

        Args:
            fps: Frames por segundo del proyecto.
        """
        interval_ms = int(1000.0 / fps)
        self._running = True
        self._timer.start(interval_ms)

    def stop(self) -> None:
        """Detiene el conteo de timecode."""
        self._running = False
        self._timer.stop()

    def reset(self) -> None:
        """Reinicia el timecode a 00:00:00:00."""
        self._hours = 0
        self._minutes = 0
        self._seconds = 0
        self._frames = 0
        self._update_display()

    def set_timecode(self, hours: int, minutes: int, seconds: int, frames: int) -> None:
        """Establece un timecode específico.

        Args:
            hours: Horas (0-23).
            minutes: Minutos (0-59).
            seconds: Segundos (0-59).
            frames: Frames (0-29 para 29.97fps).
        """
        self._hours = hours
        self._minutes = minutes
        self._seconds = seconds
        self._frames = frames
        self._update_display()

    def _advance_frame(self) -> None:
        """Avanza un frame con lógica drop frame SMPTE 12M."""
        self._frames += 1
        max_frames = 30  # Para 29.97 fps

        if self._frames >= max_frames:
            self._frames = 0
            self._seconds += 1

            if self._seconds >= 60:
                self._seconds = 0
                self._minutes += 1

                if self._minutes >= 60:
                    self._minutes = 0
                    self._hours += 1

                    if self._hours >= 24:
                        self._hours = 0

                # Drop Frame: skip frames 0,1 excepto cada 10 minutos
                if self._drop_frame and (self._minutes % 10 != 0):
                    self._frames = 2

        self._update_display()

    def _update_display(self) -> None:
        """Actualiza el texto mostrado con el formato SMPTE."""
        separator = ";" if self._drop_frame else ":"
        text = (
            f"{self._hours:02d}:{self._minutes:02d}:"
            f"{self._seconds:02d}{separator}{self._frames:02d}"
        )
        self.setText(text)
