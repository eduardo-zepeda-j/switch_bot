"""AIRouter — Enrutamiento de solicitudes de IA a Bedrock o Agente_Local.

Determina si una solicitud de IA se procesa en la nube (AWS Bedrock desde EC2)
o localmente (reenviándola al Agente_Local vía Canal_Comunicación/WebSocketHub).

Aplica timeouts diferenciados:
- Bedrock: 10 segundos
- Local (agente): 30 segundos

Garantiza estructura de salida idéntica independientemente del backend utilizado.

Requirements cubiertos:
- 5.1: Bedrock se procesa sin reenviar al agente
- 5.2: Local se reenvía al agente vía Canal_Comunicación
- 5.3: Agente procesa con runtime local y retorna resultado
- 5.4: Timeouts 30s local, 10s Bedrock
- 5.5: Timeout local registra fallo con SMPTE_TC
- 5.6: Timeout Bedrock registra fallo con SMPTE_TC
- 5.7: Agente inalcanzable registra error y marca segmento
- 5.8: Estructura de salida idéntica para ambos backends
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

from switch_bot.web.hub import WebSocketHub
from switch_bot.web.protocol import (
    AIRequestPayload,
    AIResponsePayload,
    ChannelMessage,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tipos de dominio
# ---------------------------------------------------------------------------


class AIRequest:
    """Solicitud de IA con metadata del segmento afectado.

    Attributes:
        request_id: Identificador único de la solicitud.
        operation: Tipo de operación ("embeddings", "analyze_context", "similarity").
        texts: Textos para operaciones de embeddings/similarity.
        prompt: Prompt para análisis contextual.
        context: Contexto adicional para análisis.
        smpte_tc: Timecode SMPTE del segmento afectado (para logging de fallos).
    """

    def __init__(
        self,
        operation: str,
        *,
        texts: list[str] | None = None,
        prompt: str | None = None,
        context: str | None = None,
        smpte_tc: str = "00:00:00:00",
        request_id: str | None = None,
    ):
        self.request_id = request_id or str(uuid.uuid4())
        self.operation = operation
        self.texts = texts
        self.prompt = prompt
        self.context = context
        self.smpte_tc = smpte_tc


class AIResponse:
    """Respuesta de IA con estructura idéntica independientemente del backend.

    Attributes:
        request_id: Identificador de la solicitud original.
        success: Si la operación se completó exitosamente.
        embeddings: Vectores de embeddings (lista de listas de floats).
        analysis_result: Resultado de análisis contextual (formato marcadores EDL).
        similarity_score: Score de similaridad (float).
        error: Mensaje de error si success=False.
        processed: Si el segmento fue procesado (False = marcado como no procesado).
    """

    def __init__(
        self,
        request_id: str,
        *,
        success: bool = True,
        embeddings: list[list[float]] | None = None,
        analysis_result: str | None = None,
        similarity_score: float | None = None,
        error: str | None = None,
        processed: bool = True,
    ):
        self.request_id = request_id
        self.success = success
        self.embeddings = embeddings
        self.analysis_result = analysis_result
        self.similarity_score = similarity_score
        self.error = error
        self.processed = processed


@runtime_checkable
class BedrockBackend(Protocol):
    """Protocolo que define la interfaz de un backend de AWS Bedrock.

    Permite inyección de dependencias y mocking en tests.
    """

    async def invoke_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Genera embeddings para los textos proporcionados."""
        ...

    async def invoke_analysis(
        self, prompt: str, context: str | None = None
    ) -> str:
        """Ejecuta análisis contextual con Claude/Titan."""
        ...

    async def invoke_similarity(
        self, texts: list[str]
    ) -> float:
        """Calcula score de similaridad entre textos."""
        ...


# ---------------------------------------------------------------------------
# AIRouter
# ---------------------------------------------------------------------------


