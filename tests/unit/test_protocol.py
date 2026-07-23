"""Unit tests para serialización/deserialización del protocolo ChannelMessage.

Valida:
- Round-trip (encode → decode) para cada tipo de payload
- Rechazo de mensajes con campos faltantes, tipos incorrectos o payload > 1 MB
- Compatibilidad de versión: mismo MAJOR con diferente MINOR
- Rechazo de MAJOR no soportado
- PayloadTooLargeError para payloads > 1 MB
- ProtocolValidationError para violaciones de schema
- msgspec.DecodeError para JSON malformado en decode()

Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6
"""

from __future__ import annotations

import pytest
import msgspec
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from switch_bot.web.protocol import (
    ChannelMessage,
    HeartbeatPayload,
    InferenceResultPayload,
    SwitchCommandPayload,
    StateUpdatePayload,
    AIRequestPayload,
    AIResponsePayload,
    StateSyncBatchPayload,
    StateSyncAckPayload,
    ProtocolValidationError,
    PayloadTooLargeError,
    is_version_compatible,
    CURRENT_PROTOCOL_VERSION,
    MAX_PAYLOAD_SIZE_BYTES,
    SUPPORTED_MAJOR_VERSIONS,
    _VALID_MESSAGE_TYPES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_message(
    msg_type: str = "heartbeat",
    timestamp: str = "2024-01-15T10:30:00.123Z",
    seq: int = 1,
    version: str = "1.0",
    payload: dict | None = None,
) -> ChannelMessage:
    """Crea un ChannelMessage con valores por defecto razonables."""
    if payload is None:
        payload = {"sender_timestamp": "2024-01-15T10:30:00.123Z", "seq": 1}
    return ChannelMessage(
        type=msg_type,
        timestamp=timestamp,
        seq=seq,
        version=version,
        payload=payload,
    )


def _payload_to_dict(struct: msgspec.Struct) -> dict:
    """Convierte un msgspec.Struct a dict para usar como payload."""
    return msgspec.to_builtins(struct)


# ---------------------------------------------------------------------------
# Payloads de ejemplo para round-trip
# ---------------------------------------------------------------------------

SAMPLE_HEARTBEAT = HeartbeatPayload(
    sender_timestamp="2024-01-15T10:30:00.123Z",
    seq=42,
)

SAMPLE_INFERENCE = InferenceResultPayload(
    gaze_x=0.75,
    gaze_y=0.32,
    gaze_target="character_A",
    landmarks=[0.1, 0.2, 0.3, 0.4, 0.5],
    vad_is_speaking=True,
    vad_speaker_id="speaker_01",
    vad_start_tc="01:00:05:12",
    vad_end_tc="01:00:07:24",
    smpte_tc="01:00:06:15",
    feed_index=2,
)

SAMPLE_SWITCH_CMD = SwitchCommandPayload(
    target_cam=3,
    marker_type="CUT",
    note="Cambio por gaze tracking",
    source_origin="DECISION_ENGINE",
    smpte_tc="01:00:10:00",
)

SAMPLE_STATE_UPDATE = StateUpdatePayload(
    active_cam=2,
    tally_state=[False, True, False, False],
    current_tc="01:00:15:22",
    session_state="started",
    panic_active=False,
    connected_agents=["op_01", "op_02"],
    last_marker={"type": "CUT", "cam": 2},
)

SAMPLE_AI_REQUEST = AIRequestPayload(
    request_id="req-001",
    operation="embeddings",
    texts=["texto de ejemplo para embedding"],
    prompt=None,
    context=None,
)

SAMPLE_AI_RESPONSE = AIResponsePayload(
    request_id="req-001",
    success=True,
    embeddings=[[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
    analysis_result=None,
    similarity_score=None,
    error=None,
)

SAMPLE_SYNC_BATCH = StateSyncBatchPayload(
    batch_id=1,
    events=[
        {"smpte_tc": "01:00:00:00", "type": "inference_result", "data": {}},
        {"smpte_tc": "01:00:01:00", "type": "switch_command", "data": {}},
    ],
    total_pending=150,
    tc_range_start="01:00:00:00",
    tc_range_end="01:00:01:00",
)

SAMPLE_SYNC_ACK = StateSyncAckPayload(
    batch_id=1,
    accepted=2,
    conflicts=[],
)

# Mapeo de tipos de mensaje a su payload de ejemplo
PAYLOAD_SAMPLES: dict[str, msgspec.Struct] = {
    "heartbeat": SAMPLE_HEARTBEAT,
    "heartbeat_ack": SAMPLE_HEARTBEAT,
    "inference_result": SAMPLE_INFERENCE,
    "switch_command": SAMPLE_SWITCH_CMD,
    "state_update": SAMPLE_STATE_UPDATE,
    "ai_request": SAMPLE_AI_REQUEST,
    "ai_response": SAMPLE_AI_RESPONSE,
    "state_sync_batch": SAMPLE_SYNC_BATCH,
    "state_sync_ack": SAMPLE_SYNC_ACK,
}


# ---------------------------------------------------------------------------
# Tests: Round-trip encode → decode (Req 12.3)
# ---------------------------------------------------------------------------

class TestRoundTrip:
    """Validates: Requirements 12.3 - encode → decode produce igualdad profunda."""

    @pytest.mark.parametrize("msg_type,payload_struct", list(PAYLOAD_SAMPLES.items()))
    def test_protocol_roundtrip_each_payload_type(
        self, msg_type: str, payload_struct: msgspec.Struct
    ) -> None:
        """Encode → decode produce igualdad profunda para cada tipo de payload."""
        original = _make_message(
            msg_type=msg_type,
            payload=_payload_to_dict(payload_struct),
        )

        encoded = original.encode()
        decoded = ChannelMessage.decode(encoded)

        assert decoded.type == original.type
        assert decoded.timestamp == original.timestamp
        assert decoded.seq == original.seq
        assert decoded.version == original.version
        assert decoded.payload == original.payload

    def test_protocol_roundtrip_preserves_none_fields(self) -> None:
        """Round-trip preserva campos con valor None."""
        payload = _payload_to_dict(
            AIResponsePayload(
                request_id="req-x",
                success=False,
                embeddings=None,
                analysis_result=None,
                similarity_score=None,
                error="timeout",
            )
        )
        original = _make_message(msg_type="ai_response", payload=payload)
        decoded = ChannelMessage.decode(original.encode())
        assert decoded.payload == original.payload

    def test_protocol_roundtrip_preserves_empty_lists(self) -> None:
        """Round-trip preserva listas vacías."""
        payload = _payload_to_dict(
            StateSyncAckPayload(batch_id=5, accepted=0, conflicts=[])
        )
        original = _make_message(msg_type="state_sync_ack", payload=payload)
        decoded = ChannelMessage.decode(original.encode())
        assert decoded.payload["conflicts"] == []

    def test_protocol_roundtrip_large_landmarks(self) -> None:
        """Round-trip con payload que contiene listas grandes de landmarks."""
        payload = _payload_to_dict(
            InferenceResultPayload(
                gaze_x=0.5,
                gaze_y=0.5,
                gaze_target=None,
                landmarks=[float(i) / 1000 for i in range(468)],  # MediaPipe face mesh
                vad_is_speaking=False,
                vad_speaker_id=None,
                vad_start_tc=None,
                vad_end_tc=None,
                smpte_tc="00:00:00:00",
                feed_index=0,
            )
        )
        original = _make_message(msg_type="inference_result", payload=payload)
        decoded = ChannelMessage.decode(original.encode())
        assert decoded.payload == original.payload
        assert len(decoded.payload["landmarks"]) == 468


# ---------------------------------------------------------------------------
# Tests: Round-trip property-based con Hypothesis (Req 12.3)
# ---------------------------------------------------------------------------

class TestRoundTripProperty:
    """Validates: Requirements 12.3 - propiedad round-trip con generación aleatoria."""

    @given(
        msg_type=st.sampled_from(sorted(_VALID_MESSAGE_TYPES)),
        timestamp=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N", "P")),
            min_size=1,
            max_size=30,
        ),
        seq=st.integers(min_value=0, max_value=2**63 - 1),
        minor=st.integers(min_value=0, max_value=99),
    )
    @settings(max_examples=50)
    def test_protocol_roundtrip_property(
        self, msg_type: str, timestamp: str, seq: int, minor: int
    ) -> None:
        """Para cualquier ChannelMessage válido, encode → decode = original."""
        version = f"1.{minor}"
        payload = {"key": "value", "number": seq}

        original = ChannelMessage(
            type=msg_type,
            timestamp=timestamp,
            seq=seq,
            version=version,
            payload=payload,
        )

        encoded = original.encode()
        decoded = ChannelMessage.decode(encoded)

        assert decoded.type == original.type
        assert decoded.timestamp == original.timestamp
        assert decoded.seq == original.seq
        assert decoded.version == original.version
        assert decoded.payload == original.payload


# ---------------------------------------------------------------------------
# Tests: Validación — rechazo de mensajes inválidos (Req 12.2, 12.5)
# ---------------------------------------------------------------------------

class TestValidation:
    """Validates: Requirements 12.2, 12.5 - validación rechaza mensajes inválidos."""

    def test_protocol_validation_rejects_invalid_message_type(self) -> None:
        """Tipo de mensaje no reconocido lanza ProtocolValidationError."""
        msg = _make_message(msg_type="invalid_type")
        with pytest.raises(ProtocolValidationError, match="Tipo de mensaje inválido"):
            msg.validate()

    def test_protocol_validation_rejects_empty_timestamp(self) -> None:
        """Timestamp vacío lanza ProtocolValidationError."""
        msg = _make_message(timestamp="")
        with pytest.raises(ProtocolValidationError, match="timestamp"):
            msg.validate()

    def test_protocol_validation_rejects_negative_seq(self) -> None:
        """Seq negativo lanza ProtocolValidationError."""
        msg = _make_message(seq=-1)
        with pytest.raises(ProtocolValidationError, match="seq"):
            msg.validate()

    def test_protocol_validation_rejects_invalid_version_format(self) -> None:
        """Versión con formato inválido lanza ProtocolValidationError."""
        for invalid_version in ["1", "abc", "1.2.3", "", "v1.0", "1.", ".1"]:
            msg = _make_message(version=invalid_version)
            with pytest.raises(ProtocolValidationError, match="version"):
                msg.validate()

    def test_protocol_validation_rejects_unsupported_major_version(self) -> None:
        """MAJOR no soportado lanza ProtocolValidationError."""
        msg = _make_message(version="2.0")
        with pytest.raises(ProtocolValidationError, match="no soportada"):
            msg.validate()

        msg = _make_message(version="99.0")
        with pytest.raises(ProtocolValidationError, match="no soportada"):
            msg.validate()

    def test_protocol_validation_rejects_payload_too_large(self) -> None:
        """Payload que excede 1 MB lanza PayloadTooLargeError."""
        # Crear payload que exceda 1 MB
        large_payload = {"data": "x" * (MAX_PAYLOAD_SIZE_BYTES + 1)}
        msg = _make_message(payload=large_payload)
        with pytest.raises(PayloadTooLargeError, match="excede"):
            msg.validate()

    def test_protocol_validation_accepts_valid_message(self) -> None:
        """Un mensaje válido pasa la validación sin error."""
        msg = _make_message()
        assert msg.validate() is True

    def test_protocol_validation_accepts_payload_at_limit(self) -> None:
        """Payload justo en el límite de 1 MB es aceptado."""
        # Generar un payload que ocupe justo < 1 MB en JSON serializado
        # El overhead de la clave JSON reduce el espacio disponible
        payload = {"d": "a" * (MAX_PAYLOAD_SIZE_BYTES - 10)}
        msg = _make_message(payload=payload)
        # Si esto no cabe, reducimos un poco
        payload_bytes = msgspec.json.encode(payload)
        if len(payload_bytes) > MAX_PAYLOAD_SIZE_BYTES:
            # Ajustar para que quepa
            excess = len(payload_bytes) - MAX_PAYLOAD_SIZE_BYTES
            payload = {"d": "a" * (MAX_PAYLOAD_SIZE_BYTES - 10 - excess)}
        msg = _make_message(payload=payload)
        assert msg.validate() is True


# ---------------------------------------------------------------------------
# Tests: Compatibilidad de versión (Req 12.4)
# ---------------------------------------------------------------------------

class TestVersionCompatibility:
    """Validates: Requirements 12.4 - mismo MAJOR es compatible, diferente MAJOR no."""

    def test_protocol_version_same_major_different_minor_compatible(self) -> None:
        """Versiones con mismo MAJOR son compatibles independiente del MINOR."""
        assert is_version_compatible("1.0", "1.0") is True
        assert is_version_compatible("1.0", "1.5") is True
        assert is_version_compatible("1.5", "1.0") is True
        assert is_version_compatible("1.99", "1.0") is True
        assert is_version_compatible("1.0", "1.99") is True

    def test_protocol_version_different_major_incompatible(self) -> None:
        """Versiones con diferente MAJOR son incompatibles."""
        assert is_version_compatible("2.0", "1.0") is False
        assert is_version_compatible("1.0", "2.0") is False
        assert is_version_compatible("3.0", "1.0") is False

    def test_protocol_version_invalid_format_raises(self) -> None:
        """Versiones con formato inválido lanzan ProtocolValidationError."""
        with pytest.raises(ProtocolValidationError):
            is_version_compatible("invalid", "1.0")
        with pytest.raises(ProtocolValidationError):
            is_version_compatible("1.0", "bad")
        with pytest.raises(ProtocolValidationError):
            is_version_compatible("", "1.0")

    @given(minor=st.integers(min_value=0, max_value=999))
    @settings(max_examples=20)
    def test_protocol_version_any_minor_compatible_with_same_major(
        self, minor: int
    ) -> None:
        """Cualquier MINOR es compatible con otro MINOR del mismo MAJOR."""
        assert is_version_compatible(f"1.{minor}", CURRENT_PROTOCOL_VERSION) is True

    def test_protocol_validate_message_with_compatible_version(self) -> None:
        """Mensaje con versión 1.5 pasa validación (compatible con 1.0)."""
        msg = _make_message(version="1.5")
        assert msg.validate() is True

    def test_protocol_validate_message_with_incompatible_major(self) -> None:
        """Mensaje con versión 2.0 es rechazado por validación."""
        msg = _make_message(version="2.0")
        with pytest.raises(ProtocolValidationError, match="no soportada"):
            msg.validate()


# ---------------------------------------------------------------------------
# Tests: PayloadTooLargeError (Req 12.5)
# ---------------------------------------------------------------------------

class TestPayloadTooLarge:
    """Validates: Requirements 12.5 - payload > 1 MB es rechazado."""

    def test_protocol_payload_exactly_over_limit_raises(self) -> None:
        """Payload que supera 1 MB por un byte lanza PayloadTooLargeError."""
        # Generar payload que justo exceda el límite
        payload = {"x": "a" * MAX_PAYLOAD_SIZE_BYTES}
        msg = _make_message(payload=payload)
        with pytest.raises(PayloadTooLargeError):
            msg.validate()

    def test_protocol_payload_well_over_limit_raises(self) -> None:
        """Payload significativamente mayor a 1 MB lanza PayloadTooLargeError."""
        payload = {"data": "x" * (2 * MAX_PAYLOAD_SIZE_BYTES)}
        msg = _make_message(payload=payload)
        with pytest.raises(PayloadTooLargeError):
            msg.validate()


# ---------------------------------------------------------------------------
# Tests: ProtocolValidationError para schema violations (Req 12.2)
# ---------------------------------------------------------------------------

class TestSchemaViolations:
    """Validates: Requirements 12.2 - campos faltantes/incorrectos son rechazados."""

    def test_protocol_decode_missing_required_field_raises(self) -> None:
        """JSON sin campo obligatorio lanza DecodeError en decode()."""
        # Falta 'seq'
        incomplete_json = b'{"type":"heartbeat","timestamp":"2024-01-01T00:00:00Z","version":"1.0","payload":{}}'
        with pytest.raises(msgspec.DecodeError):
            ChannelMessage.decode(incomplete_json)

    def test_protocol_decode_wrong_type_for_field_raises(self) -> None:
        """JSON con tipo incorrecto en campo lanza DecodeError."""
        # seq debería ser int, no string
        bad_json = b'{"type":"heartbeat","timestamp":"2024-01-01T00:00:00Z","seq":"not_a_number","version":"1.0","payload":{}}'
        with pytest.raises(msgspec.DecodeError):
            ChannelMessage.decode(bad_json)

    def test_protocol_decode_malformed_json_raises(self) -> None:
        """JSON malformado (sintaxis inválida) lanza DecodeError."""
        with pytest.raises(msgspec.DecodeError):
            ChannelMessage.decode(b"not json at all")

        with pytest.raises(msgspec.DecodeError):
            ChannelMessage.decode(b"{invalid json}")

        with pytest.raises(msgspec.DecodeError):
            ChannelMessage.decode(b"")

    def test_protocol_decode_null_payload_raises(self) -> None:
        """JSON con payload null lanza DecodeError (debe ser dict)."""
        null_payload = b'{"type":"heartbeat","timestamp":"2024-01-01T00:00:00Z","seq":1,"version":"1.0","payload":null}'
        with pytest.raises(msgspec.DecodeError):
            ChannelMessage.decode(null_payload)

    def test_protocol_decode_payload_as_array_raises(self) -> None:
        """JSON con payload como array lanza DecodeError (debe ser dict)."""
        array_payload = b'{"type":"heartbeat","timestamp":"2024-01-01T00:00:00Z","seq":1,"version":"1.0","payload":[]}'
        with pytest.raises(msgspec.DecodeError):
            ChannelMessage.decode(array_payload)
