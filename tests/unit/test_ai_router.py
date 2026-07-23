"""Tests unitarios para AIRouter.

Verifica enrutamiento de solicitudes de IA a Bedrock (cloud) o Agente_Local,
timeouts diferenciados, manejo de fallos, y estructura de salida uniforme.

Requirements cubiertos:
- 5.1: Bedrock procesa sin reenviar al agente
- 5.2: Local reenvía al agente vía Canal_Comunicación
- 5.4: Timeouts 30s local, 10s Bedrock
- 5.5: Timeout local registra fallo con SMPTE_TC
- 5.6: Timeout Bedrock registra fallo con SMPTE_TC
- 5.7: Agente inalcanzable registra error
- 5.8: Estructura de salida idéntica
"""

from __future__ import annotations

import asyncio

import pytest

from switch_bot.web.ai_router import (
    AIRequest,
    AIResponse,
    AIRouter,
    BedrockBackend,
)
from switch_bot.web.hub import WebSocketHub
from switch_bot.web.protocol import AIResponsePayload, ChannelMessage


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeWebSocket:
    """WebSocket falso que registra mensajes enviados."""

    def __init__(self, *, should_fail: bool = False):
        self.sent: list[bytes] = []
        self.should_fail = should_fail

    async def send_bytes(self, data: bytes) -> None:
        if self.should_fail:
            raise ConnectionError("WebSocket closed")
        self.sent.append(data)


class FakeBedrockBackend:
    """Backend de Bedrock falso para testing."""

    def __init__(
        self,
        *,
        delay: float = 0.0,
        should_fail: bool = False,
        embeddings_result: list[list[float]] | None = None,
        analysis_result: str | None = None,
        similarity_result: float | None = None,
    ):
        self.delay = delay
        self.should_fail = should_fail
        self.embeddings_result = embeddings_result or [[0.1, 0.2, 0.3]]
        self.analysis_result = analysis_result or "Análisis completado"
        self.similarity_result = similarity_result or 0.85
        self.call_count = 0

    async def invoke_embeddings(self, texts: list[str]) -> list[list[float]]:
        self.call_count += 1
        if self.delay > 0:
            await asyncio.sleep(self.delay)
        if self.should_fail:
            raise RuntimeError("Bedrock invocation failed")
        return self.embeddings_result

    async def invoke_analysis(
        self, prompt: str, context: str | None = None
    ) -> str:
        self.call_count += 1
        if self.delay > 0:
            await asyncio.sleep(self.delay)
        if self.should_fail:
            raise RuntimeError("Bedrock invocation failed")
        return self.analysis_result

    async def invoke_similarity(self, texts: list[str]) -> float:
        self.call_count += 1
        if self.delay > 0:
            await asyncio.sleep(self.delay)
        if self.should_fail:
            raise RuntimeError("Bedrock invocation failed")
        return self.similarity_result


def _valid_token_validator(token: str) -> dict | None:
    if token.startswith("valid-"):
        return {"user_id": "test-user", "role": "operador"}
    return None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def hub() -> WebSocketHub:
    return WebSocketHub(
        max_agents=4,
        max_spa_clients=10,
        token_validator=_valid_token_validator,
    )


@pytest.fixture
def bedrock() -> FakeBedrockBackend:
    return FakeBedrockBackend()


@pytest.fixture
def router(hub: WebSocketHub, bedrock: FakeBedrockBackend) -> AIRouter:
    return AIRouter(hub=hub, bedrock_backend=bedrock)


# ---------------------------------------------------------------------------
# Tests de configuración de backend
# ---------------------------------------------------------------------------


def test_default_backend_is_bedrock(router: AIRouter) -> None:
    """El backend por defecto es 'bedrock'."""
    assert router.active_backend == "bedrock"


def test_set_backend_to_local(router: AIRouter) -> None:
    router.set_backend("local")
    assert router.active_backend == "local"


def test_set_backend_to_bedrock(router: AIRouter) -> None:
    router.set_backend("local")
    router.set_backend("bedrock")
    assert router.active_backend == "bedrock"


def test_set_backend_invalid_raises(router: AIRouter) -> None:
    with pytest.raises(ValueError, match="Backend inválido"):
        router.set_backend("invalid")


# ---------------------------------------------------------------------------
# Tests de timeouts (constantes)
# ---------------------------------------------------------------------------


def test_bedrock_timeout_is_10s() -> None:
    assert AIRouter.BEDROCK_TIMEOUT == 10.0


