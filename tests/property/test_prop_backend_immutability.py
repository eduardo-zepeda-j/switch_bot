"""Property-based tests para inmutabilidad de configuración de backend durante sesión activa.

**Validates: Requirements 19.7**

Verifica que:
- WHILE a session is active, ANY attempt to change the backend configuration
  SHALL raise SessionConfigLockedError.
- ALL config fields (backend_type, embedding_model_id, llm_model_id, etc.)
  are immutable during active session.
- Config changes are only allowed AFTER the session ends.
- Regardless of what new config is provided (valid or not), the change is
  rejected during active session.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, PropertyMock

from hypothesis import given, assume
from hypothesis.strategies import (
    builds,
    floats,
    from_regex,
    integers,
    just,
    lists,
    none,
    one_of,
    sampled_from,
    text,
)

from switch_bot.engines.session_manager import (
    SessionConfigLockedError,
    SessionManager,
)
from switch_bot.ia.backend_base import IABackend
from switch_bot.ia.backend_config import IABackendConfig
from switch_bot.ia.ia_enricher import IAEnricher


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

backend_types = sampled_from(["bedrock", "local"])
local_runtimes = sampled_from(["ollama", "llamacpp"])

model_ids = text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.:/ ",
    min_size=1,
    max_size=80,
)

aws_regions = from_regex(
    r"(us|eu|ap|sa|ca|me|af)\-(north|south|east|west|central|northeast|southeast)\-[1-3]",
    fullmatch=True,
)

aws_profiles = one_of(none(), text(min_size=1, max_size=50))

local_base_urls = from_regex(
    r"https?://[a-z0-9\-\.]+:[0-9]{1,5}",
    fullmatch=True,
)

gguf_model_dirs = one_of(
    none(),
    text(
        alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_./",
        min_size=1,
        max_size=100,
    ),
)

positive_timeouts = floats(
    min_value=0.01, max_value=3600.0, allow_nan=False, allow_infinity=False
)

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

# Number of change attempts per test case
num_change_attempts = integers(min_value=1, max_value=10)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_backend(backend_type: str = "bedrock") -> IABackend:
    """Crea un mock de IABackend que valida conexión exitosamente."""
    backend = AsyncMock(spec=IABackend)
    backend.validate_connection = AsyncMock(return_value=True)
    type(backend).backend_type = PropertyMock(return_value=backend_type)
    type(backend).is_connected = PropertyMock(return_value=True)
    return backend


def _make_mock_enricher() -> IAEnricher:
    """Crea un mock de IAEnricher para start_session."""
    return AsyncMock(spec=IAEnricher)


def _start_session_sync(
    manager: SessionManager, config: IABackendConfig
) -> None:
    """Inicia sesión de forma síncrona usando asyncio.run."""
    backend = _make_mock_backend(config.backend_type)
    enricher = _make_mock_enricher()
    result = asyncio.run(
        manager.start_session(backend=backend, config=config, enricher=enricher)
    )
    assert result.success, f"Session start failed: {result.error_message}"


def _end_session_sync(manager: SessionManager) -> None:
    """Finaliza sesión de forma síncrona."""
    asyncio.run(manager.end_session())


# ---------------------------------------------------------------------------
# Test Class
# ---------------------------------------------------------------------------


class TestProperty16BackendImmutability:
    """Property 16: Inmutabilidad de configuración de backend durante sesión activa.

    **Validates: Requirements 19.7**

    Verifica que para CUALQUIER configuración generada, change_backend_config
    SIEMPRE lanza SessionConfigLockedError mientras la sesión está activa,
    y SIEMPRE tiene éxito después de que la sesión termina.
    """

    @given(
        initial_config=ia_backend_configs,
        new_config=ia_backend_configs,
    )
    def test_change_config_raises_during_active_session(
        self,
        initial_config: IABackendConfig,
        new_config: IABackendConfig,
    ) -> None:
        """FOR ALL valid configs, change_backend_config raises
        SessionConfigLockedError while session is active."""
        manager = SessionManager()
        _start_session_sync(manager, initial_config)

        assert manager.is_session_active
        assert manager.is_config_locked

        # Attempt to change config — MUST raise
        try:
            manager.change_backend_config(new_config)
            raise AssertionError(
                "change_backend_config did NOT raise SessionConfigLockedError "
                "during active session"
            )
        except SessionConfigLockedError:
            pass  # Expected behavior

        # Cleanup
        _end_session_sync(manager)

    @given(
        initial_config=ia_backend_configs,
        new_config=ia_backend_configs,
    )
    def test_change_config_succeeds_after_session_ends(
        self,
        initial_config: IABackendConfig,
        new_config: IABackendConfig,
    ) -> None:
        """FOR ALL valid configs, change_backend_config succeeds
        after session ends (config unlocked)."""
        manager = SessionManager()
        _start_session_sync(manager, initial_config)

        # End session
        _end_session_sync(manager)

        assert not manager.is_session_active
        assert not manager.is_config_locked

        # Change must succeed without raising
        manager.change_backend_config(new_config)

        # Verify config was actually updated
        assert manager.current_config == new_config

    @given(
        initial_config=ia_backend_configs,
        configs_to_try=lists(ia_backend_configs, min_size=1, max_size=5),
    )
    def test_multiple_change_attempts_all_rejected_during_session(
        self,
        initial_config: IABackendConfig,
        configs_to_try: list[IABackendConfig],
    ) -> None:
        """FOR ALL sequences of config change attempts during active session,
        ALL are rejected with SessionConfigLockedError."""
        manager = SessionManager()
        _start_session_sync(manager, initial_config)

        rejected_count = 0
        for config_attempt in configs_to_try:
            try:
                manager.change_backend_config(config_attempt)
                raise AssertionError(
                    "change_backend_config did NOT raise for attempt"
                )
            except SessionConfigLockedError:
                rejected_count += 1

        assert rejected_count == len(configs_to_try)

        _end_session_sync(manager)

    @given(
        initial_config=ia_backend_configs,
        new_config=ia_backend_configs,
    )
    def test_config_unchanged_after_rejected_change_attempt(
        self,
        initial_config: IABackendConfig,
        new_config: IABackendConfig,
    ) -> None:
        """FOR ALL configs, after a rejected change attempt during active
        session, the current config remains the original one."""
        manager = SessionManager()
        _start_session_sync(manager, initial_config)

        # Store original config reference
        original_config = manager.current_config

        # Attempt change (will be rejected)
        try:
            manager.change_backend_config(new_config)
        except SessionConfigLockedError:
            pass

        # Config must be unchanged
        assert manager.current_config == original_config

        _end_session_sync(manager)

    @given(
        initial_config=ia_backend_configs,
        new_config=ia_backend_configs,
    )
    def test_session_lifecycle_lock_unlock_cycle(
        self,
        initial_config: IABackendConfig,
        new_config: IABackendConfig,
    ) -> None:
        """FOR ALL configs, the full lifecycle: start → locked → end → unlocked
        is consistent. Config is locked during session, unlocked after."""
        manager = SessionManager()

        # Before session: config not locked
        assert not manager.is_config_locked
        assert not manager.is_session_active

        # Start session
        _start_session_sync(manager, initial_config)
        assert manager.is_config_locked
        assert manager.is_session_active

        # Reject change
        try:
            manager.change_backend_config(new_config)
        except SessionConfigLockedError:
            pass

        # End session
        _end_session_sync(manager)
        assert not manager.is_config_locked
        assert not manager.is_session_active

        # Accept change
        manager.change_backend_config(new_config)
        assert manager.current_config == new_config
