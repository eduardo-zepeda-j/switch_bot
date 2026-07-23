"""Módulo web para la arquitectura híbrida cliente-servidor.

Contiene el protocolo de comunicación bidireccional, WebSocket hub,
heartbeat, fallback, sincronización de estado, y backend FastAPI.
"""

from switch_bot.web.fallback import FallbackManager
from switch_bot.web.hub import WebSocketHub
from switch_bot.web.protocol import (
    AIRequestPayload,
    AIResponsePayload,
    ChannelMessage,
    HeartbeatPayload,
    InferenceResultPayload,
    PayloadTooLargeError,
    ProtocolValidationError,
    StateSyncAckPayload,
    StateSyncBatchPayload,
    StateUpdatePayload,
    SwitchCommandPayload,
)
from switch_bot.web.state_sync import StateSyncProtocol, StateSyncResult

__all__ = [
    "AIRequestPayload",
    "AIResponsePayload",
    "ChannelMessage",
    "FallbackManager",
    "HeartbeatPayload",
    "InferenceResultPayload",
    "PayloadTooLargeError",
    "ProtocolValidationError",
    "StateSyncAckPayload",
    "StateSyncBatchPayload",
    "StateSyncProtocol",
    "StateSyncResult",
    "StateUpdatePayload",
    "SwitchCommandPayload",
    "WebSocketHub",
]