def test_local_timeout_is_30s() -> None:
    assert AIRouter.LOCAL_TIMEOUT == 30.0


# ---------------------------------------------------------------------------
# Tests de route_request — modo Bedrock (Req 5.1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_bedrock_embeddings(router: AIRouter) -> None:
    """Backend Bedrock procesa embeddings sin reenviar al agente."""
    request = AIRequest(
        operation="embeddings",
        texts=["Hola mundo"],
        smpte_tc="01:02:03:04",
    )
    response = await router.route_request(request, "op-1")

    assert response.success is True
    assert response.embeddings == [[0.1, 0.2, 0.3]]
    assert response.processed is True
    assert response.request_id == request.request_id


@pytest.mark.asyncio
async def test_route_bedrock_analysis(router: AIRouter) -> None:
    """Backend Bedrock procesa análisis contextual."""
    request = AIRequest(
        operation="analyze_context",
        prompt="Analiza el contexto",
        context="Escena 5",
        smpte_tc="00:10:00:00",
    )
    response = await router.route_request(request, "op-1")

    assert response.success is True
    assert response.analysis_result == "Análisis completado"
    assert response.processed is True


@pytest.mark.asyncio
async def test_route_bedrock_similarity(router: AIRouter) -> None:
    """Backend Bedrock procesa similarity."""
    request = AIRequest(
        operation="similarity",
        texts=["texto A", "texto B"],
        smpte_tc="00:05:00:00",
    )
    response = await router.route_request(request, "op-1")

    assert response.success is True
    assert response.similarity_score == 0.85
    assert response.processed is True


# ---------------------------------------------------------------------------
# Tests de timeout Bedrock (Req 5.6)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bedrock_timeout_marks_unprocessed(
    hub: WebSocketHub,
) -> None:
    """Timeout de Bedrock registra fallo con SMPTE_TC y marca no procesado."""
    # Usar un timeout corto para el test
    slow_bedrock = FakeBedrockBackend(delay=0.5)
    router = AIRouter(hub=hub, bedrock_backend=slow_bedrock)
    # Override timeout para test rápido
    router.BEDROCK_TIMEOUT = 0.1

    request = AIRequest(
        operation="embeddings",
        texts=["test"],
        smpte_tc="01:30:15:12",
    )
    response = await router.route_request(request, "op-1")

    assert response.success is False
    assert response.processed is False
    assert "Timeout" in (response.error or "")
    assert "01:30:15:12" in (response.error or "")


@pytest.mark.asyncio
async def test_bedrock_error_marks_unprocessed(hub: WebSocketHub) -> None:
    """Error de Bedrock marca segmento como no procesado."""
    failing_bedrock = FakeBedrockBackend(should_fail=True)
    router = AIRouter(hub=hub, bedrock_backend=failing_bedrock)

    request = AIRequest(
        operation="embeddings",
        texts=["test"],
        smpte_tc="02:00:00:00",
    )
    response = await router.route_request(request, "op-1")

    assert response.success is False
    assert response.processed is False
    assert "Error" in (response.error or "")


# ---------------------------------------------------------------------------
# Tests de route_request — modo Local (Req 5.2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_local_sends_to_agent(
    hub: WebSocketHub, bedrock: FakeBedrockBackend
) -> None:
    """Backend local reenvía la solicitud al agente vía WebSocket."""
    ws = FakeWebSocket()
    await hub.register_agent("op-1", ws, "valid-token")

    router = AIRouter(hub=hub, bedrock_backend=bedrock)
    router.set_backend("local")

    request = AIRequest(
        operation="embeddings",
        texts=["test text"],
        smpte_tc="00:01:00:00",
    )

    # Simular respuesta del agente en un task separado
    async def simulate_agent_response():
        await asyncio.sleep(0.05)
        payload = AIResponsePayload(
            request_id=request.request_id,
            success=True,
            embeddings=[[0.5, 0.6, 0.7]],
        )
        router.handle_ai_response(payload)

    asyncio.get_event_loop().create_task(simulate_agent_response())

    response = await router.route_request(request, "op-1")

    assert response.success is True
    assert response.embeddings == [[0.5, 0.6, 0.7]]
    assert response.processed is True
    # Verificar que se envió un mensaje al agente
    assert len(ws.sent) == 1
    msg = ChannelMessage.decode(ws.sent[0])
    assert msg.type == "ai_request"
    assert msg.payload["request_id"] == request.request_id
    assert msg.payload["operation"] == "embeddings"


