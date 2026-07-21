"""Modelos de datos fundamentales del sistema."""

from switch_bot.models.config import SUPPORTED_FPS, SystemConfig
from switch_bot.models.enums import (
    EDLColor,
    MARKER_COLOR_MAP,
    MarkerType,
    SourceOrigin,
)
from switch_bot.models.inference import CameraDecision, GazeResult, VADResult
from switch_bot.models.payload import EnrichedPayload
from switch_bot.models.timecode import SMPTETimecode

__all__ = [
    "CameraDecision",
    "EDLColor",
    "EnrichedPayload",
    "GazeResult",
    "MARKER_COLOR_MAP",
    "MarkerType",
    "SMPTETimecode",
    "SUPPORTED_FPS",
    "SourceOrigin",
    "SystemConfig",
    "VADResult",
]
