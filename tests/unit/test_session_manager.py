"""Unit tests para SessionManager — ciclo de vida del backend de IA.

Verifica:
- Inicio y fin de sesión correctos.
- Inmutabilidad de configuración durante sesión activa.
- Comportamiento de fallback ante fallos de conexión.
- Manejo de timeout en validación.

Requisitos: 19.4, 19.5, 19.7
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from switch_bot.engines.session_manager import (
    SessionConfigLockedError,
    SessionManager,
    SessionStartResult,
)
from switch_bot.ia.backend_base import (
    BackendConnectionError,
    BackendTimeoutError,
    IABackend,
)
from switch_bot.ia.backend_config import IABackendConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_mock_backend(
    *,
    validate_returns: bool = True,
    validate_raises: Exception | None = None,
    backend_type: str = "bedrock",
) -> IABackend:
    """Crea un mock de IABackend con comportamiento configurable."""
    backend = MagicMock(spec=IABackend)
    backend.backend_type = backend_type
    backend.is_connected = True

    if validate_raises:
        backend.validate_connection = AsyncMock(side_effect=validate_raises)
    else:
        backend.validate_connection = AsyncMock(return_value=validate_returns)

    return backend


def _make_mock_enricher() -> MagicMock:
    """Crea un mock de IAEnricher."""
    enricher = MagicMock()
    enricher.generate_ad_suggestions = AsyncMock(return_value=[])
    return enricher


@pytest.fixture
def session_manager() -> SessionManager:
    """Fixture: SessionManager limpio."""
    return SessionManager()


@pytest.fixture
def bedrock_config() -> IABackendConfig:
    """Fixture: configuración de Bedrock por defecto."""
    return IABackendConfig.default_bedrock()


@pytest.fixture
def local_config() -> IABackendConfig:
    """Fixture: configuración local por defecto."""
    return IABackendConfig.default_local()


# ---------------------------------------------------------------------------
# Tests: Estado inicial
# ---------------------------------------------------------------------------


class TestSessionManagerInitialState:
    """Tests para el estado inicial del SessionManager."""

    def test_initial_session_not_active(
        self, session_manager: SessionManager
    ) -> None:
        assert session_manager.is_session_active is False

    def test_initial_config_not_locked(
        self, session_manager: SessionManager
    ) -> None:
        assert session_manager.is_config_locked is False

    def test_initial_backend_is_none(
        self, session_manager: SessionManager
    ) -> None:
        assert session_manager.current_backend is None

    def test_initial_config_is_none(
        self, session_manager: SessionManager
    ) -> None:
        assert session_manager.current_config is None


# ---------------------------------------------------------------------------
# Tests: Ciclo de vida (inicio y fin de sesión)
# ---------------------------------------------------------------------------


class TestSessionLifecycle:
    """Tests para inicio y fin de sesión."""

    @pytest.mark.asyncio
    async def test_start_session_success(
        self,
        session_manager: SessionManager,
        bedrock_config: IABackendConfig,
    ) -> None:
        """Req 19.4: Sesión se inicia si backend es accesible."""
        backend = _make_mock_backend(validate_returns=True)
        enricher = _make_mock_enricher()

        result = await session_manager.start_session(
            backend=backend, config=bedrock_config, enricher=enricher
        )

        assert result.success is True
        assert result.error_message == ""
        assert session_manager.is_session_active is True

    @pytest.mark.asyncio
    async def test_start_session_locks_config(
        self,
        session_manager: SessionManager,
        bedrock_config: IABackendConfig,
    ) -> None:
        """Req 19.7: Config bloqueada tras inicio de sesión."""
        backend = _make_mock_backend(validate_returns=True)
        enricher = _make_mock_enricher()

        await session_manager.start_session(
            backend=backend, config=bedrock_config, enricher=enricher
        )

        assert session_manager.is_config_locked is True

    @pytest.mark.asyncio
    async def test_start_session_stores_backend_and_config(
        self,
        session_manager: SessionManager,
        bedrock_config: IABackendConfig,
    ) -> None:
        backend = _make_mock_backend(validate_returns=True)
        enricher = _make_mock_enricher()

        await session_manager.start_session(
            backend=backend, config=bedrock_config, enricher=enricher
        )

        assert session_manager.current_backend is backend
        assert session_manager.current_config is bedrock_config

    @pytest.mark.asyncio
    async def test_start_session_validates_with_config_timeout(
        self,
        session_manager: SessionManager,
    ) -> None:
        """Req 19.4: Usa timeout de la configuración (10s por defecto)."""
        config = IABackendConfig.default_bedrock()
        config.connection_timeout_seconds = 5.0
        backend = _make_mock_backend(validate_returns=True)
        enricher = _make_mock_enricher()

        await session_manager.start_session(
            backend=backend, config=config, enricher=enricher
        )

        backend.validate_connection.assert_awaited_once_with(
            timeout_seconds=5.0
        )

    @pytest.mark.asyncio
    async def test_end_session_unlocks_config(
        self,
        session_manager: SessionManager,
        bedrock_config: IABackendConfig,
    ) -> None:
        """Req 19.7: Config se desbloquea al finalizar sesión."""
        backend = _make_mock_backend(validate_returns=True)
        enricher = _make_mock_enricher()

        await session_manager.start_session(
            backend=backend, config=bedrock_config, enricher=enricher
        )
        await session_manager.end_session()

        assert session_manager.is_session_active is False
        assert session_manager.is_config_locked is False

    @pytest.mark.asyncio
    async def test_end_session_clears_state(
        self,
        session_manager: SessionManager,
        bedrock_config: IABackendConfig,
    ) -> None:
        backend = _make_mock_backend(validate_returns=True)
        enricher = _make_mock_enricher()

        await session_manager.start_session(
            backend=backend, config=bedrock_config, enricher=enricher
        )
        await session_manager.end_session()

        assert session_manager.current_backend is None
        assert session_manager.current_config is None

    @pytest.mark.asyncio
    async def test_end_session_without_active_session_is_noop(
        self, session_manager: SessionManager
    ) -> None:
        """Finalizar sin sesión activa no produce error."""
        await session_manager.end_session()
        assert session_manager.is_session_active is False

    @pytest.mark.asyncio
    async def test_cannot_start_session_while_active(
        self,
        session_manager: SessionManager,
        bedrock_config: IABackendConfig,
    ) -> None:
        """No se puede iniciar sesión si ya hay una activa."""
        backend = _make_mock_backend(validate_returns=True)
        enricher = _make_mock_enricher()

        await session_manager.start_session(
            backend=backend, config=bedrock_config, enricher=enricher
        )

        with pytest.raises(SessionConfigLockedError):
            await session_manager.start_session(
                backend=backend, config=bedrock_config, enricher=enricher
            )


# ---------------------------------------------------------------------------
# Tests: Inmutabilidad de configuración (Req 19.7)
# ---------------------------------------------------------------------------


class TestConfigImmutability:
    """Tests para inmutabilidad de configuración durante sesión activa."""

    @pytest.mark.asyncio
    async def test_change_config_blocked_during_session(
        self,
        session_manager: SessionManager,
        bedrock_config: IABackendConfig,
        local_config: IABackendConfig,
    ) -> None:
        """Req 19.7: No se permite cambiar config durante sesión."""
        backend = _make_mock_backend(validate_returns=True)
        enricher = _make_mock_enricher()

        await session_manager.start_session(
            backend=backend, config=bedrock_config, enricher=enricher
        )

        with pytest.raises(SessionConfigLockedError):
            session_manager.change_backend_config(local_config)

    @pytest.mark.asyncio
    async def test_change_config_allowed_after_session_ends(
        self,
        session_manager: SessionManager,
        bedrock_config: IABackendConfig,
        local_config: IABackendConfig,
    ) -> None:
        """Req 19.7: Config se puede cambiar tras finalizar sesión."""
        backend = _make_mock_backend(validate_returns=True)
        enricher = _make_mock_enricher()

        await session_manager.start_session(
            backend=backend, config=bedrock_config, enricher=enricher
        )
        await session_manager.end_session()

        # No debe lanzar excepción
        session_manager.change_backend_config(local_config)
        assert session_manager.current_config is local_config

    def test_change_config_allowed_without_session(
        self,
        session_manager: SessionManager,
        local_config: IABackendConfig,
    ) -> None:
        """Config se puede cambiar sin sesión activa."""
        session_manager.change_backend_config(local_config)
        assert session_manager.current_config is local_config


# ---------------------------------------------------------------------------
# Tests: Fallback ante fallos de conexión (Req 19.5)
# ---------------------------------------------------------------------------


class TestConnectionFailureFallback:
    """Tests para comportamiento de fallback cuando el backend no es accesible."""

    @pytest.mark.asyncio
    async def test_timeout_returns_descriptive_error(
        self,
        session_manager: SessionManager,
        bedrock_config: IABackendConfig,
    ) -> None:
        """Req 19.5: Timeout produce mensaje descriptivo."""
        backend = _make_mock_backend(
            validate_raises=BackendTimeoutError(
                "Timeout de conexión", timeout_seconds=10.0
            )
        )
        enricher = _make_mock_enricher()

        result = await session_manager.start_session(
            backend=backend, config=bedrock_config, enricher=enricher
        )

        assert result.success is False
        assert "timeout" in result.error_message.lower()
        assert result.can_retry is True
        assert result.can_select_alternative is True

    @pytest.mark.asyncio
    async def test_connection_error_returns_descriptive_error(
        self,
        session_manager: SessionManager,
        bedrock_config: IABackendConfig,
    ) -> None:
        """Req 19.5: Error de conexión produce mensaje descriptivo."""
        backend = _make_mock_backend(
            validate_raises=BackendConnectionError(
                "Servicio no disponible"
            )
        )
        enricher = _make_mock_enricher()

        result = await session_manager.start_session(
            backend=backend, config=bedrock_config, enricher=enricher
        )

        assert result.success is False
        assert "conectar" in result.error_message.lower()
        assert result.can_retry is True
        assert result.can_select_alternative is True

    @pytest.mark.asyncio
    async def test_validation_false_returns_error(
        self,
        session_manager: SessionManager,
        bedrock_config: IABackendConfig,
    ) -> None:
        """Backend que retorna False en validación produce error recuperable."""
        backend = _make_mock_backend(validate_returns=False)
        enricher = _make_mock_enricher()

        result = await session_manager.start_session(
            backend=backend, config=bedrock_config, enricher=enricher
        )

        assert result.success is False
        assert result.can_retry is True
        assert result.can_select_alternative is True

    @pytest.mark.asyncio
    async def test_session_not_active_after_failure(
        self,
        session_manager: SessionManager,
        bedrock_config: IABackendConfig,
    ) -> None:
        """La sesión no se inicia si la validación falla."""
        backend = _make_mock_backend(
            validate_raises=BackendTimeoutError("Timeout")
        )
        enricher = _make_mock_enricher()

        await session_manager.start_session(
            backend=backend, config=bedrock_config, enricher=enricher
        )

        assert session_manager.is_session_active is False
        assert session_manager.is_config_locked is False

    @pytest.mark.asyncio
    async def test_can_retry_after_failure(
        self,
        session_manager: SessionManager,
        bedrock_config: IABackendConfig,
    ) -> None:
        """Req 19.5: Se puede reintentar sin reiniciar la app."""
        # Primer intento falla
        failing_backend = _make_mock_backend(
            validate_raises=BackendConnectionError("Fallo")
        )
        enricher = _make_mock_enricher()

        result = await session_manager.start_session(
            backend=failing_backend, config=bedrock_config, enricher=enricher
        )
        assert result.success is False

        # Segundo intento con backend funcional
        working_backend = _make_mock_backend(validate_returns=True)

        result = await session_manager.start_session(
            backend=working_backend, config=bedrock_config, enricher=enricher
        )
        assert result.success is True
        assert session_manager.is_session_active is True

    @pytest.mark.asyncio
    async def test_can_select_alternative_backend_after_failure(
        self,
        session_manager: SessionManager,
        bedrock_config: IABackendConfig,
        local_config: IABackendConfig,
    ) -> None:
        """Req 19.5: Se puede seleccionar backend alternativo sin reiniciar."""
        # Bedrock falla
        failing_backend = _make_mock_backend(
            validate_raises=BackendConnectionError("Bedrock no disponible"),
            backend_type="bedrock",
        )
        enricher = _make_mock_enricher()

        result = await session_manager.start_session(
            backend=failing_backend, config=bedrock_config, enricher=enricher
        )
        assert result.success is False

        # Cambia a backend local que funciona
        local_backend = _make_mock_backend(
            validate_returns=True, backend_type="local"
        )

        result = await session_manager.start_session(
            backend=local_backend, config=local_config, enricher=enricher
        )
        assert result.success is True
        assert session_manager.current_config is local_config


# ---------------------------------------------------------------------------
# Tests: Generación de sugerencias publicitarias al fin de sesión
# ---------------------------------------------------------------------------


class TestAdSuggestionGeneration:
    """Tests para invocación de generación de sugerencias al finalizar."""

    @pytest.mark.asyncio
    async def test_end_session_triggers_ad_suggestions(
        self,
        session_manager: SessionManager,
        bedrock_config: IABackendConfig,
        tmp_path: Path,
    ) -> None:
        """Al finalizar sesión se invocan sugerencias publicitarias."""
        from switch_bot.engines.script_parser import ScriptDocument

        backend = _make_mock_backend(validate_returns=True)
        enricher = _make_mock_enricher()
        log_path = tmp_path / "session.jsonl"
        log_path.write_text("", encoding="utf-8")

        await session_manager.start_session(
            backend=backend,
            config=bedrock_config,
            enricher=enricher,
            session_log_path=log_path,
        )

        # Crear un ScriptDocument real mínimo para pasar isinstance check
        script_doc = ScriptDocument(title="Test", blocks=[])

        await session_manager.end_session(script_doc=script_doc)

        enricher.generate_ad_suggestions.assert_awaited_once_with(
            session_log=log_path,
            script=script_doc,
        )

    @pytest.mark.asyncio
    async def test_end_session_without_log_path_skips_suggestions(
        self,
        session_manager: SessionManager,
        bedrock_config: IABackendConfig,
    ) -> None:
        """Sin log de sesión no se generan sugerencias."""
        backend = _make_mock_backend(validate_returns=True)
        enricher = _make_mock_enricher()

        await session_manager.start_session(
            backend=backend,
            config=bedrock_config,
            enricher=enricher,
            session_log_path=None,
        )

        await session_manager.end_session(script_doc=None)

        enricher.generate_ad_suggestions.assert_not_awaited()