# ---------------------------------------------------------------------------
# Tests de agente inalcanzable (Req 5.7)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_agent_unreachable(router: AIRouter) -> None:
    """Agente no conectado marca segmento como no procesado."""
    router.set_backend("local")

    request = AIRequest(
        operation="embeddings",
        texts=["test"],
        smpte_tc="00:45:10:20",
    )
    response = await router.route_request(request, "op-nonexistent")

    assert response.success is False
    assert response.processed is False
    assert "inalcanzable" in (response.error or "").lower()


@pytest.mark.asyncio
async def test_local_agent_connection_error(
    hub: WebSocketHub, bedrock: FakeBedrockBackend
) -> None:
    """Agente con conexión rota marca segmento como no procesado."""
    ws = FakeWebSocket(should_fail=True)
    await hub.register_agent("op-broken", ws, "valid-token")

    router = AIRouter(hub=hub, bedrock_backend=bedrock)
    router.set_backend("local")

    request = AIRequest(
        operation="embeddings",
        texts=["test"],
        smpte_tc="00:20:00:00",
    )
    response = await router.route_request(request, "op-broken")

    assert response.success is False
    assert response.processed is False


# ---------------------------------------------------------------------------
# Tests de timeout local (Req 5.5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_timeout_marks_unprocessed(
    hub: WebSocketHub, bedrock: FakeBedrockBackend
) -> None:
    """Timeout local registra fallo con SMPTE_TC y marca no procesado."""
    ws = FakeWebSocket()
    await hub.register_agent("op-1", ws, "valid-token")

    router = AIRouter(hub=hub, bedrock_backend=bedrock)
    router.set_backend("local")
    # Override timeout para test rápido
    router.LOCAL_TIMEOUT = 0.1

    request = AIRequest(
        operation="analyze_context",
        prompt="test prompt",
        smpte_tc="01:15:30:05",
    )
    # No simulamos respuesta del agente → timeout
    response = await router.route_request(request, "op-1")

    assert response.success is False
    assert response.processed is False
    assert "Timeout" in (response.error or "")
    assert "01:15:30:05" in (response.error or "")


# ---------------------------------------------------------------------------
# Tests de estructura de salida idéntica (Req 5.8)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_output_structure_identical_bedrock(router: AIRouter) -> None:
    """Respuesta de Bedrock tiene todos los campos de AIResponse."""
    request = AIRequest(operation="embeddings", texts=["x"])
    response = await router.route_request(request, "op-1")

    # Verificar que todos los atributos existen
    assert hasattr(response, "request_id")
    assert hasattr(response, "success")
    assert hasattr(response, "embeddings")
    assert hasattr(response, "analysis_result")
    assert hasattr(response, "similarity_score")
    assert hasattr(response, "error")
    assert hasattr(response, "processed")


@pytest.mark.asyncio
async def test_output_structure_identical_local(
    hub: WebSocketHub, bedrock: FakeBedrockBackend
) -> None:
    """Respuesta local tiene todos los campos de AIResponse."""
    ws = FakeWebSocket()
    await hub.register_agent("op-1", ws, "valid-token")

    router = AIRouter(hub=hub, bedrock_backend=bedrock)
    router.set_backend("local")

    request = AIRequest(operation="embeddings", texts=["x"])

    # Simular respuesta
    async def simulate_response():
        await asyncio.sleep(0.05)
        payload = AIResponsePayload(
            request_id=request.request_id,
            success=True,
            embeddings=[[1.0, 2.0]],
        )
        router.handle_ai_response(payload)

    asyncio.get_event_loop().create_task(simulate_response())

    response = await router.route_request(request, "op-1")

    assert hasattr(response, "request_id")
    assert hasattr(response, "success")
    assert hasattr(response, "embeddings")
    assert hasattr(response, "analysis_result")
    assert hasattr(response, "similarity_score")
    assert hasattr(response, "error")
    assert hasattr(response, "processed")


# ---------------------------------------------------------------------------
# Tests de handle_ai_response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_ai_response_resolves_future(router: AIRouter) -> None:
    """handle_ai_response resuelve el Future pendiente correctamente."""
    loop = asyncio.get_running_loop()
    future: asyncio.Future[AIResponsePayload] = loop.create_future()
    router._pending_responses["req-123"] = future

    payload = AIResponsePayload(
        request_id="req-123",
        success=True,
        analysis_result="resultado test",
    )
    router.handle_ai_response(payload)

    assert future.done()
    result = future.result()
    assert result.request_id == "req-123"
    assert result.success is True


