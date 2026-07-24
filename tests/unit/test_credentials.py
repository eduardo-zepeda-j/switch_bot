"""Unit tests for switch_bot.gui.credentials module.

Tests obfuscate_secret/deobfuscate_secret round-trip and ModelInfo.display_text().
Requisitos: 1.5, 2.3
"""

import pytest

from switch_bot.gui.credentials import ModelInfo, deobfuscate_secret, obfuscate_secret


class TestObfuscateSecret:
    """Tests for obfuscate_secret and deobfuscate_secret."""

    def test_roundtrip_basic(self):
        secret = "my-aws-secret-key"
        assert deobfuscate_secret(obfuscate_secret(secret)) == secret

    def test_roundtrip_single_char(self):
        assert deobfuscate_secret(obfuscate_secret("x")) == "x"

    def test_roundtrip_special_characters(self):
        secret = "P@$$w0rd!#%&*+/="
        assert deobfuscate_secret(obfuscate_secret(secret)) == secret

    def test_obfuscated_differs_from_original(self):
        secret = "visible-secret"
        obfuscated = obfuscate_secret(secret)
        assert obfuscated != secret

    def test_obfuscated_is_base64(self):
        """The output should be valid base64 (decodable without error)."""
        import base64

        secret = "test-secret"
        obfuscated = obfuscate_secret(secret)
        # Should not raise
        base64.b64decode(obfuscated.encode())

    def test_roundtrip_unicode(self):
        secret = "contraseña-ñ-ü-€"
        assert deobfuscate_secret(obfuscate_secret(secret)) == secret

    def test_roundtrip_whitespace(self):
        secret = "secret with spaces\tand\ttabs"
        assert deobfuscate_secret(obfuscate_secret(secret)) == secret


class TestModelInfo:
    """Tests for ModelInfo dataclass."""

    def test_display_text_with_size(self):
        model = ModelInfo(id="llama3:8b", name="Llama 3 8B", size_gb=4.7, model_type="llm")
        assert model.display_text() == "Llama 3 8B (4.7 GB)"

    def test_display_text_without_size(self):
        model = ModelInfo(
            id="nomic-embed-text", name="Nomic Embed Text", size_gb=None, model_type="embedding"
        )
        assert model.display_text() == "Nomic Embed Text"

    def test_display_text_size_formatting(self):
        """Size should be formatted with exactly one decimal place."""
        model = ModelInfo(id="m1", name="Model", size_gb=10.0, model_type="llm")
        assert model.display_text() == "Model (10.0 GB)"

    def test_display_text_small_size(self):
        model = ModelInfo(id="m1", name="Tiny Model", size_gb=0.3, model_type="embedding")
        assert model.display_text() == "Tiny Model (0.3 GB)"

    def test_dataclass_fields(self):
        model = ModelInfo(id="test:latest", name="Test", size_gb=2.5, model_type="llm")
        assert model.id == "test:latest"
        assert model.name == "Test"
        assert model.size_gb == 2.5
        assert model.model_type == "llm"

    def test_model_type_embedding(self):
        model = ModelInfo(id="e1", name="Embed", size_gb=1.0, model_type="embedding")
        assert model.model_type == "embedding"
