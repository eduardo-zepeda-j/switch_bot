"""Backend de IA usando runtime local (Ollama / llama.cpp / GGUF).

Implementa la interfaz IABackend para comunicarse con runtimes de IA
locales, ya sea Ollama (API HTTP nativa) o llama.cpp (servidor OpenAI-
compatible). Soporta embeddings y generación de texto con modelos GGUF.

Requisitos: 6.7, 19.3, 19.4, 19.5, 19.9
"""

from __future__ import annotations

import asyncio
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from switch_bot.ia.backend_base import (
    BackendConnectionError,
    BackendTimeoutError,
    IABackend,
    ModelDiscoveryError,
)
from switch_bot.ia.backend_config import IABackendConfig
from switch_bot.ia.model_catalog import IAModelCatalog, IAModelInfo


class LocalBackend(IABackend):
    """Backend de IA usando runtime local (Ollama / llama.cpp / GGUF).

    Se comunica con un runtime local de IA mediante HTTP. Soporta dos
    modos de operación:
    - Ollama: API nativa en http://localhost:11434
    - llama.cpp: Servidor OpenAI-compatible o escaneo de directorio GGUF

    Attributes:
        _config: Configuración del backend.
        _client: Cliente httpx asíncrono para comunicación HTTP.
        _connected: Estado de conexión con el runtime.
    """

    def __init__(self, config: IABackendConfig) -> None:
        self._config = config
        self._client: httpx.AsyncClient | None = None
        self._embedding_model: str = config.embedding_model_id
        self._llm_model: str = config.llm_model_id
        self._connected: bool = False

    # ------------------------------------------------------------------
    # Propiedades
    # ------------------------------------------------------------------

    @property
    def backend_type(self) -> str:
        """Identificador del tipo de backend."""
        return "local"

    @property
    def is_connected(self) -> bool:
        """True si el backend está activo y respondiendo."""
        return self._connected

    # ------------------------------------------------------------------
    # Métodos públicos
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Verifica que el runtime local (Ollama/llama.cpp) esté activo.

        Crea un cliente httpx asíncrono y verifica que el runtime responda
        al health check correspondiente.

        Raises:
            BackendConnectionError: Si el runtime no está iniciado o no
                es alcanzable.
        """
        try:
            self._client = httpx.AsyncClient(
                base_url=self._config.local_base_url,
                timeout=httpx.Timeout(
                    connect=self._config.connection_timeout_seconds,
                    read=self._config.prompt_timeout_seconds,
                    write=self._config.prompt_timeout_seconds,
                    pool=self._config.connection_timeout_seconds,
                ),
            )

            # Health check según runtime
            if self._config.local_runtime == "ollama":
                response = await self._client.get("/api/tags")
            else:  # llamacpp
                response = await self._client.get("/health")

            if response.status_code >= 500:
                raise BackendConnectionError(
                    f"Runtime local respondió con error: HTTP {response.status_code}"
                )

            self._connected = True

        except httpx.ConnectError as exc:
            self._connected = False
            raise BackendConnectionError(
                f"Runtime local no iniciado o no alcanzable en "
                f"{self._config.local_base_url}: {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            self._connected = False
            raise BackendConnectionError(
                f"Timeout al conectar con runtime local en "
                f"{self._config.local_base_url}: {exc}"
            ) from exc
        except BackendConnectionError:
            raise
        except Exception as exc:
            self._connected = False
            raise BackendConnectionError(
                f"Error al inicializar backend local: {exc}"
            ) from exc

    async def validate_connection(self, timeout_seconds: float = 10.0) -> bool:
        """Valida accesibilidad del runtime local dentro del timeout.

        Ejecuta un health check ligero al runtime configurado.

        Args:
            timeout_seconds: Tiempo máximo de espera en segundos.

        Returns:
            True si el runtime responde correctamente.

        Raises:
            BackendTimeoutError: Si la validación excede el timeout.
            BackendConnectionError: Si hay un error de conectividad.
        """
        if not self._client:
            raise BackendConnectionError(
                "Backend no inicializado. Llame a initialize() primero."
            )

        try:
            async def _health_check() -> bool:
                if self._config.local_runtime == "ollama":
                    resp = await self._client.get("/api/tags")  # type: ignore[union-attr]
                else:
                    resp = await self._client.get("/health")  # type: ignore[union-attr]
                return resp.status_code < 500

            result = await asyncio.wait_for(
                _health_check(),
                timeout=timeout_seconds,
            )
            self._connected = result
            return result

        except asyncio.TimeoutError as exc:
            self._connected = False
            raise BackendTimeoutError(
                "Timeout al validar conexión con runtime local",
                timeout_seconds=timeout_seconds,
            ) from exc

        except httpx.ConnectError as exc:
            self._connected = False
            raise BackendConnectionError(
                f"Runtime local no alcanzable: {exc}"
            ) from exc

    async def list_available_models(self) -> IAModelCatalog:
        """Lista modelos disponibles en el runtime local.

        Para Ollama: GET /api/tags retorna JSON con array de modelos.
        Para llama.cpp: Escanea el directorio GGUF configurado.

        Returns:
            IAModelCatalog con modelos descubiertos.

        Raises:
            ModelDiscoveryError: Si no se pueden listar los modelos.
            BackendConnectionError: Si el backend no está conectado.
        """
        if not self._client:
            raise BackendConnectionError(
                "Backend no inicializado. Llame a initialize() primero."
            )

        try:
            if self._config.local_runtime == "ollama":
                return await self._list_ollama_models()
            else:
                return self._list_llamacpp_models()

        except (BackendConnectionError, BackendTimeoutError):
            raise
        except Exception as exc:
            raise ModelDiscoveryError(
                f"Error al listar modelos locales: {exc}"
            ) from exc

    async def generate_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Genera embeddings vía modelo local (nomic-embed-text, etc.).

        Para Ollama: POST /api/embed con modelo y lista de textos.
        Para llama.cpp: POST /embedding con contenido individual.

        Args:
            texts: Lista de textos para generar embeddings.

        Returns:
            Lista de vectores de embeddings (uno por cada texto).

        Raises:
            BackendConnectionError: Si el backend no está conectado o
                el modelo no está disponible.
            BackendTimeoutError: Si la generación excede el timeout.
        """
        if not self._client:
            raise BackendConnectionError(
                "Backend no inicializado. Llame a initialize() primero."
            )

        try:
            if self._config.local_runtime == "ollama":
                return await self._ollama_embeddings(texts)
            else:
                return await self._llamacpp_embeddings(texts)

        except (BackendConnectionError, BackendTimeoutError):
            raise
        except httpx.TimeoutException as exc:
            raise BackendTimeoutError(
                f"Timeout al generar embeddings: {exc}"
            ) from exc
        except httpx.ConnectError as exc:
            raise BackendConnectionError(
                f"Runtime local no alcanzable al generar embeddings: {exc}"
            ) from exc

    async def analyze_context(self, prompt: str, context: str) -> str:
        """Análisis contextual vía LLM local (llama3, mistral, etc.).

        Para Ollama: POST /api/generate con prompt compuesto.
        Para llama.cpp: POST /completion con prompt compuesto.

        Args:
            prompt: Instrucción o pregunta para el LLM.
            context: Contexto adicional para informar la respuesta.

        Returns:
            Texto generado por el LLM como resultado del análisis.

        Raises:
            BackendConnectionError: Si el backend no está conectado.
            BackendTimeoutError: Si el análisis excede el timeout.
        """
        if not self._client:
            raise BackendConnectionError(
                "Backend no inicializado. Llame a initialize() primero."
            )

        full_prompt = f"Contexto:\n{context}\n\nInstrucción:\n{prompt}"

        try:
            if self._config.local_runtime == "ollama":
                return await self._ollama_generate(full_prompt)
            else:
                return await self._llamacpp_generate(full_prompt)

        except (BackendConnectionError, BackendTimeoutError):
            raise
        except httpx.TimeoutException as exc:
            raise BackendTimeoutError(
                f"Timeout al analizar contexto: {exc}"
            ) from exc
        except httpx.ConnectError as exc:
            raise BackendConnectionError(
                f"Runtime local no alcanzable al analizar contexto: {exc}"
            ) from exc

    async def compute_similarity(self, text_a: str, text_b: str) -> float:
        """Calcula similitud semántica usando embeddings locales + cosine similarity.

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
    # Métodos privados — Ollama
    # ------------------------------------------------------------------

    async def _ollama_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Genera embeddings usando la API de Ollama (POST /api/embed).

        Args:
            texts: Lista de textos.

        Returns:
            Lista de vectores de embeddings.
        """
        response = await self._client.post(  # type: ignore[union-attr]
            "/api/embed",
            json={"model": self._embedding_model, "input": texts},
        )

        self._check_response_errors(response, "embeddings")

        data = response.json()
        embeddings = data.get("embeddings", [])
        return embeddings

    async def _ollama_generate(self, prompt: str) -> str:
        """Genera texto usando la API de Ollama (POST /api/generate).

        Args:
            prompt: Prompt completo para el LLM.

        Returns:
            Texto generado.
        """
        response = await self._client.post(  # type: ignore[union-attr]
            "/api/generate",
            json={
                "model": self._llm_model,
                "prompt": prompt,
                "stream": False,
            },
        )

        self._check_response_errors(response, "generación de texto")

        data = response.json()
        return data.get("response", "")

    async def _list_ollama_models(self) -> IAModelCatalog:
        """Lista modelos disponibles en Ollama (GET /api/tags).

        Returns:
            IAModelCatalog con modelos clasificados.
        """
        response = await self._client.get("/api/tags")  # type: ignore[union-attr]

        if response.status_code != 200:
            raise ModelDiscoveryError(
                f"Error al listar modelos Ollama: HTTP {response.status_code}"
            )

        data = response.json()
        models_list = data.get("models", [])

        embedding_models: list[IAModelInfo] = []
        llm_models: list[IAModelInfo] = []

        for model in models_list:
            model_name = model.get("name", "")
            model_id = model.get("model", model_name)
            size_bytes = model.get("size", None)
            details = model.get("details", {})
            description = details.get("family", "")

            # Heurística: modelos con "embed" en el nombre son de embeddings
            if "embed" in model_name.lower():
                embedding_models.append(
                    IAModelInfo(
                        model_id=model_id,
                        name=model_name,
                        model_type="embedding",
                        size_bytes=size_bytes,
                        description=description,
                    )
                )
            else:
                llm_models.append(
                    IAModelInfo(
                        model_id=model_id,
                        name=model_name,
                        model_type="llm",
                        size_bytes=size_bytes,
                        description=description,
                    )
                )

        return IAModelCatalog(
            backend_type="local",
            embedding_models=embedding_models,
            llm_models=llm_models,
            last_updated=datetime.now(timezone.utc).isoformat(),
        )

    # ------------------------------------------------------------------
    # Métodos privados — llama.cpp
    # ------------------------------------------------------------------

    async def _llamacpp_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Genera embeddings usando llama.cpp (POST /embedding).

        llama.cpp procesa textos uno a uno.

        Args:
            texts: Lista de textos.

        Returns:
            Lista de vectores de embeddings.
        """
        embeddings: list[list[float]] = []

        for text in texts:
            response = await self._client.post(  # type: ignore[union-attr]
                "/embedding",
                json={"content": text},
            )

            self._check_response_errors(response, "embeddings")

            data = response.json()
            embedding = data.get("embedding", [])
            embeddings.append(embedding)

        return embeddings

    async def _llamacpp_generate(self, prompt: str) -> str:
        """Genera texto usando llama.cpp (POST /completion).

        Args:
            prompt: Prompt completo para el LLM.

        Returns:
            Texto generado.
        """
        response = await self._client.post(  # type: ignore[union-attr]
            "/completion",
            json={"prompt": prompt, "stream": False},
        )

        self._check_response_errors(response, "generación de texto")

        data = response.json()
        return data.get("content", "")

    def _list_llamacpp_models(self) -> IAModelCatalog:
        """Lista modelos GGUF escaneando el directorio configurado.

        Busca archivos .gguf en el directorio gguf_model_dir de la config.

        Returns:
            IAModelCatalog con modelos encontrados.

        Raises:
            ModelDiscoveryError: Si el directorio no existe o no se puede leer.
        """
        model_dir = self._config.gguf_model_dir

        if not model_dir:
            raise ModelDiscoveryError(
                "No se configuró gguf_model_dir para llama.cpp"
            )

        model_path = Path(model_dir)

        if not model_path.exists():
            raise ModelDiscoveryError(
                f"Directorio de modelos GGUF no existe: {model_dir}"
            )

        if not model_path.is_dir():
            raise ModelDiscoveryError(
                f"La ruta de modelos GGUF no es un directorio: {model_dir}"
            )

        embedding_models: list[IAModelInfo] = []
        llm_models: list[IAModelInfo] = []

        try:
            for gguf_file in model_path.glob("*.gguf"):
                model_name = gguf_file.stem
                model_id = gguf_file.name
                size_bytes = gguf_file.stat().st_size

                # Heurística: modelos con "embed" en el nombre son de embeddings
                if "embed" in model_name.lower():
                    embedding_models.append(
                        IAModelInfo(
                            model_id=model_id,
                            name=model_name,
                            model_type="embedding",
                            size_bytes=size_bytes,
                        )
                    )
                else:
                    llm_models.append(
                        IAModelInfo(
                            model_id=model_id,
                            name=model_name,
                            model_type="llm",
                            size_bytes=size_bytes,
                        )
                    )
        except OSError as exc:
            raise ModelDiscoveryError(
                f"Error al escanear directorio GGUF: {exc}"
            ) from exc

        return IAModelCatalog(
            backend_type="local",
            embedding_models=embedding_models,
            llm_models=llm_models,
            last_updated=datetime.now(timezone.utc).isoformat(),
        )

    # ------------------------------------------------------------------
    # Utilidades internas
    # ------------------------------------------------------------------

    def _check_response_errors(self, response: httpx.Response, operation: str) -> None:
        """Verifica errores en respuestas HTTP del runtime local.

        Detecta errores comunes (modelo no encontrado, out of memory, etc.)
        y lanza la excepción apropiada.

        Args:
            response: Respuesta HTTP del runtime.
            operation: Nombre de la operación para mensajes de error.

        Raises:
            BackendConnectionError: Si hay OOM o error de servidor.
            ModelDiscoveryError: Si el modelo no se encontró.
        """
        if response.status_code == 200:
            return

        error_text = response.text.lower()

        # Modelo no encontrado
        if response.status_code == 404 or "not found" in error_text:
            raise ModelDiscoveryError(
                f"Modelo no encontrado durante {operation}: "
                f"HTTP {response.status_code} - {response.text}"
            )

        # Out of memory
        if "out of memory" in error_text or "oom" in error_text:
            raise BackendConnectionError(
                f"Out of memory durante {operation}: {response.text}"
            )

        # Otros errores de servidor
        if response.status_code >= 400:
            raise BackendConnectionError(
                f"Error del runtime local durante {operation}: "
                f"HTTP {response.status_code} - {response.text}"
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
