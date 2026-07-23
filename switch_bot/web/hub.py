"""WebSocket Hub — Gestor centralizado de conexiones WebSocket del servidor.

Mantiene canales separados para Agentes_Locales y clientes Frontend_SPA,
con validación de token delegada a un callable inyectable (token_validator).

Requirements cubiertos:
- 1.3: Servidor_EC2 expone WebSocket endpoint para comunicación bidireccional
- 1.6: Soportar hasta 4 operadores simultáneos via sesiones WebSocket independientes
- 7.4: Separación de canales WebSocket (Agentes vs SPA)
- 7.5: Al menos 4 Agentes_Locales conectados, identificados por ID de operador único
- 15.1/15.2: Límites de conexión (4 agentes, 10 SPA clients)
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Protocol

from switch_bot.web.protocol import ChannelMessage

logger = logging.getLogger(__name__)


class WebSocketLike(Protocol):
    """Protocolo mínimo que debe cumplir un objeto WebSocket."""

    async def send_bytes(self, data: bytes) -> None: ...


class WebSocketHub:
    """Gestor centralizado de conexiones WebSocket del servidor.

    Mantiene diccionarios separados para conexiones de agentes y SPAs,
    respetando los límites de conexión configurados.

    Args:
        max_agents: Máximo de agentes simultáneos (default 4).
        max_spa_clients: Máximo de clientes SPA simultáneos (default 10).
        token_validator: Callable que recibe un token string y retorna
            un dict de claims si es válido, o None si es inválido.
            Permite desacoplar la validación del hub para testing.
    """

    def __init__(
        self,
        max_agents: int = 4,
        max_spa_clients: int = 10,
        token_validator: Callable[[str], dict | None] | None = None,
    ):
        self._agent_connections: dict[str, WebSocketLike] = {}
        self._spa_connections: dict[str, WebSocketLike] = {}
        self._message_handlers: dict[str, Callable] = {}
        self._max_agents = max_agents
        self._max_spa_clients = max_spa_clients
        self._token_validator = token_validator or self._default_validator

    @staticmethod
    def _default_validator(token: str) -> dict | None:
        """Validador por defecto — rechaza todo. Debe inyectarse uno real."""
        return None

    # ------------------------------------------------------------------
    # Registro de agentes
    # ------------------------------------------------------------------

    async def register_agent(
        self, operator_id: str, ws: WebSocketLike, token: str
    ) -> bool:
        """Registra un Agente_Local tras validar token.

        Args:
            operator_id: ID único del operador.
            ws: Conexión WebSocket del agente.
            token: Token de autenticación a validar.

        Returns:
            True si el registro fue exitoso, False si la autenticación falla
            o se excede el límite de agentes.
        """
        # Validar token
        claims = self._token_validator(token)
        if claims is None:
            logger.warning(
                "Registro de agente rechazado: token inválido para operator_id=%s",
                operator_id,
            )
            return False

        # Verificar límite de conexiones (no contar si ya está registrado)
        if (
            operator_id not in self._agent_connections
            and len(self._agent_connections) >= self._max_agents
        ):
            logger.warning(
                "Registro de agente rechazado: límite de %d agentes alcanzado "
                "(operator_id=%s)",
                self._max_agents,
                operator_id,
            )
            return False

        self._agent_connections[operator_id] = ws
        logger.info("Agente registrado: operator_id=%s", operator_id)
        return True

    async def register_spa_client(
        self, client_id: str, ws: WebSocketLike, token: str
    ) -> bool:
        """Registra un cliente SPA tras validar token.

        Args:
            client_id: ID único del cliente SPA.
            ws: Conexión WebSocket del cliente.
            token: Token de autenticación a validar.

        Returns:
            True si el registro fue exitoso, False si la autenticación falla
            o se excede el límite de clientes SPA.
        """
        # Validar token
        claims = self._token_validator(token)
        if claims is None:
            logger.warning(
                "Registro de SPA rechazado: token inválido para client_id=%s",
                client_id,
            )
            return False

        # Verificar límite de conexiones (no contar si ya está registrado)
        if (
            client_id not in self._spa_connections
            and len(self._spa_connections) >= self._max_spa_clients
        ):
            logger.warning(
                "Registro de SPA rechazado: límite de %d clientes alcanzado "
                "(client_id=%s)",
                self._max_spa_clients,
                client_id,
            )
            return False

        self._spa_connections[client_id] = ws
        logger.info("Cliente SPA registrado: client_id=%s", client_id)
        return True

    # ------------------------------------------------------------------
    # Desregistro
    # ------------------------------------------------------------------

    async def unregister_agent(self, operator_id: str) -> None:
        """Desregistra agente y notifica a SPAs conectados.

        Envía un mensaje state_update a todos los SPAs indicando que
        el agente se desconectó.

        Args:
            operator_id: ID del operador a desregistrar.
        """
        if operator_id not in self._agent_connections:
            logger.debug(
                "Intento de desregistrar agente no registrado: operator_id=%s",
                operator_id,
            )
            return

        del self._agent_connections[operator_id]
        logger.info("Agente desregistrado: operator_id=%s", operator_id)

        # Notificar a todos los SPAs conectados
        notification = ChannelMessage(
            type="state_update",
            timestamp=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            seq=0,
            version="1.0",
            payload={
                "event": "agent_disconnected",
                "operator_id": operator_id,
                "connected_agents": self.connected_agents,
            },
        )
        await self.broadcast_to_spas(notification)

    async def unregister_spa_client(self, client_id: str) -> None:
        """Desregistra un cliente SPA.

        Args:
            client_id: ID del cliente SPA a desregistrar.
        """
        if client_id not in self._spa_connections:
            logger.debug(
                "Intento de desregistrar SPA no registrado: client_id=%s",
                client_id,
            )
            return

        del self._spa_connections[client_id]
        logger.info("Cliente SPA desregistrado: client_id=%s", client_id)

    # ------------------------------------------------------------------
    # Envío de mensajes
    # ------------------------------------------------------------------

    async def broadcast_to_spas(self, message: ChannelMessage) -> None:
        """Envía mensaje a todos los clientes SPA conectados.

        Los errores de envío individuales se loguean y se continúa
        con los demás clientes (tolerancia a desconexiones parciales).

        Args:
            message: ChannelMessage a enviar.
        """
        data = message.encode()
        disconnected: list[str] = []

        for client_id, ws in self._spa_connections.items():
            try:
                await ws.send_bytes(data)
            except Exception:
                logger.warning(
                    "Error enviando a SPA client_id=%s, marcando para desregistro",
                    client_id,
                    exc_info=True,
                )
                disconnected.append(client_id)

        # Limpiar conexiones rotas detectadas durante broadcast
        for client_id in disconnected:
            del self._spa_connections[client_id]
            logger.info(
                "SPA client_id=%s eliminado por error de envío", client_id
            )

    async def send_to_agent(
        self, operator_id: str, message: ChannelMessage
    ) -> bool:
        """Envía mensaje a un agente específico.

        Args:
            operator_id: ID del operador destino.
            message: ChannelMessage a enviar.

        Returns:
            True si se envió exitosamente, False si el agente no está
            conectado o si hubo error de envío.
        """
        ws = self._agent_connections.get(operator_id)
        if ws is None:
            logger.debug(
                "send_to_agent: agente no conectado operator_id=%s",
                operator_id,
            )
            return False

        try:
            await ws.send_bytes(message.encode())
            return True
        except Exception:
            logger.warning(
                "Error enviando a agente operator_id=%s",
                operator_id,
                exc_info=True,
            )
            return False

    async def broadcast_to_agents(self, message: ChannelMessage) -> None:
        """Envía mensaje a todos los agentes conectados.

        Los errores de envío individuales se loguean y se continúa
        con los demás agentes.

        Args:
            message: ChannelMessage a enviar.
        """
        data = message.encode()
        disconnected: list[str] = []

        for operator_id, ws in self._agent_connections.items():
            try:
                await ws.send_bytes(data)
            except Exception:
                logger.warning(
                    "Error enviando a agente operator_id=%s, marcando para desregistro",
                    operator_id,
                    exc_info=True,
                )
                disconnected.append(operator_id)

        # Limpiar conexiones rotas detectadas durante broadcast
        for operator_id in disconnected:
            del self._agent_connections[operator_id]
            logger.info(
                "Agente operator_id=%s eliminado por error de envío", operator_id
            )

    # ------------------------------------------------------------------
    # Propiedades
    # ------------------------------------------------------------------

    @property
    def connected_agents(self) -> list[str]:
        """IDs de agentes conectados actualmente."""
        return list(self._agent_connections.keys())

    @property
    def connected_spa_clients(self) -> list[str]:
        """IDs de clientes SPA conectados actualmente."""
        return list(self._spa_connections.keys())

    @property
    def agent_count(self) -> int:
        """Número de agentes conectados."""
        return len(self._agent_connections)

    @property
    def spa_client_count(self) -> int:
        """Número de clientes SPA conectados."""
        return len(self._spa_connections)