def test_handle_ai_response_no_pending_future(router: AIRouter) -> None:
    """handle_ai_response con request_id sin Future pendiente no falla."""
    payload = AIResponsePayload(
        request_id="unknown-req",
        success=True,
    )
    # No debe lanzar excepción
    router.handle_ai_response(payload)


# ---------------------------------------------------------------------------
# Tests de validación de operaciones en Bedrock
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bedrock_embeddings_no_texts_fails(router: AIRouter) -> None:
    """Embeddings sin texts retorna error."""
    request = AIRequest(operation="embeddings", texts=None)
    response = await router.route_request(request, "op-1")

    assert response.success is False
    assert "texts" in (response.error or "").lower()


@pytest.mark.asyncio
async def test_bedrock_analysis_no_prompt_fails(router: AIRouter) -> None:
    """Análisis sin prompt retorna error."""
    request = AIRequest(operation="analyze_context", prompt=None)
    response = await router.route_request(request, "op-1")

    assert response.success is False
    assert "prompt" in (response.error or "").lower()


@pytest.mark.asyncio
async def test_bedrock_similarity_insufficient_texts_fails(
    router: AIRouter,
) -> None:
    """Similarity con menos de 2 textos retorna error."""
    request = AIRequest(operation="similarity", texts=["solo uno"])
    response = await router.route_request(request, "op-1")

    assert response.success is False
    assert "texts" in (response.error or "").lower()


@pytest.mark.asyncio
async def test_bedrock_unsupported_operation_fails(router: AIRouter) -> None:
    """Operación no soportada retorna error."""
    request = AIRequest(operation="unsupported_op", texts=["x"])
    response = await router.route_request(request, "op-1")

    assert response.success is False
    assert "no soportada" in (response.error or "").lower()


# ---------------------------------------------------------------------------
# Tests de AIRequest/AIResponse (domain types)
# ---------------------------------------------------------------------------


def test_ai_request_default_values() -> None:
    """AIRequest genera request_id y smpte_tc por defecto."""
    req = AIRequest(operation="embeddings")
    assert req.request_id is not None
    assert len(req.request_id) > 0
    assert req.smpte_tc == "00:00:00:00"
    assert req.texts is None
    assert req.prompt is None
    assert req.context is None


def test_ai_request_custom_values() -> None:
    req = AIRequest(
        operation="analyze_context",
        texts=["a", "b"],
        prompt="test",
        context="ctx",
        smpte_tc="01:02:03:04",
        request_id="custom-id",
    )
    assert req.request_id == "custom-id"
    assert req.operation == "analyze_context"
    assert req.texts == ["a", "b"]
    assert req.prompt == "test"
    assert req.context == "ctx"
    assert req.smpte_tc == "01:02:03:04"


def test_ai_response_default_values() -> None:
    resp = AIResponse(request_id="r1")
    assert resp.success is True
    assert resp.processed is True
    assert resp.embeddings is None
    assert resp.analysis_result is None
    assert resp.similarity_score is None
    assert resp.error is None


def test_ai_response_failure() -> None:
    resp = AIResponse(
        request_id="r1",
        success=False,
        error="timeout",
        processed=False,
    )
    assert resp.success is False
    assert resp.processed is False
    assert resp.error == "timeout"


# ---------------------------------------------------------------------------
# Tests: sesión no se detiene tras fallo (implicit en todos los timeout tests)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_continues_after_bedrock_timeout(
    hub: WebSocketHub,
) -> None:
    """Múltiples solicitudes pueden procesarse tras un timeout de Bedrock."""
    slow_bedrock = FakeBedrockBackend(delay=0.5)
    router = AIRouter(hub=hub, bedrock_backend=slow_bedrock)
    router.BEDROCK_TIMEOUT = 0.05

    # Primera solicitud timeout
    req1 = AIRequest(operation="embeddings", texts=["a"], smpte_tc="00:00:01:00")
    resp1 = await router.route_request(req1, "op-1")
    assert resp1.success is False
    assert resp1.processed is False

    # Segunda solicitud también se puede procesar (sesión no detenida)
    fast_bedrock = FakeBedrockBackend(delay=0.0)
    router._bedrock = fast_bedrock
    router.BEDROCK_TIMEOUT = 10.0

    req2 = AIRequest(operation="embeddings", texts=["b"], smpte_tc="00:00:02:00")
    resp2 = await router.route_request(req2, "op-1")
    assert resp2.success is True
    assert resp2.processed is True
