"""Enumeraciones fundamentales del sistema Switch_bot.

Define los tipos de marcadores EDL, colores de DaVinci Resolve,
orígenes de eventos y el mapeo entre marcadores y colores.
"""

from enum import Enum


class MarkerType(Enum):
    """Tipos de marcadores soportados por el Motor EDL."""

    MANUAL_NOTE = "MANUAL_NOTE"
    SCRIPT_MATCH = "SCRIPT_MATCH"
    SCRIPT_DEVIATION = "SCRIPT_DEVIATION"
    AI_PROMPT = "AI_PROMPT"
    ENTRADA = "ENTRADA"
    SALIDA = "SALIDA"
    TOS = "TOS"
    ERROR_DICCION = "ERROR_DICCION"
    CONFUSION = "CONFUSION"
    REPETICION = "REPETICION"
    PANIC = "PANIC"
    IMAGEN = "IMAGEN"


class EDLColor(Enum):
    """Colores de marcador para DaVinci Resolve EDL."""

    Red = "ResolveColorRed"
    Green = "ResolveColorGreen"
    Magenta = "ResolveColorMagenta"
    Cyan = "ResolveColorCyan"
    Yellow = "ResolveColorYellow"
    Blue = "ResolveColorBlue"


class SourceOrigin(Enum):
    """Origen del evento que genera un marcador."""

    MANUAL = "MANUAL"      # Operador humano
    AI = "AI"              # Enriquecedor IA
    AUTO = "AUTO"          # Decisión automática del motor
    ANOMALY = "ANOMALY"    # Detector de anomalías vocales


MARKER_COLOR_MAP: dict[MarkerType, EDLColor] = {
    MarkerType.MANUAL_NOTE: EDLColor.Red,
    MarkerType.TOS: EDLColor.Red,
    MarkerType.ERROR_DICCION: EDLColor.Red,
    MarkerType.CONFUSION: EDLColor.Red,
    MarkerType.REPETICION: EDLColor.Red,
    MarkerType.SCRIPT_MATCH: EDLColor.Green,
    MarkerType.IMAGEN: EDLColor.Green,
    MarkerType.AI_PROMPT: EDLColor.Magenta,
    MarkerType.ENTRADA: EDLColor.Cyan,
    MarkerType.SALIDA: EDLColor.Yellow,
}