class AIRouter:
    """Enruta solicitudes de IA a Bedrock (cloud) o Agente_Local (local).

    Aplica timeouts diferenciados según el backend activo y garantiza
    estructura de salida uniforme. Los fallos de timeout se registran
    con el SMPTE_TC del segmento afectado y marcan el segmento como
    no procesado sin detener la sesión.

    Args:
        hub: WebSocketHub para comunicación con agentes.
        bedrock_backend: Implementación del protocolo BedrockBackend.
    """

    BEDROCK_TIMEOUT: float = 10.0
    LOCAL_TIMEOUT: float = 30.0

    def __init__(self, hub: WebSocketHub, bedrock_backend: BedrockBackend):
        self._hub = hub
        self._bedrock = bedrock_backend
        self._active_backend: str = "bedrock"
        # Pending futures: request_id -> asyncio.Future[AIResponsePayload]
        self._pending_responses: dict[str, asyncio.Future[AIResponsePayload]] = {}

    @property
    def active_backend(self) -> str:
        """Backend activo actual ('bedrock' o 'local')."""
        return self._active_backend

    def set_backend(self, backend_type: str) -> None:
        """Configura el backend activo.

        Args:
            backend_type: "bedrock" o "local".

        Raises:
            ValueError: Si el tipo de backend no es válido.
        """
        if backend_type not in ("bedrock", "local"):
            raise ValueError(
                f"Backend inválido: '{backend_type}'. Debe ser 'bedrock' o 'local'."
            )
        self._active_backend = backend_type
        logger.info("Backend de IA configurado a: %s", backend_type)

    async def route_request(
        self, request: AIRequest, operator_id: str
    ) -> AIResponse:
        """Enruta solicitud según backend activo. Aplica timeout correspondiente.

        Args:
            request: Solicitud de IA con metadata del segmento.
            operator_id: ID del operador para enrutamiento al agente.

        Returns:
            AIResponse con estructura idéntica independientemente del backend.
        """
        if self._active_backend == "bedrock":
            return await self._process_bedrock(request)
        else:
            return await self._forward_to_agent(request, operator_id)

    async def _process_bedrock(self, request: AIRequest) -> AIResponse:
        """Procesa con AWS Bedrock directamente (timeout 10s).

        Invoca el backend de Bedrock sin reenviar al agente.
        En caso de timeout, registra el fallo con SMPTE_TC y marca
        el segmento como no procesado.

        Args:
            request: Solicitud de IA.

        Returns:
            AIResponse con resultado o marcado como no procesado.
        """
        try:
            result = await asyncio.wait_for(
                self._invoke_bedrock(request),
                timeout=self.BEDROCK_TIMEOUT,
            )
            return result

        except asyncio.TimeoutError:
            logger.error(
                "Timeout de Bedrock (%ss) para solicitud %s. "
                "SMPTE_TC del segmento afectado: %s. "
                "Segmento marcado como no procesado.",
                self.BEDROCK_TIMEOUT,
                request.request_id,
                request.smpte_tc,
            )
            return AIResponse(
                request_id=request.request_id,
                success=False,
                error=f"Timeout de Bedrock ({self.BEDROCK_TIMEOUT}s) "
                f"en segmento {request.smpte_tc}",
                processed=False,
            )

        except Exception as exc:
            logger.error(
                "Error procesando solicitud %s con Bedrock. "
                "SMPTE_TC: %s. Error: %s",
                request.request_id,
                request.smpte_tc,
                exc,
            )
            return AIResponse(
                request_id=request.request_id,
                success=False,
                error=f"Error de Bedrock: {exc}",
                processed=False,
            )

    async def _forward_to_agent(
        self, request: AIRequest, operator_id: str
    ) -> AIResponse:
        """Reenvía solicitud al agente vía WebSocket (timeout 30s).

        Envía la solicitud como ChannelMessage al agente y espera
        la respuesta mediante un Future pendiente. En caso de timeout
        o agente inalcanzable, registra el fallo con SMPTE_TC.

        Args:
            request: Solicitud de IA.
            operator_id: ID del operador destino.

        Returns:
            AIResponse con resultado o marcado como no procesado.
        """
        # Crear Future para esperar respuesta del agente
        loop = asyncio.get_running_loop()
        future: asyncio.Future[AIResponsePayload] = loop.create_future()
        self._pending_responses[request.request_id] = future

        try:
            # Construir ChannelMessage con payload de solicitud
            message = ChannelMessage(
                type="ai_request",
                timestamp=datetime.now(timezone.utc).isoformat(
                    timespec="milliseconds"
                ),
                seq=0,
                version="1.0",
                payload={
                    "request_id": request.request_id,
                    "operation": request.operation,
                    "texts": request.texts,
                    "prompt": request.prompt,
                    "context": request.context,
                },
            )

            # Enviar al agente
            sent = await self._hub.send_to_agent(operator_id, message)
            if not sent:
                logger.error(
                    "Agente inalcanzable (operator_id=%s) para solicitud %s. "
                    "SMPTE_TC del segmento afectado: %s. "
                    "Segmento marcado como no procesado.",
                    operator_id,
                    request.request_id,
                    request.smpte_tc,
                )
                return AIResponse(
                    request_id=request.request_id,
                    success=False,
                    error=f"Agente inalcanzable (operator_id={operator_id})",
                    processed=False,
                )

            # Esperar respuesta con timeout
            response_payload = await asyncio.wait_for(
                future, timeout=self.LOCAL_TIMEOUT
            )

            # Construir AIResponse uniforme desde el payload del agente
            return AIResponse(
                request_id=response_payload.request_id,
                success=response_payload.success,
                embeddings=response_payload.embeddings,
                analysis_result=response_payload.analysis_result,
                similarity_score=response_payload.similarity_score,
                error=response_payload.error,
                processed=response_payload.success,
            )

        except asyncio.TimeoutError:
            logger.error(
                "Timeout local (%ss) para solicitud %s (operator_id=%s). "
                "SMPTE_TC del segmento afectado: %s. "
                "Segmento marcado como no procesado.",
                self.LOCAL_TIMEOUT,
                request.request_id,
                operator_id,
                request.smpte_tc,
            )
            return AIResponse(
                request_id=request.request_id,
                success=False,
                error=f"Timeout local ({self.LOCAL_TIMEOUT}s) "
                f"en segmento {request.smpte_tc}",
                processed=False,
            )

        except Exception as exc:
            logger.error(
                "Error reenviando solicitud %s al agente (operator_id=%s). "
                "SMPTE_TC: %s. Error: %s",
                request.request_id,
                operator_id,
                request.smpte_tc,
                exc,
            )
            return AIResponse(
                request_id=request.request_id,
                success=False,
                error=f"Error de comunicación con agente: {exc}",
                processed=False,
            )

        finally:
            # Limpiar el Future pendiente
            self._pending_responses.pop(request.request_id, None)

    def handle_ai_response(self, payload: AIResponsePayload) -> None:
        """Maneja una respuesta de IA recibida de un agente.

        Resuelve el Future pendiente correspondiente al request_id
        del payload recibido. Se invoca cuando llega un mensaje tipo
        'ai_response' desde el agente.

        Args:
            payload: AIResponsePayload recibido del agente.
        """
        future = self._pending_responses.get(payload.request_id)
        if future is not None and not future.done():
            future.set_result(payload)
            logger.debug(
                "Respuesta de IA recibida para request_id=%s",
                payload.request_id,
            )
        else:
            logger.warning(
                "Respuesta de IA recibida para request_id=%s "
                "sin Future pendiente (posible timeout previo).",
                payload.request_id,
            )

    # ------------------------------------------------------------------
    # Métodos internos
    # ------------------------------------------------------------------

    async def _invoke_bedrock(self, request: AIRequest) -> AIResponse:
        """Invoca el backend de Bedrock según el tipo de operación.

        Args:
            request: Solicitud de IA.

        Returns:
            AIResponse con los resultados de Bedrock.
        """
        if request.operation == "embeddings":
            if not request.texts:
                return AIResponse(
                    request_id=request.request_id,
                    success=False,
                    error="Campo 'texts' requerido para operación 'embeddings'",
                    processed=False,
                )
            embeddings = await self._bedrock.invoke_embeddings(request.texts)
            return AIResponse(
                request_id=request.request_id,
                success=True,
                embeddings=embeddings,
            )

        elif request.operation == "analyze_context":
            if not request.prompt:
                return AIResponse(
                    request_id=request.request_id,
                    success=False,
                    error="Campo 'prompt' requerido para operación 'analyze_context'",
                    processed=False,
                )
            result = await self._bedrock.invoke_analysis(
                request.prompt, request.context
            )
            return AIResponse(
                request_id=request.request_id,
                success=True,
                analysis_result=result,
            )

        elif request.operation == "similarity":
            if not request.texts or len(request.texts) < 2:
                return AIResponse(
                    request_id=request.request_id,
                    success=False,
                    error="Campo 'texts' con al menos 2 elementos requerido "
                    "para operación 'similarity'",
                    processed=False,
                )
            score = await self._bedrock.invoke_similarity(request.texts)
            return AIResponse(
                request_id=request.request_id,
                success=True,
                similarity_score=score,
            )

        else:
            return AIResponse(
                request_id=request.request_id,
                success=False,
                error=f"Operación no soportada: '{request.operation}'",
                processed=False,
            )
