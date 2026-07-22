"""Property-based tests para IABackendConfig — Round-trip de persistencia.

**Validates: Requirements 19.6**
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from hypothesis import given
from hypothesis.strategies import (
    builds,
    from_regex,
    just,
    none,
    one_of,
    sampled_from,
    text,
    floats,
)

from switch_bot.ia.backend_config import IABackendConfig


# --- Strategies ---

backend_types = sampled_from(["bedrock", "local"])
local_runtimes = sampled_from(["ollama", "llamacpp"])

# Non-empty strings for model IDs (printable, no control chars)
model_ids = text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.:/ ",
    min_size=1,
    max_size=100,
)

# Valid AWS region strings (realistic format)
aws_regions = from_regex(
    r"(us|eu|ap|sa|ca|me|af)\-(north|south|east|west|central|northeast|southeast)\-[1-3]",
    fullmatch=True,
)

# Optional AWS profile
aws_profiles = one_of(none(), text(min_size=1, max_size=50))

# Valid URL strings for local_base_url
local_base_urls = from_regex(
    r"https?://[a-z0-9\-\.]+:[0-9]{1,5}",
    fullmatch=True,
)

# Optional gguf model directory
gguf_model_dirs = one_of(
    none(),
    text(
        alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_./",
        min_size=1,
        max_size=200,
    ),
)

# Positive floats for timeouts (avoid infinity and NaN)
positive_timeouts = floats(min_value=0.01, max_value=3600.0, allow_nan=False, allow_infinity=False)

# Composite strategy for IABackendConfig
ia_backend_configs = builds(
    IABackendConfig,
    backend_type=backend_types,
    embedding_model_id=model_ids,
    llm_model_id=model_ids,
    aws_region=aws_regions,
    aws_profile=aws_profiles,
    local_runtime=local_runtimes,
    local_base_url=local_base_urls,
    gguf_model_dir=gguf_model_dirs,
    connection_timeout_seconds=positive_timeouts,
    prompt_timeout_seconds=positive_timeouts,
)


class TestProperty15RoundTripPersistencia:
    """Property 15: Round-trip de persistencia de IABackendConfig.

    **Validates: Requirements 19.6**
    """

    @given(config=ia_backend_configs)
    def test_json_roundtrip_produces_equivalent_object(
        self, config: IABackendConfig
    ) -> None:
        """FOR ALL valid IABackendConfig, to_json() -> from_json() == original."""
        json_str = config.to_json()
        restored = IABackendConfig.from_json(json_str)
        assert restored == config

    @given(config=ia_backend_configs)
    def test_file_roundtrip_produces_equivalent_object(
        self, config: IABackendConfig
    ) -> None:
        """FOR ALL valid IABackendConfig, save() -> load() == original."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test_config.json"
            config.save(path)
            restored = IABackendConfig.load(path)
            assert restored is not None
            assert restored == config

    @given(config=ia_backend_configs)
    def test_json_output_is_valid_json_string(
        self, config: IABackendConfig
    ) -> None:
        """FOR ALL valid IABackendConfig, to_json() produces a parseable JSON string."""
        import json

        json_str = config.to_json()
        # Must not raise
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)
        assert "backend_type" in parsed
        assert "embedding_model_id" in parsed
        assert "llm_model_id" in parsed

    @given(config=ia_backend_configs)
    def test_load_nonexistent_file_returns_none(
        self, config: IABackendConfig  # noqa: ARG002
    ) -> None:
        """FOR ALL configs, loading from a non-existent path returns None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "nonexistent.json"
            result = IABackendConfig.load(path)
            assert result is None
