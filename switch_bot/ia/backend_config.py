"""Configuración persistente del backend de IA seleccionado."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


# Ruta por defecto para persistencia de configuración
CONFIG_DIR = Path.home() / ".switch_bot"
CONFIG_FILE = CONFIG_DIR / "config.json"


@dataclass
class IABackendConfig:
    """Configuración persistente del backend de IA seleccionado.

    Almacena la selección del backend activo (Bedrock o Local) y los
    modelos elegidos para reutilización entre sesiones.

    Attributes:
        backend_type: Tipo de backend activo ("bedrock" o "local").
        embedding_model_id: ID del modelo de embeddings seleccionado.
        llm_model_id: ID del modelo de lenguaje seleccionado.
        aws_region: Región AWS para Bedrock.
        aws_profile: Perfil AWS (opcional).
        local_runtime: Runtime local ("ollama" o "llamacpp").
        local_base_url: URL del runtime local.
        gguf_model_dir: Directorio de modelos GGUF (para llama.cpp).
        connection_timeout_seconds: Timeout de validación de conexión.
        prompt_timeout_seconds: Timeout para prompts manuales.
    """

    backend_type: str  # "bedrock" o "local"
    embedding_model_id: str  # ID del modelo de embeddings seleccionado
    llm_model_id: str  # ID del modelo de lenguaje seleccionado

    # Campos específicos de Bedrock
    aws_region: str = "us-east-1"
    aws_profile: str | None = None

    # Campos específicos de Backend Local
    local_runtime: str = "ollama"  # "ollama" o "llamacpp"
    local_base_url: str = "http://localhost:11434"
    gguf_model_dir: str | None = None

    # Timeouts
    connection_timeout_seconds: float = 10.0
    prompt_timeout_seconds: float = 10.0

    def to_json(self) -> str:
        """Serializa la configuración a JSON para persistencia."""
        return json.dumps(asdict(self), indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> IABackendConfig:
        """Deserializa la configuración desde JSON persistido."""
        data = json.loads(json_str)
        return cls(**data)

    @classmethod
    def default_bedrock(cls) -> IABackendConfig:
        """Configuración por defecto para AWS Bedrock."""
        return cls(
            backend_type="bedrock",
            embedding_model_id="amazon.titan-embed-text-v2:0",
            llm_model_id="anthropic.claude-3-5-sonnet-20241022-v2:0",
        )

    @classmethod
    def default_local(cls) -> IABackendConfig:
        """Configuración por defecto para Backend Local (Ollama)."""
        return cls(
            backend_type="local",
            embedding_model_id="nomic-embed-text",
            llm_model_id="llama3:8b",
            local_runtime="ollama",
        )

    def save(self, path: Path | None = None) -> None:
        """Persiste la configuración en disco.

        Crea el directorio ~/.switch_bot/ si no existe.

        Args:
            path: Ruta del archivo de configuración. Si es None usa la ruta
                  por defecto (~/.switch_bot/config.json).
        """
        config_file = path or CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: Path | None = None) -> IABackendConfig | None:
        """Carga la configuración desde disco.

        Args:
            path: Ruta del archivo de configuración. Si es None usa la ruta
                  por defecto (~/.switch_bot/config.json).

        Returns:
            La configuración cargada o None si el archivo no existe.
        """
        config_file = path or CONFIG_FILE
        if not config_file.exists():
            return None
        json_str = config_file.read_text(encoding="utf-8")
        return cls.from_json(json_str)
