"""Sistema de tema y estilos para la GUI de Switch_bot.

Define la paleta de colores (Catppuccin Mocha adaptada para broadcast)
y el stylesheet base QSS para todos los widgets de la aplicación.

Requisitos: 4.1, 4.2
"""

# ---------------------------------------------------------------------------
# Paleta de Colores — Catppuccin Mocha adaptada para broadcast
# ---------------------------------------------------------------------------

COLORS: dict[str, str] = {
    "base": "#1e1e2e",        # Background principal
    "mantle": "#181825",      # Background más oscuro (headers, barras)
    "crust": "#11111b",       # Background más oscuro aún (bordes)
    "surface0": "#313244",    # Panels, cards
    "surface1": "#45475a",    # Widgets elevados
    "surface2": "#585b70",    # Bordes activos
    "text": "#cdd6f4",        # Texto principal
    "subtext0": "#a6adc8",    # Texto secundario
    "subtext1": "#bac2de",    # Texto terciario
    "blue": "#89b4fa",        # Acento primario, acciones
    "red": "#f38ba8",         # On-air, tally activo, panic, errores
    "green": "#a6e3a1",       # Preview, conectado, success
    "yellow": "#f9e2af",      # Warning, reconectando
    "magenta": "#cba6f7",     # IA/Prompt markers
    "cyan": "#94e2d5",        # Información, timecodes
    "peach": "#fab387",       # Secundario warm
}


# ---------------------------------------------------------------------------
# Stylesheet Base QSS
# ---------------------------------------------------------------------------

BASE_STYLESHEET: str = """
QMainWindow, QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-family: "Inter", "Segoe UI", sans-serif;
    font-size: 10pt;
}

QGroupBox {
    background-color: #313244;
    border: 1px solid #45475a;
    border-radius: 8px;
    margin-top: 12px;
    padding: 12px;
    padding-top: 24px;
    font-weight: bold;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 4px;
    color: #a6adc8;
}

QPushButton {
    background-color: #45475a;
    border: 1px solid #585b70;
    border-radius: 6px;
    padding: 8px 16px;
    color: #cdd6f4;
    min-height: 28px;
}

QPushButton:hover {
    background-color: #585b70;
    border-color: #89b4fa;
}

QPushButton:pressed {
    background-color: #89b4fa;
    color: #1e1e2e;
}

QPushButton:disabled {
    background-color: #313244;
    border-color: #45475a;
    color: #585b70;
}

QPushButton#panicButton {
    background-color: #f38ba8;
    color: #1e1e2e;
    font-size: 14pt;
    font-weight: bold;
    border: 3px solid #eba0ac;
    border-radius: 12px;
    min-height: 60px;
    min-width: 120px;
}

QPushButton#panicButton:hover {
    background-color: #eba0ac;
    border-color: #f38ba8;
}

QPushButton#panicButton:pressed {
    background-color: #cdd6f4;
    color: #f38ba8;
}

QPushButton#startButton {
    background-color: #a6e3a1;
    color: #1e1e2e;
    font-weight: bold;
    border: 1px solid #a6e3a1;
}

QPushButton#startButton:hover {
    background-color: #b4f0b2;
}

QPushButton#stopButton {
    background-color: #f38ba8;
    color: #1e1e2e;
    font-weight: bold;
    border: 1px solid #f38ba8;
}

QPushButton#stopButton:hover {
    background-color: #f5a0b8;
}

QComboBox {
    background-color: #45475a;
    border: 1px solid #585b70;
    border-radius: 6px;
    padding: 6px 12px;
    color: #cdd6f4;
    min-height: 28px;
}

QComboBox:hover {
    border-color: #89b4fa;
}

QComboBox:disabled {
    background-color: #313244;
    border-color: #45475a;
    color: #585b70;
}

QComboBox QAbstractItemView {
    background-color: #313244;
    border: 1px solid #585b70;
    selection-background-color: #45475a;
    color: #cdd6f4;
}

QComboBox::drop-down {
    border: none;
    padding-right: 8px;
}

QLineEdit, QTextEdit {
    background-color: #313244;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 6px 8px;
    color: #cdd6f4;
}

QLineEdit:focus, QTextEdit:focus {
    border-color: #89b4fa;
}

QLineEdit:disabled, QTextEdit:disabled {
    background-color: #181825;
    border-color: #313244;
    color: #585b70;
}

QLabel#timecodeDisplay {
    font-family: "JetBrains Mono", "Fira Code", "Consolas", monospace;
    font-size: 14pt;
    color: #94e2d5;
    background-color: #181825;
    border-radius: 4px;
    padding: 4px 8px;
}

QLabel#sectionHeader {
    font-size: 11pt;
    font-weight: bold;
    color: #a6adc8;
    padding-bottom: 4px;
}

QLabel#statusLabel {
    font-size: 9pt;
    color: #a6adc8;
}

QScrollBar:vertical {
    background-color: #181825;
    width: 10px;
    border-radius: 5px;
}

QScrollBar::handle:vertical {
    background-color: #45475a;
    border-radius: 5px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background-color: #585b70;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    background-color: #181825;
    height: 10px;
    border-radius: 5px;
}

QScrollBar::handle:horizontal {
    background-color: #45475a;
    border-radius: 5px;
    min-width: 30px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #585b70;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}

QSplitter::handle {
    background-color: #45475a;
    width: 2px;
}

QToolTip {
    background-color: #313244;
    border: 1px solid #585b70;
    border-radius: 4px;
    padding: 4px 8px;
    color: #cdd6f4;
    font-size: 9pt;
}
"""
