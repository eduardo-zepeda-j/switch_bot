"""Catálogo de modelos de IA disponibles en un backend.

Define las estructuras de datos para representar la información de modelos
individuales (IAModelInfo) y el catálogo completo de modelos disponibles
en un backend específico (IAModelCatalog).

Requisitos: 19.2, 19.3
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class IAModelInfo:
    """Información de un modelo disponible en un backend.

    Representa los metadatos de un modelo de IA individual, ya sea
    de embeddings o de lenguaje (LLM).

    Attributes:
        model_id: Identificador único del modelo.
        name: Nombre legible del modelo.
        model_type: Tipo de modelo ("embedding" o "llm").
        size_bytes: Tamaño del modelo en bytes (si disponible).
        context_window: Ventana de contexto en tokens (si disponible).
        description: Descripción breve del modelo.
    """

    model_id: str
    name: str
    model_type: str  # "embedding" o "llm"
    size_bytes: int | None = None
    context_window: int | None = None
    description: str = ""


@dataclass
class IAModelCatalog:
    """Catálogo de modelos disponibles en un backend.

    Agrupa los modelos de embeddings y LLM disponibles en un backend
    específico, junto con la marca temporal de la última consulta.

    Attributes:
        backend_type: Tipo de backend ("bedrock" o "local").
        embedding_models: Lista de modelos de embeddings disponibles.
        llm_models: Lista de modelos de lenguaje disponibles.
        last_updated: Marca temporal ISO de la última consulta al backend.
    """

    backend_type: str
    embedding_models: list[IAModelInfo] = field(default_factory=list)
    llm_models: list[IAModelInfo] = field(default_factory=list)
    last_updated: str = ""  # ISO timestamp de última consulta

    def get_embedding_model_ids(self) -> list[str]:
        """Devuelve los IDs de todos los modelos de embeddings disponibles."""
        return [m.model_id for m in self.embedding_models]

    def get_llm_model_ids(self) -> list[str]:
        """Devuelve los IDs de todos los modelos de lenguaje disponibles."""
        return [m.model_id for m in self.llm_models]
