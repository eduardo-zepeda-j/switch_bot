"""Interfaz abstracta para backends de IA (Patrón Strategy).

Define la clase base abstracta IABackend y las excepciones asociadas
para la comunicación con backends de IA (AWS Bedrock o modelos locales).

Requisitos: 19.4, 19.5, 19.8, 19.9
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from switch_bot.ia.model_catalog import IAModelCatalog


# ---------------------------------------------------------------------------
# Excepciones del Backend de IA
# ---------------------------------------------------------------------------


class BackendConnectionError(Exception):
    """Error al establecer o mantener conexión con el backend de IA.

    Se lanza cuando el backend no es alcanzable, las credenciales son
    inválidas, o la conexión se pierde durante una operación.
    """

    def __init__(self, message: str = "No se pudo conectar al backend de IA") -> None:
        super().__init__(message)


class BackendTimeoutError(Exception):
    """Error de timeout al comunicarse con el backend de IA.

    Se lanza cuando una operación (validación de conexión, generación de
    embeddings, análisis contextual) excede el tiempo máximo permitido.
    """

    def __init__(
        self,
        message: str = "Timeout al comunicarse con el backend de IA",
        timeout_seconds: float | None = None,
    ) -> None:
        if timeout_seconds is not None:
            message = f"{message} (timeout: {timeout_seconds}s)"
        super().__init__(message)
        self.timeout_seconds = timeout_seconds


class ModelDiscoveryError(Exception):
    """Error al descubrir o listar modelos disponibles en el backend.

    Se lanza cuando el backend no puede enumerar los modelos disponibles,
    ya sea por problemas de permisos, conectividad o configuración.
    """

    def __init__(
        self, message: str = "Error al descubrir modelos en el backend de IA"
    ) -> None:
        super().__init__(message)


# ---------------------------------------------------------------------------
# Interfaz Abstracta IABackend
# ---------------------------------------------------------------------------


class IABackend(ABC):
    """Interfaz abstracta para backends de IA. Implementa patrón Strategy.

    Define el contrato que deben cumplir todas las implementaciones de
    backend de IA (BedrockBackend, LocalBackend). Permite intercambiar
    backends de forma transparente para el orquestador IAEnricher.

    Métodos abstractos:
        initialize: Inicializa la conexión con el backend.
        validate_connection: Valida que el backend esté accesible.
        list_available_models: Descubre los modelos disponibles.
        generate_embeddings: Genera embeddings vectoriales.
        analyze_context: Ejecuta análisis contextual con el LLM.
        compute_similarity: Calcula similitud semántica entre textos.

    Propiedades abstractas:
        backend_type: Identificador del tipo de backend.
        is_connected: Estado de conexión del backend.
    """

    @abstractmethod
    async def initialize(self) -> None:
        """Inicializa la conexión con el backend.

        Realiza la configuración necesaria para que el backend esté listo
        para recibir solicitudes (crear clientes, verificar credenciales, etc.).

        Raises:
            BackendConnectionError: Si la conexión no puede establecerse.
        """
        ...

    @abstractmethod
    async def validate_connection(self, timeout_seconds: float = 10.0) -> bool:
        """Valida que el backend esté accesible dentro del timeout especificado.

        Ejecuta un health-check ligero para confirmar que el backend
        puede responder a solicitudes.

        Args:
            timeout_seconds: Tiempo máximo de espera en segundos para la
                validación. Por defecto 10.0 segundos.

        Returns:
            True si el backend responde correctamente dentro del timeout.

        Raises:
            BackendTimeoutError: Si la validación excede el timeout.
            BackendConnectionError: Si hay un error de conectividad.
        """
        ...

    @abstractmethod
    async def list_available_models(self) -> IAModelCatalog:
        """Descubre y retorna los modelos disponibles en el backend.

        Consulta al backend para obtener la lista completa de modelos
        de embeddings y LLMs disponibles para su uso.

        Returns:
            IAModelCatalog con los modelos descubiertos.

        Raises:
            ModelDiscoveryError: Si no se pueden listar los modelos.
            BackendConnectionError: Si el backend no está conectado.
        """
        ...

    @abstractmethod
    async def generate_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Genera embeddings vectoriales para una lista de textos.

        Envía los textos al modelo de embeddings configurado y retorna
        las representaciones vectoriales correspondientes.

        Args:
            texts: Lista de textos para generar embeddings.

        Returns:
            Lista de vectores de embeddings (uno por cada texto de entrada).

        Raises:
            BackendConnectionError: Si el backend no está conectado.
            BackendTimeoutError: Si la generación excede el timeout.
        """
        ...

    @abstractmethod
    async def analyze_context(self, prompt: str, context: str) -> str:
        """Ejecuta análisis contextual con el LLM del backend.

        Envía un prompt junto con contexto al modelo de lenguaje para
        obtener un análisis o respuesta generada.

        Args:
            prompt: Instrucción o pregunta para el LLM.
            context: Contexto adicional para informar la respuesta.

        Returns:
            Texto generado por el LLM como resultado del análisis.

        Raises:
            BackendConnectionError: Si el backend no está conectado.
            BackendTimeoutError: Si el análisis excede el timeout.
        """
        ...

    @abstractmethod
    async def compute_similarity(self, text_a: str, text_b: str) -> float:
        """Calcula score de similitud semántica entre dos textos.

        Genera embeddings para ambos textos y calcula la similitud
        coseno entre los vectores resultantes.

        Args:
            text_a: Primer texto para comparación.
            text_b: Segundo texto para comparación.

        Returns:
            Valor de similitud en el rango [0.0, 1.0], donde 1.0 indica
            textos semánticamente idénticos.

        Raises:
            BackendConnectionError: Si el backend no está conectado.
            BackendTimeoutError: Si el cálculo excede el timeout.
        """
        ...

    @property
    @abstractmethod
    def backend_type(self) -> str:
        """Identificador del tipo de backend ('bedrock' o 'local')."""
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """True si el backend está activo y respondiendo."""
        ...
