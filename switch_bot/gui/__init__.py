"""Interfaz gráfica PyQt6 para control de sesión.

Exporta la ventana principal, el puente GUI↔Coordinator y los widgets
reutilizables del sistema de producción broadcast multicámara Switch_bot.

Requisitos: 4.1, 4.2, 4.3, 4.4, 5.2, 17.5
"""

from switch_bot.gui.ad_suggestions_dialog import AdSuggestionsDialog
from switch_bot.gui.gui_bridge import GuiBridge
from switch_bot.gui.main_window import MainWindow
from switch_bot.gui.theme import BASE_STYLESHEET, COLORS
from switch_bot.gui.widgets import (
    ConnectionState,
    StatusDot,
    TallyIndicator,
    TallyState,
    TimecodeDisplay,
)

__all__ = [
    "AdSuggestionsDialog",
    "BASE_STYLESHEET",
    "COLORS",
    "ConnectionState",
    "GuiBridge",
    "MainWindow",
    "StatusDot",
    "TallyIndicator",
    "TallyState",
    "TimecodeDisplay",
]
