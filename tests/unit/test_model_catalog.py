"""Unit tests para IAModelInfo e IAModelCatalog."""

from switch_bot.ia.model_catalog import IAModelCatalog, IAModelInfo


class TestIAModelInfoCreation:
    """Tests para creación e instanciación de IAModelInfo."""

    def test_embedding_model_required_fields(self) -> None:
        model = IAModelInfo(
            model_id="nomic-embed-text",
            name="Nomic Embed Text",
            model_type="embedding",
        )
        assert model.model_id == "nomic-embed-text"
        assert model.name == "Nomic Embed Text"
        assert model.model_type == "embedding"

    def test_llm_model_required_fields(self) -> None:
        model = IAModelInfo(
            model_id="llama3:8b",
            name="Llama 3 8B",
            model_type="llm",
        )
        assert model.model_id == "llama3:8b"
        assert model.name == "Llama 3 8B"
        assert model.model_type == "llm"

    def test_optional_fields_default_to_none_or_empty(self) -> None:
        model = IAModelInfo(
            model_id="test-model",
            name="Test",
            model_type="embedding",
        )
        assert model.size_bytes is None
        assert model.context_window is None
        assert model.description == ""

    def test_all_fields_populated(self) -> None:
        model = IAModelInfo(
            model_id="titan-embed-v2",
            name="Titan Embeddings V2",
            model_type="embedding",
            size_bytes=500_000_000,
            context_window=8192,
            description="AWS Titan text embedding model",
        )
        assert model.size_bytes == 500_000_000
        assert model.context_window == 8192
        assert model.description == "AWS Titan text embedding model"


class TestIAModelCatalogCreation:
    """Tests para creación e instanciación de IAModelCatalog."""

    def test_empty_catalog(self) -> None:
        catalog = IAModelCatalog(backend_type="bedrock")
        assert catalog.backend_type == "bedrock"
        assert catalog.embedding_models == []
        assert catalog.llm_models == []
        assert catalog.last_updated == ""

    def test_catalog_with_models(self) -> None:
        emb = IAModelInfo(model_id="emb-1", name="Emb 1", model_type="embedding")
        llm = IAModelInfo(model_id="llm-1", name="LLM 1", model_type="llm")
        catalog = IAModelCatalog(
            backend_type="local",
            embedding_models=[emb],
            llm_models=[llm],
            last_updated="2024-01-15T10:30:00Z",
        )
        assert len(catalog.embedding_models) == 1
        assert len(catalog.llm_models) == 1
        assert catalog.last_updated == "2024-01-15T10:30:00Z"


class TestIAModelCatalogMethods:
    """Tests para métodos de IAModelCatalog."""

    def test_get_embedding_model_ids_empty(self) -> None:
        catalog = IAModelCatalog(backend_type="bedrock")
        assert catalog.get_embedding_model_ids() == []

    def test_get_llm_model_ids_empty(self) -> None:
        catalog = IAModelCatalog(backend_type="bedrock")
        assert catalog.get_llm_model_ids() == []

    def test_get_embedding_model_ids_returns_ids(self) -> None:
        models = [
            IAModelInfo(model_id="emb-a", name="A", model_type="embedding"),
            IAModelInfo(model_id="emb-b", name="B", model_type="embedding"),
        ]
        catalog = IAModelCatalog(
            backend_type="local",
            embedding_models=models,
            last_updated="2024-01-01T00:00:00Z",
        )
        assert catalog.get_embedding_model_ids() == ["emb-a", "emb-b"]

    def test_get_llm_model_ids_returns_ids(self) -> None:
        models = [
            IAModelInfo(model_id="llm-x", name="X", model_type="llm"),
            IAModelInfo(model_id="llm-y", name="Y", model_type="llm"),
            IAModelInfo(model_id="llm-z", name="Z", model_type="llm"),
        ]
        catalog = IAModelCatalog(
            backend_type="bedrock",
            llm_models=models,
            last_updated="2024-06-01T12:00:00Z",
        )
        assert catalog.get_llm_model_ids() == ["llm-x", "llm-y", "llm-z"]


class TestIAModelCatalogImport:
    """Tests para verificar que las clases se exportan correctamente."""

    def test_import_model_info_from_ia_module(self) -> None:
        from switch_bot.ia import IAModelInfo as Imported
        assert Imported is IAModelInfo

    def test_import_model_catalog_from_ia_module(self) -> None:
        from switch_bot.ia import IAModelCatalog as Imported
        assert Imported is IAModelCatalog
