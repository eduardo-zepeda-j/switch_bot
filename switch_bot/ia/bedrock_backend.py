"""Backend de IA usando AWS Bedrock (Titan Embeddings V2 + Claude 3.5).

Implementa la interfaz IABackend para comunicarse con los servicios de
AWS Bedrock, utilizando Titan Embeddings V2 para embeddings vectoriales
y Claude 3.5 Sonnet/Haiku para análisis contextual.

Requisitos: 6.6, 19.2, 19.4, 19.5
"""

from __future__ import annotations

import asyncio
import json
import math
from typing import Any

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import (
    ClientError,
    EndpointConnectionError,
    ReadTimeoutError,
)

from switch_bot.ia.backend_base import (
    BackendConnectionError,
    BackendTimeoutError,
    IABackend,
    ModelDiscoveryError,
)
from switch_bot.ia.backend_config import IABackendConfig
from switch_bot.ia.model_catalog import IAModelCatalog, IAModelInfo


# ---------------------------------------------------------------------------
# Constantes de retry
# ---------------------------------------------------------------------------

_MAX_RETRIES = 3
_BASE_DELAY_SECONDS = 1.0  # Delay base para backoff exponencial


def _is_retryable_error(error: ClientError) -> bool:
    """Determina si un error de boto3 es retriable (throttle/timeout)."""
    error_code = error.response.get("Error", {}).get("Code", "")
    retryable_codes = {
        "ThrottlingException",
        "TooManyRequestsException",
        "ServiceUnavailableException",
        "ModelTimeoutException",
        "RequestTimeout",
    }
    return error_code in retryable_codes


# ---------------------------------------------------------------------------
# BedrockBackend
# ---------------------------------------------------------------------------


