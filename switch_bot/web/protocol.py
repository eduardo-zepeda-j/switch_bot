"""Protocolo de comunicación bidireccional para el Canal_Comunicación.

Define el schema versionado de mensajes (ChannelMessage) y los payload structs
tipados para cada tipo de mensaje del protocolo WebSocket entre Agente_Local,
Servidor_EC2 y Frontend_SPA.

Usa msgspec.Struct para serialización/deserialización JSON de alto rendimiento
(5-10x más rápido que json.dumps/loads estándar).
"""

from __future__ import annotations

import logging
import re
from typing import Literal

import msgspec

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes del protocolo
# ---------------------------------------------------------------------------

MAX_PAYLOAD_SIZE_BYTES: int = 1_048_576  # 1 MB

CURRENT_PROTOCOL_VERSION: str = "1.0"

SUPPORTED_MAJOR_VERSIONS: frozenset[int] = frozenset({1})

_VERSION_PATTERN: re.Pattern[str] = re.compile(r"^(\d+)\.(\d+)$")

# ---------------------------------------------------------------------------
# Tipos de mensaje
# ---------------------------------------------------------------------------

MESSAGE_TYPES = Literal[
    "heartbeat",
    "heartbeat_ack",
    "inference_result",
    "switch_command",
    "state_update",
    "ai_request",
    "ai_response",
    "note_inject",
    "panic_button",
    "session_control",
    "state_sync_batch",
    "state_sync_ack",
    "error",
]

_VALID_MESSAGE_TYPES: frozenset[str] = frozenset(
    {
        "heartbeat",
        "heartbeat_ack",
        "inference_result",
        "switch_command",
        "state_update",
        "ai_request",
        "ai_response",
        "note_inject",
        "panic_button",
        "session_control",
        "state_sync_batch",
        "state_sync_ack",
        "error",
    }
)

# ---------------------------------------------------------------------------
# Excepciones de dominio
# ---------------------------------------------------------------------------


class ProtocolValidationError(Exception):
    """Error de validación de mensaje del protocolo.

    Se lanza cuando un mensaje no cumple el schema esperado:
    campos faltantes, tipos incorrectos o versión de protocolo no soportada.
    """


class PayloadTooLargeError(Exception):
    """Error de payload que excede el tamaño máximo permitido (1 MB).

    Se lanza cuando el payload serializado supera MAX_PAYLOAD_SIZE_BYTES.
    """


# ---------------------------------------------------------------------------
# Payload Structs
# ---------------------------------------------------------------------------


class HeartbeatPayload(msgspec.Struct, frozen=True):
    """Payload para heartbeat y heartbeat_ack."""

    sender_timestamp: str  # ISO 8601 ms precision
    seq: int  # Sequence number (uint64, monotonically increasing)


class InferenceResultPayload(msgspec.Struct, frozen=True):
    """Payload de resultado de inferencia (Agente → Servidor)."""

    gaze_x: float
    gaze_y: float
    gaze_target: str | None  # ID del personaje mirado
    landmarks: list[float]  # Landmarks faciales comprimidos
    vad_is_speaking: bool
    vad_speaker_id: str | None
    vad_start_tc: str | None  # SMPTE TC inicio actividad vocal
    vad_end_tc: str | None  # SMPTE TC fin actividad vocal
    smpte_tc: str  # TC actual del frame
    feed_index: int  # Índice de cámara fuente (0-3)


class SwitchCommandPayload(msgspec.Struct, frozen=True):
    """Payload de comando de conmutación (Servidor → Agente)."""

    target_cam: int  # Cámara destino (1-4)
    marker_type: str  # MarkerType como string
    note: str
    source_origin: str  # SourceOrigin como string
    smpte_tc: str


class StateUpdatePayload(msgspec.Struct, frozen=True):
    """Payload de actualización de estado (Servidor → SPA)."""

    active_cam: int
    tally_state: list[bool]  # [cam1_active, cam2_active, ...]
    current_tc: str  # SMPTE TC actual
    session_state: str  # created, started, paused, finalized
    panic_active: bool
    connected_agents: list[str]
    last_marker: dict | None  # Último marcador generado


class AIRequestPayload(msgspec.Struct, frozen=True):
    """Payload de solicitud de IA (Servidor → Agente para local)."""

    request_id: str
    operation: str  # "embeddings" | "analyze_context" | "similarity"
    texts: list[str] | None = None
    prompt: str | None = None
    context: str | None = None


class AIResponsePayload(msgspec.Struct, frozen=True):
    """Payload de respuesta de IA (Agente → Servidor)."""

    request_id: str
    success: bool
    embeddings: list[list[float]] | None = None
    analysis_result: str | None = None
    similarity_score: float | None = None
    error: str | None = None


class StateSyncBatchPayload(msgspec.Struct, frozen=True):
    """Payload de lote de State_Sync (Agente → Servidor)."""

    batch_id: int
    events: list[dict]  # Eventos con smpte_tc y datos
    total_pending: int
    tc_range_start: str  # Primer TC del lote
    tc_range_end: str  # Último TC del lote


