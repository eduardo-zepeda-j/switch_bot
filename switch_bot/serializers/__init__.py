"""Serializadores EDL (CMX 3600) y DRP (JSON Lines)."""

from switch_bot.serializers.drp_serializer import (
    DRPDocument,
    DRPProjectConfig,
    DRPSource,
    DRPSwitchEvent,
)
from switch_bot.serializers.edl_serializer import EDLDocument, EDLEvent

__all__ = [
    "DRPDocument",
    "DRPProjectConfig",
    "DRPSource",
    "DRPSwitchEvent",
    "EDLDocument",
    "EDLEvent",
]
