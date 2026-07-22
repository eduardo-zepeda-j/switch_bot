"""Módulo de backend de IA multi-proveedor (Patrón Strategy).

Contiene la interfaz abstracta IABackend y las implementaciones:
- BedrockBackend (AWS Bedrock — Titan Embeddings V2 + Claude 3.5)
- LocalBackend (Ollama / llama.cpp / GGUF)
- IAEnricher (orquestador agnóstico al backend)
"""

from switch_bot.ia.backend_base import (
    BackendConnectionError,
    BackendTimeoutError,
    IABackend,
    ModelDiscoveryError,
)
from switch_bot.ia.backend_config import IABackendConfig
from switch_bot.ia.enrichment_result import EnrichmentResult
from switch_bot.ia.ia_enricher import AdSuggestion, IAEnricher, MarkerEvent, VectorStore
from switch_bot.ia.local_backend import LocalBackend
from switch_bot.ia.model_catalog import IAModelCatalog, IAModelInfo

__all__ = [
    "AdSuggestion",
    "BackendConnectionError",
    "BackendTimeoutError",
    "EnrichmentResult",
    "IABackend",
    "IABackendConfig",
    "IAEnricher",
    "IAModelCatalog",
    "IAModelInfo",
    "LocalBackend",
    "MarkerEvent",
    "ModelDiscoveryError",
    "VectorStore",
]
