"""Captura multicanal de video y audio.

Expone CaptureManager como API principal del módulo de captura.
"""

from switch_bot.capture.capture_manager import (
    AudioPacket,
    CaptureManager,
    FramePacket,
)

__all__ = ["CaptureManager", "FramePacket", "AudioPacket"]