class BedrockBackend(IABackend):
    """Backend de IA usando AWS Bedrock (Titan Embeddings V2 + Claude 3.5).

    Utiliza boto3 para comunicarse con AWS Bedrock Runtime (inferencia)
    y AWS Bedrock (listado de modelos). Implementa retry con backoff
    exponencial (máx 3 reintentos) para errores de throttle/timeout.
    """

    def __init__(self, config: IABackendConfig) -> None:
        self._config = config
        self._bedrock_client: Any = None  # boto3 client para gestión
        self._bedrock_runtime_client: Any = None  # boto3 client para inferencia
        self._embedding_model: str = config.embedding_model_id
        self._llm_model: str = config.llm_model_id
        self._connected: bool = False

    # ------------------------------------------------------------------
    # Propiedades
    # ------------------------------------------------------------------

    @property
    def backend_type(self) -> str:
        """Identificador del tipo de backend."""
        return "bedrock"

    @property
    def is_connected(self) -> bool:
        """True si el backend está activo y respondiendo."""
        return self._connected

    # ------------------------------------------------------------------
    # Métodos públicos
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Crea clientes boto3 con las credenciales AWS configuradas.

        Raises:
            BackendConnectionError: Si no se pueden crear los clientes boto3.
        """
        try:
            session_kwargs: dict[str, Any] = {}
            if self._config.aws_profile:
                session_kwargs["profile_name"] = self._config.aws_profile
            if self._config.aws_region:
                session_kwargs["region_name"] = self._config.aws_region

            session = boto3.Session(**session_kwargs)

            boto_config = BotoConfig(
                read_timeout=int(self._config.prompt_timeout_seconds),
                connect_timeout=int(self._config.connection_timeout_seconds),
                retries={"max_attempts": 0},  # Manejamos retry manualmente
            )

            # Cliente para gestión (list_foundation_models)
            self._bedrock_client = session.client(
                "bedrock", config=boto_config
            )

            # Cliente para inferencia (invoke_model)
            self._bedrock_runtime_client = session.client(
                "bedrock-runtime", config=boto_config
            )

            self._connected = True

        except Exception as exc:
            self._connected = False
            raise BackendConnectionError(
                f"Error al inicializar cliente Bedrock: {exc}"
            ) from exc

    async def validate_connection(self, timeout_seconds: float = 10.0) -> bool:
        """Valida acceso a Bedrock con un health check dentro del timeout.

        Realiza una llamada ligera a list_foundation_models() para confirmar
        que las credenciales y la conectividad son válidas.

        Args:
            timeout_seconds: Tiempo máximo de espera en segundos.

        Returns:
            True si el backend responde correctamente.

        Raises:
            BackendTimeoutError: Si la validación excede el timeout.
            BackendConnectionError: Si hay un error de conectividad.
        """
        if not self._bedrock_client:
            raise BackendConnectionError(
                "Backend no inicializado. Llame a initialize() primero."
            )

        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    self._bedrock_client.list_foundation_models,
                    byOutputModality="TEXT",
                ),
                timeout=timeout_seconds,
            )
            self._connected = True
            return True

        except asyncio.TimeoutError as exc:
            self._connected = False
            raise BackendTimeoutError(
                "Timeout al validar conexión con Bedrock",
                timeout_seconds=timeout_seconds,
            ) from exc

        except (EndpointConnectionError, ClientError) as exc:
            self._connected = False
            raise BackendConnectionError(
                f"Error al validar conexión con Bedrock: {exc}"
            ) from exc

    async def list_available_models(self) -> IAModelCatalog:
        """Lista modelos disponibles en la cuenta AWS Bedrock configurada.

        Returns:
            IAModelCatalog con modelos de embeddings y LLMs descubiertos.

        Raises:
            ModelDiscoveryError: Si no se pueden listar los modelos.
            BackendConnectionError: Si el backend no está conectado.
        """
        if not self._bedrock_client:
            raise BackendConnectionError(
                "Backend no inicializado. Llame a initialize() primero."
            )

        try:
            response = await self._call_with_retry(
                self._bedrock_client.list_foundation_models
            )

            model_summaries = response.get("modelSummaries", [])

            embedding_models: list[IAModelInfo] = []
            llm_models: list[IAModelInfo] = []

            for model in model_summaries:
                model_id = model.get("modelId", "")
                model_name = model.get("modelName", model_id)
                output_modalities = model.get("outputModalities", [])
                description = model.get("modelArn", "")

                if "EMBEDDING" in output_modalities:
                    embedding_models.append(
                        IAModelInfo(
                            model_id=model_id,
                            name=model_name,
                            model_type="embedding",
                            description=description,
                        )
                    )
                elif "TEXT" in output_modalities:
                    llm_models.append(
                        IAModelInfo(
                            model_id=model_id,
                            name=model_name,
                            model_type="llm",
                            description=description,
                        )
                    )

            from datetime import datetime, timezone

            return IAModelCatalog(
                backend_type="bedrock",
                embedding_models=embedding_models,
                llm_models=llm_models,
                last_updated=datetime.now(timezone.utc).isoformat(),
            )

        except (BackendConnectionError, BackendTimeoutError):
            raise
        except Exception as exc:
            raise ModelDiscoveryError(
                f"Error al listar modelos de Bedrock: {exc}"
            ) from exc

    async def generate_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Genera embeddings usando Titan Embeddings V2.

        Envía cada texto al modelo Titan Embeddings V2 y retorna los
        vectores de embeddings correspondientes.

        Args:
            texts: Lista de textos para generar embeddings.

        Returns:
            Lista de vectores de embeddings (uno por cada texto).

        Raises:
            BackendConnectionError: Si el backend no está conectado.
            BackendTimeoutError: Si la generación excede el timeout.
        """
        if not self._bedrock_runtime_client:
            raise BackendConnectionError(
                "Backend no inicializado. Llame a initialize() primero."
            )

        embeddings: list[list[float]] = []

        for text in texts:
            body = json.dumps({"inputText": text})

            response = await self._call_with_retry(
                self._bedrock_runtime_client.invoke_model,
                modelId=self._embedding_model,
                body=body,
                contentType="application/json",
                accept="application/json",
            )

            response_body = json.loads(response["body"].read())
            embedding = response_body.get("embedding", [])
            embeddings.append(embedding)

        return embeddings

    async def analyze_context(self, prompt: str, context: str) -> str:
        """Ejecuta análisis contextual con Claude 3.5 Sonnet/Haiku.

        Envía un prompt y contexto al modelo Claude 3.5 utilizando la
        API de mensajes de Anthropic en formato Bedrock.

        Args:
            prompt: Instrucción o pregunta para el LLM.
            context: Contexto adicional para informar la respuesta.

        Returns:
            Texto generado por el LLM como resultado del análisis.

        Raises:
            BackendConnectionError: Si el backend no está conectado.
            BackendTimeoutError: Si el análisis excede el timeout.
        """
        if not self._bedrock_runtime_client:
            raise BackendConnectionError(
                "Backend no inicializado. Llame a initialize() primero."
            )

        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 4096,
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"Contexto:\n{context}\n\n"
                        f"Instrucción:\n{prompt}"
                    ),
                }
            ],
        })

        response = await self._call_with_retry(
            self._bedrock_runtime_client.invoke_model,
            modelId=self._llm_model,
            body=body,
            contentType="application/json",
            accept="application/json",
        )

        response_body = json.loads(response["body"].read())

        # Claude 3.5 responde con formato messages API
        content_blocks = response_body.get("content", [])
        result_parts: list[str] = []
        for block in content_blocks:
            if block.get("type") == "text":
                result_parts.append(block["text"])

        return "\n".join(result_parts)

    async def compute_similarity(self, text_a: str, text_b: str) -> float:
        """Calcula similitud semántica usando embeddings Titan + cosine similarity.

        Genera embeddings para ambos textos y calcula el coseno del ángulo
        entre los vectores resultantes.

        Args:
            text_a: Primer texto para comparación.
            text_b: Segundo texto para comparación.

        Returns:
            Valor de similitud en el rango [0.0, 1.0].

        Raises:
            BackendConnectionError: Si el backend no está conectado.
            BackendTimeoutError: Si el cálculo excede el timeout.
        """
        embeddings = await self.generate_embeddings([text_a, text_b])
        vec_a = embeddings[0]
        vec_b = embeddings[1]
        return self._cosine_similarity(vec_a, vec_b)

    # ------------------------------------------------------------------
    # Métodos privados
    # ------------------------------------------------------------------

    async def _call_with_retry(
        self,
        func: Any,
        **kwargs: Any,
    ) -> Any:
        """Ejecuta una llamada boto3 con retry y backoff exponencial.

        Reintenta hasta _MAX_RETRIES veces para errores de throttle/timeout,
        con delay exponencial entre intentos.

        Args:
            func: Función boto3 a ejecutar.
            **kwargs: Argumentos para la función.

        Returns:
            Respuesta de la llamada boto3.

        Raises:
            BackendTimeoutError: Si se agotan los reintentos por timeout.
            BackendConnectionError: Si se agotan los reintentos por conexión.
        """
        last_exception: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                result = await asyncio.to_thread(func, **kwargs)
                return result

            except ReadTimeoutError as exc:
                last_exception = exc
                if attempt < _MAX_RETRIES - 1:
                    delay = _BASE_DELAY_SECONDS * (2**attempt)
                    await asyncio.sleep(delay)
                else:
                    raise BackendTimeoutError(
                        f"Timeout tras {_MAX_RETRIES} reintentos: {exc}"
                    ) from exc

            except ClientError as exc:
                last_exception = exc
                if _is_retryable_error(exc) and attempt < _MAX_RETRIES - 1:
                    delay = _BASE_DELAY_SECONDS * (2**attempt)
                    await asyncio.sleep(delay)
                elif _is_retryable_error(exc):
                    raise BackendTimeoutError(
                        f"Throttle/timeout tras {_MAX_RETRIES} reintentos: {exc}"
                    ) from exc
                else:
                    raise BackendConnectionError(
                        f"Error de cliente Bedrock: {exc}"
                    ) from exc

            except EndpointConnectionError as exc:
                last_exception = exc
                if attempt < _MAX_RETRIES - 1:
                    delay = _BASE_DELAY_SECONDS * (2**attempt)
                    await asyncio.sleep(delay)
                else:
                    raise BackendConnectionError(
                        f"Error de conexión tras {_MAX_RETRIES} reintentos: {exc}"
                    ) from exc

        # No debería llegar aquí, pero por seguridad:
        raise BackendConnectionError(
            f"Error inesperado tras reintentos: {last_exception}"
        )

    @staticmethod
    def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
        """Calcula la similitud coseno entre dos vectores.

        Args:
            vec_a: Primer vector.
            vec_b: Segundo vector.

        Returns:
            Similitud coseno en rango [-1.0, 1.0], clamped a [0.0, 1.0].
        """
        if not vec_a or not vec_b or len(vec_a) != len(vec_b):
            return 0.0

        dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = math.sqrt(sum(a * a for a in vec_a))
        norm_b = math.sqrt(sum(b * b for b in vec_b))

        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0

        similarity = dot_product / (norm_a * norm_b)
        # Clamp al rango [0.0, 1.0] para la interfaz pública
        return max(0.0, min(1.0, similarity))