class StateSyncAckPayload(msgspec.Struct, frozen=True):
    """Payload de ACK de State_Sync (Servidor → Agente)."""

    batch_id: int
    accepted: int  # Eventos aceptados
    conflicts: list[dict]  # Conflictos detectados (flag CONFLICT)


# ---------------------------------------------------------------------------
# ChannelMessage principal
# ---------------------------------------------------------------------------

# Encoders/decoders reutilizables (evita recrear en cada llamada)
_encoder = msgspec.json.Encoder()
_decoder = msgspec.json.Decoder(type=None)  # For raw payload size check


class ChannelMessage(msgspec.Struct):
    """Mensaje del protocolo de comunicación bidireccional.

    Todos los mensajes intercambiados entre Agente_Local, Servidor_EC2 y
    Frontend_SPA se encapsulan en esta estructura con campos obligatorios:
    type, timestamp, seq, version y payload.
    """

    type: str  # Tipo de mensaje (heartbeat, inference_result, etc.)
    timestamp: str  # ISO 8601 con ms precision
    seq: int  # Unsigned 64-bit sequence number
    version: str  # "MAJOR.MINOR" del protocolo
    payload: dict  # Datos específicos del tipo de mensaje

    def validate(self) -> bool:
        """Valida campos obligatorios, tipos y restricciones del protocolo.

        Returns:
            True si el mensaje es válido.

        Raises:
            ProtocolValidationError: Si el mensaje no cumple el schema.
            PayloadTooLargeError: Si el payload excede 1 MB.
        """
        # Validar tipo de mensaje
        if self.type not in _VALID_MESSAGE_TYPES:
            raise ProtocolValidationError(
                f"Tipo de mensaje inválido: '{self.type}'. "
                f"Tipos válidos: {sorted(_VALID_MESSAGE_TYPES)}"
            )

        # Validar timestamp no vacío
        if not self.timestamp:
            raise ProtocolValidationError(
                "Campo 'timestamp' es obligatorio y no puede estar vacío."
            )

        # Validar seq >= 0 (unsigned 64-bit)
        if self.seq < 0:
            raise ProtocolValidationError(
                f"Campo 'seq' debe ser un entero no negativo, recibido: {self.seq}"
            )

        # Validar formato de versión "MAJOR.MINOR"
        match = _VERSION_PATTERN.match(self.version)
        if not match:
            raise ProtocolValidationError(
                f"Campo 'version' debe tener formato 'MAJOR.MINOR', "
                f"recibido: '{self.version}'"
            )

        # Validar MAJOR soportado
        major = int(match.group(1))
        if major not in SUPPORTED_MAJOR_VERSIONS:
            raise ProtocolValidationError(
                f"Versión MAJOR {major} no soportada. "
                f"Versiones soportadas: {sorted(SUPPORTED_MAJOR_VERSIONS)}"
            )

        # Validar tamaño de payload
        payload_bytes = msgspec.json.encode(self.payload)
        if len(payload_bytes) > MAX_PAYLOAD_SIZE_BYTES:
            raise PayloadTooLargeError(
                f"Payload excede el tamaño máximo de {MAX_PAYLOAD_SIZE_BYTES} bytes "
                f"({len(payload_bytes)} bytes)."
            )

        return True

    def encode(self) -> bytes:
        """Serializa el mensaje completo a JSON bytes con msgspec.

        Returns:
            Bytes JSON del mensaje serializado.

        Note:
            Este método NO ejecuta validación. Llamar validate() primero si se
            requiere garantizar integridad antes de enviar.
        """
        return msgspec.json.encode(self)

    @classmethod
    def decode(cls, data: bytes) -> ChannelMessage:
        """Deserializa un mensaje desde JSON bytes.

        Args:
            data: Bytes JSON a deserializar.

        Returns:
            Instancia de ChannelMessage.

        Raises:
            msgspec.DecodeError: Si los datos no son JSON válido o no cumplen
                la estructura de ChannelMessage.
        """
        return msgspec.json.decode(data, type=cls)


# ---------------------------------------------------------------------------
# Funciones utilitarias
# ---------------------------------------------------------------------------


def is_version_compatible(message_version: str, supported_version: str) -> bool:
    """Verifica si la versión del mensaje es compatible con la soportada.

    Compatibilidad se define como: mismo MAJOR, independiente del MINOR.

    Args:
        message_version: Versión del mensaje recibido (formato "MAJOR.MINOR").
        supported_version: Versión del protocolo soportado (formato "MAJOR.MINOR").

    Returns:
        True si son compatibles (mismo MAJOR).

    Raises:
        ProtocolValidationError: Si alguna versión tiene formato inválido.
    """
    msg_match = _VERSION_PATTERN.match(message_version)
    sup_match = _VERSION_PATTERN.match(supported_version)

    if not msg_match:
        raise ProtocolValidationError(
            f"Versión de mensaje inválida: '{message_version}'"
        )
    if not sup_match:
        raise ProtocolValidationError(
            f"Versión soportada inválida: '{supported_version}'"
        )

    return int(msg_match.group(1)) == int(sup_match.group(1))
