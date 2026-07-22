"""Unit tests para IABackendConfig."""

import json
from pathlib import Path

from switch_bot.ia.backend_config import IABackendConfig


class TestIABackendConfigDefaults:
    """Tests para valores por defecto de IABackendConfig."""

    def test_bedrock_defaults(self) -> None:
        cfg = IABackendConfig.default_bedrock()
        assert cfg.backend_type == "bedrock"
        assert cfg.embedding_model_id == "amazon.titan-embed-text-v2:0"
        assert cfg.llm_model_id == "anthropic.claude-3-5-sonnet-20241022-v2:0"
        assert cfg.aws_region == "us-east-1"
        assert cfg.aws_profile is None

    def test_local_defaults(self) -> None:
        cfg = IABackendConfig.default_local()
        assert cfg.backend_type == "local"
        assert cfg.embedding_model_id == "nomic-embed-text"
        assert cfg.llm_model_id == "llama3:8b"
        assert cfg.local_runtime == "ollama"
        assert cfg.local_base_url == "http://localhost:11434"
        assert cfg.gguf_model_dir is None

    def test_default_timeouts(self) -> None:
        cfg = IABackendConfig.default_bedrock()
        assert cfg.connection_timeout_seconds == 10.0
        assert cfg.prompt_timeout_seconds == 10.0


class TestIABackendConfigSerialization:
    """Tests para serialización/deserialización JSON."""

    def test_to_json_produces_valid_json(self) -> None:
        cfg = IABackendConfig.default_bedrock()
        json_str = cfg.to_json()
        data = json.loads(json_str)
        assert data["backend_type"] == "bedrock"

    def test_from_json_reconstructs_bedrock(self) -> None:
        cfg = IABackendConfig.default_bedrock()
        json_str = cfg.to_json()
        restored = IABackendConfig.from_json(json_str)
        assert restored == cfg

    def test_from_json_reconstructs_local(self) -> None:
        cfg = IABackendConfig.default_local()
        json_str = cfg.to_json()
        restored = IABackendConfig.from_json(json_str)
        assert restored == cfg

    def test_roundtrip_with_custom_fields(self) -> None:
        cfg = IABackendConfig(
            backend_type="local",
            embedding_model_id="custom-embed",
            llm_model_id="mistral:7b",
            local_runtime="llamacpp",
            local_base_url="http://localhost:8080",
            gguf_model_dir="/models/gguf",
            connection_timeout_seconds=5.0,
            prompt_timeout_seconds=15.0,
        )
        json_str = cfg.to_json()
        restored = IABackendConfig.from_json(json_str)
        assert restored == cfg

    def test_roundtrip_preserves_none_fields(self) -> None:
        cfg = IABackendConfig.default_bedrock()
        assert cfg.aws_profile is None
        json_str = cfg.to_json()
        restored = IABackendConfig.from_json(json_str)
        assert restored.aws_profile is None

    def test_to_json_contains_all_fields(self) -> None:
        cfg = IABackendConfig.default_bedrock()
        data = json.loads(cfg.to_json())
        expected_keys = {
            "backend_type", "embedding_model_id", "llm_model_id",
            "aws_region", "aws_profile", "local_runtime",
            "local_base_url", "gguf_model_dir",
            "connection_timeout_seconds", "prompt_timeout_seconds",
        }
        assert set(data.keys()) == expected_keys


class TestIABackendConfigPersistence:
    """Tests para persistencia en archivo JSON."""

    def test_save_creates_file(self, tmp_path: Path) -> None:
        cfg = IABackendConfig.default_bedrock()
        config_file = tmp_path / "config.json"
        cfg.save(path=config_file)
        assert config_file.exists()

    def test_save_creates_parent_directory(self, tmp_path: Path) -> None:
        cfg = IABackendConfig.default_local()
        config_file = tmp_path / "nested" / "dir" / "config.json"
        cfg.save(path=config_file)
        assert config_file.exists()

    def test_load_returns_none_if_not_exists(self, tmp_path: Path) -> None:
        config_file = tmp_path / "nonexistent.json"
        result = IABackendConfig.load(path=config_file)
        assert result is None

    def test_save_and_load_roundtrip_bedrock(self, tmp_path: Path) -> None:
        cfg = IABackendConfig.default_bedrock()
        config_file = tmp_path / "config.json"
        cfg.save(path=config_file)
        loaded = IABackendConfig.load(path=config_file)
        assert loaded == cfg

    def test_save_and_load_roundtrip_local(self, tmp_path: Path) -> None:
        cfg = IABackendConfig.default_local()
        config_file = tmp_path / "config.json"
        cfg.save(path=config_file)
        loaded = IABackendConfig.load(path=config_file)
        assert loaded == cfg

    def test_save_overwrites_existing(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        # Guardar bedrock
        cfg_bedrock = IABackendConfig.default_bedrock()
        cfg_bedrock.save(path=config_file)
        # Sobreescribir con local
        cfg_local = IABackendConfig.default_local()
        cfg_local.save(path=config_file)
        # Cargar debe retornar local
        loaded = IABackendConfig.load(path=config_file)
        assert loaded is not None
        assert loaded.backend_type == "local"

    def test_file_content_is_valid_json(self, tmp_path: Path) -> None:
        cfg = IABackendConfig.default_bedrock()
        config_file = tmp_path / "config.json"
        cfg.save(path=config_file)
        content = config_file.read_text(encoding="utf-8")
        data = json.loads(content)
        assert data["backend_type"] == "bedrock"


class TestIABackendConfigImport:
    """Tests para verificar que IABackendConfig se exporta correctamente."""

    def test_import_from_ia_module(self) -> None:
        from switch_bot.ia import IABackendConfig as Imported
        assert Imported is IABackendConfig
