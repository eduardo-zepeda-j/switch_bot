---
inclusion: fileMatch
fileMatchPattern: "switch_bot/gui/**"
---

# Sistema de Diseño UI — Switch_bot

## Filosofía de Diseño

Switch_bot es una herramienta de producción broadcast profesional. El diseño visual debe seguir las convenciones de software de producción de video (DaVinci Resolve, vMix, OBS Studio):

- **Tema oscuro** para reducir fatiga visual en sesiones largas
- **Información densa pero organizada** — el operador necesita ver mucha información simultáneamente
- **Acciones críticas prominentes** — Panic Button y tally son lo más visible
- **Feedback inmediato** — cada acción del operador debe reflejarse visualmente en < 100ms

## Paleta de Colores (Catppuccin Mocha adaptada para broadcast)

```python
# theme.py — Definición centralizada de colores
COLORS = {
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
```

## Stylesheet Base (QSS)

```python
BASE_STYLESHEET = """
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

QPushButton#panicButton:pressed {
    background-color: #eba0ac;
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

QComboBox QAbstractItemView {
    background-color: #313244;
    border: 1px solid #585b70;
    selection-background-color: #45475a;
    color: #cdd6f4;
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
"""
```

## Componentes Estándar

### TallyIndicator

```python
class TallyIndicator(QFrame):
    """Indicador de tally para cada cámara. Mínimo 60x60px."""
    
    # Estados: OFF (gris), PREVIEW (verde), ON_AIR (rojo pulsante)
    # Debe mostrar: número de cámara (grande), nombre de personaje (pequeño)
    # Border-radius: 8px
    # Animación de pulso cuando on-air (QPropertyAnimation en opacity)
```

### StatusDot

```python
class StatusDot(QWidget):
    """Indicador circular de estado de conexión. 12x12px."""
    
    # Colores: green=#a6e3a1, yellow=#f9e2af, red=#f38ba8
    # paintEvent con QPainter.drawEllipse
    # Tooltip con estado detallado
```

### TimecodeDisplay

```python
class TimecodeDisplay(QLabel):
    """Display de timecode SMPTE. Font monoespaciada, alineado a la derecha."""
    
    # objectName = "timecodeDisplay" para QSS
    # Actualización cada frame (33.33ms vía QTimer)
    # Formato: HH:MM:SS:FF con separador ; para drop frame
```

## Layout Guidelines

- **Spacing entre widgets**: 8px (usar `layout.setSpacing(8)`)
- **Margen de contenedores**: 16px (usar `layout.setContentsMargins(16, 16, 16, 16)`)
- **Panels colapsables** para configuración (backend IA, ATEM IP, OBS URL) — usar QToolBox o custom collapsible
- **Zona principal** (70% del ancho): Tally indicators + timecode + controles de sesión
- **Panel lateral** (30% del ancho): Notas, prompts, log de marcadores

## Atajos de Teclado

| Atajo | Acción |
|-------|--------|
| F12 o Escape | Panic Button (toggle) |
| F1-F4 | Nota rápida en cámara 1-4 |
| Ctrl+Enter | Enviar prompt de IA |
| Space | Marcador manual rápido |
| Ctrl+S | Inicio/Parada de sesión |

## Accesibilidad

- Todos los botones deben tener `setToolTip()` con descripción y atajo
- Contraste mínimo WCAG AA entre texto y fondo (ratio 4.5:1 mínimo)
- No depender solo del color para transmitir información — usar iconos o texto complementario
- Los indicadores de tally deben tener texto "ON AIR" además del color rojo
