"""Pipeline OBS — Control de OBS Studio vía WebSocket v5.

Implementa la comunicación WebSocket asíncrona con OBS Studio para
conmutación de escenas en tiempo real. Proporciona reconexión automática
con backoff exponencial y sincronización de estado al reconectar.

Requisitos: 11.1, 11.2, 11.3, 11.4
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from switch_bot.models.payload import EnrichedPayload
from switch_bot.pipelines.base import Pipeline

logger = logging.getLogger(__name__)

# Reconnection backoff parameters
_INITIAL_BACKOFF_S = 1.0
_MAX_BACKOFF_S = 30.0
_BACKOFF_MULTIPLIER = 2.0


class OBSPipeline(Pipeline):
    """Control de OBS Studio vía WebSocket/MCP.

    Envía eventos JSON a OBS Studio mediante WebSocket v5 para cambiar
    escenas asociadas a personajes y encuadres de cámara. Implementa
    reconexión asíncrona automática con backoff exponencial.

    Attributes:
        ws_url: URL del servidor WebSocket de OBS Studio.
    """

    def __init__(self, ws_url: str, *, password: str | None = None) -> None:
        """Inicializa el pipeline OBS.

        Args:
            ws_url: URL WebSocket de OBS Studio (ej: ws://localhost:4455).
            password: Contraseña opcional para autenticación OBS WebSocket.
        """
        self._ws_url = ws_url
        self._password = password
        self._connected: bool = False
        self._healthy: bool = False
        self._ws: Any = None  # websockets connection object
        self._request_id: int = 0
        self._reconnect_task: asyncio.Task[None] | None = None
        self._shutdown: bool = False

        # Last requested scene for state sync on reconnect
        self._last_scene: str | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Inicia la conexión WebSocket con OBS Studio.

        Intenta conectar al servidor OBS WebSocket. Si falla, inicia
        el proceso de reconexión automática en background.
        """
        self._shutdown = False
        await self._connect()
        if not self._connected:
            logger.warning(
                "OBS initial connection failed, starting reconnect loop"
            )
            self._start_reconnect_task()

    async def stop(self) -> None:
        """Detiene el pipeline OBS y cierra la conexión WebSocket."""
        self._shutdown = True

        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
            self._reconnect_task = None

        await self._disconnect()
        logger.info("OBSPipeline stopped")

    async def _connect(self) -> None:
        """Establece conexión WebSocket con OBS Studio.

        Importa websockets bajo demanda y realiza el handshake
        con el protocolo OBS WebSocket v5.
        """
        try:
            import websockets  # type: ignore[import-untyped]

            self._ws = await websockets.connect(self._ws_url)
            # Read the Hello message from OBS
            hello_raw = await asyncio.wait_for(self._ws.recv(), timeout=5.0)
            hello = json.loads(hello_raw)
            logger.debug("OBS Hello: %s", hello)

            # Send Identify message (OBS WebSocket v5 protocol)
            identify_msg = {
                "op": 1,  # Identify opcode
                "d": {"rpcVersion": 1},
            }
            if self._password:
                # If authentication is required, include auth fields
                # (simplified — full auth requires challenge/salt hashing)
                identify_msg["d"]["authentication"] = self._password

            await self._ws.send(json.dumps(identify_msg))

            # Read Identified response
            identified_raw = await asyncio.wait_for(
                self._ws.recv(), timeout=5.0
            )
            identified = json.loads(identified_raw)
            logger.debug("OBS Identified: %s", identified)

            self._connected = True
            self._healthy = True
            logger.info("OBS connected at %s", self._ws_url)

        except Exception:
            logger.exception("OBS connection failed for %s", self._ws_url)
            self._connected = False
            self._healthy = False

    async def _disconnect(self) -> None:
        """Cierra la conexión WebSocket con OBS Studio."""
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                logger.debug("Error closing OBS WebSocket", exc_info=True)
            self._ws = None

        self._connected = False
        self._healthy = False

    async def execute(self, payload: EnrichedPayload) -> None:
        """Cambia escena OBS al personaje/encuadre seleccionado.

        Construye el nombre de escena a partir del personaje y la cámara
        destino, y envía la solicitud SetCurrentProgramScene al servidor
        OBS WebSocket.

        Args:
            payload: Payload enriquecido con personaje y target_cam.

        Raises:
            RuntimeError: Si el pipeline no está conectado a OBS Studio.
        """
        if not self._connected or self._ws is None:
            raise RuntimeError(
                f"OBS pipeline not connected to {self._ws_url}"
            )

        # Build scene name from character and camera index
        scene_name = f"{payload.personaje}_cam{payload.target_cam}"

        logger.debug(
            "Switching OBS to scene '%s' (personaje=%s, cam=%d)",
            scene_name,
            payload.personaje,
            payload.target_cam,
        )

        try:
            await self._set_current_scene(scene_name)
            async with self._lock:
                self._last_scene = scene_name
            logger.info("OBS switched to scene '%s'", scene_name)
        except Exception:
            logger.exception("Failed to switch OBS scene to '%s'", scene_name)
            self._healthy = False
            self._start_reconnect_task()
            raise

    async def _set_current_scene(self, scene_name: str) -> None:
        """Envía solicitud SetCurrentProgramScene a OBS.

        Utiliza el protocolo OBS WebSocket v5 (opcode 6 = Request).

        Args:
            scene_name: Nombre de la escena OBS destino.
        """
        self._request_id += 1
        request = {
            "op": 6,  # Request opcode
            "d": {
                "requestType": "SetCurrentProgramScene",
                "requestId": str(self._request_id),
                "requestData": {"sceneName": scene_name},
            },
        }

        await self._ws.send(json.dumps(request))

        # Wait for response
        response_raw = await asyncio.wait_for(self._ws.recv(), timeout=5.0)
        response = json.loads(response_raw)
        logger.debug("OBS response: %s", response)

        # Check for error in response
        if response.get("op") == 7:  # RequestResponse opcode
            status = response.get("d", {}).get("requestStatus", {})
            if not status.get("result", False):
                error_comment = status.get("comment", "Unknown error")
                raise RuntimeError(
                    f"OBS SetCurrentProgramScene failed: {error_comment}"
                )

    async def reconnect(self) -> None:
        """Reconexión asíncrona automática con backoff exponencial.

        Intenta reconectar al servidor OBS WebSocket duplicando el
        intervalo de espera en cada intento fallido, desde 1s hasta
        un máximo de 30s. Al reconectar, sincroniza el estado de la
        escena actual con el último estado solicitado.

        Req 11.3: La reconexión no afecta a los demás pipelines.
        Req 11.4: Al reconectar, sincroniza el estado actual.
        """
        backoff = _INITIAL_BACKOFF_S

        while not self._shutdown:
            logger.info(
                "OBS reconnecting in %.1fs (url=%s)", backoff, self._ws_url
            )
            await asyncio.sleep(backoff)

            if self._shutdown:
                break

            # Close stale connection
            await self._disconnect()

            # Attempt reconnection
            await self._connect()

            if self._connected:
                logger.info("OBS reconnected successfully")
                # Sync state: restore last requested scene (Req 11.4)
                await self._sync_state()
                return

            # Exponential backoff
            backoff = min(backoff * _BACKOFF_MULTIPLIER, _MAX_BACKOFF_S)
            logger.warning(
                "OBS reconnection failed, next attempt in %.1fs", backoff
            )

    async def _sync_state(self) -> None:
        """Sincroniza el estado actual de la escena tras reconexión.

        Reenvía el último cambio de escena solicitado para asegurar
        que OBS refleja el estado esperado por el Motor de Decisión.

        Req 11.4: Sincronización de estado al reconectar.
        """
        async with self._lock:
            scene = self._last_scene

        if scene is not None:
            try:
                await self._set_current_scene(scene)
                logger.info("OBS state synced: scene '%s' restored", scene)
            except Exception:
                logger.exception(
                    "Failed to sync OBS state to scene '%s'", scene
                )

    def _start_reconnect_task(self) -> None:
        """Inicia la tarea de reconexión en background si no existe.

        La reconexión se ejecuta como tarea asyncio independiente
        para no bloquear otros pipelines (Req 11.3).
        """
        if self._reconnect_task and not self._reconnect_task.done():
            return  # Already reconnecting

        try:
            loop = asyncio.get_running_loop()
            self._reconnect_task = loop.create_task(
                self.reconnect(), name="OBSPipeline-Reconnect"
            )
        except RuntimeError:
            logger.warning("No running event loop for OBS reconnect task")

    def is_healthy(self) -> bool:
        """Retorna True si el pipeline está conectado y operativo.

        Returns:
            True si la conexión WebSocket a OBS está activa y el último
            comando se ejecutó sin error.
        """
        return self._healthy

    @property
    def connected(self) -> bool:
        """Retorna True si la conexión WebSocket a OBS está establecida."""
        return self._connected

    @property
    def last_scene(self) -> str | None:
        """Retorna el nombre de la última escena solicitada."""
        return self._last_scene
