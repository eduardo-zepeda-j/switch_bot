"""SessionManager — Control de ciclo de vida del backend de IA durante sesiones.

Gestiona el inicio y fin de sesiones de grabación, garantizando que la
configuración del backend sea inmutable durante la sesión activa y
coordinando la generación de sugerencias publicitarias al finalizar.

Requisitos: 19.4, 19.5, 19.7
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from switch_bot.ia.backend_base import (
    BackendConnectionError,
    BackendTimeoutError,
    IABackend,
)
from switch_bot.ia.backend_config import IABackendConfig

if TYPE_CHECKING:
    from switch_bot.ia.ia_enricher import IAEnricher

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Excepciones del SessionManager
# ---------------------------------------------------------------------------


class SessionConfigLockedError(Exception):
    """Error al intentar cambiar configuración durante sesión activa.

    Se lanza cuando se intenta modificar el backend o la configuración
    mientras una sesión de grabación está en curso (Req 19.7).
    """

    def __init__(
        self,
        message: str = (
            "No se puede modificar la configuración del backend mientras "
            "una sesión está activa. Finalice la sesión primero."
        ),
    ) -> None:
        super().__init__(message)


class SessionStartError(Exception):
    """Error al iniciar una sesión de grabación.

    Se lanza cuando la validación de conexión al backend falla
    durante el inicio de sesión (Req 19.4, 19.5).
    """

    def __init__(self, message: str, backend_type: str = "") -> None:
        full_message = (
            f"No se pudo iniciar sesión con backend '{backend_type}': {message}"
            if backend_type
            else f"No se pudo iniciar sesión: {message}"
        )
        super().__init__(full_message)
        self.backend_type = backend_type
        self.detail = message


# ---------------------------------------------------------------------------
# Resultado de inicio de sesión
# ---------------------------------------------------------------------------


@dataclass
class SessionStartResult:
    """Resultado del intento de inicio de sesión.

    Attributes:
        success: True si la sesión se inició correctamente.
        error_message: Mensaje descriptivo en caso de fallo.
        can_retry: True si el operador puede reintentar la conexión.
        can_select_alternative: True si el operador puede seleccionar otro backend.
    """

    success: bool
    error_message: str = ""
    can_retry: bool = False
    can_select_alternative: bool = False


# ---------------------------------------------------------------------------
# SessionManager
# ---------------------------------------------------------------------------


class SessionManager:
    """Gestiona el ciclo de vida del backend de IA durante sesiones de grabación.

    Responsabilidades:
    - Validar accesibilidad del backend antes de iniciar sesión (Req 19.4).
    - Bloquear la configuración del backend durante la sesión activa (Req 19.7).
    - Desbloquear configuración y disparar generación de sugerencias al
      finalizar la sesión.
    - Proveer fallback descriptivo si el backend no es accesible (Req 19.5).

    Requisitos: 19.4, 19.5, 19.7
    """

    # Timeout de validación por defecto (segundos)
    DEFAULT_VALIDATION_TIMEOUT: float = 10.0

    def __init__(self) -> None:
        """Inicializa el SessionManager sin sesión activa."""
        self._session_active: bool = False
        self._current_backend: IABackend | None = None
        self._current_config: IABackendConfig | None = None
        self._current_enricher: IAEnricher | None = None
        self._session_log_path: Path | None = None

    # ------------------------------------------------------------------
    # Propiedades
    # ------------------------------------------------------------------

    @property
    def is_session_active(self) -> bool:
        """True mientras una sesión de grabación está en curso."""
        return self._session_active

    @property
    def is_config_locked(self) -> bool:
        """True mientras la configuración está bloqueada (sesión activa).

        La configuración se bloquea al iniciar sesión y se desbloquea
        al finalizarla (Req 19.7).
        """
        return self._session_active

    @property
    def current_backend(self) -> IABackend | None:
        """Backend activo durante la sesión (None si no hay sesión)."""
        return self._current_backend

    @property
    def current_config(self) -> IABackendConfig | None:
        """Configuración activa durante la sesión (None si no hay sesión)."""
        return self._current_config

    # ------------------------------------------------------------------
    # Inicio de sesión
    # ------------------------------------------------------------------

    async def start_session(
        self,
        backend: IABackend,
        config: IABackendConfig,
        enricher: IAEnricher,
        session_log_path: Path | None = None,
    ) -> SessionStartResult:
        """Inicia una sesión de grabación validando el backend.

        Valida que el backend esté accesible (timeout 10s) y bloquea
        la configuración para garantizar inmutabilidad durante la sesión.

        Args:
            backend: Implementación concreta del backend de IA.
            config: Configuración del backend a usar.
            enricher: Enriquecedor IA para sugerencias publicitarias post-sesión.
            session_log_path: Ruta opcional al log de sesión (.jsonl).

        Returns:
            SessionStartResult indicando éxito o fallo con información
            de recuperación.

        Raises:
            SessionConfigLockedError: Si ya hay una sesión activa.
        """
        if self._session_active:
            raise SessionConfigLockedError(
                "Ya existe una sesión activa. Finalícela antes de iniciar otra."
            )

        # Req 19.4: Validar backend accesible con timeout de 10 segundos
        timeout = config.connection_timeout_seconds or self.DEFAULT_VALIDATION_TIMEOUT

        try:
            is_accessible = await backend.validate_connection(
                timeout_seconds=timeout
            )
        except BackendTimeoutError as e:
            # Req 19.5: Informar con mensaje descriptivo
            error_msg = (
                f"El backend '{config.backend_type}' no respondió dentro del "
                f"timeout de {timeout}s. Verifique que el servicio esté "
                f"ejecutándose y sea accesible."
            )
            logger.error(
                "Timeout validando backend '%s': %s", config.backend_type, e
            )
            return SessionStartResult(
                success=False,
                error_message=error_msg,
                can_retry=True,
                can_select_alternative=True,
            )
        except BackendConnectionError as e:
            # Req 19.5: Informar con mensaje descriptivo
            error_msg = (
                f"No se pudo conectar al backend '{config.backend_type}': "
                f"{e}. Verifique la configuración de red y credenciales."
            )
            logger.error(
                "Error de conexión con backend '%s': %s",
                config.backend_type,
                e,
            )
            return SessionStartResult(
                success=False,
                error_message=error_msg,
                can_retry=True,
                can_select_alternative=True,
            )

        if not is_accessible:
            error_msg = (
                f"El backend '{config.backend_type}' no está accesible. "
                f"Seleccione un backend alternativo o reintente la conexión."
            )
            logger.warning(
                "Backend '%s' no accesible en validación",
                config.backend_type,
            )
            return SessionStartResult(
                success=False,
                error_message=error_msg,
                can_retry=True,
                can_select_alternative=True,
            )

        # Backend accesible — bloquear configuración e iniciar sesión
        self._session_active = True
        self._current_backend = backend
        self._current_config = config
        self._current_enricher = enricher
        self._session_log_path = session_log_path

        logger.info(
            "Sesión iniciada con backend '%s' (modelos: emb=%s, llm=%s)",
            config.backend_type,
            config.embedding_model_id,
            config.llm_model_id,
        )

        return SessionStartResult(success=True)

    # ------------------------------------------------------------------
    # Fin de sesión
    # ------------------------------------------------------------------

    async def end_session(
        self,
        script_doc=None,
    ) -> list:
        """Finaliza la sesión activa, desbloquea configuración y genera sugerencias.

        Desbloquea la configuración del backend y, si hay un enricher y
        log de sesión disponibles, dispara la generación de sugerencias
        publicitarias.

        Args:
            script_doc: Documento de guión para generación de sugerencias
                       (opcional, requerido si se desea generar sugerencias).

        Returns:
            Lista de AdSuggestion generadas (puede estar vacía si no se
            pudieron generar o no se proporcionó script_doc).
        """
        if not self._session_active:
            logger.warning("Se intentó finalizar sesión sin sesión activa.")
            return []

        enricher = self._current_enricher
        session_log = self._session_log_path
        suggestions: list = []

        # Desbloquear configuración
        self._session_active = False

        logger.info(
            "Sesión finalizada. Configuración desbloqueada (backend: '%s')",
            self._current_config.backend_type if self._current_config else "N/A",
        )

        # Invocar generación de sugerencias publicitarias si es posible
        if enricher and session_log and script_doc:
            try:
                from switch_bot.engines.script_parser import ScriptDocument

                if isinstance(script_doc, ScriptDocument):
                    suggestions = await enricher.generate_ad_suggestions(
                        session_log=session_log,
                        script=script_doc,
                    )
                    logger.info(
                        "Generadas %d sugerencias publicitarias post-sesión",
                        len(suggestions),
                    )
            except Exception as e:
                logger.error(
                    "Error generando sugerencias publicitarias: %s", e
                )

        # Limpiar estado de sesión
        self._current_backend = None
        self._current_config = None
        self._current_enricher = None
        self._session_log_path = None

        return suggestions

    # ------------------------------------------------------------------
    # Control de inmutabilidad de configuración
    # ------------------------------------------------------------------

    def change_backend_config(self, new_config: IABackendConfig) -> None:
        """Cambia la configuración del backend.

        Solo permitido cuando no hay sesión activa (Req 19.7).

        Args:
            new_config: Nueva configuración del backend.

        Raises:
            SessionConfigLockedError: Si hay una sesión activa.
        """
        if self._session_active:
            raise SessionConfigLockedError()

        self._current_config = new_config
        logger.info(
            "Configuración de backend actualizada a: tipo=%s, emb=%s, llm=%s",
            new_config.backend_type,
            new_config.embedding_model_id,
            new_config.llm_model_id,
        )
